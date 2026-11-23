"""Preserve earlier reports when explicitly refreshing evaluation evidence."""
import sqlalchemy as sa
from alembic import op

revision = "20261123_0016"
down_revision = "20261122_0015"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("task_evaluations", sa.Column("revision", sa.Integer, nullable=False, server_default=sa.text("0")))
    op.drop_constraint("task_evaluations_identity", "task_evaluations", type_="unique")
    op.create_unique_constraint("task_evaluations_identity", "task_evaluations",
        ["task_id", "input_sha256", "config_sha256", "revision"])
    op.create_check_constraint("task_evaluations_revision", "task_evaluations", "revision >= 0")


def downgrade():
    duplicates = op.get_bind().execute(sa.text("SELECT 1 FROM task_evaluations GROUP BY task_id, input_sha256, "
        "config_sha256 HAVING count(*) > 1 LIMIT 1")).first()
    if duplicates:
        raise RuntimeError("Cannot downgrade while multiple evaluation revisions exist; preserve or archive them first")
    op.drop_constraint("task_evaluations_revision", "task_evaluations", type_="check")
    op.drop_constraint("task_evaluations_identity", "task_evaluations", type_="unique")
    op.create_unique_constraint("task_evaluations_identity", "task_evaluations", ["task_id", "input_sha256", "config_sha256"])
    op.drop_column("task_evaluations", "revision")
