import type { Page, TaskStatus } from './types';
import { request } from './client';
// v3-only unified research API; execution is reserved for the Agent integration.
export interface AgentResearchRequest { question: string; paper_ids?: string[]; allow_search?: boolean }
export interface AgentEvidence { chunk_id: string; source_id: string; paper_id: string; version?: string; page: number; source_text: string; url: string; title: string }
export interface AgentResult { task_id: string; question: string; answer: string; comparison_table: string; citations: AgentEvidence[]; unresolved: string[]; stop_reason: string; usage: { agent_steps: number; model_calls: number; tool_calls: number; input_tokens: number | null; output_tokens: number | null; total_tokens: number | null; token_usage_complete: boolean; elapsed_seconds: number }; trace: unknown[]; errors: { stage: string; type: string }[]; configuration: Record<string, unknown>; sources: { paper_id: string; source_id: string; title: string; version?: string; url: string }[] }

export interface AgentResearchRecord {
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
  papers: { id: string; title: string }[];
  status: TaskStatus;
  created_at: string;
}
export const agentResearch = {
  async list(params: { status?: TaskStatus; limit: number; offset: number }, signal?: AbortSignal): Promise<Page<AgentResearchSummary>> {
    return request<Page<AgentResearchSummary>>({ url: '/api/v1/agent-research', params, signal });
  },
  async remove(taskId: string, signal?: AbortSignal): Promise<void> {
    return request<void>({ url: '/api/v1/agent-research/' + encodeURIComponent(taskId), method: 'DELETE', signal });
  },
  async create(input: AgentResearchRequest, signal?: AbortSignal) {
    return request<{ task_id: string }>({ url: '/api/v1/agent-research', method: 'POST', data: { ...input, paper_ids: input.paper_ids ?? [], allow_search: input.allow_search ?? true }, signal });
  },
  async record(taskId: string, signal?: AbortSignal) {
    return request<AgentResearchRecord>({ url: '/api/v1/agent-research/' + encodeURIComponent(taskId), signal });
  },
};
