import os
from typing import Annotated, Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import Depends, APIRouter, Query, Request
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.responses import StreamingResponse

from app.api.pagination import Limit, Offset
from app.api.schemas import Page, PaperResponse, PaperStatus
from app.api.views import paper_view
from app.db.models import Paper, PaperImport, PaperSource, TaskPaper
from app.errors import APIError
from app.papers.storage import controlled_path, remove_file, save_paper

from app.auth.dependencies import require_user
from app.db.models import User

CurrentUser = Annotated[User, Depends(require_user)]

router = APIRouter()


def get_paper(session: Session, paper_id: UUID, user_id: UUID) -> Paper:
    paper = session.scalar(select(Paper).where(Paper.id == paper_id, Paper.user_id == user_id))
    if paper is None:
        raise APIError(404, "PAPER_NOT_FOUND", "论文不存在")
    return paper


@router.post(
    "/api/v1/papers", status_code=201, response_model=PaperResponse,
    openapi_extra={"requestBody": {"required": True, "content": {"multipart/form-data": {
        "schema": {
            "type": "object", "required": ["file"], "additionalProperties": False,
            "properties": {"file": {"type": "string", "format": "binary"}},
        }
    }}}},
)
async def upload_paper(request: Request, user: CurrentUser) -> dict:
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
                upload.file, upload.filename, user_id=user.id,
            )
    except HTTPException:
        raise APIError(422, "INVALID_REQUEST", "multipart 请求不合法或包含多余字段") from None
    except OSError:
        raise APIError(500, "STORAGE_WRITE_FAILED", "上传临时文件写入失败") from None


@router.get("/api/v1/papers", response_model=Page[PaperResponse])
def list_papers(
    request: Request, user: CurrentUser, limit: Limit = 20, offset: Offset = 0,
    status: PaperStatus | None = None, q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
) -> dict:
    conditions = [Paper.user_id == user.id]
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
def paper_detail(request: Request, paper_id: UUID, user: CurrentUser) -> dict:
    with request.app.state.sessions() as session:
        return paper_view(get_paper(session, paper_id, user.id))


@router.delete("/api/v1/papers/{paper_id}", status_code=204)
def delete_paper(request: Request, paper_id: UUID, user: CurrentUser) -> None:
    with request.app.state.sessions.begin() as session:
        paper = session.scalar(select(Paper).where(Paper.id == paper_id, Paper.user_id == user.id).with_for_update())
        if paper is None:
            raise APIError(404, "PAPER_NOT_FOUND", "论文不存在")
        if session.scalar(select(TaskPaper.paper_id).where(TaskPaper.paper_id == paper_id).limit(1)) is not None:
            raise APIError(409, "PAPER_IN_USE", "论文已被研究任务引用，无法删除")
        if paper.status == "processing":
            raise APIError(409, "PAPER_PROCESSING", "论文正在解析，请稍后再删除")
        path = controlled_path(request.app.state.settings.storage_root, paper_id, paper.storage_key)
        session.execute(delete(PaperImport).where(PaperImport.paper_id == paper_id))
        session.execute(delete(PaperSource).where(PaperSource.paper_id == paper_id))
        session.delete(paper)
    remove_file(path)


@router.get("/api/v1/papers/{paper_id}/file", response_class=StreamingResponse, responses={200: {"content": {"application/pdf": {}}}})
def paper_file(request: Request, paper_id: UUID, user: CurrentUser) -> StreamingResponse:
    with request.app.state.sessions() as session:
        return stream_paper_file(request, get_paper(session, paper_id, user.id))


def stream_paper_file(
    request: Request, paper: Paper, *, disposition: Literal["inline", "attachment"] = "inline",
) -> StreamingResponse:
    source = None
    try:
        path = controlled_path(request.app.state.settings.storage_root, paper.id, paper.storage_key)
        source = path.open("rb")
        size = os.fstat(source.fileno()).st_size
    except (OSError, ValueError):
        if source is not None:
            source.close()
        raise APIError(500, "FILE_UNAVAILABLE", "论文文件不可用") from None
    filename = quote(paper.original_filename, safe="")

    def chunks():
        try:
            while chunk := source.read(64 * 1024):
                yield chunk
        finally:
            source.close()

    return StreamingResponse(
        chunks(), media_type="application/pdf", background=BackgroundTask(source.close),
        headers={
            "Content-Disposition": f"{disposition}; filename*=utf-8''{filename}",
            "Content-Length": str(size), "X-Content-Type-Options": "nosniff",
        },
    )
