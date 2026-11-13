"""Add durable staged review evidence, checkpoints and usage reservations."""

from alembic import op

revision: str = "20261114_0003"
down_revision: str = "20261112_0002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE tasks ADD COLUMN review_state jsonb NOT NULL DEFAULT '{}'::jsonb")
    op.execute("ALTER TABLE tasks ADD CONSTRAINT ck_tasks_review_state_object CHECK (jsonb_typeof(review_state) = 'object')")
    op.execute("ALTER TABLE tasks DROP CONSTRAINT tasks_lifecycle")
    op.execute("""ALTER TABLE tasks ADD CONSTRAINT tasks_lifecycle CHECK (
        (status = 'queued' AND stage = 'queued' AND (started_at IS NULL OR workflow_version = 'langgraph-review-v2')
            AND finished_at IS NULL AND worker_id IS NULL AND lease_expires_at IS NULL)
        OR (status = 'running' AND started_at IS NOT NULL AND finished_at IS NULL
            AND worker_id IS NOT NULL AND lease_expires_at IS NOT NULL AND lease_expires_at > started_at)
        OR (status = 'succeeded' AND started_at IS NOT NULL AND finished_at IS NOT NULL
            AND worker_id IS NULL AND lease_expires_at IS NULL)
        OR (status = 'failed' AND stage = 'failed' AND finished_at IS NOT NULL
            AND worker_id IS NULL AND lease_expires_at IS NULL))""")


def downgrade() -> None:
    op.execute("ALTER TABLE tasks DROP CONSTRAINT tasks_lifecycle")
    op.execute("""ALTER TABLE tasks ADD CONSTRAINT tasks_lifecycle CHECK (
        (status = 'queued' AND stage = 'queued' AND started_at IS NULL
            AND finished_at IS NULL AND worker_id IS NULL AND lease_expires_at IS NULL)
        OR (status = 'running' AND started_at IS NOT NULL AND finished_at IS NULL
            AND worker_id IS NOT NULL AND lease_expires_at IS NOT NULL AND lease_expires_at > started_at)
        OR (status = 'succeeded' AND started_at IS NOT NULL AND finished_at IS NOT NULL
            AND worker_id IS NULL AND lease_expires_at IS NULL)
        OR (status = 'failed' AND stage = 'failed' AND finished_at IS NOT NULL
            AND worker_id IS NULL AND lease_expires_at IS NULL))""")
    op.execute("ALTER TABLE tasks DROP CONSTRAINT ck_tasks_review_state_object")
    op.execute("ALTER TABLE tasks DROP COLUMN review_state")
