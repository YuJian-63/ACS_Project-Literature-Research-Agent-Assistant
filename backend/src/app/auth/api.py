from fastapi import APIRouter, Depends, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.auth.dependencies import auth_service, client_ip, require_origin, require_user
from app.auth.security import cookie_name, csrf_token, normalize_email, normalize_username
from app.db.models import User
from app.errors import APIError


class AuthRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handle(request):
            if request.method == "POST":
                require_origin(request)
                if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise APIError(415, "JSON_REQUIRED", "Account requests require application/json")
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > 16384:
                        raise APIError(413, "REQUEST_TOO_LARGE", "Account request is too large")
                request._body = bytes(body)
            try:
                response = await original(request)
            except RequestValidationError:
                raise APIError(422, "INVALID_REQUEST", "Account request fields are invalid") from None
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
            return response

        return handle


class AuthInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="before")
    @classmethod
    def valid_unicode(cls, value):
        if isinstance(value, str):
            value.encode("utf-8")
        return value


class EmailInput(AuthInput):
    email: str = Field(max_length=320)

    @field_validator("email")
    @classmethod
    def email_valid(cls, value):
        return normalize_email(value)[0]


class RegisterInput(EmailInput):
    username: str = Field(max_length=64)
    password: str = Field(min_length=6, max_length=128, repr=False)

    @field_validator("username")
    @classmethod
    def username_valid(cls, value):
        return normalize_username(value)[0]


class LoginInput(AuthInput):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128, repr=False)


class TokenInput(AuthInput):
    token: str = Field(min_length=32, max_length=256, repr=False)
    password: str = Field(min_length=6, max_length=128, repr=False)


class ChangeInput(AuthInput):
    current_password: str = Field(min_length=1, max_length=128, repr=False)
    password: str = Field(min_length=6, max_length=128, repr=False)


router = APIRouter(prefix="/api/v1/auth", tags=["auth"], route_class=AuthRoute)


def locale(request):
    language = request.headers.get("accept-language", "en").split(",", 1)[0].lower()
    return "zh" if language.startswith("zh") else "en"


def user_view(user, settings, raw):
    return {"user": {"id": str(user.id), "username": user.username, "email": user.email},
            "csrf_token": csrf_token(settings, raw)}


def clear_cookie(response, settings):
    response.delete_cookie(cookie_name(settings), path="/", secure=settings.auth_cookie_secure,
                           httponly=True, samesite="lax")


@router.post("/register", status_code=202)
def register(data: RegisterInput, request: Request):
    auth_service(request).register(data.username, data.email, data.password, client_ip(request), locale(request))
    return {"accepted": True}


@router.post("/verify-email")
def verify_email(data: TokenInput, request: Request):
    auth_service(request).verify_email(data.token, data.password, client_ip(request))
    return {"ok": True}


@router.post("/resend-verification", status_code=202)
def resend(data: EmailInput, request: Request):
    auth_service(request).email_request(data.email, "verify_email", client_ip(request), locale(request))
    return {"accepted": True}


@router.post("/forgot-password", status_code=202)
def forgot(data: EmailInput, request: Request):
    auth_service(request).email_request(data.email, "reset_password", client_ip(request), locale(request))
    return {"accepted": True}


@router.post("/login")
def login(data: LoginInput, request: Request, response: Response):
    settings = request.app.state.settings
    user, raw = auth_service(request).login(data.username, data.password, client_ip(request))
    response.set_cookie(cookie_name(settings), raw, max_age=settings.auth_session_ttl_seconds, path="/",
                        secure=settings.auth_cookie_secure, httponly=True, samesite="lax")
    return user_view(user, settings, raw)


@router.get("/me")
def me(request: Request, user: User = Depends(require_user)):
    settings = request.app.state.settings
    return user_view(user, settings, request.cookies[cookie_name(settings)])


@router.post("/logout")
def logout(request: Request, response: Response, user: User = Depends(require_user)):
    settings = request.app.state.settings
    auth_service(request).logout(request.cookies[cookie_name(settings)])
    clear_cookie(response, settings)
    return {"ok": True}


@router.post("/reset-password")
def reset(data: TokenInput, request: Request, response: Response):
    auth_service(request).reset_password(data.token, data.password, client_ip(request))
    clear_cookie(response, request.app.state.settings)
    return {"ok": True}


@router.post("/change-password")
def change(data: ChangeInput, request: Request, response: Response, user: User = Depends(require_user)):
    settings = request.app.state.settings
    auth_service(request).change_password(user.id, request.cookies[cookie_name(settings)], data.current_password,
                                          data.password, client_ip(request))
    return {"ok": True}
