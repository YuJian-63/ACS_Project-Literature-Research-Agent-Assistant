from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAt, UpdatedAt, UUIDPrimaryKey


class User(UUIDPrimaryKey, CreatedAt, UpdatedAt, Base):
    __tablename__ = 'users'
    username: Mapped[str] = mapped_column(String(32))
    username_key: Mapped[str] = mapped_column(String(32), unique=True)
    email: Mapped[str] = mapped_column(String(320))
    email_key: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default='pending')
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auth_version: Mapped[int] = mapped_column(Integer, server_default='1')
    __table_args__ = (
        CheckConstraint("status IN ('pending','active','disabled')", name='users_status'),
        CheckConstraint('auth_version > 0', name='users_auth_version'),
        CheckConstraint("status <> 'active' OR email_verified_at IS NOT NULL", name='users_verified'),
    )


class AuthSession(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = 'auth_sessions'
    user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    auth_version: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index('auth_sessions_user_idx', 'user_id'), Index('auth_sessions_expiry_idx', 'expires_at'))


class AuthEmailToken(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = 'auth_email_tokens'
    user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'))
    purpose: Mapped[str] = mapped_column(Text)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("purpose IN ('verify_email','reset_password')", name='auth_email_token_purpose'),
        Index('auth_email_tokens_user_idx', 'user_id', 'purpose'),
        Index('auth_email_tokens_expiry_idx', 'expires_at'),
    )


class AuthMailOutbox(UUIDPrimaryKey, CreatedAt, UpdatedAt, Base):
    __tablename__ = 'auth_mail_outbox'
    user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'))
    token_id: Mapped[UUID] = mapped_column(ForeignKey('auth_email_tokens.id', ondelete='CASCADE'))
    payload_ciphertext: Mapped[str | None] = mapped_column(Text)
    locale: Mapped[str] = mapped_column(String(5), server_default='zh-CN')
    status: Mapped[str] = mapped_column(Text, server_default='queued')
    attempts: Mapped[int] = mapped_column(Integer, server_default='0')
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text('now()'))
    worker_id: Mapped[UUID | None]
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    __table_args__ = (
        CheckConstraint("status IN ('queued','sending','sent','failed')", name='auth_mail_status'),
        CheckConstraint('attempts BETWEEN 0 AND 3', name='auth_mail_attempts'),
        CheckConstraint("(status = 'sending') = (worker_id IS NOT NULL AND lease_expires_at IS NOT NULL)", name='auth_mail_lease'),
        Index('auth_mail_queue_idx', 'next_attempt_at', postgresql_where=text("status = 'queued'")),
    )


class AuthRateBucket(Base):
    __tablename__ = 'auth_rate_buckets'
    bucket_key: Mapped[str] = mapped_column(Text, primary_key=True)
    count: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint('count > 0', name='auth_rate_count'), Index('auth_rate_expiry_idx', 'expires_at'))
