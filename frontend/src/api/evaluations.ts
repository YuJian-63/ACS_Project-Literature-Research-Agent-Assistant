import { request } from './client';
import type { EvaluationStatus } from './taskMetrics';

export interface EvaluationReport extends Record<string, unknown> {
  summary?: string;
  evaluation_scope?: string;
  issues?: { severity: string; code: string; message: string; citation_keys: string[]; answer_excerpt: string }[];
  suggestions?: string[];
  limitations?: string[];
}
export interface EvaluationVersion extends Record<string, unknown> {
  task_id: string;
  id: string | null;
  enabled: boolean;
  configured: boolean;
  status: EvaluationStatus;
  attempts: number;
  max_attempts: number | null;
  error_code: string | null;
  report: EvaluationReport | null;
  usage: Record<string, unknown> | null;
}
export const evaluations = {
  get(taskId: string, evaluationId: string, signal: AbortSignal) {
    return request<EvaluationVersion>({ url: `/api/v1/tasks/${encodeURIComponent(taskId)}/evaluation`, params: { evaluation_id: evaluationId }, signal });
  },
  request(taskId: string, signal: AbortSignal) {
    return request<EvaluationVersion>({ url: `/api/v1/tasks/${encodeURIComponent(taskId)}/evaluation`, method: 'POST', signal });
  },
};
