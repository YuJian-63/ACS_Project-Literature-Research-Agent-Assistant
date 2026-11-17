import type { AgentTaskCreate, TaskType } from '../../../api/types';
export function normalizeAgentSubmission(values: { task_type: TaskType; question?: string; sources?: string; allow_search?: boolean; max_papers?: number }): AgentTaskCreate {
  return { task_type: values.task_type, question: values.question?.trim() || '', sources: (values.sources || '').split(/\r?\n/).map((source) => source.trim()).filter(Boolean), allow_search: values.allow_search ?? false, max_papers: values.max_papers ?? 3, max_steps: 40, timeout_seconds: 600, max_output_tokens: 4096 };
}
export function agentCitationUrl(raw: string, page: number): string | undefined {
  try { const url = new URL(raw); if (!['http:', 'https:'].includes(url.protocol)) return; url.hash = `page=${page}`; return url.href; } catch { return; }
}
