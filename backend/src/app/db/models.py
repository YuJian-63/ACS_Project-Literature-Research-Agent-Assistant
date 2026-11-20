from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAt, UpdatedAt, UUIDPrimaryKey
from app.db.accounts import AuthEmailToken, AuthMailOutbox, AuthRateBucket, AuthSession, User


class Paper(UUIDPrimaryKey, CreatedAt, UpdatedAt, Base):
    __tablename__ = "papers"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    title: Mapped[str] = mapped_column(String(255))
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(Text, unique=True)
    content_type: Mapped[str] = mapped_column(Text, server_default="application/pdf")
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(Text, server_default="uploaded")
    page_count: Mapped[int | None] = mapped_column(Integer)
    parser_version: Mapped[str | None] = mapped_column(Text)
    parse_worker_id: Mapped[UUID | None]
    parse_lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    error_details: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))

    source: Mapped["PaperSource | None"] = relationship(lazy="selectin", uselist=False, foreign_keys="PaperSource.paper_id")

    __table_args__ = (
        CheckConstraint("length(btrim(title)) > 0"),
        CheckConstraint("length(btrim(original_filename)) > 0"),
        CheckConstraint("content_type = 'application/pdf'"),
        CheckConstraint("size_bytes BETWEEN 1 AND 20971520"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'"),
        CheckConstraint("status IN ('uploaded', 'processing', 'ready', 'failed')"),
        CheckConstraint("page_count > 0"),
        CheckConstraint("length(btrim(parser_version)) > 0"),
        UniqueConstraint("id", "sha256", name="papers_source_identity"),
        UniqueConstraint("id", "user_id", name="papers_owner_identity"),
        Index("papers_owner_created_idx", "user_id", text("created_at DESC")),
        CheckConstraint("storage_key = 'uploads/' || id::text || '.pdf'", name="papers_storage_key"),
        CheckConstraint("updated_at >= created_at", name="papers_updated_at"),
        CheckConstraint(
            "status <> 'ready' OR (page_count IS NOT NULL AND parser_version IS NOT NULL)",
            name="papers_ready",
        ),
        CheckConstraint(
            "(status = 'processing' AND parse_worker_id IS NOT NULL AND parse_lease_expires_at IS NOT NULL) "
            "OR (status <> 'processing' AND parse_worker_id IS NULL AND parse_lease_expires_at IS NULL)",
            name="papers_parse_lease",
        ),
        CheckConstraint(
            "(status = 'failed' AND error_code IS NOT NULL AND length(btrim(error_code)) > 0 "
            "AND error_message IS NOT NULL AND length(btrim(error_message)) > 0 "
            "AND error_details IS NOT NULL AND jsonb_typeof(error_details) = 'object') "
            "OR (status <> 'failed' AND error_code IS NULL AND error_message IS NULL AND error_details IS NULL)",
            name="papers_error_state",
        ),
        Index("papers_created_idx", text("created_at DESC"), text("id DESC")),
        Index("papers_status_created_idx", "status", text("created_at DESC"), text("id DESC")),
        Index("papers_sha256_idx", "sha256"),
        Index("papers_parse_queue_idx", "created_at", "id", postgresql_where=text("status = 'uploaded'")),
        Index("papers_parse_lease_idx", "parse_lease_expires_at", postgresql_where=text("status = 'processing'")),
    )


class PaperChunk(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "paper_chunks"

    paper_id: Mapped[UUID] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"))
    chunk_index: Mapped[int] = mapped_column(Integer)
    page_number: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64))
    parser_version: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("chunk_index >= 0"),
        CheckConstraint("page_number >= 1"),
        CheckConstraint("length(btrim(content)) > 0"),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'"),
        CheckConstraint("length(btrim(parser_version)) > 0"),
        UniqueConstraint("paper_id", "chunk_index", name="paper_chunks_position"),
        UniqueConstraint("id", "paper_id", "page_number", name="paper_chunks_citation_identity"),
        Index("paper_chunks_page_idx", "paper_id", "page_number", "chunk_index"),
    )


ARXIV_SOURCE_ID = r"^([0-9]{2}(0[1-9]|1[0-2])\.[0-9]{4,5}|[a-z][a-z-]*(\.[A-Z]{2})?/[0-9]{2}(0[1-9]|1[0-2])[0-9]{3})v[1-9][0-9]*$"


class PaperSource(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "paper_sources"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))

    paper_id: Mapped[UUID] = mapped_column(ForeignKey("papers.id", ondelete="RESTRICT"), unique=True)
    provider: Mapped[str] = mapped_column(Text)
    external_id: Mapped[str] = mapped_column(String(80))
    source_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB)

    __table_args__ = (
        CheckConstraint("provider = 'arxiv'"),
        CheckConstraint(f"external_id ~ '{ARXIV_SOURCE_ID}'"),
        CheckConstraint("jsonb_typeof(metadata) = 'object'"),
        UniqueConstraint("user_id", "provider", "external_id", name="paper_sources_identity"),
        ForeignKeyConstraint(["paper_id", "user_id"], ["papers.id", "papers.user_id"], name="paper_sources_paper_owner", ondelete="RESTRICT"),
        Index("paper_sources_owner_idx", "user_id"),
    )


class PaperImport(UUIDPrimaryKey, CreatedAt, UpdatedAt, Base):
    __tablename__ = "paper_imports"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))

    provider: Mapped[str] = mapped_column(Text)
    external_id: Mapped[str] = mapped_column(String(80))
    source_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    attempt: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    status: Mapped[str] = mapped_column(Text, server_default="queued")
    paper_id: Mapped[UUID | None] = mapped_column(ForeignKey("papers.id", ondelete="RESTRICT"), unique=True)
    worker_id: Mapped[UUID | None]
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    error_details: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))

    __table_args__ = (
        CheckConstraint("provider = 'arxiv'"),
        CheckConstraint(f"external_id ~ '{ARXIV_SOURCE_ID}'"),
        CheckConstraint("attempt > 0"),
        CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')"),
        UniqueConstraint("user_id", "provider", "external_id", name="paper_imports_identity"),
        ForeignKeyConstraint(["paper_id", "user_id"], ["papers.id", "papers.user_id"], name="paper_imports_paper_owner", ondelete="RESTRICT"),
        Index("paper_imports_owner_idx", "user_id"),
        CheckConstraint(
            "(status = 'succeeded' AND paper_id IS NOT NULL AND paper_id = id) "
            "OR (status <> 'succeeded' AND paper_id IS NULL)", name="paper_imports_result",
        ),
        CheckConstraint(
            "(status = 'queued' AND worker_id IS NULL AND lease_expires_at IS NULL AND started_at IS NULL AND finished_at IS NULL) "
            "OR (status = 'running' AND worker_id IS NOT NULL AND lease_expires_at IS NOT NULL AND started_at IS NOT NULL AND finished_at IS NULL) "
            "OR (status IN ('succeeded', 'failed') AND worker_id IS NULL AND lease_expires_at IS NULL AND started_at IS NOT NULL AND finished_at IS NOT NULL)",
            name="paper_imports_execution",
        ),
        CheckConstraint(
            "(status = 'failed' AND error_code IS NOT NULL AND length(btrim(error_code)) > 0 "
            "AND error_message IS NOT NULL AND length(btrim(error_message)) > 0 "
            "AND error_details IS NOT NULL AND jsonb_typeof(error_details) = 'object' "
            "AND error_details ? 'retryable' AND jsonb_typeof(error_details->'retryable') = 'boolean') "
            "OR (status <> 'failed' AND error_code IS NULL AND error_message IS NULL AND error_details IS NULL)",
            name="paper_imports_errors",
        ),
        CheckConstraint(
            "updated_at >= created_at AND (started_at IS NULL OR started_at >= created_at) "
            "AND (finished_at IS NULL OR finished_at >= started_at) "
            "AND (lease_expires_at IS NULL OR lease_expires_at > started_at)", name="paper_imports_times",
        ),
        Index("paper_imports_created_idx", text("created_at DESC"), text("id DESC")),
        Index("paper_imports_status_created_idx", "status", text("created_at DESC"), text("id DESC")),
        Index("paper_imports_queue_idx", "created_at", "id", postgresql_where=text("status = 'queued'")),
        Index("paper_imports_expired_lease_idx", "lease_expires_at", postgresql_where=text("status = 'running'")),
    )


class SourceRequestGate(Base):
    __tablename__ = "source_request_gates"

    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    next_allowed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    owner_id: Mapped[UUID | None]
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("provider = 'arxiv'"),
        CheckConstraint(
            "(owner_id IS NULL AND lease_expires_at IS NULL) OR (owner_id IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="source_request_gates_owner",
        ),
    )


class AgentResearch(UUIDPrimaryKey, CreatedAt, UpdatedAt, Base):
    __tablename__ = "agent_research"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    question: Mapped[str] = mapped_column(Text)
    allow_search: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    status: Mapped[str] = mapped_column(Text, server_default="queued")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    __table_args__ = (
        CheckConstraint("length(btrim(question)) BETWEEN 1 AND 8000", name="agent_research_question"),
        CheckConstraint("status IN ('queued','running','succeeded','failed')", name="agent_research_status"),
        UniqueConstraint("id", "user_id", name="agent_research_owner"),
        Index("agent_research_owner_created", "user_id", text("created_at DESC")),
    )


class ResearchPaper(CreatedAt, Base):
    __tablename__ = "research_papers"
    research_id: Mapped[UUID] = mapped_column(primary_key=True)
    paper_id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID]
    selection_order: Mapped[int] = mapped_column(SmallInteger)
    __table_args__ = (
        ForeignKeyConstraint(["research_id", "user_id"], ["agent_research.id", "agent_research.user_id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["paper_id", "user_id"], ["papers.id", "papers.user_id"], ondelete="RESTRICT"),
        CheckConstraint("selection_order BETWEEN 0 AND 19", name="research_papers_order"),
        UniqueConstraint("research_id", "selection_order"),
        Index("research_papers_paper", "paper_id"),
    )
