import os
from typing import Annotated, Literal
from urllib.parse import quote
from uuid import UUID

from alembic.migration import MigrationContext
from fastapi import APIRouter, Header, Query, Request, Response
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.responses import StreamingResponse

from app.db.models import Artifact, Citation, Paper, Task, TaskEvent
from app.errors import APIError
from app.schemas import (
    ArtifactList, ErrorResponse, EventPage, HealthResponse, Page, PaperResponse, PaperStatus,
    TaskAccepted, TaskCreate, TaskResponse, TaskStatus, TaskSummary, TaskType, WorkflowType,
)
from app.storage import controlled_path, save_paper
from app.tasks import get_task, selected_papers, submit_task
from app.views import paper_view, summary_view, task_view

router = APIRouter(responses={
    status: {"model": ErrorResponse} for status in (404, 409, 413, 415, 422, 500, 503)
})
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


def get_paper(session: Session, paper_id: UUID) -> Paper:
    paper = session.get(Paper, paper_id)
    if paper is None:
        raise APIError(404, "PAPER_NOT_FOUND", "论文不存在")
    return paper


@router.get("/health", response_model=HealthResponse)
def health() -> dict:
    return {"status": "ok"}


@router.get("/ready", response_model=HealthResponse)
def ready(request: Request) -> dict:
    try:
        with request.app.state.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            heads = set(MigrationContext.configure(connection).get_current_heads())
        if heads != request.app.state.migration_heads:
            raise APIError(503, "SERVICE_NOT_READY", "数据库迁移尚未就绪")
    except SQLAlchemyError:
        raise APIError(503, "SERVICE_NOT_READY", "数据库尚未就绪") from None
    return {"status": "ready"}


@router.post(
    "/api/v1/papers", status_code=201, response_model=PaperResponse,
    openapi_extra={"requestBody": {"required": True, "content": {"multipart/form-data": {
        "schema": {
            "type": "object", "required": ["file"], "additionalProperties": False,
            "properties": {"file": {"type": "string", "format": "binary"}},
        }
    }}}},
)
async def upload_paper(request: Request) -> dict:
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "multipart/form-data":
        raise APIError(415, "UNSUPPORTED_MEDIA_TYPE", "上传须使用 multipart/form-data")
    try:
        async with request.form(max_files=1, max_fields=0) as form:
            parts = form.multi_items()
            if len(parts) != 1 or parts[0][0] != "file" or not isinstance(parts[0][1], UploadFile):
                raise APIError(422, "INVALID_REQUEST", "必须且只能包含一个 file 文件字段")
            upload = parts[0][1]
            return await run_in_threadpool(
                save_paper, request.app.state.sessions, request.app.state.settings.storage_root,
                upload.file, upload.filename,
            )
    except HTTPException:
        raise APIError(422, "INVALID_REQUEST", "multipart 请求不合法或包含多余字段") from None
    except OSError:
        raise APIError(500, "STORAGE_WRITE_FAILED", "上传临时文件写入失败") from None


@router.get("/api/v1/papers", response_model=Page[PaperResponse])
def list_papers(
    request: Request, limit: Limit = 20, offset: Offset = 0,
    status: PaperStatus | None = None, q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
) -> dict:
    conditions = []
    if status is not None:
        conditions.append(Paper.status == status)
    if q is not None:
        if "\x00" in q:
            raise APIError(422, "INVALID_REQUEST", "q 不能包含空字节")
        conditions.append(or_(Paper.title.contains(q, autoescape=True), Paper.original_filename.contains(q, autoescape=True)))
    with request.app.state.sessions() as session:
        total = session.scalar(select(func.count()).select_from(Paper).where(*conditions))
        papers = session.scalars(
            select(Paper).where(*conditions).order_by(Paper.created_at.desc(), Paper.id.desc())
            .offset(offset).limit(limit)
        )
        return {"items": [paper_view(paper) for paper in papers], "total": total, "limit": limit, "offset": offset}


@router.get("/api/v1/papers/{paper_id}", response_model=PaperResponse)
def paper_detail(request: Request, paper_id: UUID) -> dict:
    with request.app.state.sessions() as session:
        return paper_view(get_paper(session, paper_id))


@router.get("/api/v1/papers/{paper_id}/file", response_class=StreamingResponse, responses={200: {"content": {"application/pdf": {}}}})
def paper_file(request: Request, paper_id: UUID) -> StreamingResponse:
    with request.app.state.sessions() as session:
        paper = get_paper(session, paper_id)
        try:
            path = controlled_path(request.app.state.settings.storage_root, paper_id, paper.storage_key)
            source = path.open("rb")
            size = os.fstat(source.fileno()).st_size
        except (OSError, ValueError):
            raise APIError(500, "FILE_UNAVAILABLE", "论文文件不可用") from None
        filename = paper.original_filename

    def chunks():
        try:
            while chunk := source.read(64 * 1024):
                yield chunk
        finally:
            source.close()

    return StreamingResponse(
        chunks(), media_type="application/pdf", background=BackgroundTask(source.close),
        headers={
            "Content-Disposition": f"inline; filename*=utf-8''{quote(filename, safe='')}",
            "Content-Length": str(size), "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/api/v1/tasks", status_code=202, response_model=TaskAccepted)
def create_task(
    request: Request, body: TaskCreate, response: Response,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> dict:
    if len(request.headers.getlist("idempotency-key")) > 1:
        raise APIError(422, "INVALID_REQUEST", "Idempotency-Key 不能重复")
    result, replayed = submit_task(request.app.state.sessions, request.app.state.settings, body, idempotency_key)
    response.headers["Location"] = f"/api/v1/tasks/{result['id']}"
    response.headers["Idempotency-Replayed"] = str(replayed).lower()
    return result


@router.get("/api/v1/tasks", response_model=Page[TaskSummary])
def list_tasks(
    request: Request, limit: Limit = 20, offset: Offset = 0,
    status: TaskStatus | None = None, task_type: TaskType | None = None,
    workflow_type: WorkflowType | None = None, is_mock: Literal["true", "false"] | None = None,
) -> dict:
    conditions = []
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
def task_detail(request: Request, task_id: UUID) -> dict:
    with request.app.state.sessions() as session:
        task = get_task(session, task_id)
        return task_view(task, selected_papers(session, [task_id])[task_id])


@router.get("/api/v1/tasks/{task_id}/events", response_model=EventPage)
def task_events(
    request: Request, task_id: UUID, after_seq: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict:
    with request.app.state.sessions() as session:
        get_task(session, task_id)
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
def task_artifacts(request: Request, task_id: UUID) -> dict:
    with request.app.state.sessions() as session:
        task = get_task(session, task_id)
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
