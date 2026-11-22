"""Allow up to four concurrent research jobs while keeping the selected limit."""
from alembic import op

revision = "20261122_0013"
down_revision = "20261122_0012"
branch_labels = None
depends_on = None

TABLE = "agent_queue_settings"
CHECK = "agent_queue_settings_concurrency_check"


def upgrade():
    op.drop_constraint(CHECK, TABLE, type_="check")
    op.create_check_constraint(CHECK, TABLE, "concurrency BETWEEN 1 AND 4")


def downgrade():
    op.execute("UPDATE agent_queue_settings SET concurrency = 2 WHERE concurrency > 2")
    op.drop_constraint(CHECK, TABLE, type_="check")
    op.create_check_constraint(CHECK, TABLE, "concurrency IN (1, 2)")
