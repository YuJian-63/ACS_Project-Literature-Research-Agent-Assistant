BEGIN;

CREATE TABLE papers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    title varchar(255) NOT NULL CHECK (length(btrim(title)) > 0),
    original_filename varchar(255) NOT NULL CHECK (length(btrim(original_filename)) > 0),
    storage_key text NOT NULL UNIQUE,
    content_type text NOT NULL DEFAULT 'application/pdf' CHECK (content_type = 'application/pdf'),
    size_bytes bigint NOT NULL CHECK (size_bytes BETWEEN 1 AND 20971520),
    sha256 varchar(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    status text NOT NULL DEFAULT 'uploaded' CHECK (status IN ('uploaded', 'processing', 'ready', 'failed')),
    page_count integer CHECK (page_count > 0),
    parser_version text CHECK (length(btrim(parser_version)) > 0),
    parse_worker_id uuid,
    parse_lease_expires_at timestamptz,
    error_code varchar(64),
    error_message text,
    error_details jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT papers_source_identity UNIQUE (id, sha256),
    CONSTRAINT papers_storage_key CHECK (storage_key = 'uploads/' || id::text || '.pdf'),
    CONSTRAINT papers_updated_at CHECK (updated_at >= created_at),
    CONSTRAINT papers_ready CHECK (status <> 'ready' OR (page_count IS NOT NULL AND parser_version IS NOT NULL)),
    CONSTRAINT papers_parse_lease CHECK (
        (status = 'processing' AND parse_worker_id IS NOT NULL AND parse_lease_expires_at IS NOT NULL)
        OR (status <> 'processing' AND parse_worker_id IS NULL AND parse_lease_expires_at IS NULL)
    ),
    CONSTRAINT papers_error_state CHECK (
        (status = 'failed' AND error_code IS NOT NULL AND length(btrim(error_code)) > 0
            AND error_message IS NOT NULL AND length(btrim(error_message)) > 0
            AND error_details IS NOT NULL AND jsonb_typeof(error_details) = 'object')
        OR (status <> 'failed' AND error_code IS NULL AND error_message IS NULL AND error_details IS NULL)
    )
);

CREATE TABLE paper_chunks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_id uuid NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    chunk_index integer NOT NULL CHECK (chunk_index >= 0),
    page_number integer NOT NULL CHECK (page_number >= 1),
    content text NOT NULL CHECK (length(btrim(content)) > 0),
    content_sha256 varchar(64) NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    parser_version text NOT NULL CHECK (length(btrim(parser_version)) > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT paper_chunks_position UNIQUE (paper_id, chunk_index),
    CONSTRAINT paper_chunks_citation_identity UNIQUE (id, paper_id, page_number)
);

CREATE TABLE tasks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    task_type text NOT NULL CHECK (task_type IN ('summary', 'qa', 'review')),
    question text,
    workflow_type text NOT NULL DEFAULT 'baseline' CHECK (workflow_type IN ('baseline', 'extended')),
    runner_type text NOT NULL CHECK (runner_type IN ('mock', 'langgraph', 'agent')),
    workflow_version text NOT NULL CHECK (length(btrim(workflow_version)) > 0),
    prompt_version text CHECK (length(btrim(prompt_version)) > 0),
    model_id text CHECK (length(btrim(model_id)) > 0),
    dataset_version text CHECK (length(btrim(dataset_version)) > 0),
    run_config jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(run_config) = 'object'),
    review_state jsonb NOT NULL DEFAULT '{}'::jsonb CONSTRAINT ck_tasks_review_state_object CHECK (jsonb_typeof(review_state) = 'object'),
    max_steps integer NOT NULL DEFAULT 10 CHECK (max_steps BETWEEN 1 AND 200),
    max_tokens integer NOT NULL DEFAULT 8000 CHECK (max_tokens BETWEEN 1 AND 100000),
    timeout_seconds integer NOT NULL DEFAULT 120 CHECK (timeout_seconds BETWEEN 1 AND 1800),
    status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    stage varchar(64) NOT NULL DEFAULT 'queued' CHECK (stage ~ '^[a-z][a-z0-9_]{0,63}$'),
    worker_id uuid,
    lease_expires_at timestamptz,
    last_event_seq bigint NOT NULL DEFAULT 0 CHECK (last_event_seq >= 0),
    idempotency_key varchar(128) UNIQUE,
    request_hash varchar(64) NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    input_tokens bigint CHECK (input_tokens >= 0),
    output_tokens bigint CHECK (output_tokens >= 0),
    model_calls bigint CHECK (model_calls >= 0),
    tool_calls bigint CHECK (tool_calls >= 0),
    error_code varchar(64),
    error_message text,
    error_details jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz,
    CONSTRAINT tasks_question CHECK (
        (task_type = 'summary' AND (question IS NULL OR length(btrim(question)) BETWEEN 1 AND 8000))
        OR (task_type IN ('qa', 'review') AND question IS NOT NULL AND length(btrim(question)) BETWEEN 1 AND 8000)
    ),
    CONSTRAINT tasks_idempotency_key CHECK (
        idempotency_key IS NULL OR (length(btrim(idempotency_key)) BETWEEN 1 AND 128 AND idempotency_key = btrim(idempotency_key))
    ),
    CONSTRAINT tasks_timestamps CHECK (
        updated_at >= created_at
        AND (started_at IS NULL OR started_at >= created_at)
        AND (finished_at IS NULL OR finished_at >= coalesce(started_at, created_at))
    ),
    CONSTRAINT tasks_lifecycle CHECK (
        (status = 'queued' AND stage = 'queued' AND (started_at IS NULL OR workflow_version IN ('langgraph-review-v2', 'langgraph-search-v1', 'agent-io-v1')) AND finished_at IS NULL
            AND worker_id IS NULL AND lease_expires_at IS NULL)
        OR (status = 'running' AND started_at IS NOT NULL AND finished_at IS NULL
            AND worker_id IS NOT NULL AND lease_expires_at IS NOT NULL AND lease_expires_at > started_at)
        OR (status = 'succeeded' AND started_at IS NOT NULL AND finished_at IS NOT NULL
            AND worker_id IS NULL AND lease_expires_at IS NULL)
        OR (status = 'failed' AND stage = 'failed' AND finished_at IS NOT NULL
            AND worker_id IS NULL AND lease_expires_at IS NULL)
    ),
    CONSTRAINT tasks_error_state CHECK (
        (status = 'failed' AND error_code IS NOT NULL AND length(btrim(error_code)) > 0
            AND error_message IS NOT NULL AND length(btrim(error_message)) > 0
            AND error_details IS NOT NULL AND jsonb_typeof(error_details) = 'object')
        OR (status <> 'failed' AND error_code IS NULL AND error_message IS NULL AND error_details IS NULL)
    ),
    CONSTRAINT tasks_mock_usage CHECK (
        runner_type <> 'mock' OR (model_id IS NULL AND input_tokens IS NULL
            AND output_tokens IS NULL AND model_calls IS NULL AND tool_calls IS NULL)
    )
);

CREATE TABLE agent_runs (
    task_id uuid PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
    dispatch_id uuid NOT NULL UNIQUE,
    input_sha256 varchar(64) NOT NULL,
    manifest jsonb NOT NULL,
    result jsonb,
    remote_job_id varchar(256),
    stop_reason varchar(64),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT agent_runs_input_sha256 CHECK (input_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT agent_runs_manifest_object CHECK (jsonb_typeof(manifest) = 'object'),
    CONSTRAINT agent_runs_result_object CHECK (result IS NULL OR jsonb_typeof(result) = 'object')
);

CREATE TABLE task_papers (
    task_id uuid NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    paper_id uuid NOT NULL,
    paper_sha256 varchar(64) NOT NULL,
    selection_order smallint CHECK (selection_order BETWEEN 0 AND 19),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (task_id, paper_id),
    CONSTRAINT task_papers_order UNIQUE (task_id, selection_order),
    CONSTRAINT task_papers_source FOREIGN KEY (paper_id, paper_sha256)
        REFERENCES papers(id, sha256) ON DELETE RESTRICT ON UPDATE RESTRICT
);

CREATE TABLE task_events (
    task_id uuid NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    seq bigint NOT NULL CHECK (seq >= 1),
    event_type text NOT NULL CHECK (event_type IN ('status', 'stage', 'warning', 'error')),
    status text NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    stage varchar(64) NOT NULL CHECK (stage ~ '^[a-z][a-z0-9_]{0,63}$'),
    message varchar(2000) NOT NULL CHECK (length(btrim(message)) > 0),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(payload) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (task_id, seq)
);

CREATE TABLE artifacts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id uuid NOT NULL UNIQUE REFERENCES tasks(id) ON DELETE CASCADE,
    schema_version integer NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    title varchar(255) NOT NULL CHECK (length(btrim(title)) > 0),
    content_markdown text NOT NULL CHECK (length(btrim(content_markdown)) > 0),
    comparison_table jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT artifacts_task_identity UNIQUE (id, task_id),
    CONSTRAINT artifacts_comparison_table CHECK (
        comparison_table IS NULL OR (jsonb_typeof(comparison_table) = 'object'
            AND comparison_table ?& ARRAY['columns', 'rows']
            AND jsonb_typeof(comparison_table -> 'columns') = 'array'
            AND jsonb_typeof(comparison_table -> 'rows') = 'array')
    )
);

CREATE TABLE citations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_id uuid NOT NULL,
    task_id uuid NOT NULL,
    citation_key varchar(32) NOT NULL CHECK (citation_key ~ '^C[1-9][0-9]*$'),
    paper_id uuid NOT NULL,
    chunk_id uuid,
    agent_chunk_id text,
    agent_source_id text,
    page_number integer NOT NULL CHECK (page_number >= 1),
    quote text NOT NULL CHECK (length(btrim(quote)) > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT citations_key UNIQUE (artifact_id, citation_key),
    CONSTRAINT citations_evidence_identity CHECK (
        (chunk_id IS NOT NULL AND agent_chunk_id IS NULL AND agent_source_id IS NULL)
        OR (chunk_id IS NULL AND length(btrim(agent_chunk_id)) > 0 AND agent_chunk_id IS NOT NULL
            AND length(btrim(agent_source_id)) > 0 AND agent_source_id IS NOT NULL)
    ),
    CONSTRAINT citations_artifact FOREIGN KEY (artifact_id, task_id)
        REFERENCES artifacts(id, task_id) ON DELETE CASCADE,
    CONSTRAINT citations_selected_paper FOREIGN KEY (task_id, paper_id)
        REFERENCES task_papers(task_id, paper_id) DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT citations_chunk_source FOREIGN KEY (chunk_id, paper_id, page_number)
        REFERENCES paper_chunks(id, paper_id, page_number) ON DELETE RESTRICT
);

CREATE INDEX papers_created_idx ON papers (created_at DESC, id DESC);
CREATE INDEX papers_status_created_idx ON papers (status, created_at DESC, id DESC);
CREATE INDEX papers_sha256_idx ON papers (sha256);
CREATE INDEX papers_parse_queue_idx ON papers (created_at, id) WHERE status = 'uploaded';
CREATE INDEX papers_parse_lease_idx ON papers (parse_lease_expires_at) WHERE status = 'processing';
CREATE INDEX paper_chunks_page_idx ON paper_chunks (paper_id, page_number, chunk_index);
CREATE INDEX tasks_created_idx ON tasks (created_at DESC, id DESC);
CREATE INDEX tasks_status_created_idx ON tasks (status, created_at DESC, id DESC);
CREATE INDEX tasks_queue_idx ON tasks (created_at, id) WHERE status = 'queued';
CREATE INDEX tasks_expired_lease_idx ON tasks (lease_expires_at) WHERE status = 'running';
CREATE INDEX task_papers_paper_idx ON task_papers (paper_id, task_id);
CREATE INDEX citations_chunk_idx ON citations (chunk_id, paper_id, page_number);
CREATE INDEX citations_task_paper_idx ON citations (task_id, paper_id);

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

DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM papers) OR EXISTS (SELECT 1 FROM tasks)
            OR EXISTS (SELECT 1 FROM paper_imports) OR EXISTS (SELECT 1 FROM paper_sources) THEN
            RAISE EXCEPTION 'Account migration requires empty business tables. Stop services and use the guarded reset command first.';
        END IF;
    END $$;

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
    CREATE INDEX auth_rate_expiry_idx ON auth_rate_buckets(expires_at);;

INSERT INTO source_request_gates (provider) VALUES ('arxiv') ON CONFLICT (provider) DO NOTHING;

ALTER TABLE papers ADD COLUMN user_id UUID NOT NULL;

ALTER TABLE papers ADD CONSTRAINT papers_user_id_fkey FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT;

ALTER TABLE tasks ADD COLUMN user_id UUID NOT NULL;

ALTER TABLE tasks ADD CONSTRAINT tasks_user_id_fkey FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT;

ALTER TABLE task_papers ADD COLUMN user_id UUID NOT NULL;

ALTER TABLE task_papers ADD CONSTRAINT task_papers_user_id_fkey FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT;

ALTER TABLE paper_sources ADD COLUMN user_id UUID NOT NULL;

ALTER TABLE paper_sources ADD CONSTRAINT paper_sources_user_id_fkey FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT;

ALTER TABLE paper_imports ADD COLUMN user_id UUID NOT NULL;

ALTER TABLE paper_imports ADD CONSTRAINT paper_imports_user_id_fkey FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT;

ALTER TABLE papers ADD CONSTRAINT papers_owner_identity UNIQUE (id, user_id);

CREATE INDEX papers_owner_created_idx ON papers(user_id,created_at DESC);

ALTER TABLE tasks ADD CONSTRAINT tasks_owner_identity UNIQUE (id, user_id);

CREATE INDEX tasks_owner_created_idx ON tasks(user_id,created_at DESC);

ALTER TABLE tasks DROP CONSTRAINT tasks_idempotency_key_key;

ALTER TABLE tasks ADD CONSTRAINT tasks_owner_idempotency UNIQUE (user_id, idempotency_key);

ALTER TABLE task_papers ADD CONSTRAINT task_papers_task_owner FOREIGN KEY(task_id, user_id) REFERENCES tasks (id, user_id) ON DELETE CASCADE;

ALTER TABLE task_papers ADD CONSTRAINT task_papers_paper_owner FOREIGN KEY(paper_id, user_id) REFERENCES papers (id, user_id) ON DELETE RESTRICT;

ALTER TABLE paper_sources DROP CONSTRAINT paper_sources_identity;

ALTER TABLE paper_sources ADD CONSTRAINT paper_sources_identity UNIQUE (user_id, provider, external_id);

ALTER TABLE paper_sources ADD CONSTRAINT paper_sources_paper_owner FOREIGN KEY(paper_id, user_id) REFERENCES papers (id, user_id) ON DELETE RESTRICT;

CREATE INDEX paper_sources_owner_idx ON paper_sources (user_id);

ALTER TABLE paper_imports DROP CONSTRAINT paper_imports_identity;

ALTER TABLE paper_imports ADD CONSTRAINT paper_imports_identity UNIQUE (user_id, provider, external_id);

ALTER TABLE paper_imports ADD CONSTRAINT paper_imports_paper_owner FOREIGN KEY(paper_id, user_id) REFERENCES papers (id, user_id) ON DELETE RESTRICT;

CREATE INDEX paper_imports_owner_idx ON paper_imports (user_id);


-- Verified search metadata reused by independent import workers (20261118_0006).
ALTER TABLE paper_imports ADD COLUMN source_metadata JSONB;

CREATE TABLE course_service (
    id integer PRIMARY KEY,
    state text NOT NULL,
    generation uuid,
    owner_id uuid,
    job_id text,
    base_url text,
    detail text,
    stop_requested boolean NOT NULL DEFAULT false,
    checked_at timestamptz,
    requested_at timestamptz
);
INSERT INTO course_service (id, state) VALUES (1, 'stopped');

CREATE TABLE shared_model_endpoints (
    user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    base_url text NOT NULL
);

CREATE TABLE agent_queue_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    concurrency INTEGER NOT NULL DEFAULT 2 CHECK (concurrency BETWEEN 1 AND 4)
);
INSERT INTO agent_queue_settings (id, concurrency) VALUES (1, 2);

CREATE TABLE evaluation_daily_quotas (
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day date NOT NULL,
    reserved integer NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day),
    CONSTRAINT evaluation_daily_quotas_reserved CHECK (reserved >= 0)
);

CREATE TABLE task_evaluations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id uuid NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    artifact_id uuid,
    input_sha256 varchar(64) NOT NULL,
    config_sha256 varchar(64) NOT NULL,
    input_payload jsonb NOT NULL,
    config jsonb NOT NULL,
    revision integer NOT NULL DEFAULT 0,
    evidence jsonb,
    evidence_sha256 varchar(64),
    status text NOT NULL DEFAULT 'pending',
    report jsonb,
    usage jsonb,
    error_code varchar(64),
    attempts integer NOT NULL DEFAULT 0,
    lease_token uuid,
    lease_expires_at timestamptz,
    next_attempt_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (artifact_id, task_id) REFERENCES artifacts(id, task_id) ON DELETE CASCADE,
    CONSTRAINT task_evaluations_identity UNIQUE (task_id, input_sha256, config_sha256, revision),
    CONSTRAINT task_evaluations_status CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'skipped')),
    CONSTRAINT task_evaluations_attempts CHECK (attempts >= 0),
    CONSTRAINT task_evaluations_revision CHECK (revision >= 0)
);
CREATE INDEX task_evaluations_queue_idx ON task_evaluations(status, next_attempt_at);
CREATE INDEX task_evaluations_task_created_idx ON task_evaluations(task_id, created_at);

COMMIT;
