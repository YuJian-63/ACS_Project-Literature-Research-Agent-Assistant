"""Allow larger Agent step budgets without rewriting existing research."""
from alembic import op

revision = "20261122_0015"
down_revision = "20261122_0014"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("tasks_max_steps_check", "tasks", type_="check")
    op.create_check_constraint("tasks_max_steps_check", "tasks", "max_steps BETWEEN 1 AND 200")


def downgrade():
    op.drop_constraint("tasks_max_steps_check", "tasks", type_="check")
    op.create_check_constraint("tasks_max_steps_check", "tasks", "max_steps BETWEEN 1 AND 100")
