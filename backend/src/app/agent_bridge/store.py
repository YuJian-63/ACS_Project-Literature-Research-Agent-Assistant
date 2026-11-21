from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.agent_bridge.bundles import manifest_digest
from app.agent_bridge.contracts import DispatchManifest, ResultEnvelope
from app.agent_bridge.results import present_result, validate_delivery
from app.db.models import AgentRun, Artifact, Citation
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


def load_manifest(sessions: sessionmaker[Session], task_id: UUID, owner: UUID) -> DispatchManifest | None:
    execution = load_execution(sessions, task_id, owner)
    return execution.manifest if execution else None


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


def complete_delivery(sessions: sessionmaker[Session], task_id: UUID, owner: UUID,
    manifest: DispatchManifest, envelope: ResultEnvelope) -> bool:
    validate_delivery(manifest, envelope)
    result = envelope.result
    presentation = present_result(manifest, result)
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
            mark_failed(session, task, now, "AGENT_" + result.stop_reason.upper(),
                "Agent 未完成研究任务，停止原因：" + result.stop_reason)
            task.error_details = {"stop_reason": result.stop_reason, "unresolved": result.unresolved}
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
        if result.stop_reason == "partial" or result.unresolved:
            append_event(session, task, now, "Agent 已返回可用结果，仍有未解决项", "warning",
                {"stop_reason": result.stop_reason, "unresolved": result.unresolved})
        append_event(session, task, now, "Agent 结果已保存" if result.stop_reason == "completed" else "Agent 部分结果已保存",
            "status", {"stop_reason": result.stop_reason})
        return True
