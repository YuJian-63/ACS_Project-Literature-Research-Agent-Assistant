"""Increase uploaded and imported PDF size limit to 50 MB."""

from alembic import op

revision = "v3_0003"
down_revision = "v3_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("papers_size_bytes_check", "papers", type_="check")
    op.create_check_constraint("papers_size_bytes_check", "papers", "size_bytes BETWEEN 1 AND 52428800")


def downgrade() -> None:
    op.drop_constraint("papers_size_bytes_check", "papers", type_="check")
    op.create_check_constraint("papers_size_bytes_check", "papers", "size_bytes BETWEEN 1 AND 20971520")
