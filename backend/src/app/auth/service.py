from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.auth.mail import encrypt_payload, make_payload
from app.auth.rates import mail_limits, rate_limits
from app.auth.security import check_config, hash_password, new_token, normalize_email, normalize_username, token_hash, validate_password, verify_password
from app.db.models import AuthEmailToken, AuthMailOutbox, AuthSession, User
from app.errors import APIError


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def db_now(session) -> datetime:
    clock = func.clock_timestamp() if session.bind.dialect.name == "postgresql" else func.current_timestamp()
    value = session.scalar(select(clock))
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return aware(value)


def usable_token(token, now) -> bool:
    return not token.consumed_at and not token.revoked_at and aware(token.expires_at) > now


def active_session(user: User | None, current: AuthSession | None, now: datetime) -> bool:
    return bool(
        user and user.status == "active" and user.email_verified_at and current
        and current.user_id == user.id and current.revoked_at is None
        and aware(current.expires_at) > now and current.auth_version == user.auth_version
    )


def unauthorized() -> APIError:
    return APIError(401, "AUTH_REQUIRED", "Please sign in")


def invalid_token() -> APIError:
    return APIError(400, "AUTH_TOKEN_INVALID", "The link is invalid or expired")


def invalid_credentials() -> APIError:
    return APIError(401, "INVALID_CREDENTIALS", "Invalid username or password")


class AuthService:
    def __init__(self, sessions, settings):
        self.sessions = sessions
        self.settings = settings

    def limits(self, limits):
        rate_limits(self.sessions, self.settings, limits)

    def register(self, username, email, password, ip, locale="en") -> None:
        check_config(self.settings, mail=True)
        username, username_key = normalize_username(username)
        email, email_key = normalize_email(email)
        validate_password(password)
        self.limits([("register_ip", ip, 10, 3600)] + mail_limits(ip, email_key))
        encoded = hash_password(password)
        try:
            with self.sessions.begin() as session:
                self.prune_conflicts(session, username_key, email_key)
                now = db_now(session)
                user = User(id=uuid4(), username=username, username_key=username_key, email=email, email_key=email_key,
                            password_hash=encoded, status="pending", auth_version=1, created_at=now, updated_at=now)
                session.add(user)
                session.flush()
                self.issue_email(session, user, "verify_email", locale, now)
        except IntegrityError:
            raise APIError(409, "REGISTRATION_UNAVAILABLE", "This registration information is unavailable") from None

    def prune_conflicts(self, session, username_key, email_key):
        candidates = session.scalars(select(User).where(or_(User.username_key == username_key, User.email_key == email_key))
                                    .order_by(User.id).with_for_update()).all()
        now = db_now(session)
        for user in candidates:
            if user.status != "pending" or aware(user.created_at) + timedelta(days=1) > now:
                continue
            if session.scalar(select(AuthSession.id).where(AuthSession.user_id == user.id).limit(1)):
                continue
            try:
                with session.begin_nested():
                    session.execute(delete(User).where(User.id == user.id))
            except IntegrityError:
                pass

    def issue_email(self, session, user, purpose, locale, now):
        self.revoke_tokens(session, user.id, now, purpose)
        raw = new_token()
        ttl = self.settings.auth_verify_ttl_seconds if purpose == "verify_email" else self.settings.auth_reset_ttl_seconds
        expiry = now + timedelta(seconds=ttl)
        if purpose == "verify_email":
            expiry = min(expiry, aware(user.created_at) + timedelta(days=1))
        token = AuthEmailToken(id=uuid4(), user_id=user.id, purpose=purpose, token_hash=token_hash(raw),
                               expires_at=expiry, created_at=now)
        session.add(token)
        session.flush()
        payload = make_payload(self.settings, purpose, user.email, user.username, raw, locale,
                               ttl_seconds=max(1, int((expiry - now).total_seconds())))
        session.add(AuthMailOutbox(id=uuid4(), user_id=user.id, token_id=token.id,
                                  payload_ciphertext=encrypt_payload(self.settings, payload), locale=locale,
                                  status="queued", attempts=0, next_attempt_at=now, created_at=now, updated_at=now))

    def revoke_tokens(self, session, user_id, now, purpose=None):
        condition = [AuthEmailToken.user_id == user_id, AuthEmailToken.revoked_at.is_(None), AuthEmailToken.consumed_at.is_(None)]
        if purpose:
            condition.append(AuthEmailToken.purpose == purpose)
        token_ids = select(AuthEmailToken.id).where(*condition)
        session.execute(update(AuthMailOutbox).where(AuthMailOutbox.token_id.in_(token_ids),
                        AuthMailOutbox.status.in_(["queued", "sending"])).values(
                            status="failed", payload_ciphertext=None, worker_id=None,
                            lease_expires_at=None, error_code="TOKEN_REVOKED", updated_at=now))
        session.execute(update(AuthEmailToken).where(*condition).values(revoked_at=now))

    def email_request(self, email, purpose, ip, locale="en") -> None:
        check_config(self.settings, mail=True)
        if purpose not in {"verify_email", "reset_password"}:
            raise ValueError("Invalid token purpose")
        email_key = normalize_email(email)[1]
        self.limits(mail_limits(ip, email_key))
        with self.sessions.begin() as session:
            user = session.scalar(select(User).where(User.email_key == email_key).with_for_update())
            now = db_now(session)
            expected = "pending" if purpose == "verify_email" else "active"
            if not user or user.status != expected:
                return
            if purpose == "verify_email" and aware(user.created_at) + timedelta(days=1) <= now:
                return
            self.issue_email(session, user, purpose, locale, now)

    def locked_token(self, session, raw, purpose):
        if not 32 <= len(raw) <= 256:
            raise invalid_token()
        user_id = session.scalar(select(AuthEmailToken.user_id).where(AuthEmailToken.token_hash == token_hash(raw),
                                                                 AuthEmailToken.purpose == purpose))
        if not user_id:
            raise invalid_token()
        user = session.scalar(select(User).where(User.id == user_id).with_for_update())
        token = session.scalar(select(AuthEmailToken).where(AuthEmailToken.token_hash == token_hash(raw),
                                AuthEmailToken.purpose == purpose).with_for_update())
        now = db_now(session)
        expected = "pending" if purpose == "verify_email" else "active"
        if not user or user.status != expected or not token or not usable_token(token, now):
            raise invalid_token()
        if purpose == "verify_email" and aware(user.created_at) + timedelta(days=1) <= now:
            raise invalid_token()
        return user, token, now

    def verify_email(self, raw, password, ip) -> None:
        check_config(self.settings)
        self.limits([("token_ip", ip, 30, 900)])
        with self.sessions.begin() as session:
            user, token, now = self.locked_token(session, raw, "verify_email")
            if not verify_password(user.password_hash, password):
                raise invalid_token()
            user.status = "active"
            user.email_verified_at = now
            user.updated_at = now
            self.revoke_tokens(session, user.id, now, "verify_email")
            token.consumed_at = now
            token.revoked_at = None

    def login(self, username, password, ip):
        check_config(self.settings)
        self.limits([("login_ip", ip, 30, 60), ("login_username", username.strip().lower(), 10, 900)])
        with self.sessions.begin() as session:
            user = session.scalar(select(User).where(User.username_key == username.strip().lower()).with_for_update())
            if not verify_password(user.password_hash if user else None, password) or user.username != username.strip():
                raise invalid_credentials()
            if user.status == "pending":
                raise APIError(403, "EMAIL_NOT_VERIFIED", "Please verify your email before signing in")
            if user.status != "active" or not user.email_verified_at:
                raise invalid_credentials()
            raw, now = new_token(), db_now(session)
            session.add(AuthSession(id=uuid4(), user_id=user.id, token_hash=token_hash(raw), auth_version=user.auth_version,
                                   expires_at=now + timedelta(seconds=self.settings.auth_session_ttl_seconds), created_at=now))
        return user, raw

    def session_user(self, session, raw, *, lock=False):
        if not raw or not 32 <= len(raw) <= 256:
            raise unauthorized()
        user_id = session.scalar(select(AuthSession.user_id).where(AuthSession.token_hash == token_hash(raw)))
        if not user_id:
            raise unauthorized()
        statement = select(User).where(User.id == user_id)
        user = session.scalar(statement.with_for_update() if lock else statement)
        statement = select(AuthSession).where(AuthSession.token_hash == token_hash(raw))
        current = session.scalar(statement.with_for_update() if lock else statement)
        if not active_session(user, current, db_now(session)):
            raise unauthorized()
        return user, current

    def authenticate(self, raw):
        check_config(self.settings)
        with self.sessions.begin() as session:
            return self.session_user(session, raw)

    def logout(self, raw) -> None:
        check_config(self.settings)
        with self.sessions.begin() as session:
            user, current = self.session_user(session, raw, lock=True)
            current.revoked_at = db_now(session)

    def replace_password(self, session, user, encoded, now):
        user.password_hash = encoded
        user.auth_version += 1
        user.updated_at = now
        session.execute(update(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None)).values(revoked_at=now))
        self.revoke_tokens(session, user.id, now)

    def reset_password(self, raw, password, ip) -> None:
        check_config(self.settings)
        validate_password(password)
        self.limits([("token_ip", ip, 30, 900)])
        encoded = hash_password(password)
        with self.sessions.begin() as session:
            user, token, now = self.locked_token(session, raw, "reset_password")
            self.replace_password(session, user, encoded, now)
            token.consumed_at = now
            token.revoked_at = None

    def change_password(self, user_id, raw, current_password, password, ip) -> None:
        check_config(self.settings)
        validate_password(password)
        self.limits([("change_ip", ip, 30, 900), ("change_user", str(user_id), 10, 900)])
        encoded = hash_password(password)
        with self.sessions.begin() as session:
            user, current = self.session_user(session, raw, lock=True)
            if user.id != user_id:
                raise unauthorized()
            if not verify_password(user.password_hash, current_password):
                raise APIError(400, "CURRENT_PASSWORD_INCORRECT", "当前密码不正确，请重新输入。")
            self.replace_password(session, user, encoded, db_now(session))
            current.revoked_at = None
            current.auth_version = user.auth_version
