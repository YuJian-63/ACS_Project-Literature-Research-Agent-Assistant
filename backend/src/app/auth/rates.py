from datetime import timedelta

from sqlalchemy import case, delete, select
from sqlalchemy.dialects.postgresql import insert

from app.auth.security import check_config, keyed_hash
from app.db.models import AuthRateBucket
from app.errors import APIError


def rate_limits(sessions, settings, limits) -> None:
    from app.auth.service import db_now
    check_config(settings)
    blocked = False
    retry_after = 1
    with sessions.begin() as session:
        now = db_now(session)
        expired = select(AuthRateBucket.bucket_key).where(AuthRateBucket.expires_at <= now).limit(100)
        session.execute(delete(AuthRateBucket).where(AuthRateBucket.expires_at <= now,
                                                     AuthRateBucket.bucket_key.in_(expired)))
        for scope, target, maximum, seconds in sorted(limits):
            key = keyed_hash(settings.auth_rate_key, scope + ":" + target)
            statement = insert(AuthRateBucket).values(bucket_key=key, count=1, expires_at=now + timedelta(seconds=seconds))
            stale = AuthRateBucket.expires_at <= now
            statement = statement.on_conflict_do_update(index_elements=[AuthRateBucket.bucket_key], set_={
                "count": case((stale, 1), else_=AuthRateBucket.count + 1),
                "expires_at": case((stale, now + timedelta(seconds=seconds)), else_=AuthRateBucket.expires_at),
            }).returning(AuthRateBucket.count, AuthRateBucket.expires_at)
            count, expiry = session.execute(statement).one()
            if count > maximum:
                from app.auth.service import aware
                blocked = True
                retry_after = max(retry_after, int((aware(expiry) - now).total_seconds()) + 1)
    if blocked:
        raise APIError(429, "AUTH_RATE_LIMITED", "Please try again later", headers={"Retry-After": str(retry_after)})


def mail_limits(ip, email):
    return [("mail_email_cooldown", email, 1, 60), ("mail_email_hour", email, 5, 3600),
            ("mail_ip", ip, 20, 3600), ("mail_global", "all", 100, 3600)]
