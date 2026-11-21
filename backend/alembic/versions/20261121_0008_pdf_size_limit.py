"""Increase uploaded and imported PDF size limit to 50 MB."""

from alembic import op

revision = "20261121_0008"
down_revision = "20261120_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("papers_size_bytes_check", "papers", type_="check")
    op.create_check_constraint("papers_size_bytes_check", "papers", "size_bytes BETWEEN 1 AND 52428800")


def downgrade() -> None:
    op.drop_constraint("papers_size_bytes_check", "papers", type_="check")
    op.create_check_constraint("papers_size_bytes_check", "papers", "size_bytes BETWEEN 1 AND 20971520")
