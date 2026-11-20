export type PaperStatus = 'uploaded' | 'processing' | 'ready' | 'failed';
export type TaskStatus = 'queued' | 'running' | 'succeeded' | 'failed';

export interface ResourceError {
  code: string;
  message: string;
  details: Record<string, unknown>;
}

export interface Paper {
  source: PaperSource | null;
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

export interface PaperSource {
  provider: 'arxiv';
  external_id: string;
  title: string;
  authors: string[];
  abstract: string;
  doi: string | null;
  categories: string[];
  published_at: string;
  source_updated_at: string;
  abstract_url: string;
  pdf_url: string;
}

export type ImportStatus = 'queued' | 'running' | 'succeeded' | 'failed';

export interface PaperImport {
  id: string;
  provider: 'arxiv';
  external_id: string;
  attempt: number;
  status: ImportStatus;
  paper_id: string | null;
  paper_status: PaperStatus | null;
  error: ResourceError | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface SearchPaper extends PaperSource {
  import_id: string | null;
  import_status: ImportStatus | null;
  paper_id: string | null;
  paper_status: PaperStatus | null;
}

export interface PaperSearchParameters {
  q: string;
  limit: number;
  offset: number;
  sort_by?: 'relevance' | 'submittedDate' | 'lastUpdatedDate';
  sort_order?: 'ascending' | 'descending';
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}
