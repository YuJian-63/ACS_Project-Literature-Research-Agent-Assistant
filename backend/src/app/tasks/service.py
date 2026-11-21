import hashlib
import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.api.schemas import TaskCreate
from app.api.views import accepted_view
from app.config import Settings
from app.db.models import AgentRun, Paper, Task, TaskPaper
from app.db.ownership import check_task_capacity, lock_active_user
from app.errors import APIError
from app.tasks.policy import automatic_budget
from app.agent_bridge.submission import create_agent_task, ensure_agent_ready


def request_hash(request: TaskCreate, *, automatic: bool = False) -> str:
    data = request.model_dump(mode="json")
    if automatic:
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
    digest = request_hash(request, automatic=True)
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
            ensure_agent_ready(settings)
            papers = list(session.scalars(
                select(Paper).where(Paper.user_id == user_id, Paper.id.in_(request.paper_ids)).order_by(Paper.id).with_for_update()
            ))
            missing = sorted(set(request.paper_ids) - {paper.id for paper in papers})
            if missing:
                raise APIError(404, "PAPER_NOT_FOUND", "部分论文不存在", {
                    "missing_paper_ids": [str(paper_id) for paper_id in missing]
                })
            if any(paper.status not in {"uploaded", "processing", "ready"} for paper in papers):
                raise APIError(409, "PAPER_NOT_READY", "选定论文尚不可用于执行任务")
            return create_agent_task(session, settings, request, papers, user_id=user_id, key=key, digest=digest), False
    except IntegrityError:
        if key is not None:
            with sessions.begin() as session:
                existing = session.scalar(select(Task).where(Task.user_id == user_id, Task.idempotency_key == key))
                if existing is not None:
                    return replay(existing, request_hash(request, automatic=automatic_budget(existing)))
        raise


def ensure_task_deletable(session: Session, task: Task) -> None:
    if task.status == "running" or (
        task.runner_type == "agent" and task.status == "queued" and task.started_at is not None
    ):
        raise APIError(409, "TASK_RUNNING", "研究正在执行，请等待完成后再删除")
    if (task.runner_type == "agent" and task.status == "failed"
        and task.run_config.get("transport") in {"local-process-v1", "tacc-ssh-slurm-v1"}
        and not task.run_config.get("agent_cancel_confirmed")):
        run = session.get(AgentRun, task.id)
        if run is not None and run.result is None:
            raise APIError(409, "AGENT_STOP_PENDING", "Agent 作业尚未确认停止，请稍后再删除")


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
