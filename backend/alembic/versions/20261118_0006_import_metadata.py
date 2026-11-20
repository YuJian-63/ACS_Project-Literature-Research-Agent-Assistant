"""Persist verified search metadata for independent import workers."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20261118_0006'
down_revision = '20261115_0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('paper_imports', sa.Column('source_metadata', postgresql.JSONB(none_as_null=True), nullable=True))


def downgrade() -> None:
    op.drop_column('paper_imports', 'source_metadata')
