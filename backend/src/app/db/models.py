from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
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
        CheckConstraint("size_bytes BETWEEN 1 AND 52428800", name="papers_size_bytes_check"),
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


class Task(UUIDPrimaryKey, CreatedAt, UpdatedAt, Base):
    __tablename__ = "tasks"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    task_type: Mapped[str] = mapped_column(Text)
    question: Mapped[str | None] = mapped_column(Text)
    workflow_type: Mapped[str] = mapped_column(Text, server_default="baseline")
    runner_type: Mapped[str] = mapped_column(Text)
    workflow_version: Mapped[str] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    model_id: Mapped[str | None] = mapped_column(Text)
    dataset_version: Mapped[str | None] = mapped_column(Text)
    run_config: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    review_state: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    max_steps: Mapped[int] = mapped_column(Integer, server_default=text("10"))
    max_tokens: Mapped[int] = mapped_column(Integer, server_default=text("8000"))
    timeout_seconds: Mapped[int] = mapped_column(Integer, server_default=text("120"))
    status: Mapped[str] = mapped_column(Text, server_default="queued")
    stage: Mapped[str] = mapped_column(String(64), server_default="queued")
    worker_id: Mapped[UUID | None]
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_event_seq: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int | None] = mapped_column(BigInteger)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger)
    model_calls: Mapped[int | None] = mapped_column(BigInteger)
    tool_calls: Mapped[int | None] = mapped_column(BigInteger)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    error_details: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("id", "user_id", name="tasks_owner_identity"),
        UniqueConstraint("user_id", "idempotency_key", name="tasks_owner_idempotency"),
        Index("tasks_owner_created_idx", "user_id", text("created_at DESC")),
        CheckConstraint("task_type IN ('summary', 'qa', 'review')"),
        CheckConstraint("workflow_type IN ('baseline', 'extended')"),
        CheckConstraint("runner_type IN ('mock', 'langgraph', 'agent')", name="tasks_runner_type_check"),
        CheckConstraint("length(btrim(workflow_version)) > 0"),
        CheckConstraint("length(btrim(prompt_version)) > 0"),
        CheckConstraint("length(btrim(model_id)) > 0"),
        CheckConstraint("length(btrim(dataset_version)) > 0"),
        CheckConstraint("jsonb_typeof(run_config) = 'object'"),
        CheckConstraint("jsonb_typeof(review_state) = 'object'", name="ck_tasks_review_state_object"),
        CheckConstraint("max_steps BETWEEN 1 AND 100"),
        CheckConstraint("max_tokens BETWEEN 1 AND 100000"),
        CheckConstraint("timeout_seconds BETWEEN 1 AND 1800"),
        CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')"),
        CheckConstraint("stage ~ '^[a-z][a-z0-9_]{0,63}$'"),
        CheckConstraint("last_event_seq >= 0"),
        CheckConstraint("request_hash ~ '^[0-9a-f]{64}$'"),
        CheckConstraint("input_tokens >= 0"),
        CheckConstraint("output_tokens >= 0"),
        CheckConstraint("model_calls >= 0"),
        CheckConstraint("tool_calls >= 0"),
        CheckConstraint(
            "(task_type = 'summary' AND (question IS NULL OR length(btrim(question)) BETWEEN 1 AND 8000)) "
            "OR (task_type IN ('qa', 'review') AND question IS NOT NULL AND length(btrim(question)) BETWEEN 1 AND 8000)",
            name="tasks_question",
        ),
        CheckConstraint(
            "idempotency_key IS NULL OR (length(btrim(idempotency_key)) BETWEEN 1 AND 128 "
            "AND idempotency_key = btrim(idempotency_key))",
            name="tasks_idempotency_key",
        ),
        CheckConstraint(
            "updated_at >= created_at AND (started_at IS NULL OR started_at >= created_at) "
            "AND (finished_at IS NULL OR finished_at >= coalesce(started_at, created_at))",
            name="tasks_timestamps",
        ),
        CheckConstraint(
            "(status = 'queued' AND stage = 'queued' AND (started_at IS NULL OR workflow_version IN ('langgraph-review-v2', 'langgraph-search-v1', 'agent-io-v1')) AND finished_at IS NULL "
            "AND worker_id IS NULL AND lease_expires_at IS NULL) "
            "OR (status = 'running' AND started_at IS NOT NULL AND finished_at IS NULL "
            "AND worker_id IS NOT NULL AND lease_expires_at IS NOT NULL AND lease_expires_at > started_at) "
            "OR (status = 'succeeded' AND started_at IS NOT NULL AND finished_at IS NOT NULL "
            "AND worker_id IS NULL AND lease_expires_at IS NULL) "
            "OR (status = 'failed' AND stage = 'failed' AND finished_at IS NOT NULL "
            "AND worker_id IS NULL AND lease_expires_at IS NULL)",
            name="tasks_lifecycle",
        ),
        CheckConstraint(
            "(status = 'failed' AND error_code IS NOT NULL AND length(btrim(error_code)) > 0 "
            "AND error_message IS NOT NULL AND length(btrim(error_message)) > 0 "
            "AND error_details IS NOT NULL AND jsonb_typeof(error_details) = 'object') "
            "OR (status <> 'failed' AND error_code IS NULL AND error_message IS NULL AND error_details IS NULL)",
            name="tasks_error_state",
        ),
        CheckConstraint(
            "runner_type <> 'mock' OR (model_id IS NULL AND input_tokens IS NULL "
            "AND output_tokens IS NULL AND model_calls IS NULL AND tool_calls IS NULL)",
            name="tasks_mock_usage",
        ),
        Index("tasks_created_idx", text("created_at DESC"), text("id DESC")),
        Index("tasks_status_created_idx", "status", text("created_at DESC"), text("id DESC")),
        Index("tasks_queue_idx", "created_at", "id", postgresql_where=text("status = 'queued'")),
        Index("tasks_expired_lease_idx", "lease_expires_at", postgresql_where=text("status = 'running'")),
    )


class AgentRun(CreatedAt, UpdatedAt, Base):
    __tablename__ = "agent_runs"

    task_id: Mapped[UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    dispatch_id: Mapped[UUID] = mapped_column(unique=True)
    input_sha256: Mapped[str] = mapped_column(String(64))
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    remote_job_id: Mapped[str | None] = mapped_column(String(256))
    stop_reason: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        CheckConstraint("input_sha256 ~ '^[0-9a-f]{64}$'", name="agent_runs_input_sha256"),
        CheckConstraint("jsonb_typeof(manifest) = 'object'", name="agent_runs_manifest_object"),
        CheckConstraint("result IS NULL OR jsonb_typeof(result) = 'object'", name="agent_runs_result_object"),
    )


class TaskPaper(CreatedAt, Base):
    __tablename__ = "task_papers"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))

    task_id: Mapped[UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    paper_id: Mapped[UUID] = mapped_column(primary_key=True)
    paper_sha256: Mapped[str] = mapped_column(String(64))
    selection_order: Mapped[int | None] = mapped_column(SmallInteger)

    __table_args__ = (
        CheckConstraint("selection_order BETWEEN 0 AND 19"),
        UniqueConstraint("task_id", "selection_order", name="task_papers_order"),
        ForeignKeyConstraint(["task_id", "user_id"], ["tasks.id", "tasks.user_id"], name="task_papers_task_owner", ondelete="CASCADE"),
        ForeignKeyConstraint(["paper_id", "user_id"], ["papers.id", "papers.user_id"], name="task_papers_paper_owner", ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["paper_id", "paper_sha256"], ["papers.id", "papers.sha256"],
            name="task_papers_source", ondelete="RESTRICT", onupdate="RESTRICT",
        ),
        Index("task_papers_paper_idx", "paper_id", "task_id"),
    )


class TaskEvent(CreatedAt, Base):
    __tablename__ = "task_events"

    task_id: Mapped[UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    event_type: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    stage: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(String(2000))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))

    __table_args__ = (
        CheckConstraint("seq >= 1"),
        CheckConstraint("event_type IN ('status', 'stage', 'warning', 'error')"),
        CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')"),
        CheckConstraint("stage ~ '^[a-z][a-z0-9_]{0,63}$'"),
        CheckConstraint("length(btrim(message)) > 0"),
        CheckConstraint("jsonb_typeof(payload) = 'object'"),
    )


class Artifact(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "artifacts"

    task_id: Mapped[UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), unique=True)
    schema_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    title: Mapped[str] = mapped_column(String(255))
    content_markdown: Mapped[str] = mapped_column(Text)
    comparison_table: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))

    __table_args__ = (
        CheckConstraint("schema_version = 1"),
        CheckConstraint("length(btrim(title)) > 0"),
        CheckConstraint("length(btrim(content_markdown)) > 0"),
        UniqueConstraint("id", "task_id", name="artifacts_task_identity"),
        CheckConstraint(
            "comparison_table IS NULL OR (jsonb_typeof(comparison_table) = 'object' "
            "AND comparison_table ?& ARRAY['columns', 'rows'] "
            "AND jsonb_typeof(comparison_table -> 'columns') = 'array' "
            "AND jsonb_typeof(comparison_table -> 'rows') = 'array')",
            name="artifacts_comparison_table",
        ),
    )


class Citation(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "citations"

    artifact_id: Mapped[UUID]
    task_id: Mapped[UUID]
    citation_key: Mapped[str] = mapped_column(String(32))
    paper_id: Mapped[UUID]
    chunk_id: Mapped[UUID | None]
    agent_chunk_id: Mapped[str | None] = mapped_column(Text)
    agent_source_id: Mapped[str | None] = mapped_column(Text)
    page_number: Mapped[int] = mapped_column(Integer)
    quote: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("citation_key ~ '^C[1-9][0-9]*$'"),
        CheckConstraint(
            "(chunk_id IS NOT NULL AND agent_chunk_id IS NULL AND agent_source_id IS NULL) "
            "OR (chunk_id IS NULL AND length(btrim(agent_chunk_id)) > 0 AND agent_chunk_id IS NOT NULL "
            "AND length(btrim(agent_source_id)) > 0 AND agent_source_id IS NOT NULL)",
            name="citations_evidence_identity",
        ),
        CheckConstraint("page_number >= 1"),
        CheckConstraint("length(btrim(quote)) > 0"),
        UniqueConstraint("artifact_id", "citation_key", name="citations_key"),
        ForeignKeyConstraint(
            ["artifact_id", "task_id"], ["artifacts.id", "artifacts.task_id"],
            name="citations_artifact", ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["task_id", "paper_id"], ["task_papers.task_id", "task_papers.paper_id"],
            name="citations_selected_paper", deferrable=True, initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["chunk_id", "paper_id", "page_number"],
            ["paper_chunks.id", "paper_chunks.paper_id", "paper_chunks.page_number"],
            name="citations_chunk_source", ondelete="RESTRICT",
        ),
        Index("citations_chunk_idx", "chunk_id", "paper_id", "page_number"),
        Index("citations_task_paper_idx", "task_id", "paper_id"),
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


class CourseService(Base):
    __tablename__ = "course_service"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    state: Mapped[str] = mapped_column(Text)
    generation: Mapped[UUID | None]
    owner_id: Mapped[UUID | None]
    job_id: Mapped[str | None] = mapped_column(Text)
    base_url: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[str | None] = mapped_column(Text)
    stop_requested: Mapped[bool] = mapped_column(server_default=text("false"))
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SharedModelEndpoint(Base):
    __tablename__ = "shared_model_endpoints"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    base_url: Mapped[str] = mapped_column(Text)


class AgentQueueSettings(Base):
    __tablename__ = "agent_queue_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    concurrency: Mapped[int] = mapped_column(Integer, server_default=text("2"))

    __table_args__ = (
        CheckConstraint("id = 1"),
        CheckConstraint("concurrency BETWEEN 1 AND 4"),
    )
