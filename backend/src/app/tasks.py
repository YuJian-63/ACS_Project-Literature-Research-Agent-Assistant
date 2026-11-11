import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.models import Paper, Task, TaskEvent, TaskPaper
from app.errors import APIError
from app.schemas import TaskCreate
from app.views import accepted_view


def request_hash(request: TaskCreate) -> str:
    canonical = json.dumps(
        request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
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
    sessions: sessionmaker[Session], settings: Settings, request: TaskCreate, key: str | None
) -> tuple[dict, bool]:
    validate_idempotency_key(key)
    digest = request_hash(request)
    try:
        with sessions.begin() as session:
            if key is not None:
                existing = session.scalar(select(Task).where(Task.idempotency_key == key))
                if existing is not None:
                    return replay(existing, digest)
            if request.workflow_type != "baseline":
                raise APIError(422, "WORKFLOW_NOT_AVAILABLE", "Mock 阶段仅开放 baseline 工作流")
            papers = list(session.scalars(
                select(Paper).where(Paper.id.in_(request.paper_ids)).order_by(Paper.id).with_for_update()
            ))
            missing = sorted(set(request.paper_ids) - {paper.id for paper in papers})
            if missing:
                raise APIError(404, "PAPER_NOT_FOUND", "部分论文不存在", {
                    "missing_paper_ids": [str(paper_id) for paper_id in missing]
                })
            if any(paper.status not in {"uploaded", "ready"} for paper in papers):
                raise APIError(409, "PAPER_NOT_READY", "选定论文尚不可用于执行任务")
            task = Task(
                id=uuid4(), task_type=request.task_type, question=request.question,
                workflow_type=request.workflow_type, runner_type="mock", workflow_version="mock-v1",
                run_config={"mock_step_delay_seconds": settings.mock_step_delay_seconds},
                **request.budget.model_dump(), idempotency_key=key, request_hash=digest,
                last_event_seq=1,
            )
            session.add(task)
            session.flush()
            session.add_all([
                TaskPaper(task_id=task.id, paper_id=paper.id, paper_sha256=paper.sha256, selection_order=order)
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
                existing = session.scalar(select(Task).where(Task.idempotency_key == key))
                if existing is not None:
                    return replay(existing, digest)
        raise


def get_task(session: Session, task_id: UUID) -> Task:
    task = session.get(Task, task_id)
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
