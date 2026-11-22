"""Keep each user's shared TACC endpoint separate from the managed GPU service."""
from alembic import op
import sqlalchemy as sa

revision = "20261122_0011"
down_revision = "20261122_0010"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("shared_model_endpoints",
        sa.Column("user_id", sa.Uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("base_url", sa.Text, nullable=False))


def downgrade():
    op.drop_table("shared_model_endpoints")
