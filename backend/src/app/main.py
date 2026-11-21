import logging
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from alembic.script import ScriptDirectory
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from app.api.router import router
from app.auth.api import router as auth_router
from app.auth.dependencies import AuthResponseMiddleware
from app.config import Settings
from app.db.session import create_database_engine, create_session_factory
from app.errors import APIError
from app.tasks.lifecycle import TaskMonitor
from app.papers.storage import MAX_FILE_BYTES

logger = logging.getLogger(__name__)


class RequestMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if scope["method"] == "POST" and scope["path"].rstrip("/") == "/api/v1/papers":
                received += len(message.get("body", b""))
                if received > MAX_FILE_BYTES + 64 * 1024:
                    raise APIError(413, "FILE_TOO_LARGE", "文件最大为 50 MB，multipart 元数据最大为 64 KB")
            return message

        async def send_with_id(message):
            if message["type"] == "http.response.start":
                headers = [(key, value) for key, value in message.get("headers", []) if key.lower() != b"x-request-id"]
                message["headers"] = headers + [(b"x-request-id", request_id.encode("ascii"))]
            await send(message)

        await self.app(scope, limited_receive, send_with_id)


class ErrorMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def track_response(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, track_response)
        except Exception:
            if started:
                raise
            request_id = scope["state"]["request_id"]
            logger.error("Unhandled request failure: request_id=%s", request_id)
            await JSONResponse({"error": {
                "code": "INTERNAL_ERROR", "message": "服务内部错误", "details": {}
            }}, status_code=500)(scope, receive, send)


def create_app(settings: Settings | None = None, engine: Engine | None = None, *, arxiv_client=None) -> FastAPI:
    from app.sources.arxiv import ArxivClient, ArxivError
    from app.sources.arxiv_transport import SupervisedArxivTransport
    from app.api.imports import router as import_router
    from app.sources.access import SearchCache, source_permit
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        database = engine if engine is not None else create_database_engine(settings)
        application.state.engine = database
        application.state.sessions = create_session_factory(database)
        application.state.arxiv_client = arxiv_client
        if arxiv_client is None and settings.arxiv_configured:
            application.state.arxiv_client = ArxivClient(SupervisedArxivTransport(
                settings.arxiv_contact_email, lambda: source_permit(application.state.sessions),
            ))
        monitor = TaskMonitor(application.state.sessions) if settings.task_monitor_enabled else None
        try:
            if monitor is not None:
                await run_in_threadpool(monitor.start)
            yield
        finally:
            if monitor is not None and monitor.thread.is_alive():
                await run_in_threadpool(monitor.close)
            if engine is None:
                await run_in_threadpool(database.dispose)

    application = FastAPI(title="Literature Research Agent Assistant", version="0.1.0", lifespan=lifespan)
    application.state.settings = settings
    application.state.arxiv_cache = SearchCache()
    application.state.migration_heads = set(ScriptDirectory(str(Path(__file__).resolve().parents[2] / "alembic_v3")).get_heads())

    @application.exception_handler(APIError)
    async def api_error_handler(request: Request, error: APIError):
        return JSONResponse({"error": error.error}, status_code=error.status_code, headers=error.headers)

    @application.exception_handler(ArxivError)
    async def arxiv_error_handler(request: Request, error: ArxivError):
        status = {"ARXIV_RATE_LIMITED": 429, "ARXIV_TIMEOUT": 504}.get(error.code, 502)
        details = {"retry_after_seconds": error.retry_after} if error.retry_after else {}
        headers = {"Retry-After": str(error.retry_after)} if error.retry_after else None
        return JSONResponse({"error": {"code": error.code, "message": error.message, "details": details}}, status_code=status, headers=headers)

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, error: RequestValidationError):
        fields = [{
            "location": ".".join(str(part) for part in item["loc"]), "message": item["msg"]
        } for item in error.errors()]
        return JSONResponse({"error": {
            "code": "INVALID_REQUEST", "message": "请求参数不合法", "details": {"fields": fields}
        }}, status_code=422)

    @application.exception_handler(HTTPException)
    async def http_error_handler(request: Request, error: HTTPException):
        return JSONResponse({"error": {
            "code": "INVALID_REQUEST", "message": "请求路径、方法或格式不合法", "details": {}
        }}, status_code=error.status_code, headers=error.headers)

    @application.exception_handler(SQLAlchemyError)
    async def database_error_handler(request: Request, error: SQLAlchemyError):
        logger.warning("Database request failed: request_id=%s", request.state.request_id)
        return JSONResponse({"error": {
            "code": "SERVICE_NOT_READY", "message": "数据库暂不可用", "details": {}
        }}, status_code=503)

    application.include_router(auth_router)
    application.include_router(router)
    application.include_router(import_router)
    application.add_middleware(ErrorMiddleware)
    application.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["GET", "POST", "DELETE"],
        allow_credentials=True,
        allow_headers=["Content-Type", "Idempotency-Key", "X-CSRF-Token"],
        expose_headers=["X-Request-ID", "Location", "Idempotency-Replayed", "Retry-After"],
    )
    application.add_middleware(AuthResponseMiddleware)
    application.add_middleware(RequestMiddleware)
    return application
