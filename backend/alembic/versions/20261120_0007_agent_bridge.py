"""Add Agent dispatch and native results without rewriting historical artifacts."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261120_0007"
down_revision = "20261118_0006"
branch_labels = None
depends_on = None


def lifecycle(workflows: str) -> str:
    return f"""ALTER TABLE tasks ADD CONSTRAINT tasks_lifecycle CHECK (
        (status = 'queued' AND stage = 'queued' AND (started_at IS NULL OR workflow_version IN ({workflows}))
            AND finished_at IS NULL AND worker_id IS NULL AND lease_expires_at IS NULL)
        OR (status = 'running' AND started_at IS NOT NULL AND finished_at IS NULL
            AND worker_id IS NOT NULL AND lease_expires_at IS NOT NULL AND lease_expires_at > started_at)
        OR (status = 'succeeded' AND started_at IS NOT NULL AND finished_at IS NOT NULL
            AND worker_id IS NULL AND lease_expires_at IS NULL)
        OR (status = 'failed' AND stage = 'failed' AND finished_at IS NOT NULL
            AND worker_id IS NULL AND lease_expires_at IS NULL))"""


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "source_metadata" not in {column["name"] for column in inspector.get_columns("paper_imports")}:
        op.add_column("paper_imports", sa.Column("source_metadata", postgresql.JSONB(none_as_null=True), nullable=True))
    if inspector.has_table("agent_runs"):
        expected = {"task_id", "dispatch_id", "input_sha256", "manifest", "result", "remote_job_id", "stop_reason", "created_at", "updated_at"}
        citations = {column["name"]: column for column in inspector.get_columns("citations")}
        if (expected != {column["name"] for column in inspector.get_columns("agent_runs")}
                or not {"agent_chunk_id", "agent_source_id"}.issubset(citations)
                or not citations["chunk_id"]["nullable"]):
            raise RuntimeError("Existing Agent schema is incomplete; inspect it before upgrading")
        return
    op.drop_constraint("tasks_runner_type_check", "tasks", type_="check")
    op.create_check_constraint("tasks_runner_type_check", "tasks", "runner_type IN ('mock', 'langgraph', 'agent')")
    op.drop_constraint("tasks_lifecycle", "tasks", type_="check")
    op.execute(lifecycle("'langgraph-review-v2', 'langgraph-search-v1', 'agent-io-v1'"))
    op.create_table("agent_runs",
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("dispatch_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("manifest", postgresql.JSONB(), nullable=False),
        sa.Column("result", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("remote_job_id", sa.String(256), nullable=True),
        sa.Column("stop_reason", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("input_sha256 ~ '^[0-9a-f]{64}$'", name="agent_runs_input_sha256"),
        sa.CheckConstraint("jsonb_typeof(manifest) = 'object'", name="agent_runs_manifest_object"),
        sa.CheckConstraint("result IS NULL OR jsonb_typeof(result) = 'object'", name="agent_runs_result_object"))
    op.alter_column("citations", "chunk_id", existing_type=sa.Uuid(), nullable=True)
    op.add_column("citations", sa.Column("agent_chunk_id", sa.Text(), nullable=True))
    op.add_column("citations", sa.Column("agent_source_id", sa.Text(), nullable=True))
    op.create_check_constraint("citations_evidence_identity", "citations",
        "(chunk_id IS NOT NULL AND agent_chunk_id IS NULL AND agent_source_id IS NULL) "
        "OR (chunk_id IS NULL AND length(btrim(agent_chunk_id)) > 0 AND agent_chunk_id IS NOT NULL "
        "AND length(btrim(agent_source_id)) > 0 AND agent_source_id IS NOT NULL)")


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM tasks WHERE runner_type = 'agent')
            OR EXISTS (SELECT 1 FROM citations WHERE chunk_id IS NULL) THEN
            RAISE EXCEPTION 'Agent task data exists; export or remove it explicitly before downgrade';
        END IF;
    END $$""")
    op.drop_constraint("citations_evidence_identity", "citations", type_="check")
    op.drop_column("citations", "agent_source_id")
    op.drop_column("citations", "agent_chunk_id")
    op.alter_column("citations", "chunk_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_table("agent_runs")
    op.drop_constraint("tasks_lifecycle", "tasks", type_="check")
    op.execute(lifecycle("'langgraph-review-v2', 'langgraph-search-v1'"))
    op.drop_constraint("tasks_runner_type_check", "tasks", type_="check")
    op.create_check_constraint("tasks_runner_type_check", "tasks", "runner_type IN ('mock', 'langgraph')")
