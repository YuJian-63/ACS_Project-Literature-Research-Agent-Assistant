"""Persist the managed course model service across browser and worker restarts."""
from alembic import op
import sqlalchemy as sa

revision = "20261122_0010"
down_revision = "20261121_0009"
branch_labels = None
depends_on = None


def upgrade():
    table = op.create_table("course_service",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column("state", sa.Text, nullable=False),
        sa.Column("generation", sa.Uuid), sa.Column("owner_id", sa.Uuid),
        sa.Column("job_id", sa.Text), sa.Column("base_url", sa.Text),
        sa.Column("detail", sa.Text), sa.Column("stop_requested", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("checked_at", sa.DateTime(timezone=True)), sa.Column("requested_at", sa.DateTime(timezone=True)))
    op.bulk_insert(table, [{"id": 1, "state": "stopped"}])


def downgrade():
    op.drop_table("course_service")
