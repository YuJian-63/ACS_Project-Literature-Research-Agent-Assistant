import type { TaskMetrics } from './taskMetrics';
import type { Page, TaskStatus } from './types';
import { request } from './client';
export interface ResearchOptions {
  model_provider?: 'bailian' | 'tacc' | 'custom';
  endpoint_url?: string;
  workflow: 'baseline' | 'extension';
  context_policy: 'full' | 'compact';
  planner: boolean;
  reflection: boolean;
}
export const defaultResearch: ResearchOptions = { model_provider: 'tacc', workflow: 'baseline', context_policy: 'compact', planner: false, reflection: false };
export interface AgentResearchRequest { question: string; paper_ids?: string[]; allow_search?: boolean; research?: ResearchOptions }
export interface AgentSource { source_id: string; paper_id: string; version?: string | number | null; url: string; title: string }
export interface AgentEvidence extends AgentSource { chunk_id: string; page: number; source_text: string }
export interface AgentResult { task_id: string; question: string; answer: string; comparison_table: string; citations: AgentEvidence[]; unresolved: string[]; stop_reason: string; usage: { agent_steps: number; model_calls: number; tool_calls: number; input_tokens: number | null; output_tokens: number | null; total_tokens: number | null; token_usage_complete: boolean; elapsed_seconds: number }; trace: unknown[]; errors: { stage: string; type: string }[]; configuration: Record<string, unknown>; sources: AgentSource[] }

export interface AgentResearchRecord {
  metrics?: TaskMetrics;
  task_id: string;
  status: 'queued' | 'running' | 'succeeded' | 'failed';
  question: string;
  paper_ids: string[];
  result: AgentResult | null;
  error: { code: string; message: string } | null;
}
export interface AgentResearchSummary {
  id: string;
  question: string;
  paper_ids: string[];
  papers: ({ id: string; title: string } | (AgentSource & { id: null }))[];
  status: TaskStatus;
  created_at: string;
}
export const agentResearch = {
  getConcurrency(signal: AbortSignal) {
    return request<{ concurrency: number }>({ url: '/api/v1/agent-research/queue/concurrency', signal });
  },
  setConcurrency(concurrency: number) {
    return request<{ concurrency: number }>({ url: '/api/v1/agent-research/queue/concurrency', method: 'PUT', data: { concurrency } });
  },
  async list(params: { status?: TaskStatus; limit: number; offset: number }, signal?: AbortSignal): Promise<Page<AgentResearchSummary>> {
    return request<Page<AgentResearchSummary>>({ url: '/api/v1/agent-research', params, signal });
  },
  async remove(taskId: string, signal?: AbortSignal): Promise<void> {
    return request<void>({ url: '/api/v1/agent-research/' + encodeURIComponent(taskId), method: 'DELETE', signal });
  },
  async create(input: AgentResearchRequest, idempotencyKey: string, signal?: AbortSignal) {
    return request<{ task_id: string }>({ url: '/api/v1/agent-research', method: 'POST', headers: { 'Idempotency-Key': idempotencyKey }, data: { ...input, paper_ids: input.paper_ids ?? [], allow_search: input.allow_search ?? true }, signal });
  },
  async record(taskId: string, signal?: AbortSignal) {
    return request<AgentResearchRecord>({ url: '/api/v1/agent-research/' + encodeURIComponent(taskId), signal });
  },
};
