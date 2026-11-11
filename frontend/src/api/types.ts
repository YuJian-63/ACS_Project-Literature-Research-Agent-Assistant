export type PaperStatus = 'uploaded' | 'processing' | 'ready' | 'failed';
export type TaskStatus = 'queued' | 'running' | 'succeeded' | 'failed';
export type TaskType = 'summary' | 'qa' | 'review';

export interface ResourceError {
  code: string;
  message: string;
  details: Record<string, unknown>;
}

export interface Paper {
  id: string;
  title: string;
  original_filename: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  status: PaperStatus;
  page_count: number | null;
  parser_version: string | null;
  error: ResourceError | null;
  created_at: string;
  updated_at: string;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface Budget {
  max_steps: number;
  max_tokens: number;
  timeout_seconds: number;
}

export interface TaskCreate {
  task_type: TaskType;
  question: string | null;
  paper_ids: string[];
  workflow_type: 'baseline';
  budget: Budget;
}

export interface TaskAccepted {
  id: string;
  task_type: TaskType;
  workflow_type: 'baseline' | 'extended';
  is_mock: boolean;
  status: TaskStatus;
  stage: string;
  created_at: string;
}

export interface TaskSummary extends TaskAccepted {
  question: string | null;
  paper_ids: string[];
  error: ResourceError | null;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface Task extends TaskSummary {
  budget: Budget;
  versions: {
    model_id: string | null;
    workflow_version: string;
    prompt_version: string | null;
    dataset_version: string | null;
  };
  stats: {
    queue_ms: number | null;
    execution_ms: number | null;
    end_to_end_ms: number | null;
    input_tokens: number | null;
    output_tokens: number | null;
    total_tokens: number | null;
    model_calls: number | null;
    tool_calls: number | null;
  };
  last_event_seq: number;
}

export interface TaskEvent {
  task_id: string;
  seq: number;
  event_type: 'status' | 'stage' | 'warning' | 'error';
  status: TaskStatus;
  stage: string;
  message: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface EventPage {
  items: TaskEvent[];
  next_after_seq: number;
  has_more: boolean;
}

export interface Citation {
  id: string;
  citation_key: string;
  paper_id: string;
  paper_title: string;
  chunk_id: string;
  page_number: number;
  quote: string;
}

export interface ComparisonTable {
  columns: { key: string; label: string }[];
  rows: {
    paper_id: string;
    cells: Record<string, { value: string | null; citation_keys: string[] }>;
  }[];
}

export interface Artifact {
  id: string;
  task_id: string;
  task_type: TaskType;
  schema_version: number;
  is_mock: boolean;
  title: string;
  content_markdown: string;
  comparison_table: ComparisonTable | null;
  citations: Citation[];
  created_at: string;
}
