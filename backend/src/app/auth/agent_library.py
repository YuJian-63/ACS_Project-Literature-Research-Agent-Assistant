import hmac
import re
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.auth.security import check_config, keyed_hash
from app.auth.service import active_session, aware, db_now, unauthorized
from app.db.models import AuthSession, User
from app.errors import APIError

TOKEN_TTL = timedelta(minutes=30)
TOKEN_FORMAT = re.compile(r"v1\.([0-9a-f]{32})\.([0-9]{1,12})\.([0-9a-f]{64})")
library_bearer = HTTPBearer(auto_error=False, scheme_name="AgentLibraryToken")


def library_signature(settings, claims: str) -> str:
    return keyed_hash(settings.auth_csrf_key, f"agent-paper-library:{claims}")


def issue_library_token(request: Request, user: User) -> dict:
    settings = request.app.state.settings
    with request.app.state.sessions() as session:
        current = session.get(AuthSession, request.state.auth_session_id)
        now = db_now(session)
        if not active_session(user, current, now):
            raise unauthorized()
        expiry = int(min(now + TOKEN_TTL, aware(current.expires_at)).timestamp())
        expires_at = datetime.fromtimestamp(expiry, timezone.utc)
        if expires_at <= now:
            raise unauthorized()
        claims = f"v1.{current.id.hex}.{expiry}"
    return {
        "access_token": f"{claims}.{library_signature(settings, claims)}",
        "token_type": "Bearer", "expires_at": expires_at,
    }


def library_unauthorized() -> APIError:
    return APIError(
        401, "AGENT_LIBRARY_TOKEN_REQUIRED", "A valid agent library token is required",
        headers={"WWW-Authenticate": 'Bearer realm="agent-library"'},
    )


def require_library_user(
    request: Request, credential: Annotated[HTTPAuthorizationCredentials | None, Depends(library_bearer)],
) -> UUID:
    settings = request.app.state.settings
    check_config(settings)
    if credential is None or (parsed := TOKEN_FORMAT.fullmatch(credential.credentials)) is None:
        raise library_unauthorized()
    session_id, expiry, signature = parsed.groups()
    claims = f"v1.{session_id}.{expiry}"
    if not hmac.compare_digest(signature, library_signature(settings, claims)):
        raise library_unauthorized()
    with request.app.state.sessions() as session:
        now = db_now(session)
        if int(expiry) <= now.timestamp():
            raise library_unauthorized()
        statement = select(User, AuthSession).join(AuthSession, AuthSession.user_id == User.id)
        account = session.execute(statement.where(AuthSession.id == UUID(hex=session_id))).one_or_none()
        if account is None or not active_session(account.User, account.AuthSession, now):
            raise library_unauthorized()
        return account.User.id
