from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, APIRouter, Header, Query, Request, Response
from sqlalchemy import func, select

from app.api.pagination import Limit, Offset
from app.api.schemas import (
    ArtifactList, EventPage, Page, TaskAccepted, TaskCreate, TaskResponse,
    TaskStatus, TaskSummary, TaskType, WorkflowType,
)
from app.api.views import summary_view, task_view
from app.db.models import Artifact, Citation, Paper, Task, TaskEvent
from app.errors import APIError
from app.tasks.service import get_task, selected_papers, submit_task

from app.auth.dependencies import require_user
from app.db.models import User

CurrentUser = Annotated[User, Depends(require_user)]

router = APIRouter()


@router.post("/api/v1/tasks", status_code=202, response_model=TaskAccepted)
def create_task(
    request: Request, body: TaskCreate, response: Response, user: CurrentUser,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> dict:
    if len(request.headers.getlist("idempotency-key")) > 1:
        raise APIError(422, "INVALID_REQUEST", "Idempotency-Key 不能重复")
    result, replayed = submit_task(request.app.state.sessions, request.app.state.settings, body, idempotency_key, user_id=user.id)
    response.headers["Location"] = f"/api/v1/tasks/{result['id']}"
    response.headers["Idempotency-Replayed"] = str(replayed).lower()
    return result


@router.get("/api/v1/tasks", response_model=Page[TaskSummary])
def list_tasks(
    request: Request, user: CurrentUser, limit: Limit = 20, offset: Offset = 0,
    status: TaskStatus | None = None, task_type: TaskType | None = None,
    workflow_type: WorkflowType | None = None, is_mock: Literal["true", "false"] | None = None,
) -> dict:
    conditions = [Task.user_id == user.id]
    for column, value in ((Task.status, status), (Task.task_type, task_type), (Task.workflow_type, workflow_type)):
        if value is not None:
            conditions.append(column == value)
    if is_mock is not None:
        conditions.append(Task.runner_type == ("mock" if is_mock == "true" else "langgraph"))
    with request.app.state.sessions() as session:
        total = session.scalar(select(func.count()).select_from(Task).where(*conditions))
        tasks = list(session.scalars(
            select(Task).where(*conditions).order_by(Task.created_at.desc(), Task.id.desc()).offset(offset).limit(limit)
        ))
        papers = selected_papers(session, [task.id for task in tasks])
        return {
            "items": [summary_view(task, papers[task.id]) for task in tasks],
            "total": total, "limit": limit, "offset": offset,
        }


@router.get("/api/v1/tasks/{task_id}", response_model=TaskResponse)
def task_detail(request: Request, task_id: UUID, user: CurrentUser) -> dict:
    with request.app.state.sessions() as session:
        task = get_task(session, task_id, user.id)
        return task_view(task, selected_papers(session, [task_id])[task_id])


@router.get("/api/v1/tasks/{task_id}/events", response_model=EventPage)
def task_events(
    request: Request, task_id: UUID, user: CurrentUser, after_seq: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict:
    with request.app.state.sessions() as session:
        get_task(session, task_id, user.id)
        events = list(session.scalars(
            select(TaskEvent).where(TaskEvent.task_id == task_id, TaskEvent.seq > after_seq)
            .order_by(TaskEvent.seq).limit(limit + 1)
        ))
        items = [
            {name: getattr(event, name) for name in (
                "task_id", "seq", "event_type", "status", "stage", "message", "payload", "created_at"
            )} for event in events[:limit]
        ]
        return {
            "items": items, "next_after_seq": items[-1]["seq"] if items else after_seq,
            "has_more": len(events) > limit,
        }


@router.get("/api/v1/tasks/{task_id}/artifacts", response_model=ArtifactList)
def task_artifacts(request: Request, task_id: UUID, user: CurrentUser) -> dict:
    with request.app.state.sessions() as session:
        task = get_task(session, task_id, user.id)
        if task.status != "succeeded":
            return {"items": []}
        artifact = session.scalar(select(Artifact).where(Artifact.task_id == task_id))
        if artifact is None or task.runner_type not in {"mock", "langgraph"}:
            raise APIError(500, "INTERNAL_ERROR", "任务结果不可用")
        citation_rows = list(session.execute(
            select(Citation, Paper.title).join(Paper, Paper.id == Citation.paper_id)
            .where(Citation.artifact_id == artifact.id)
        ))
        citation_rows.sort(key=lambda row: int(row[0].citation_key[1:]))
        return {"items": [{
            **{name: getattr(artifact, name) for name in (
                "id", "task_id", "schema_version", "title", "content_markdown", "comparison_table", "created_at"
            )},
            "task_type": task.task_type, "is_mock": task.runner_type == "mock",
            "citations": [{
                "id": citation.id, "citation_key": citation.citation_key,
                "paper_id": citation.paper_id, "paper_title": paper_title,
                "chunk_id": citation.chunk_id, "page_number": citation.page_number,
                "quote": citation.quote,
            } for citation, paper_title in citation_rows],
        }]}
