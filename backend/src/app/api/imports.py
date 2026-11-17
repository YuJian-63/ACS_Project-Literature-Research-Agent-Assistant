import logging
import time
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, APIRouter, Query, Request, Response
from pydantic import Field, field_validator
from sqlalchemy import func, select

from app.sources.arxiv import ERROR_PHASES, MAX_SEARCH_RESULTS, ArxivError, SearchSortBy, SearchSortOrder, build_search_query, normalize_arxiv_id
from app.db.models import PaperImport
from app.errors import APIError
from app.sources.imports import get_import, import_view, retry_import, submit_import
from app.api.schemas import Error, ErrorResponse, Page, PaperSourceResponse, PaperStatus, StrictModel

from app.auth.dependencies import require_user
from app.db.models import User

CurrentUser = Annotated[User, Depends(require_user)]

logger = logging.getLogger(__name__)
router = APIRouter(responses={status: {"model": ErrorResponse} for status in [404, 409, 422, 429, 502, 503, 504]})
ImportStatus = Literal["queued", "running", "succeeded", "failed"]


class ImportCreate(StrictModel):
    provider: Literal["arxiv"]
    external_id: str = Field(max_length=80)

    _identifier = field_validator("external_id")(normalize_arxiv_id)


class ImportRetry(StrictModel):
    expected_attempt: int = Field(gt=0, strict=True)


class ImportResponse(StrictModel):
    id: UUID
    provider: Literal["arxiv"]
    external_id: str
    attempt: int
    status: ImportStatus
    paper_id: UUID | None
    paper_status: PaperStatus | None
    error: Error | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class SearchPaper(PaperSourceResponse):
    import_id: UUID | None
    import_status: ImportStatus | None
    paper_id: UUID | None
    paper_status: PaperStatus | None


def require_arxiv(request: Request) -> None:
    if not request.app.state.settings.arxiv_configured:
        raise APIError(503, "ARXIV_NOT_CONFIGURED", "arXiv 搜索与导入尚未启用或缺少联系邮箱")


def accepted(response: Response, item: dict) -> dict:
    response.status_code = 202 if item["status"] in {"queued", "running"} else 200
    response.headers["Location"] = f"/api/v1/paper-imports/{item['id']}"
    return item


@router.get("/api/v1/paper-search", response_model=Page[SearchPaper])
def search_papers(
    request: Request, user: CurrentUser, q: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=MAX_SEARCH_RESULTS)] = 10, offset: Annotated[int, Query(ge=0, le=1000)] = 0,
    sort_by: SearchSortBy = "relevance", sort_order: SearchSortOrder = "descending",
) -> dict:
    try:
        normalized, _ = build_search_query(q)
    except ValueError:
        raise APIError(422, "INVALID_REQUEST", "关键词须为 1—200 字符且最多 20 个词，不得含控制字符") from None
    require_arxiv(request)
    cache = request.app.state.arxiv_cache
    page = cache.get(normalized, limit, offset, sort_by=sort_by, sort_order=sort_order)
    if page is None:
        started = time.monotonic()
        try:
            page = request.app.state.arxiv_client.search(normalized, limit=limit, offset=offset, sort_by=sort_by, sort_order=sort_order)
        except ArxivError as error:
            phase = error.phase if isinstance(error.phase, str) and error.phase in ERROR_PHASES else "unknown"
            logger.warning("arXiv search failed: request_id=%s phase=%s elapsed_ms=%d code=%s",
                           request.state.request_id, phase, round((time.monotonic() - started) * 1000), error.code)
            raise
        cache.put(normalized, limit, offset, page, sort_by=sort_by, sort_order=sort_order)
    with request.app.state.sessions() as session:
        identities = [paper.external_id for paper in page.items]
        imports = {item.external_id: item for item in session.scalars(select(PaperImport).where(PaperImport.user_id == user.id, PaperImport.provider == "arxiv", PaperImport.external_id.in_(identities)))}
        items = []
        for paper in page.items:
            item = imports.get(paper.external_id)
            local = import_view(session, item) if item is not None else None
            items.append({**paper.source_view(), "import_id": item.id if item else None,
                          "import_status": item.status if item else None, "paper_id": item.paper_id if item else None,
                          "paper_status": local["paper_status"] if local else None})
    return {"items": items, "total": page.total, "limit": limit, "offset": offset}


@router.post("/api/v1/paper-imports", response_model=ImportResponse)
def create_import(request: Request, body: ImportCreate, response: Response, user: CurrentUser) -> dict:
    require_arxiv(request)
    return accepted(response, submit_import(request.app.state.sessions, body.provider, body.external_id, user_id=user.id, settings=request.app.state.settings))


@router.get("/api/v1/paper-imports", response_model=Page[ImportResponse])
def list_imports(
    request: Request, user: CurrentUser, limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0, status: ImportStatus | None = None,
) -> dict:
    conditions = [PaperImport.user_id == user.id]
    if status is not None:
        conditions.append(PaperImport.status == status)
    with request.app.state.sessions() as session:
        total = session.scalar(select(func.count()).select_from(PaperImport).where(*conditions))
        records = session.scalars(select(PaperImport).where(*conditions).order_by(PaperImport.created_at.desc(), PaperImport.id.desc()).offset(offset).limit(limit))
        return {"items": [import_view(session, item) for item in records], "total": total, "limit": limit, "offset": offset}


@router.get("/api/v1/paper-imports/{import_id}", response_model=ImportResponse)
def import_detail(request: Request, import_id: UUID, user: CurrentUser) -> dict:
    return get_import(request.app.state.sessions, import_id, user_id=user.id)


@router.post("/api/v1/paper-imports/{import_id}/retry", response_model=ImportResponse)
def retry(request: Request, import_id: UUID, body: ImportRetry, response: Response, user: CurrentUser) -> dict:
    require_arxiv(request)
    return accepted(response, retry_import(request.app.state.sessions, import_id, body.expected_attempt, user_id=user.id, settings=request.app.state.settings))
