export type EvaluationStatus =
  | 'not_requested' | 'pending' | 'running' | 'succeeded' | 'failed' | 'skipped';
export type DimensionKey =
  | 'grounded_correctness' | 'citation_support' | 'task_completion'
  | 'analysis_quality' | 'clarity';

export interface EvaluationMetrics {
  status: EvaluationStatus;
  enabled: boolean;
  configured: boolean;
  evaluation_id: string | null;
  provider: string | null;
  model: string | null;
  rubric_version: string | null;
  prompt_version: string | null;
  error_code: string | null;
  assessment: 'scored' | 'insufficient_evidence' | null;
  overall_score: number | null;
  score_max: number;
  overall_score_max: number;
  weights: Record<string, number>;
  dimensions: Record<DimensionKey, { score: number | null; reason: string | null }>;
}

export interface AgentMetrics {
  available: boolean;
  unavailable_reason: string | null;
  agent_steps: number | null;
  model_calls: number | null;
  tool_calls: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  token_usage_complete: boolean | null;
}

export interface MetricAggregate {
  mean: number | null;
  samples: number;
  source: string | null;
  unavailable_reason: 'NO_SAMPLES' | 'MIXED_SOURCES' | null;
}

export interface CacheTokenMetrics {
  cache_hit_tokens: number | null;
  cache_query_tokens: number | null;
  cache_hit_ratio: number | null;
}

export interface GPUReading {
  uuid: string;
  utilization_percent: number | null;
}

export interface ModelRequestMetrics extends CacheTokenMetrics {
  call_index: number;
  available: boolean;
  request_id: string | null;
  ttft_ms: number | null;
  tpot_ms: number | null;
  mean_itl_ms: number | null;
  tokens_per_second: number | null;
  sources: Record<string, string>;
  gpus: GPUReading[];
  gpu_sampled_at: string | null;
  unavailable_reason: string | null;
}

export interface ModelServerMetrics extends CacheTokenMetrics {
  status: 'available' | 'partial' | 'unavailable';
  unavailable_reason: string | null;
  model_calls_total: number | null;
  observed_model_calls: number;
  measured_model_calls: number;
  cache_measured_model_calls: number;
  cache_usage_complete: boolean;
  cache_unavailable_reason: 'CACHE_USAGE_NOT_AVAILABLE' | 'ZERO_CACHE_QUERY_TOKENS' | null;
  aggregation: string;
  ttft_ms: MetricAggregate;
  tpot_ms: MetricAggregate;
  mean_itl_ms: MetricAggregate;
  tokens_per_second: MetricAggregate;
  gpus: (GPUReading & { call_index: number; sampled_at: string | null })[];
  requests: ModelRequestMetrics[];
  gpu_scope: string;
}

export interface TaskMetrics {
  schema_version: 'task-metrics-v1';
  evaluation: EvaluationMetrics;
  agent: AgentMetrics;
  model_server: ModelServerMetrics;
}
