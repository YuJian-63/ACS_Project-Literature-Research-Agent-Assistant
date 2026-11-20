from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from starlette.responses import StreamingResponse

from app.api.pagination import Limit, Offset
from app.api.papers import CurrentUser, get_paper, stream_paper_file
from app.api.schemas import ErrorResponse, Page, PaperStatus
from app.auth.agent_library import issue_library_token, require_library_user
from app.db.models import Paper
from app.errors import APIError

router = APIRouter(prefix="/api/v1/agent", tags=["Agent library"], responses={401: {"model": ErrorResponse}})
LibraryUser = Annotated[UUID, Depends(require_library_user)]


class LibraryToken(BaseModel):
    access_token: str
    token_type: Literal["Bearer"]
    expires_at: datetime


class LibraryPaper(BaseModel):
    id: UUID
    title: str
    original_filename: str
    status: PaperStatus
    page_count: int | None
    size_bytes: int
    sha256: str
    download_url: str


@router.post("/library-token", response_model=LibraryToken, responses={403: {"model": ErrorResponse}})
def create_library_token(request: Request, user: CurrentUser) -> dict:
    return issue_library_token(request, user)


@router.get("/papers", response_model=Page[LibraryPaper])
def search_library(
    request: Request, user_id: LibraryUser, limit: Limit = 20, offset: Offset = 0,
    status: PaperStatus | None = None, q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    match_mode: Annotated[Literal["all", "any"], Query(alias="match")] = "all",
) -> dict:
    conditions = [Paper.user_id == user_id]
    if status is not None:
        conditions.append(Paper.status == status)
    if q is not None:
        keywords = q.split()
        if not keywords or "\x00" in q:
            raise APIError(422, "INVALID_REQUEST", "q 必须包含关键词且不能包含空字节")
        keyword_conditions = [
            or_(Paper.title.icontains(keyword, autoescape=True), Paper.original_filename.icontains(keyword, autoescape=True))
            for keyword in keywords
        ]
        conditions.append((and_ if match_mode == "all" else or_)(*keyword_conditions))
    with request.app.state.sessions() as session:
        total = session.scalar(select(func.count()).select_from(Paper).where(*conditions))
        papers = session.execute(
            select(Paper.id, Paper.title, Paper.original_filename, Paper.status, Paper.page_count, Paper.size_bytes, Paper.sha256)
            .where(*conditions).order_by(Paper.created_at.desc(), Paper.id.desc()).offset(offset).limit(limit)
        ).mappings()
        items = [
            {**paper, "download_url": request.url_for("download_library_pdf", paper_id=str(paper["id"])).path}
            for paper in papers
        ]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get(
    "/papers/{paper_id}/pdf", response_class=StreamingResponse,
    responses={200: {"content": {"application/pdf": {}}}},
)
def download_library_pdf(request: Request, paper_id: UUID, user_id: LibraryUser) -> StreamingResponse:
    with request.app.state.sessions() as session:
        return stream_paper_file(request, get_paper(session, paper_id, user_id), disposition="attachment")
