from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.agent_bridge.bundles import manifest_digest
from app.agent_bridge.policy import WORKFLOW_VERSION, build_manifest
from app.agent_bridge.transport import transport_name
from app.api.schemas import TaskCreate
from app.api.views import accepted_view
from app.config import Settings
from app.db.models import AgentRun, Paper, Task, TaskEvent, TaskPaper


def create_agent_task(session: Session, settings: Settings, request: TaskCreate, papers: list[Paper],
    *, user_id: UUID, key: str | None, digest: str) -> dict:
    task_id = uuid4()
    manifest = build_manifest(task_id, uuid4(), request.task_type, request.question,
        [{"paper_id": str(paper.id), "title": paper.title, "sha256": paper.sha256,
            "size_bytes": paper.size_bytes, "page_count": paper.page_count} for paper in papers], settings)
    limits = {name: getattr(manifest.task, name) for name in
        ("max_steps", "max_papers", "timeout_seconds", "max_output_tokens")}
    limits["context_window"] = manifest.runtime.context_window
    task = Task(id=task_id, user_id=user_id, task_type=request.task_type, question=request.question,
        workflow_type=request.workflow_type, runner_type="agent", workflow_version=WORKFLOW_VERSION,
        prompt_version="agent-dispatch-v1", model_id=None,
        run_config={"budget_mode": "automatic", "agent_limits": limits, "transport": transport_name(settings)},
        review_state={}, max_steps=manifest.task.max_steps, max_tokens=100000,
        timeout_seconds=int(manifest.task.timeout_seconds), idempotency_key=key, request_hash=digest, last_event_seq=1)
    session.add(task)
    session.flush()
    session.add(AgentRun(task_id=task_id, dispatch_id=manifest.dispatch_id, input_sha256=manifest_digest(manifest),
        manifest=manifest.model_dump(mode="json")))
    session.add_all([TaskPaper(task_id=task_id, user_id=user_id, paper_id=paper.id,
        paper_sha256=paper.sha256, selection_order=index) for index, paper in enumerate(papers)])
    session.add(TaskEvent(task_id=task_id, seq=1, event_type="status", status="queued", stage="queued",
        message="任务已加入 Agent 派发队列", payload={"dispatch_id": str(manifest.dispatch_id)}))
    return accepted_view(task)
