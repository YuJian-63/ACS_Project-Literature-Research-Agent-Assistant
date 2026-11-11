import axios, { type AxiosRequestConfig } from 'axios';
import type { Artifact, EventPage, Page, Paper, PaperStatus, Task, TaskAccepted, TaskCreate, TaskStatus, TaskSummary, TaskType } from './types';

const baseURL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');
const client = axios.create({ baseURL, timeout: 30000 });

export class ApiError extends Error {
  readonly code: string;
  readonly requestId: string | null;
  readonly status: number | null;
  readonly details: Record<string, unknown>;

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
    return new ApiError(
      message,
      typeof resourceError?.code === 'string' ? resourceError.code : 'NETWORK_ERROR',
      error.response?.status ?? null,
      typeof error.response?.headers['x-request-id'] === 'string' ? error.response.headers['x-request-id'] : null,
      resourceError?.details && typeof resourceError.details === 'object' && !Array.isArray(resourceError.details) ? resourceError.details : {},
    );
  }
  return new ApiError('请求未完成，请重试。', 'CLIENT_ERROR');
}

async function request<T>(configuration: AxiosRequestConfig): Promise<T> {
  try {
    return (await client.request<T>(configuration)).data;
  } catch (error) {
    if (isCanceled(error)) throw error;
    throw asApiError(error);
  }
}

export const api = {
  papers: (parameters: { limit?: number; offset?: number; q?: string; status?: PaperStatus }, signal: AbortSignal) =>
    request<Page<Paper>>({ url: '/api/v1/papers', params: parameters, signal }),
  paper: (id: string, signal: AbortSignal) => request<Paper>({ url: `/api/v1/papers/${encodeURIComponent(id)}`, signal }),
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
