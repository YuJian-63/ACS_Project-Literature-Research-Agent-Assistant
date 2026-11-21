"""Add Agent execution storage to the isolated v3 database without replacing existing data.

Revision ID: v3_0002
Revises: v3_0001
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'v3_0002'
down_revision = 'v3_0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Explicit schema snapshot; existing v3 tables and records remain intact.
    op.create_table('tasks',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('task_type', sa.Text(), nullable=False),
    sa.Column('question', sa.Text(), nullable=True),
    sa.Column('workflow_type', sa.Text(), server_default='baseline', nullable=False),
    sa.Column('runner_type', sa.Text(), nullable=False),
    sa.Column('workflow_version', sa.Text(), nullable=False),
    sa.Column('prompt_version', sa.Text(), nullable=True),
    sa.Column('model_id', sa.Text(), nullable=True),
    sa.Column('dataset_version', sa.Text(), nullable=True),
    sa.Column('run_config', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('review_state', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('max_steps', sa.Integer(), server_default=sa.text('10'), nullable=False),
    sa.Column('max_tokens', sa.Integer(), server_default=sa.text('8000'), nullable=False),
    sa.Column('timeout_seconds', sa.Integer(), server_default=sa.text('120'), nullable=False),
    sa.Column('status', sa.Text(), server_default='queued', nullable=False),
    sa.Column('stage', sa.String(length=64), server_default='queued', nullable=False),
    sa.Column('worker_id', sa.Uuid(), nullable=True),
    sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_event_seq', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('idempotency_key', sa.String(length=128), nullable=True),
    sa.Column('request_hash', sa.String(length=64), nullable=False),
    sa.Column('input_tokens', sa.BigInteger(), nullable=True),
    sa.Column('output_tokens', sa.BigInteger(), nullable=True),
    sa.Column('model_calls', sa.BigInteger(), nullable=True),
    sa.Column('tool_calls', sa.BigInteger(), nullable=True),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('error_details', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(status = 'failed' AND error_code IS NOT NULL AND length(btrim(error_code)) > 0 AND error_message IS NOT NULL AND length(btrim(error_message)) > 0 AND error_details IS NOT NULL AND jsonb_typeof(error_details) = 'object') OR (status <> 'failed' AND error_code IS NULL AND error_message IS NULL AND error_details IS NULL)", name='tasks_error_state'),
    sa.CheckConstraint("(status = 'queued' AND stage = 'queued' AND (started_at IS NULL OR workflow_version IN ('langgraph-review-v2', 'langgraph-search-v1', 'agent-io-v1')) AND finished_at IS NULL AND worker_id IS NULL AND lease_expires_at IS NULL) OR (status = 'running' AND started_at IS NOT NULL AND finished_at IS NULL AND worker_id IS NOT NULL AND lease_expires_at IS NOT NULL AND lease_expires_at > started_at) OR (status = 'succeeded' AND started_at IS NOT NULL AND finished_at IS NOT NULL AND worker_id IS NULL AND lease_expires_at IS NULL) OR (status = 'failed' AND stage = 'failed' AND finished_at IS NOT NULL AND worker_id IS NULL AND lease_expires_at IS NULL)", name='tasks_lifecycle'),
    sa.CheckConstraint("(task_type = 'summary' AND (question IS NULL OR length(btrim(question)) BETWEEN 1 AND 8000)) OR (task_type IN ('qa', 'review') AND question IS NOT NULL AND length(btrim(question)) BETWEEN 1 AND 8000)", name='tasks_question'),
    sa.CheckConstraint("jsonb_typeof(review_state) = 'object'", name='ck_tasks_review_state_object'),
    sa.CheckConstraint("jsonb_typeof(run_config) = 'object'"),
    sa.CheckConstraint("request_hash ~ '^[0-9a-f]{64}$'"),
    sa.CheckConstraint("runner_type <> 'mock' OR (model_id IS NULL AND input_tokens IS NULL AND output_tokens IS NULL AND model_calls IS NULL AND tool_calls IS NULL)", name='tasks_mock_usage'),
    sa.CheckConstraint("runner_type IN ('mock', 'langgraph', 'agent')", name='tasks_runner_type_check'),
    sa.CheckConstraint("stage ~ '^[a-z][a-z0-9_]{0,63}$'"),
    sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')"),
    sa.CheckConstraint("task_type IN ('summary', 'qa', 'review')"),
    sa.CheckConstraint("workflow_type IN ('baseline', 'extended')"),
    sa.CheckConstraint('idempotency_key IS NULL OR (length(btrim(idempotency_key)) BETWEEN 1 AND 128 AND idempotency_key = btrim(idempotency_key))', name='tasks_idempotency_key'),
    sa.CheckConstraint('input_tokens >= 0'),
    sa.CheckConstraint('last_event_seq >= 0'),
    sa.CheckConstraint('length(btrim(dataset_version)) > 0'),
    sa.CheckConstraint('length(btrim(model_id)) > 0'),
    sa.CheckConstraint('length(btrim(prompt_version)) > 0'),
    sa.CheckConstraint('length(btrim(workflow_version)) > 0'),
    sa.CheckConstraint('max_steps BETWEEN 1 AND 100'),
    sa.CheckConstraint('max_tokens BETWEEN 1 AND 100000'),
    sa.CheckConstraint('model_calls >= 0'),
    sa.CheckConstraint('output_tokens >= 0'),
    sa.CheckConstraint('timeout_seconds BETWEEN 1 AND 1800'),
    sa.CheckConstraint('tool_calls >= 0'),
    sa.CheckConstraint('updated_at >= created_at AND (started_at IS NULL OR started_at >= created_at) AND (finished_at IS NULL OR finished_at >= coalesce(started_at, created_at))', name='tasks_timestamps'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id', 'user_id', name='tasks_owner_identity'),
    sa.UniqueConstraint('user_id', 'idempotency_key', name='tasks_owner_idempotency')
    )
    op.create_index('tasks_created_idx', 'tasks', [sa.literal_column('created_at DESC'), sa.literal_column('id DESC')], unique=False)
    op.create_index('tasks_expired_lease_idx', 'tasks', ['lease_expires_at'], unique=False, postgresql_where=sa.text("status = 'running'"))
    op.create_index('tasks_owner_created_idx', 'tasks', ['user_id', sa.literal_column('created_at DESC')], unique=False)
    op.create_index('tasks_queue_idx', 'tasks', ['created_at', 'id'], unique=False, postgresql_where=sa.text("status = 'queued'"))
    op.create_index('tasks_status_created_idx', 'tasks', ['status', sa.literal_column('created_at DESC'), sa.literal_column('id DESC')], unique=False)
    op.create_table('agent_runs',
    sa.Column('task_id', sa.Uuid(), nullable=False),
    sa.Column('dispatch_id', sa.Uuid(), nullable=False),
    sa.Column('input_sha256', sa.String(length=64), nullable=False),
    sa.Column('manifest', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('result', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True),
    sa.Column('remote_job_id', sa.String(length=256), nullable=True),
    sa.Column('stop_reason', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("input_sha256 ~ '^[0-9a-f]{64}$'", name='agent_runs_input_sha256'),
    sa.CheckConstraint("jsonb_typeof(manifest) = 'object'", name='agent_runs_manifest_object'),
    sa.CheckConstraint("result IS NULL OR jsonb_typeof(result) = 'object'", name='agent_runs_result_object'),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('task_id'),
    sa.UniqueConstraint('dispatch_id')
    )
    op.create_table('artifacts',
    sa.Column('task_id', sa.Uuid(), nullable=False),
    sa.Column('schema_version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('content_markdown', sa.Text(), nullable=False),
    sa.Column('comparison_table', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("comparison_table IS NULL OR (jsonb_typeof(comparison_table) = 'object' AND comparison_table ?& ARRAY['columns', 'rows'] AND jsonb_typeof(comparison_table -> 'columns') = 'array' AND jsonb_typeof(comparison_table -> 'rows') = 'array')", name='artifacts_comparison_table'),
    sa.CheckConstraint('length(btrim(content_markdown)) > 0'),
    sa.CheckConstraint('length(btrim(title)) > 0'),
    sa.CheckConstraint('schema_version = 1'),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id', 'task_id', name='artifacts_task_identity'),
    sa.UniqueConstraint('task_id')
    )
    op.create_table('task_events',
    sa.Column('task_id', sa.Uuid(), nullable=False),
    sa.Column('seq', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('event_type', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('stage', sa.String(length=64), nullable=False),
    sa.Column('message', sa.String(length=2000), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("event_type IN ('status', 'stage', 'warning', 'error')"),
    sa.CheckConstraint("jsonb_typeof(payload) = 'object'"),
    sa.CheckConstraint("stage ~ '^[a-z][a-z0-9_]{0,63}$'"),
    sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')"),
    sa.CheckConstraint('length(btrim(message)) > 0'),
    sa.CheckConstraint('seq >= 1'),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('task_id', 'seq')
    )
    op.create_table('task_papers',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('task_id', sa.Uuid(), nullable=False),
    sa.Column('paper_id', sa.Uuid(), nullable=False),
    sa.Column('paper_sha256', sa.String(length=64), nullable=False),
    sa.Column('selection_order', sa.SmallInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('selection_order BETWEEN 0 AND 19'),
    sa.ForeignKeyConstraint(['paper_id', 'paper_sha256'], ['papers.id', 'papers.sha256'], name='task_papers_source', onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['paper_id', 'user_id'], ['papers.id', 'papers.user_id'], name='task_papers_paper_owner', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['task_id', 'user_id'], ['tasks.id', 'tasks.user_id'], name='task_papers_task_owner', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('task_id', 'paper_id'),
    sa.UniqueConstraint('task_id', 'selection_order', name='task_papers_order')
    )
    op.create_index('task_papers_paper_idx', 'task_papers', ['paper_id', 'task_id'], unique=False)
    op.create_table('citations',
    sa.Column('artifact_id', sa.Uuid(), nullable=False),
    sa.Column('task_id', sa.Uuid(), nullable=False),
    sa.Column('citation_key', sa.String(length=32), nullable=False),
    sa.Column('paper_id', sa.Uuid(), nullable=False),
    sa.Column('chunk_id', sa.Uuid(), nullable=True),
    sa.Column('agent_chunk_id', sa.Text(), nullable=True),
    sa.Column('agent_source_id', sa.Text(), nullable=True),
    sa.Column('page_number', sa.Integer(), nullable=False),
    sa.Column('quote', sa.Text(), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("citation_key ~ '^C[1-9][0-9]*$'"),
    sa.CheckConstraint('(chunk_id IS NOT NULL AND agent_chunk_id IS NULL AND agent_source_id IS NULL) OR (chunk_id IS NULL AND length(btrim(agent_chunk_id)) > 0 AND agent_chunk_id IS NOT NULL AND length(btrim(agent_source_id)) > 0 AND agent_source_id IS NOT NULL)', name='citations_evidence_identity'),
    sa.CheckConstraint('length(btrim(quote)) > 0'),
    sa.CheckConstraint('page_number >= 1'),
    sa.ForeignKeyConstraint(['artifact_id', 'task_id'], ['artifacts.id', 'artifacts.task_id'], name='citations_artifact', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['chunk_id', 'paper_id', 'page_number'], ['paper_chunks.id', 'paper_chunks.paper_id', 'paper_chunks.page_number'], name='citations_chunk_source', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['task_id', 'paper_id'], ['task_papers.task_id', 'task_papers.paper_id'], name='citations_selected_paper', initially='DEFERRED', deferrable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('artifact_id', 'citation_key', name='citations_key')
    )
    op.create_index('citations_chunk_idx', 'citations', ['chunk_id', 'paper_id', 'page_number'], unique=False)
    op.create_index('citations_task_paper_idx', 'citations', ['task_id', 'paper_id'], unique=False)



def downgrade() -> None:
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM tasks) THEN
            RAISE EXCEPTION 'Agent execution data exists; export it before downgrading v3_0002';
        END IF;
    END $$""")
    # Explicit schema snapshot; existing v3 tables and records remain intact.
    op.drop_table('citations')
    op.drop_table('task_papers')
    op.drop_table('task_events')
    op.drop_table('artifacts')
    op.drop_table('agent_runs')
    op.drop_table('tasks')
