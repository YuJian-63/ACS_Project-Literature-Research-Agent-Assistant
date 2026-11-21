"""Allow a research task to reference papers discovered after submission."""

from alembic import op

revision = "20261121_0009"
down_revision = "20261121_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("task_papers", "selection_order", nullable=True)


def downgrade() -> None:
    # PostgreSQL rejects the downgrade if it would discard the distinction for an existing result.
    op.alter_column("task_papers", "selection_order", nullable=False)
