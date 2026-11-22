from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy import func, select

from app.api.agent_research_schemas import (
    AgentResearchAccepted, AgentResearchCreate, AgentResearchRecord, AgentResearchSummary, QueueConcurrency,
)
from app.api.pagination import Limit, Offset
from app.api.schemas import Page, TaskStatus
from app.api.views import resource_error
from app.auth.dependencies import require_user
from app.db.models import AgentQueueSettings, AgentRun, Task, User
from app.errors import APIError
from app.task_metrics.service import task_metrics
from app.tasks.service import ensure_task_deletable
from app.tasks.lifecycle import lock_agent_queue
from app.tasks.unified import get_research, history_papers, research_filters, research_references, submit_research

router = APIRouter(prefix="/api/v1/agent-research")
CurrentUser = Annotated[User, Depends(require_user)]


@router.post("", status_code=202, response_model=AgentResearchAccepted)
def create_record(request: Request, body: AgentResearchCreate, response: Response, user: CurrentUser,
    idempotency_key: Annotated[str | None, Header()] = None):
    if len(request.headers.getlist("idempotency-key")) > 1:
        raise APIError(422, "INVALID_REQUEST", "Idempotency-Key 不能重复")
    result, replayed = submit_research(request.app.state.sessions, request.app.state.settings,
        body, idempotency_key, user_id=user.id)
    response.headers["Location"] = f"/api/v1/agent-research/{result['task_id']}"
    response.headers["Idempotency-Replayed"] = str(replayed).lower()
    return result


@router.get("", response_model=Page[AgentResearchSummary])
def list_records(request: Request, user: CurrentUser, limit: Limit = 20, offset: Offset = 0,
    status: TaskStatus | None = None):
    conditions = [*research_filters(user.id)]
    if status is not None:
        conditions.append(Task.status == status)
    with request.app.state.sessions() as session:
        total = session.scalar(select(func.count()).select_from(Task).where(*conditions))
        rows = list(session.scalars(select(Task).where(*conditions)
            .order_by(Task.created_at.desc(), Task.id.desc()).offset(offset).limit(limit)))
        references = research_references(session, [task.id for task in rows], user.id)
        papers = history_papers(session, references, user.id)
        return {"items": [{"id": task.id, "question": task.question, "status": task.status,
            "paper_ids": [paper["id"] for paper in references[task.id]], "papers": papers[task.id],
            "created_at": task.created_at} for task in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/queue/concurrency", response_model=QueueConcurrency)
def read_concurrency(request: Request, user: CurrentUser):
    with request.app.state.sessions() as session:
        queue = session.get(AgentQueueSettings, 1)
        return {"concurrency": queue.concurrency if queue else 2}


@router.put("/queue/concurrency", response_model=QueueConcurrency)
def update_concurrency(body: QueueConcurrency, request: Request, user: CurrentUser):
    with request.app.state.sessions.begin() as session:
        lock_agent_queue(session).concurrency = body.concurrency
    return body


@router.get("/{task_id}", response_model=AgentResearchRecord)
def get_record(task_id: UUID, request: Request, user: CurrentUser):
    with request.app.state.sessions() as session:
        task = get_research(session, task_id, user.id)
        run = session.get(AgentRun, task_id)
        if run is None:
            raise APIError(500, "INTERNAL_ERROR", "研究执行记录不可用")
        papers = research_references(session, [task_id], user.id)[task_id]
        return {"task_id": task.id, "question": task.question, "status": task.status,
            "paper_ids": [paper["id"] for paper in papers], "result": run.result, "error": resource_error(task),
            "metrics": task_metrics(session, task, run, request.app.state.settings)}


@router.delete("/{task_id}", status_code=204)
def delete_record(task_id: UUID, request: Request, user: CurrentUser):
    with request.app.state.sessions.begin() as session:
        task = get_research(session, task_id, user.id, lock=True)
        ensure_task_deletable(session, task)
        session.delete(task)
    return Response(status_code=204)
