from alembic.migration import MigrationContext
from fastapi import APIRouter, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.schemas import HealthResponse
from app.errors import APIError

router = APIRouter()


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
