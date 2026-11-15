import hmac

from fastapi import Request
from starlette.datastructures import MutableHeaders

from app.auth.security import check_config, cookie_name, csrf_token
from app.auth.service import AuthService
from app.db.models import User
from app.errors import APIError


def auth_service(request: Request) -> AuthService:
    return AuthService(request.app.state.sessions, request.app.state.settings)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def require_origin(request: Request) -> None:
    settings = request.app.state.settings
    check_config(settings)
    if request.headers.get("origin") != settings.frontend_public_url.rstrip("/"):
        raise APIError(403, "ORIGIN_REJECTED", "Request origin is not allowed")


def require_user(request: Request) -> User:
    settings = request.app.state.settings
    check_config(settings)
    raw = request.cookies.get(cookie_name(settings))
    user, current = auth_service(request).authenticate(raw)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_origin(request)
        supplied = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(supplied.encode("utf-8"), csrf_token(settings, raw).encode("ascii")):
            raise APIError(403, "CSRF_REJECTED", "Request verification failed")
    request.state.auth_user = user
    request.state.auth_session_id = current.id
    return user


class AuthResponseMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api/v1/"):
            return await self.app(scope, receive, send)

        async def no_store(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "no-store"
                headers["Pragma"] = "no-cache"
                headers["Referrer-Policy"] = "no-referrer"
            await send(message)

        await self.app(scope, receive, no_store)
