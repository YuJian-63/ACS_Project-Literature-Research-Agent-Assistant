"""Store independent research evaluations and their durable work queue."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261122_0014"
down_revision = "20261122_0013"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("evaluation_daily_quotas",
        sa.Column("user_id", sa.Uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("day", sa.Date, primary_key=True),
        sa.Column("reserved", sa.Integer, server_default=sa.text("0"), nullable=False),
        sa.CheckConstraint("reserved >= 0", name="evaluation_daily_quotas_reserved"))
    op.create_table("task_evaluations",
        sa.Column("id", sa.Uuid, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("task_id", sa.Uuid, sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("artifact_id", sa.Uuid),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("config_sha256", sa.String(64), nullable=False),
        sa.Column("input_payload", postgresql.JSONB, nullable=False),
        sa.Column("config", postgresql.JSONB, nullable=False),
        sa.Column("evidence", postgresql.JSONB), sa.Column("evidence_sha256", sa.String(64)),
        sa.Column("status", sa.Text, server_default=sa.text("'pending'"), nullable=False),
        sa.Column("report", postgresql.JSONB), sa.Column("usage", postgresql.JSONB),
        sa.Column("error_code", sa.String(64)),
        sa.Column("attempts", sa.Integer, server_default=sa.text("0"), nullable=False),
        sa.Column("lease_token", sa.Uuid), sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)), sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["artifact_id", "task_id"], ["artifacts.id", "artifacts.task_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("task_id", "input_sha256", "config_sha256", name="task_evaluations_identity"),
        sa.CheckConstraint("status IN ('pending', 'running', 'succeeded', 'failed', 'skipped')", name="task_evaluations_status"),
        sa.CheckConstraint("attempts >= 0", name="task_evaluations_attempts"))
    op.create_index("task_evaluations_queue_idx", "task_evaluations", ["status", "next_attempt_at"])
    op.create_index("task_evaluations_task_created_idx", "task_evaluations", ["task_id", "created_at"])


def downgrade():
    op.drop_table("task_evaluations")
    op.drop_table("evaluation_daily_quotas")
