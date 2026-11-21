import hashlib
import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.agent_bridge.submission import create_research_task, ensure_agent_ready
from app.api.agent_research_schemas import AgentResearchCreate
from app.db.models import Paper, Task, TaskPaper
from app.db.ownership import check_task_capacity, lock_active_user
from app.errors import APIError
from app.tasks.service import validate_idempotency_key

RESEARCH_INTERFACE = "agent-research-v1"


def research_filters(user_id: UUID):
    return (
        Task.user_id == user_id,
        Task.runner_type == "agent",
        Task.run_config["interface"].as_string() == RESEARCH_INTERFACE,
    )


def get_research(session, task_id: UUID, user_id: UUID, *, lock: bool = False):
    query = select(Task).where(Task.id == task_id, *research_filters(user_id))
    task = session.scalar(query.with_for_update() if lock else query)
    if task is None:
        raise APIError(404, "TASK_NOT_FOUND", "研究记录不存在")
    return task


def research_references(session, task_ids: list[UUID], user_id: UUID):
    result = {task_id: [] for task_id in task_ids}
    if task_ids:
        rows = session.execute(
            select(TaskPaper.task_id, Paper.id, Paper.title)
            .join(Paper, (Paper.id == TaskPaper.paper_id) & (Paper.user_id == TaskPaper.user_id))
            .where(TaskPaper.task_id.in_(task_ids), TaskPaper.user_id == user_id, TaskPaper.selection_order.is_not(None))
            .order_by(TaskPaper.selection_order)
        )
        for task_id, paper_id, title in rows:
            result[task_id].append({"id": paper_id, "title": title})
    return result


def research_request_hash(request: AgentResearchCreate) -> str:
    payload = {"interface": RESEARCH_INTERFACE, **request.model_dump(mode="json")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()


def _replay(task, digest):
    if task.request_hash != digest or task.run_config.get("interface") != RESEARCH_INTERFACE:
        raise APIError(409, "IDEMPOTENCY_CONFLICT", "该幂等键已用于不同请求")
    return {"task_id": task.id, "status": task.status}, True


def submit_research(sessions, settings, request: AgentResearchCreate, key: str | None, *, user_id: UUID):
    validate_idempotency_key(key)
    digest = research_request_hash(request)
    try:
        with sessions.begin() as session:
            lock_active_user(session, user_id)
            if key is not None:
                existing = session.scalar(select(Task).where(Task.user_id == user_id, Task.idempotency_key == key))
                if existing is not None:
                    return _replay(existing, digest)
            ensure_agent_ready(settings, unavailable_code="AGENT_NOT_CONNECTED",
                unavailable_message="研究服务暂未连接，请稍后再试。")
            check_task_capacity(session, user_id, settings.user_active_tasks, settings.user_daily_tasks)
            rows = list(session.scalars(select(Paper).where(
                Paper.user_id == user_id, Paper.id.in_(request.paper_ids),
            ).order_by(Paper.id).with_for_update()))
            by_id = {paper.id: paper for paper in rows}
            missing = [paper_id for paper_id in request.paper_ids if paper_id not in by_id]
            if missing:
                raise APIError(404, "PAPER_NOT_FOUND", "部分论文不存在", {
                    "missing_paper_ids": [str(paper_id) for paper_id in missing],
                })
            papers = [by_id[paper_id] for paper_id in request.paper_ids]
            if any(paper.status not in {"uploaded", "processing", "ready"} for paper in papers):
                raise APIError(409, "PAPER_NOT_READY", "选定论文尚不可用于执行任务")
            accepted = create_research_task(session, settings, request, papers, user_id=user_id,
                key=key, digest=digest, interface=RESEARCH_INTERFACE)
            return {"task_id": accepted["id"], "status": accepted["status"]}, False
    except IntegrityError:
        if key is not None:
            with sessions() as session:
                existing = session.scalar(select(Task).where(Task.user_id == user_id, Task.idempotency_key == key))
                if existing is not None:
                    return _replay(existing, digest)
        raise
