from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy import func, select, union_all, literal

from app.api.agent_research_schemas import (
    AgentResearchAccepted, AgentResearchCreate, AgentResearchRecord, AgentResearchSummary,
)
from app.api.pagination import Limit, Offset
from app.api.schemas import Page, TaskStatus
from app.api.views import resource_error
from app.auth.dependencies import require_user
from app.db.models import AgentRun, Task, User, AgentResearch, ResearchPaper, Paper
from app.errors import APIError
from app.tasks.service import ensure_task_deletable
from app.tasks.unified import get_research, research_filters, research_references, submit_research

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
    legacy_conditions = [AgentResearch.user_id == user.id]
    if status is not None:
        conditions.append(Task.status == status)
        legacy_conditions.append(AgentResearch.status == status)
    # Paginate both generations together so existing v3 records stay accessible.
    records = union_all(
        select(Task.id, Task.question, Task.status, Task.created_at, literal(False).label("legacy"))
        .where(*conditions),
        select(AgentResearch.id, AgentResearch.question, AgentResearch.status,
            AgentResearch.created_at, literal(True).label("legacy")).where(*legacy_conditions),
    ).subquery()
    with request.app.state.sessions() as session:
        total = session.scalar(select(func.count()).select_from(records))
        rows = session.execute(select(records).order_by(records.c.created_at.desc(), records.c.id.desc())
            .offset(offset).limit(limit)).all()
        references = research_references(session, [row.id for row in rows if not row.legacy], user.id)
        references.update(legacy_references(session, [row.id for row in rows if row.legacy], user.id))
        return {"items": [{"id": row.id, "question": row.question, "status": row.status,
            "paper_ids": [paper["id"] for paper in references[row.id]], "papers": references[row.id],
            "created_at": row.created_at} for row in rows], "total": total, "limit": limit, "offset": offset}


def legacy_references(session, identifiers, user_id):
    references = {identifier: [] for identifier in identifiers}
    if identifiers:
        for research_id, paper_id, title in session.execute(
            select(ResearchPaper.research_id, Paper.id, Paper.title)
            .join(Paper, (Paper.id == ResearchPaper.paper_id) & (Paper.user_id == ResearchPaper.user_id))
            .where(ResearchPaper.research_id.in_(identifiers), ResearchPaper.user_id == user_id)
            .order_by(ResearchPaper.selection_order)
        ):
            references[research_id].append({"id": paper_id, "title": title})
    return references



@router.get("/{task_id}", response_model=AgentResearchRecord)
def get_record(task_id: UUID, request: Request, user: CurrentUser):
    with request.app.state.sessions() as session:
        previous = session.scalar(select(AgentResearch).where(
            AgentResearch.id == task_id, AgentResearch.user_id == user.id))
        if previous is not None:
            papers = legacy_references(session, [task_id], user.id)[task_id]
            result = previous.result
            if result is not None:
                result = {"task_id": str(task_id), "question": previous.question,
                    "stop_reason": "completed", "usage": {}, **result}
            return {"task_id": task_id, "question": previous.question, "status": previous.status,
                "paper_ids": [paper["id"] for paper in papers], "result": result, "error": previous.error}
        task = get_research(session, task_id, user.id)
        run = session.get(AgentRun, task_id)
        if run is None:
            raise APIError(500, "INTERNAL_ERROR", "研究执行记录不可用")
        papers = research_references(session, [task_id], user.id)[task_id]
        return {"task_id": task.id, "question": task.question, "status": task.status,
            "paper_ids": [paper["id"] for paper in papers], "result": run.result, "error": resource_error(task)}


@router.delete("/{task_id}", status_code=204)
def delete_record(task_id: UUID, request: Request, user: CurrentUser):
    with request.app.state.sessions.begin() as session:
        previous = session.scalar(select(AgentResearch).where(
            AgentResearch.id == task_id, AgentResearch.user_id == user.id).with_for_update())
        if previous is not None:
            if previous.status == "running":
                raise APIError(409, "TASK_RUNNING", "研究正在执行，请等待完成后再删除")
            session.delete(previous)
        else:
            task = get_research(session, task_id, user.id, lock=True)
            ensure_task_deletable(session, task)
            session.delete(task)
    return Response(status_code=204)
