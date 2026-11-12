"""Add versioned arXiv provenance, imports and shared request permits."""

from alembic import op

revision: str = "20261112_0002"
down_revision: str = "20261110_0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(r"""
CREATE TABLE paper_sources (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_id uuid NOT NULL UNIQUE REFERENCES papers(id) ON DELETE RESTRICT,
    provider text NOT NULL CHECK (provider = 'arxiv'),
    external_id varchar(80) NOT NULL CHECK (external_id ~ '^([0-9]{2}(0[1-9]|1[0-2])\.[0-9]{4,5}|[a-z][a-z-]*(\.[A-Z]{2})?/[0-9]{2}(0[1-9]|1[0-2])[0-9]{3})v[1-9][0-9]*$'),
    metadata jsonb NOT NULL CHECK (jsonb_typeof(metadata) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT paper_sources_identity UNIQUE (provider, external_id)
);
CREATE TABLE paper_imports (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider text NOT NULL CHECK (provider = 'arxiv'),
    external_id varchar(80) NOT NULL CHECK (external_id ~ '^([0-9]{2}(0[1-9]|1[0-2])\.[0-9]{4,5}|[a-z][a-z-]*(\.[A-Z]{2})?/[0-9]{2}(0[1-9]|1[0-2])[0-9]{3})v[1-9][0-9]*$'),
    attempt integer NOT NULL DEFAULT 1 CHECK (attempt > 0),
    status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    paper_id uuid UNIQUE REFERENCES papers(id) ON DELETE RESTRICT,
    worker_id uuid,
    lease_expires_at timestamptz,
    started_at timestamptz,
    finished_at timestamptz,
    error_code varchar(64),
    error_message text,
    error_details jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT paper_imports_identity UNIQUE (provider, external_id),
    CONSTRAINT paper_imports_result CHECK (
        (status = 'succeeded' AND paper_id IS NOT NULL AND paper_id = id)
        OR (status <> 'succeeded' AND paper_id IS NULL)
    ),
    CONSTRAINT paper_imports_execution CHECK (
        (status = 'queued' AND worker_id IS NULL AND lease_expires_at IS NULL AND started_at IS NULL AND finished_at IS NULL)
        OR (status = 'running' AND worker_id IS NOT NULL AND lease_expires_at IS NOT NULL AND started_at IS NOT NULL AND finished_at IS NULL)
        OR (status IN ('succeeded', 'failed') AND worker_id IS NULL AND lease_expires_at IS NULL AND started_at IS NOT NULL AND finished_at IS NOT NULL)
    ),
    CONSTRAINT paper_imports_errors CHECK (
        (status = 'failed' AND error_code IS NOT NULL AND length(btrim(error_code)) > 0
         AND error_message IS NOT NULL AND length(btrim(error_message)) > 0
         AND error_details IS NOT NULL AND jsonb_typeof(error_details) = 'object'
         AND error_details ? 'retryable' AND jsonb_typeof(error_details->'retryable') = 'boolean')
        OR (status <> 'failed' AND error_code IS NULL AND error_message IS NULL AND error_details IS NULL)
    ),
    CONSTRAINT paper_imports_times CHECK (
        updated_at >= created_at AND (started_at IS NULL OR started_at >= created_at)
        AND (finished_at IS NULL OR finished_at >= started_at)
        AND (lease_expires_at IS NULL OR lease_expires_at > started_at)
    )
);
CREATE INDEX paper_imports_created_idx ON paper_imports (created_at DESC, id DESC);
CREATE INDEX paper_imports_status_created_idx ON paper_imports (status, created_at DESC, id DESC);
CREATE INDEX paper_imports_queue_idx ON paper_imports (created_at, id) WHERE status = 'queued';
CREATE INDEX paper_imports_expired_lease_idx ON paper_imports (lease_expires_at) WHERE status = 'running';
CREATE TABLE source_request_gates (
    provider text PRIMARY KEY CHECK (provider = 'arxiv'),
    next_allowed_at timestamptz NOT NULL DEFAULT now(),
    owner_id uuid,
    lease_expires_at timestamptz,
    blocked_until timestamptz,
    CONSTRAINT source_request_gates_owner CHECK (
        (owner_id IS NULL AND lease_expires_at IS NULL) OR (owner_id IS NOT NULL AND lease_expires_at IS NOT NULL)
    )
);
INSERT INTO source_request_gates (provider) VALUES ('arxiv');
""")


def downgrade() -> None:
    op.execute("""
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM paper_sources) OR EXISTS (SELECT 1 FROM paper_imports) THEN
        RAISE EXCEPTION 'Cannot downgrade while paper imports or provenance exist';
    END IF;
END $$;
DROP TABLE source_request_gates;
DROP TABLE paper_imports;
DROP TABLE paper_sources;
""")
