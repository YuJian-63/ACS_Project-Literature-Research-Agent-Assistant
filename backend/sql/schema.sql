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
    runner_type text NOT NULL CHECK (runner_type IN ('mock', 'langgraph')),
    workflow_version text NOT NULL CHECK (length(btrim(workflow_version)) > 0),
    prompt_version text CHECK (length(btrim(prompt_version)) > 0),
    model_id text CHECK (length(btrim(model_id)) > 0),
    dataset_version text CHECK (length(btrim(dataset_version)) > 0),
    run_config jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(run_config) = 'object'),
    max_steps integer NOT NULL DEFAULT 10 CHECK (max_steps BETWEEN 1 AND 100),
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
        (status = 'queued' AND stage = 'queued' AND started_at IS NULL AND finished_at IS NULL
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

CREATE TABLE task_papers (
    task_id uuid NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    paper_id uuid NOT NULL,
    paper_sha256 varchar(64) NOT NULL,
    selection_order smallint NOT NULL CHECK (selection_order BETWEEN 0 AND 19),
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
    chunk_id uuid NOT NULL,
    page_number integer NOT NULL CHECK (page_number >= 1),
    quote text NOT NULL CHECK (length(btrim(quote)) > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT citations_key UNIQUE (artifact_id, citation_key),
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

COMMIT;
