import hmac
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.agent_bridge.contracts import DispatchManifest
from app.auth.security import check_config, keyed_hash
from app.auth.service import active_session, aware, db_now, unauthorized
from app.config import Settings
from app.db.models import AgentRun, AuthSession, Task, User
from app.errors import APIError

TOKEN_TTL = timedelta(minutes=30)
TOKEN_FORMAT = re.compile(r"v1\.([0-9a-f]{32})\.([0-9]{1,12})\.([0-9a-f]{64})")
JOB_TOKEN_FORMAT = re.compile(r"job-v1\.([0-9a-f]{32})\.([0-9]{1,12})\.([0-9a-f]{64})")
library_bearer = HTTPBearer(auto_error=False, scheme_name="AgentLibraryToken")


@dataclass(frozen=True)
class LibraryAccess:
    user_id: UUID
    selected_only: frozenset[UUID] | None = None


def library_signature(settings, claims: str) -> str:
    return keyed_hash(settings.auth_csrf_key, f"agent-paper-library:{claims}")


def issue_job_library_token(settings: Settings, dispatch_id: UUID, deadline: float) -> str:
    key = settings.auth_csrf_key
    if not key or len(key.get_secret_value().encode()) < 32:
        raise ValueError("A configured signing key is required for job library access")
    claims = f"job-v1.{dispatch_id.hex}.{int(deadline)}"
    signature = keyed_hash(key, f"agent-job-library-read:{claims}")
    return f"{claims}.{signature}"


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


def require_library_access(
    request: Request, credential: Annotated[HTTPAuthorizationCredentials | None, Depends(library_bearer)],
) -> LibraryAccess:
    settings = request.app.state.settings
    check_config(settings)
    if credential is None:
        raise library_unauthorized()
    token = credential.credentials
    job = JOB_TOKEN_FORMAT.fullmatch(token)
    if job is not None:
        dispatch_id, expiry, _ = job.groups()
        expected = issue_job_library_token(settings, UUID(hex=dispatch_id), int(expiry))
        if not hmac.compare_digest(token, expected):
            raise library_unauthorized()
        with request.app.state.sessions() as session:
            now = db_now(session)
            if now.timestamp() >= int(expiry):
                raise library_unauthorized()
            row = session.execute(
                select(Task.user_id, Task.started_at, Task.timeout_seconds, AgentRun.manifest)
                .select_from(AgentRun).join(Task, Task.id == AgentRun.task_id).join(User, User.id == Task.user_id)
                .where(AgentRun.dispatch_id == UUID(hex=dispatch_id), User.status == "active",
                    Task.runner_type == "agent", Task.status.in_(("running", "queued")), Task.started_at.is_not(None))
            ).one_or_none()
            if row is None or now >= aware(row.started_at) + timedelta(seconds=row.timeout_seconds):
                raise library_unauthorized()
            manifest = DispatchManifest.model_validate(row.manifest)
            selected_only = None if manifest.task.allow_search else frozenset(source.paper_id for source in manifest.sources)
            return LibraryAccess(row.user_id, selected_only)

    parsed = TOKEN_FORMAT.fullmatch(token)
    if parsed is None:
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
        return LibraryAccess(account.User.id)
