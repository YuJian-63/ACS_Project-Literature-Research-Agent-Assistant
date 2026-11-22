"""Store the live concurrency limit for the shared research queue."""
import sqlalchemy as sa
from alembic import op

revision = "20261122_0012"
down_revision = "20261122_0011"
branch_labels = None
depends_on = None


def upgrade():
    table = op.create_table("agent_queue_settings",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column("concurrency", sa.Integer, nullable=False, server_default=sa.text("2")),
        sa.CheckConstraint("id = 1"), sa.CheckConstraint("concurrency IN (1, 2)"))
    op.bulk_insert(table, [{"id": 1, "concurrency": 2}])


def downgrade():
    op.drop_table("agent_queue_settings")
