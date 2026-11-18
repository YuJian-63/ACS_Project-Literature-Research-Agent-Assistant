import axios, { type AxiosRequestConfig } from 'axios';
import { sessionSnapshot, unauthorized } from './session';
import type { Artifact, EventPage, Page, Paper, PaperImport, PaperSearchParameters, PaperStatus, SearchPaper, Task, TaskAccepted, TaskCreate, TaskStatus, TaskSummary, TaskType } from './types';

const baseURL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');
const client = axios.create({ baseURL, timeout: 30000, withCredentials: true });

export class ApiError extends Error {
  readonly code: string;
  readonly requestId: string | null;
  readonly status: number | null;
  readonly details: Record<string, unknown>;
  retryAfterSeconds: number | null = null;

  constructor(message: string, code = 'NETWORK_ERROR', status: number | null = null, requestId: string | null = null, details: Record<string, unknown> = {}) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.requestId = requestId;
    this.details = details;
  }
}

export function isCanceled(error: unknown): boolean {
  return axios.isCancel(error) || (error instanceof DOMException && error.name === 'AbortError');
}

export function asApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  if (axios.isAxiosError(error)) {
    const resourceError = error.response?.data?.error;
    const message = typeof resourceError?.message === 'string'
      ? resourceError.message
      : error.response ? `请求未成功（HTTP ${error.response.status}），请重试。` : '无法连接后端或请求超时，请检查服务后重试。';
    const result = new ApiError(
      message,
      typeof resourceError?.code === 'string' ? resourceError.code : 'NETWORK_ERROR',
      error.response?.status ?? null,
      typeof error.response?.headers['x-request-id'] === 'string' ? error.response.headers['x-request-id'] : null,
      resourceError?.details && typeof resourceError.details === 'object' && !Array.isArray(resourceError.details) ? resourceError.details : {},
    );
    const retryAfter = Number(error.response?.headers['retry-after']);
    if (Number.isFinite(retryAfter) && retryAfter > 0) result.retryAfterSeconds = Math.min(86400, Math.max(3, retryAfter));
    return result;
  }
  return new ApiError('请求未完成，请重试。', 'CLIENT_ERROR');
}

export async function request<T>(configuration: AxiosRequestConfig, publicAuth = false): Promise<T> {
  const session = sessionSnapshot();
  const controller = new AbortController();
  const abort = () => controller.abort();
  const signal = configuration.signal;
  session.signal.addEventListener('abort', abort, { once: true });
  signal?.addEventListener?.('abort', abort, { once: true });
  if (session.signal.aborted || signal?.aborted || (!publicAuth && !session.csrfToken)) controller.abort();
  const method = (configuration.method || 'GET').toUpperCase();
  try {
    const response = await client.request<T>({
      ...configuration,
      signal: controller.signal,
      headers: {
        ...configuration.headers,
        ...(!publicAuth && !['GET', 'HEAD', 'OPTIONS'].includes(method) ? { 'X-CSRF-Token': session.csrfToken } : {}),
      },
    });
    if (controller.signal.aborted || session.generation !== sessionSnapshot().generation) throw new axios.CanceledError();
    return response.data;
  } catch (error) {
    if (controller.signal.aborted || session.generation !== sessionSnapshot().generation) throw new axios.CanceledError();
    if (isCanceled(error)) throw error;
    if (!publicAuth && axios.isAxiosError(error) && error.response?.status === 401) {
      unauthorized();
      throw new axios.CanceledError();
    }
    throw asApiError(error);
  } finally {
    session.signal.removeEventListener('abort', abort);
    signal?.removeEventListener?.('abort', abort);
  }
}

export const api = {
  searchPapers: (parameters: PaperSearchParameters, signal: AbortSignal) =>
    request<Page<SearchPaper>>({ url: '/api/v1/paper-search', params: parameters, signal }),
  imports: (parameters: { limit?: number; offset?: number }, signal: AbortSignal) =>
    request<Page<PaperImport>>({ url: '/api/v1/paper-imports', params: parameters, signal }),
  paperImport: (id: string, signal: AbortSignal) => request<PaperImport>({ url: `/api/v1/paper-imports/${encodeURIComponent(id)}`, signal }),
  importPaper: (external_id: string, signal: AbortSignal) =>
    request<PaperImport>({ url: '/api/v1/paper-imports', method: 'POST', data: { provider: 'arxiv', external_id }, signal }),
  retryImport: (id: string, expected_attempt: number, signal: AbortSignal) =>
    request<PaperImport>({ url: `/api/v1/paper-imports/${encodeURIComponent(id)}/retry`, method: 'POST', data: { expected_attempt }, signal }),
  papers: (parameters: { limit?: number; offset?: number; q?: string; status?: PaperStatus }, signal: AbortSignal) =>
    request<Page<Paper>>({ url: '/api/v1/papers', params: parameters, signal }),
  deletePaper: (id: string, signal: AbortSignal) => request<void>({ url: `/api/v1/papers/${encodeURIComponent(id)}`, method: 'DELETE', signal }),
  paper: (id: string, signal: AbortSignal) => request<Paper>({ url: `/api/v1/papers/${encodeURIComponent(id)}`, signal }),
  paperFile: (id: string, signal: AbortSignal) =>
    request<Blob>({ url: '/api/v1/papers/' + encodeURIComponent(id) + '/file', responseType: 'blob', signal }),
  upload: (file: File, signal: AbortSignal, onProgress: (percent: number) => void) => {
    const data = new FormData();
    data.append('file', file);
    return request<Paper>({ url: '/api/v1/papers', method: 'POST', data, signal, onUploadProgress: (progress) => {
      if (progress.total) onProgress(Math.min(99, Math.round(progress.loaded / progress.total * 100)));
    } });
  },
  tasks: (parameters: { limit?: number; offset?: number; status?: TaskStatus; task_type?: TaskType }, signal: AbortSignal) =>
    request<Page<TaskSummary>>({ url: '/api/v1/tasks', params: parameters, signal }),
  task: (id: string, signal: AbortSignal) => request<Task>({ url: `/api/v1/tasks/${encodeURIComponent(id)}`, signal }),
  createTask: (data: TaskCreate, key: string, signal: AbortSignal) =>
    request<TaskAccepted>({ url: '/api/v1/tasks', method: 'POST', data, headers: { 'Idempotency-Key': key }, signal }),
  events: (id: string, after: number, signal: AbortSignal) =>
    request<EventPage>({ url: `/api/v1/tasks/${encodeURIComponent(id)}/events`, params: { after_seq: after, limit: 500 }, signal }),
  artifacts: (id: string, signal: AbortSignal) => request<{ items: Artifact[] }>({ url: `/api/v1/tasks/${encodeURIComponent(id)}/artifacts`, signal }),
};

export function paperFileUrl(id: string, page?: number): string {
  return `${baseURL}/api/v1/papers/${encodeURIComponent(id)}/file${page ? `#page=${page}` : ''}`;
}
