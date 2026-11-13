import logging
import signal
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.models import Paper, PaperChunk, Task, TaskPaper
from app.db.session import create_database_engine, create_session_factory
from app.tasks.lifecycle import (
    HEARTBEAT_SECONDS, TaskMonitor, claim_task, complete_real, fail_owned,
    heartbeat, set_task_stage,
)
from app.research.model_client import ChatModel, ModelTimeoutError, OpenAICompatibleChatModel
from app.research.graph import build_research_graph
from app.research.review_policy import WORKFLOW_VERSION
from app.research.review_runner import ReviewResultError, run_staged_review
from app.research.review_store import ReviewStore, ReviewOwnershipLost, ReviewLimitError
from app.research.validation import (
    evidence_insufficient_review, invalid_result_diagnostic, validate_paragraph_result,
    validate_result, validate_review_result, validate_selected_evidence_result,
    validate_selected_review_result,
)
from app.research.retrieval import EvidenceBudgetError, EvidenceChunk, build_messages, select_evidence, select_review_evidence

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResearchJob:
    task_id: UUID
    task_type: str
    question: str | None
    model_id: str
    model_base_url: str
    model_timeout_seconds: float
    evidence_context_chars: int
    max_tokens: int
    timeout_seconds: int
    started_at: datetime
    paper_title: str
    evidence: list[EvidenceChunk]
    selected_papers: list[dict[str, str]]
    model_thinking_mode: str = "provider_default"
    prompt_version: str | None = None
    max_output_tokens: int = 2048
    review_plan: dict | None = None


class TaskInputError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(code)


def remaining_task_seconds(started_at: datetime, timeout_seconds: int, *, now: datetime | None = None) -> float:
    current_time = now or datetime.now(timezone.utc)
    return max(0.0, timeout_seconds - (current_time - started_at).total_seconds())


def load_research_job(sessions: sessionmaker[Session], task_id: UUID) -> ResearchJob:
    with sessions() as session:
        task = session.get(Task, task_id)
        if task is None or task.runner_type != "langgraph":
            raise TaskInputError("INVALID_AGENT_RESULT", "任务配置不可用")
        rows = list(session.execute(
            select(TaskPaper, Paper).join(Paper, Paper.id == TaskPaper.paper_id)
            .where(TaskPaper.task_id == task_id).order_by(TaskPaper.selection_order)
        ))
        expected_count = 2 <= len(rows) <= 20 if task.task_type == "review" else len(rows) == 1
        if not expected_count:
            raise TaskInputError("INVALID_AGENT_RESULT", "任务选定论文数量不符合要求")
        for selection, paper in rows:
            if paper.status != "ready":
                raise TaskInputError("PAPER_NOT_READY", "选定论文尚未完成解析")
            if paper.sha256 != selection.paper_sha256:
                raise TaskInputError("PAPER_SOURCE_CHANGED", "论文文件与任务创建时不一致")
        papers = {paper.id: paper for _, paper in rows}
        selected_papers = [{"paper_id": str(paper.id), "paper_title": paper.title} for _, paper in rows]
        chunks = list(session.scalars(
            select(PaperChunk).where(PaperChunk.paper_id.in_(papers)).order_by(PaperChunk.paper_id, PaperChunk.chunk_index)
        ))
        evidence_source = [EvidenceChunk(
            chunk_id=str(chunk.id), paper_id=str(chunk.paper_id), paper_title=papers[chunk.paper_id].title,
            chunk_index=chunk.chunk_index, page_number=chunk.page_number, content=chunk.content,
        ) for chunk in chunks]
        run_config: dict[str, Any] = task.run_config
        if not task.model_id or not run_config.get("model_base_url"):
            raise TaskInputError("INVALID_AGENT_RESULT", "任务模型配置不可用")
        max_output_tokens = run_config.get("max_output_tokens", 2048)
        allowed_output_caps = {2048, 4096} if task.task_type == "review" else {2048}
        if type(max_output_tokens) is not int or max_output_tokens not in allowed_output_caps:
            raise TaskInputError("INVALID_AGENT_RESULT", "任务输出预算配置不可用")
        context_chars = int(run_config.get("evidence_context_chars", 24000))
        staged_review = task.workflow_version == WORKFLOW_VERSION
        if staged_review:
            if not run_config.get("review_policy") or "evidence" not in task.review_state:
                raise TaskInputError("INVALID_AGENT_RESULT", "综述执行计划不可用")
            evidence = [EvidenceChunk.model_validate(chunk) for chunk in task.review_state["evidence"]]
        elif task.task_type == "review":
            groups = {paper["paper_id"]: [] for paper in selected_papers}
            for chunk in evidence_source:
                groups[chunk.paper_id].append(chunk)
            evidence = select_review_evidence(groups, task.question, context_chars)
        else:
            evidence = select_evidence(evidence_source, task.task_type, task.question, context_chars)
        return ResearchJob(
            task_id=task.id, task_type=task.task_type, question=task.question,
            model_id=task.model_id, model_base_url=run_config["model_base_url"],
            model_timeout_seconds=float(run_config.get("model_timeout_seconds", 60)),
            evidence_context_chars=int(run_config.get("evidence_context_chars", 24000)),
            max_tokens=task.max_tokens, timeout_seconds=task.timeout_seconds,
            started_at=task.started_at, paper_title=selected_papers[0]["paper_title"], evidence=evidence,
            selected_papers=selected_papers,
            model_thinking_mode=run_config.get("model_thinking_mode", "provider_default"),
            prompt_version=getattr(task, "prompt_version", None) or ("evidence-review-v1" if task.task_type == "review" else "evidence-v1"),
            max_output_tokens=max_output_tokens,
            review_plan=run_config.get("review_policy") if staged_review else None,
        )


def estimate_input_tokens(
    evidence: list[EvidenceChunk], task_type: str, question: str | None,
    selected_papers: list[dict[str, str]] | None = None,
    *, prompt_version: str | None = None,
) -> int:
    if not evidence:
        return 0
    messages = build_messages(task_type, question, evidence, selected_papers=selected_papers, prompt_version=prompt_version)
    encoded_bytes = sum(len(message["content"].encode("utf-8")) for message in messages)
    return (encoded_bytes + 2) // 3 + 512


class RunnerWorker:
    def __init__(
        self, sessions: sessionmaker[Session], settings: Settings,
        model_factory: Callable[[ResearchJob, Settings], ChatModel] | None = None,
    ) -> None:
        self.sessions = sessions
        self.settings = settings
        self.model_factory = model_factory or (
            lambda job, current: OpenAICompatibleChatModel(
                job.model_base_url, current.llm_api_key, thinking_mode=job.model_thinking_mode,
            )
        )
        self.owner = uuid4()
        self.stopped = threading.Event()

    def run_once(self) -> bool:
        task_id = claim_task(self.sessions, self.owner, runner_type="langgraph")
        if task_id is None:
            return False
        self.execute(task_id)
        return True

    def execute(self, task_id: UUID) -> None:
        heartbeat_done = threading.Event()
        ownership_lost = threading.Event()

        def renew() -> None:
            while not heartbeat_done.wait(HEARTBEAT_SECONDS):
                try:
                    if heartbeat(self.sessions, task_id, self.owner):
                        continue
                except Exception:
                    logger.warning("Runner heartbeat failed: task_id=%s", task_id)
                ownership_lost.set()
                return

        thread = threading.Thread(target=renew, name="runner-heartbeat", daemon=True)
        thread.start()
        try:
            job = load_research_job(self.sessions, task_id)
            if getattr(job, "review_plan", None) is not None:
                store = ReviewStore(self.sessions, task_id, self.owner)
                model = self.model_factory(job, self.settings)
                try:
                    result = run_staged_review(job, model, store, stopped=lambda: self.stopped.is_set() or ownership_lost.is_set())
                finally:
                    model.close()
                store.progress("validating", "正在校验综述与引用")
                usage = store.read().get("usage", {"input_tokens": 0, "output_tokens": 0, "model_calls": 0})
                complete_real(self.sessions, task_id, self.owner, result, **usage)
                return
            prompt_version = getattr(job, "prompt_version", None) or ("evidence-review-v1" if job.task_type == "review" else "evidence-v1")
            estimated = estimate_input_tokens(
                job.evidence, job.task_type, job.question, job.selected_papers,
                prompt_version=prompt_version,
            )
            if job.evidence and estimated >= job.max_tokens:
                fail_owned(self.sessions, task_id, self.owner, "BUDGET_EXCEEDED", "证据上下文超过任务 Token 预算")
                return
            if not set_task_stage(self.sessions, task_id, self.owner, "retrieving", "generating", "正在生成带来源的研究结果"):
                return
            if ownership_lost.is_set() or self.stopped.is_set():
                return
            if job.task_type == "review" and not job.evidence:
                complete_real(
                    self.sessions, task_id, self.owner, evidence_insufficient_review(job.selected_papers),
                    input_tokens=0, output_tokens=0, model_calls=0,
                )
                return
            remaining = remaining_task_seconds(job.started_at, job.timeout_seconds)
            if remaining <= 0:
                fail_owned(self.sessions, task_id, self.owner, "TASK_TIMEOUT", "任务执行超时")
                return
            timeout = min(job.model_timeout_seconds, remaining)
            model = self.model_factory(job, self.settings)
            try:
                graph = build_research_graph(model)
                output = graph.invoke({
                    "task_type": job.task_type, "question": job.question,
                    "evidence": job.evidence, "model_id": job.model_id,
                    "selected_papers": job.selected_papers,
                    "prompt_version": prompt_version,
                    "max_tokens": max(1, min(getattr(job, "max_output_tokens", 2048), job.max_tokens - estimated)),
                    "timeout_seconds": timeout,
                })
            finally:
                model.close()
            if ownership_lost.is_set() or self.stopped.is_set():
                return
            try:
                if job.task_type == "review":
                    if prompt_version == "evidence-review-v2":
                        result = validate_selected_review_result(output["output"], job.evidence, job.selected_papers)
                    else:
                        result = validate_review_result(output["output"], job.evidence, job.selected_papers)
                elif prompt_version == "evidence-v4":
                    result = validate_selected_evidence_result(output["output"], job.evidence)
                elif prompt_version == "evidence-v3":
                    result = validate_paragraph_result(output["output"], job.evidence)
                else:
                    result = validate_result(output["output"], job.evidence)
            except (KeyError, TypeError, ValueError) as error:
                message, details = invalid_result_diagnostic(error, finish_reason=output.get("finish_reason"))
                logger.warning(
                    "Runner returned invalid result: task_id=%s reason=%s finish_reason=%s",
                    task_id, details["validation_reason"], details["model_finish_reason"],
                )
                fail_owned(self.sessions, task_id, self.owner, "INVALID_AGENT_RESULT", message, details=details)
                return
            input_tokens = output.get("input_tokens")
            output_tokens = output.get("output_tokens")
            if input_tokens is not None and output_tokens is not None and input_tokens + output_tokens > job.max_tokens:
                fail_owned(self.sessions, task_id, self.owner, "BUDGET_EXCEEDED", "模型用量超过任务 Token 预算")
                return
            complete_real(
                self.sessions, task_id, self.owner, result,
                input_tokens=input_tokens, output_tokens=output_tokens,
                model_calls=output.get("model_calls", 1),
            )
        except ReviewOwnershipLost:
            return
        except ReviewResultError as error:
            fail_owned(self.sessions, task_id, self.owner, "INVALID_AGENT_RESULT", str(error), details=error.details)
        except ReviewLimitError:
            fail_owned(self.sessions, task_id, self.owner, "BUDGET_EXCEEDED", "综述已达到服务器自动分配的处理上限")
        except EvidenceBudgetError:
            fail_owned(self.sessions, task_id, self.owner, "BUDGET_EXCEEDED", "上下文预算不足以覆盖所有选定论文")
        except TaskInputError as error:
            fail_owned(self.sessions, task_id, self.owner, error.code, error.message)
        except ModelTimeoutError:
            fail_owned(self.sessions, task_id, self.owner, "AGENT_EXECUTION_FAILED", "模型服务请求超时")
        except Exception:
            logger.warning("Runner execution failed: task_id=%s", task_id)
            try:
                fail_owned(self.sessions, task_id, self.owner, "AGENT_EXECUTION_FAILED", "真实研究任务执行失败")
            except Exception:
                logger.warning("Runner failure recording deferred: task_id=%s", task_id)
        finally:
            heartbeat_done.set()
            thread.join()

    def run(self) -> None:
        monitor = TaskMonitor(self.sessions)
        monitor.start()
        try:
            while not self.stopped.is_set():
                try:
                    if self.run_once():
                        continue
                except Exception:
                    logger.warning("Runner task claim deferred; database may not be ready")
                self.stopped.wait(1)
        finally:
            monitor.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    settings = Settings()
    if settings.task_runner != "langgraph" or not settings.real_runner_configured:
        raise SystemExit("TASK_RUNNER=langgraph and all LLM settings are required")
    engine = create_database_engine(settings)
    worker = RunnerWorker(create_session_factory(engine), settings)
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signal_number, lambda *_: worker.stopped.set())
    try:
        worker.run()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
