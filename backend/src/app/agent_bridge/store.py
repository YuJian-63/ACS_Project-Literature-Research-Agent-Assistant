import os
import subprocess
import sys
from pathlib import Path
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.agent_bridge.bundles import canonical_json, manifest_digest
from app.agent_bridge.contracts import DispatchManifest, ResultEnvelope
from app.agent_bridge.results import present_result, validate_delivery
from app.config import Settings
from app.db.models import AgentRun, Artifact, Citation, Paper, Task, TaskPaper
from app.papers.pdf_parser import ParseFailure
from app.papers.storage import controlled_path
from app.workers.parser import ParserWorker
from app.tasks.lifecycle import (
    append_event,
    database_time,
    locked_task,
    mark_failed,
    owns_task,
)


@dataclass(frozen=True)
class Execution:
    manifest: DispatchManifest
    job_id: str | None
    transport: str
    deadline: float


def load_execution(sessions: sessionmaker[Session], task_id: UUID, owner: UUID) -> Execution | None:
    with sessions() as session:
        task = locked_task(session, task_id)
        now = database_time(session)
        if not owns_task(task, owner, now) or task.runner_type != "agent":
            return None
        run = session.get(AgentRun, task_id)
        if run is None:
            raise ValueError("Agent dispatch record is missing")
        manifest = DispatchManifest.model_validate(run.manifest)
        if manifest_digest(manifest) != run.input_sha256 or str(task_id) != manifest.task.task_id or run.dispatch_id != manifest.dispatch_id:
            raise ValueError("Agent dispatch record is inconsistent")
        deadline = (task.started_at + timedelta(seconds=task.timeout_seconds)).timestamp()
        return Execution(manifest, run.remote_job_id, task.run_config.get("transport", "file-exchange-v1"), deadline)


def record_job(sessions: sessionmaker[Session], task_id: UUID, owner: UUID, manifest: DispatchManifest, job_id: str) -> bool:
    if not job_id.strip() or len(job_id) > 256 or "\x00" in job_id:
        raise ValueError("Invalid remote job ID")
    with sessions.begin() as session:
        task = locked_task(session, task_id)
        now = database_time(session)
        if not owns_task(task, owner, now) or task.runner_type != "agent" or task.stage != "agent_waiting":
            return False
        run = session.get(AgentRun, task_id)
        if run is None or run.dispatch_id != manifest.dispatch_id or run.input_sha256 != manifest_digest(manifest):
            raise ValueError("Dispatch identity changed")
        if run.remote_job_id is not None and run.remote_job_id != job_id:
            raise ValueError("Dispatch already has another job")
        if run.remote_job_id is None:
            run.remote_job_id = job_id
            run.updated_at = now
            append_event(session, task, now, "Agent 作业已提交，正在等待执行结果", "stage", {"remote_job_id": job_id})
        return True


def read_missing_page_counts(sessions, task_id, settings, discovered, cited_pages):
    # A newly uploaded PDF may be cited before the parser Worker processes it.
    # Read its metadata outside the commit transaction so the task can still heartbeat.
    with sessions() as session:
        papers = session.execute(
            select(Paper.id, Paper.storage_key, Paper.sha256, Paper.size_bytes)
            .where(Paper.id.in_(cited_pages), Paper.page_count.is_(None),
                Paper.user_id == select(Task.user_id).where(Task.id == task_id).scalar_subquery())
        ).all()
    counts = {}
    parser = ParserWorker(sessions, settings)
    for paper in papers:
        if paper.sha256 != discovered[paper.id]:
            raise ValueError("Discovered library PDF has changed")
        controlled_path(settings.storage_root, paper.id, paper.storage_key)
        try:
            metadata = parser.extract(paper.id, paper.sha256, paper.size_bytes, maintain_lease=False)
        except ParseFailure as error:
            raise ValueError("Cannot verify cited PDF page count") from error
        counts[paper.id] = metadata.page_count
    return counts


def persist_dispatch(settings, manifest, envelope):
    result = envelope.result
    if any(item.get("stage") == "persistence" for item in result.errors):
        result.configuration["persistence"] = "failed"
        return
    result.configuration["persistence"] = "saved"
    key = result.task_id
    if manifest.runtime.research and manifest.runtime.research.workflow == "extension":
        key = f"extension/{key}"
    try:
        if not settings or not settings.agent_persist_database_url or not settings.agent_persist_database_url.get_secret_value():
            raise ValueError("No Agent persistence database configured")
        subprocess.run([sys.executable, "-m", "apis.database", "--save-dispatch"],
            cwd=Path(__file__).resolve().parents[4] / "agent",
            env={**os.environ, "DATABASE_URL": settings.agent_persist_database_url.get_secret_value()},
            input=canonical_json({"storage_key": key, "papers": envelope.parsed_papers,
                "result": result.model_dump(mode="json")}),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=35, check=True)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        result.configuration["persistence"] = "failed"
        result.errors.append({"stage": "persistence", "type": type(exc).__name__})


def complete_delivery(sessions: sessionmaker[Session], task_id: UUID, owner: UUID,
    manifest: DispatchManifest, envelope: ResultEnvelope, *, settings: Settings | None = None) -> bool:
    discovered = validate_delivery(manifest, envelope)
    result = envelope.result
    presentation = present_result(manifest, result, discovered)
    cited_pages = {}
    for citation in presentation.citations:
        if citation.paper_id in discovered:
            cited_pages[citation.paper_id] = max(citation.page_number, cited_pages.get(citation.paper_id, 0))
    counts = read_missing_page_counts(sessions, task_id, settings, discovered, cited_pages) if settings and cited_pages else {}
    with sessions.begin() as session:
        task = locked_task(session, task_id)
        now = database_time(session)
        if not owns_task(task, owner, now) or task.runner_type != "agent" or task.stage != "agent_waiting":
            return False
        run = session.get(AgentRun, task_id)
        if run is None or run.dispatch_id != envelope.dispatch_id or run.input_sha256 != envelope.input_sha256:
            raise ValueError("Agent delivery identity changed")
        if run.remote_job_id is not None and run.remote_job_id != envelope.remote_job_id:
            raise ValueError("Agent delivery belongs to another job")
        if run.result is not None:
            return False
        if discovered:
            papers = session.execute(
                select(Paper.id, Paper.sha256, Paper.page_count)
                .where(Paper.user_id == task.user_id, Paper.id.in_(discovered))
                .order_by(Paper.id).with_for_update(read=True)
            ).all()
            if len(papers) != len(discovered):
                raise ValueError("Discovered PDF is not in the task owner's library")
            for paper in papers:
                if paper.sha256 != discovered[paper.id]:
                    raise ValueError("Discovered library PDF has changed")
                if paper.id in cited_pages:
                    page_count = paper.page_count or counts.get(paper.id)
                    if page_count is None or cited_pages[paper.id] > page_count:
                        raise ValueError("Citation exceeds verified library PDF pages")
                session.add(TaskPaper(task_id=task_id, user_id=task.user_id, paper_id=paper.id,
                    paper_sha256=paper.sha256, selection_order=None))
        if manifest.runtime.persist:
            persist_dispatch(settings, manifest, envelope)
            now = database_time(session)
        run.result = result.model_dump(mode="json")
        run.stop_reason = result.stop_reason
        run.remote_job_id = envelope.remote_job_id
        run.updated_at = now
        task.input_tokens = result.usage.input_tokens
        task.output_tokens = result.usage.output_tokens
        task.model_calls = result.usage.model_calls
        task.tool_calls = result.usage.tool_calls
        task.review_state = {"agent_outcome": {"stop_reason": result.stop_reason,
            "unresolved": result.unresolved, "usage_complete": result.usage.token_usage_complete,
            "total_tokens": result.usage.total_tokens, "agent_steps": result.usage.agent_steps}}
        model = result.configuration.get("model")
        if isinstance(model, str) and model.strip() and len(model) <= 256:
            task.model_id = model
        if result.stop_reason not in {"completed", "partial"}:
            message = "Agent 未完成研究任务，停止原因：" + result.stop_reason
            if manifest.runtime.research and manifest.runtime.research.model_provider in {"custom", "tacc"} and result.stop_reason == "model_error":
                message = "课程模型调用失败，请在模型管理中检查 GPU 作业状态后重试"
            mark_failed(session, task, now, "AGENT_" + result.stop_reason.upper(), message)
            task.error_details = {"stop_reason": result.stop_reason, "unresolved": result.unresolved}
            if settings and settings.evaluation_enabled:
                from app.evaluations.service import enqueue_evaluation
                enqueue_evaluation(session, task, settings, automatic=True)
            return True
        artifact = Artifact(task_id=task_id,
            title={"summary": "论文摘要", "qa": "论文问答", "review": "论文综述"}[task.task_type],
            content_markdown=presentation.content_markdown, comparison_table=None, created_at=now)
        session.add(artifact)
        session.flush()
        session.add_all([Citation(artifact_id=artifact.id, task_id=task_id, citation_key=item.citation_key,
            paper_id=item.paper_id, chunk_id=None, agent_chunk_id=item.agent_chunk_id,
            agent_source_id=item.agent_source_id, page_number=item.page_number, quote=item.quote, created_at=now)
            for item in presentation.citations])
        task.status = "succeeded"
        task.stage = "partial" if result.stop_reason == "partial" else "completed"
        task.finished_at = now
        task.worker_id = None
        task.lease_expires_at = None
        task.error_code = None
        task.error_message = None
        task.error_details = None
        if settings and settings.evaluation_enabled:
            from app.evaluations.service import enqueue_evaluation
            enqueue_evaluation(session, task, settings, automatic=True)
        if result.stop_reason == "partial" or result.unresolved:
            append_event(session, task, now, "Agent 已返回可用结果，仍有未解决项", "warning",
                {"stop_reason": result.stop_reason, "unresolved": result.unresolved})
        append_event(session, task, now, "Agent 结果已保存" if result.stop_reason == "completed" else "Agent 部分结果已保存",
            "status", {"stop_reason": result.stop_reason})
        return True
