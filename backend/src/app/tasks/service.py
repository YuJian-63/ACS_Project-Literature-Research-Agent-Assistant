import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.api.schemas import TaskCreate
from app.api.views import accepted_view
from app.config import Settings
from app.db.models import Paper, PaperChunk, Task, TaskEvent, TaskPaper
from app.db.ownership import check_task_capacity, lock_active_user
from app.errors import APIError
from app.research.retrieval import EvidenceChunk
from app.research.search_policy import (
    WORKFLOW_VERSION,
    build_search_plan,
    source_snapshot,
)
from app.research.task_policy import automatic_budget


def request_hash(request: TaskCreate, *, automatic_review: bool = False, automatic: bool = False) -> str:
    data = request.model_dump(mode="json")
    if automatic_review or automatic:
        data.pop("budget", None)
    canonical = json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_idempotency_key(key: str | None) -> None:
    if key is not None and (not 1 <= len(key) <= 128 or any(not "!" <= char <= "~" for char in key)):
        raise APIError(422, "INVALID_REQUEST", "Idempotency-Key 须为 1—128 个不含空白的 ASCII 可见字符")


def replay(task: Task, digest: str) -> tuple[dict, bool]:
    if task.request_hash != digest:
        raise APIError(409, "IDEMPOTENCY_CONFLICT", "该幂等键已用于不同请求")
    return accepted_view(task), True


def submit_task(
    sessions: sessionmaker[Session], settings: Settings, request: TaskCreate, key: str | None, *, user_id: UUID
) -> tuple[dict, bool]:
    validate_idempotency_key(key)
    digest = request_hash(request)
    try:
        with sessions.begin() as session:
            lock_active_user(session, user_id)
            if key is not None:
                existing = session.scalar(select(Task).where(Task.user_id == user_id, Task.idempotency_key == key))
                if existing is not None:
                    return replay(existing, request_hash(request, automatic=automatic_budget(existing)))
            check_task_capacity(session, user_id, settings.user_active_tasks, settings.user_daily_tasks)
            if request.workflow_type != "baseline":
                raise APIError(422, "WORKFLOW_NOT_AVAILABLE", "当前阶段仅开放 baseline 工作流")
            runner_type = settings.task_runner
            if runner_type == "agent" and not settings.agent_dispatch_enabled:
                raise APIError(503, "RUNNER_NOT_CONFIGURED", "Agent 派发尚未启用，请先完成传输配置")
            if runner_type == "agent":
                from app.agent_bridge.transport import create_transport

                try:
                    create_transport(settings)
                except ValueError:
                    raise APIError(503, "RUNNER_NOT_CONFIGURED", "Agent 传输配置不完整，请检查部署配置") from None
            if runner_type == "langgraph":
                if not settings.real_runner_configured:
                    raise APIError(503, "RUNNER_NOT_CONFIGURED", "真实研究模型尚未配置")
            papers = list(session.scalars(
                select(Paper).where(Paper.user_id == user_id, Paper.id.in_(request.paper_ids)).order_by(Paper.id).with_for_update()
            ))
            missing = sorted(set(request.paper_ids) - {paper.id for paper in papers})
            if missing:
                raise APIError(404, "PAPER_NOT_FOUND", "部分论文不存在", {
                    "missing_paper_ids": [str(paper_id) for paper_id in missing]
                })
            allowed_statuses = {"ready"} if runner_type == "langgraph" else {"uploaded", "ready"}
            if runner_type == "agent":
                allowed_statuses.add("processing")
            if any(paper.status not in allowed_statuses for paper in papers):
                raise APIError(409, "PAPER_NOT_READY", "选定论文尚不可用于执行任务")
            if runner_type == "agent":
                from app.agent_bridge.submission import create_agent_task

                return create_agent_task(session, settings, request, papers, user_id=user_id, key=key,
                    digest=request_hash(request, automatic=True)), False
            run_config = {"mock_step_delay_seconds": settings.mock_step_delay_seconds}
            budget = {"max_steps": 2, "max_tokens": 1,
                      "timeout_seconds": max(30, int(settings.mock_step_delay_seconds * 2) + 15)}
            review_state = {}
            staged_review = runner_type == "langgraph" and request.task_type == "review"
            if runner_type == "langgraph":
                run_config = {
                    "model_base_url": settings.llm_base_url,
                    "model_thinking_mode": settings.llm_thinking_mode,
                    "model_timeout_seconds": settings.llm_timeout_seconds,
                    "evidence_context_chars": settings.evidence_context_chars,
                }
                by_id = {paper.id: paper for paper in papers}
                chunks = list(session.scalars(select(PaperChunk).where(PaperChunk.paper_id.in_(by_id)).order_by(PaperChunk.paper_id, PaperChunk.chunk_index)))
                source = [EvidenceChunk(chunk_id=str(chunk.id), paper_id=str(chunk.paper_id),
                    paper_title=by_id[chunk.paper_id].title, chunk_index=chunk.chunk_index,
                    page_number=chunk.page_number, content=chunk.content) for chunk in chunks]
                selected = [{"paper_id": str(paper.id), "paper_title": paper.title,
                    "sha256": paper.sha256, "parser_version": paper.parser_version} for paper in papers]
                try:
                    snapshot = source_snapshot(selected, source, max_bytes=getattr(settings, "retrieval_snapshot_bytes", 8 * 1024 * 1024))
                    search, plan, evidence = build_search_plan(request.task_type, request.question, selected, source, settings)
                except ValueError:
                    code = "REVIEW_CAPACITY_EXCEEDED" if staged_review else "RESEARCH_CAPACITY_EXCEEDED"
                    raise APIError(422, code, "当前研究输入超过服务器处理上限，请缩小问题范围或减少论文数量") from None
                run_config["search_policy"] = search
                if staged_review:
                    run_config["review_policy"] = plan
                else:
                    run_config.update(research_policy=plan, max_output_tokens=plan["max_output_tokens"],
                        model_timeout_seconds=plan["model_timeout_seconds"], evidence_context_chars=plan["evidence_context_chars"])
                review_state = {"source_snapshot": snapshot, "evidence": [chunk.model_dump() for chunk in evidence],
                    "units": {}, "usage_estimated": False}
                budget = {name: search[name] for name in ("max_steps", "max_tokens", "timeout_seconds")}
            run_config["budget_mode"] = "automatic"
            digest = request_hash(request, automatic=True)
            task = Task(
                id=uuid4(), user_id=user_id, task_type=request.task_type, question=request.question,
                workflow_type=request.workflow_type, runner_type=runner_type,
                workflow_version="mock-v1" if runner_type == "mock" else WORKFLOW_VERSION,
                prompt_version=None if runner_type == "mock" else ("evidence-review-search-v1" if staged_review else "evidence-search-v1"),
                model_id=None if runner_type == "mock" else settings.llm_model_id,
                run_config=run_config, review_state=review_state,
                **budget, idempotency_key=key, request_hash=digest,
                last_event_seq=1,
            )
            session.add(task)
            session.flush()
            session.add_all([
                TaskPaper(task_id=task.id, user_id=user_id, paper_id=paper.id, paper_sha256=paper.sha256, selection_order=order)
                for order, paper in enumerate(papers)
            ])
            session.add(TaskEvent(
                task_id=task.id, seq=1, event_type="status", status="queued", stage="queued",
                message="任务已加入队列", payload={},
            ))
            result = accepted_view(task)
        return result, False
    except IntegrityError:
        if key is not None:
            with sessions.begin() as session:
                existing = session.scalar(select(Task).where(Task.user_id == user_id, Task.idempotency_key == key))
                if existing is not None:
                    return replay(existing, request_hash(request, automatic=automatic_budget(existing)))
        raise


def get_task(session: Session, task_id: UUID, user_id: UUID) -> Task:
    task = session.scalar(select(Task).where(Task.id == task_id, Task.user_id == user_id))
    if task is None:
        raise APIError(404, "TASK_NOT_FOUND", "任务不存在")
    return task


def selected_papers(session: Session, task_ids: list[UUID]) -> dict[UUID, list[UUID]]:
    result = {task_id: [] for task_id in task_ids}
    if task_ids:
        rows = session.execute(
            select(TaskPaper.task_id, TaskPaper.paper_id)
            .where(TaskPaper.task_id.in_(task_ids)).order_by(TaskPaper.paper_id)
        )
        for task_id, paper_id in rows:
            result[task_id].append(paper_id)
    return result
