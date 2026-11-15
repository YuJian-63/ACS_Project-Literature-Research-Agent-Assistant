"""Add verified accounts and strict per-user resource ownership; requires empty old data."""

from alembic import op
import sqlalchemy as sa

revision = "20261114_0004"
down_revision = "20261114_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM papers) OR EXISTS (SELECT 1 FROM tasks)
            OR EXISTS (SELECT 1 FROM paper_imports) OR EXISTS (SELECT 1 FROM paper_sources) THEN
            RAISE EXCEPTION 'Account migration requires empty business tables. Stop services and use the guarded reset command first.';
        END IF;
    END $$""")
    op.execute("""
    CREATE TABLE users (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        username varchar(32) NOT NULL, username_key varchar(32) NOT NULL UNIQUE,
        email varchar(320) NOT NULL, email_key varchar(320) NOT NULL UNIQUE,
        password_hash text NOT NULL, status text NOT NULL DEFAULT 'pending',
        email_verified_at timestamptz, auth_version integer NOT NULL DEFAULT 1,
        created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT users_status CHECK (status IN ('pending','active','disabled')),
        CONSTRAINT users_auth_version CHECK (auth_version > 0),
        CONSTRAINT users_verified CHECK (status <> 'active' OR email_verified_at IS NOT NULL)
    );
    CREATE TABLE auth_sessions (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        token_hash varchar(64) NOT NULL UNIQUE, auth_version integer NOT NULL,
        expires_at timestamptz NOT NULL, revoked_at timestamptz, created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX auth_sessions_user_idx ON auth_sessions(user_id);
    CREATE INDEX auth_sessions_expiry_idx ON auth_sessions(expires_at);
    CREATE TABLE auth_email_tokens (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        purpose text NOT NULL, token_hash varchar(64) NOT NULL UNIQUE, expires_at timestamptz NOT NULL,
        consumed_at timestamptz, revoked_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT auth_email_token_purpose CHECK (purpose IN ('verify_email','reset_password'))
    );
    CREATE INDEX auth_email_tokens_user_idx ON auth_email_tokens(user_id,purpose);
    CREATE INDEX auth_email_tokens_expiry_idx ON auth_email_tokens(expires_at);
    CREATE TABLE auth_mail_outbox (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        token_id uuid NOT NULL REFERENCES auth_email_tokens(id) ON DELETE CASCADE,
        payload_ciphertext text, locale varchar(5) NOT NULL DEFAULT 'zh-CN', status text NOT NULL DEFAULT 'queued',
        attempts integer NOT NULL DEFAULT 0, next_attempt_at timestamptz NOT NULL DEFAULT now(),
        worker_id uuid, lease_expires_at timestamptz, error_code varchar(64),
        created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT auth_mail_status CHECK (status IN ('queued','sending','sent','failed')),
        CONSTRAINT auth_mail_attempts CHECK (attempts BETWEEN 0 AND 3),
        CONSTRAINT auth_mail_lease CHECK ((status = 'sending') = (worker_id IS NOT NULL AND lease_expires_at IS NOT NULL))
    );
    CREATE INDEX auth_mail_queue_idx ON auth_mail_outbox(next_attempt_at) WHERE status = 'queued';
    CREATE TABLE auth_rate_buckets (
        bucket_key text PRIMARY KEY, count integer NOT NULL, expires_at timestamptz NOT NULL,
        CONSTRAINT auth_rate_count CHECK (count > 0)
    );
    CREATE INDEX auth_rate_expiry_idx ON auth_rate_buckets(expires_at);
    """)
    op.execute("INSERT INTO source_request_gates (provider) VALUES ('arxiv') ON CONFLICT (provider) DO NOTHING")
    for table in ('papers','tasks','task_papers','paper_sources','paper_imports'):
        op.add_column(table, sa.Column('user_id', sa.UUID(), nullable=False))
        op.create_foreign_key(table + '_user_id_fkey', table, 'users', ['user_id'], ['id'], ondelete='RESTRICT')
    for table in ('papers','tasks'):
        op.create_unique_constraint(table + '_owner_identity', table, ['id','user_id'])
        op.execute(f'CREATE INDEX {table}_owner_created_idx ON {table}(user_id,created_at DESC)')
    op.drop_constraint('tasks_idempotency_key_key','tasks',type_='unique')
    op.create_unique_constraint('tasks_owner_idempotency','tasks',['user_id','idempotency_key'])
    op.create_foreign_key('task_papers_task_owner','task_papers','tasks',['task_id','user_id'],['id','user_id'],ondelete='CASCADE')
    op.create_foreign_key('task_papers_paper_owner','task_papers','papers',['paper_id','user_id'],['id','user_id'],ondelete='RESTRICT')
    for table in ('paper_sources','paper_imports'):
        op.drop_constraint(table + '_identity',table,type_='unique')
        op.create_unique_constraint(table + '_identity',table,['user_id','provider','external_id'])
        op.create_foreign_key(table + '_paper_owner',table,'papers',['paper_id','user_id'],['id','user_id'],ondelete='RESTRICT')
        op.create_index(table + '_owner_idx',table,['user_id'])


def downgrade() -> None:
    raise RuntimeError('User ownership cannot be downgraded into anonymous shared access. Restore a verified pre-upgrade backup instead.')
