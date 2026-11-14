"""Allow checkpointed cross-language tasks to resume without resetting deadlines."""

from alembic import op

revision = "20261115_0005"
down_revision = "20261114_0004"
branch_labels = None
depends_on = None


def lifecycle(workflows: str) -> str:
    return f"""ALTER TABLE tasks ADD CONSTRAINT tasks_lifecycle CHECK (
        (status = 'queued' AND stage = 'queued' AND (started_at IS NULL OR workflow_version IN ({workflows})) AND finished_at IS NULL
            AND worker_id IS NULL AND lease_expires_at IS NULL)
        OR (status = 'running' AND started_at IS NOT NULL AND finished_at IS NULL
            AND worker_id IS NOT NULL AND lease_expires_at IS NOT NULL AND lease_expires_at > started_at)
        OR (status = 'succeeded' AND started_at IS NOT NULL AND finished_at IS NOT NULL
            AND worker_id IS NULL AND lease_expires_at IS NULL)
        OR (status = 'failed' AND stage = 'failed' AND finished_at IS NOT NULL
            AND worker_id IS NULL AND lease_expires_at IS NULL))"""


def upgrade() -> None:
    op.execute("ALTER TABLE tasks DROP CONSTRAINT tasks_lifecycle")
    op.execute(lifecycle("'langgraph-review-v2', 'langgraph-search-v1'"))


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM tasks WHERE workflow_version = 'langgraph-search-v1' AND status = 'queued' AND started_at IS NOT NULL) THEN
            RAISE EXCEPTION 'Finish or fail resumed search tasks before downgrading';
        END IF;
    END $$""")
    op.execute("ALTER TABLE tasks DROP CONSTRAINT tasks_lifecycle")
    op.execute(lifecycle("'langgraph-review-v2'"))
