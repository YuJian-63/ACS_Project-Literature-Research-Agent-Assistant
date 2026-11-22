from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class DimensionMetric(BaseModel):
    score: float | None = Field(ge=0, le=5, allow_inf_nan=False)
    reason: str | None


class EvaluationDimensions(BaseModel):
    grounded_correctness: DimensionMetric
    citation_support: DimensionMetric
    task_completion: DimensionMetric
    analysis_quality: DimensionMetric
    clarity: DimensionMetric


class EvaluationMetrics(BaseModel):
    status: Literal["not_requested", "pending", "running", "succeeded", "failed", "skipped"]
    enabled: bool
    configured: bool
    evaluation_id: UUID | None
    provider: str | None
    model: str | None
    rubric_version: str | None
    prompt_version: str | None
    error_code: str | None
    assessment: Literal["scored", "insufficient_evidence"] | None
    overall_score: float | None = Field(ge=0, le=100, allow_inf_nan=False)
    score_max: int
    overall_score_max: int
    weights: dict[str, int]
    dimensions: EvaluationDimensions


class AgentMetrics(BaseModel):
    available: bool
    unavailable_reason: str | None
    agent_steps: int | None
    model_calls: int | None
    tool_calls: int | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    token_usage_complete: bool | None


class MetricAggregate(BaseModel):
    mean: float | None = Field(ge=0, allow_inf_nan=False)
    samples: int
    source: str | None
    unavailable_reason: Literal["NO_SAMPLES", "MIXED_SOURCES"] | None


class GPUReading(BaseModel):
    uuid: str
    utilization_percent: float | None = Field(ge=0, le=100, allow_inf_nan=False)


class LatestGPUReading(GPUReading):
    call_index: int
    sampled_at: datetime | None


class CacheTokenMetrics(BaseModel):
    cache_hit_tokens: int | None = Field(ge=0)
    cache_query_tokens: int | None = Field(ge=0)
    cache_hit_ratio: float | None = Field(ge=0, le=1, allow_inf_nan=False)


class ModelRequestMetrics(CacheTokenMetrics):
    call_index: int
    available: bool
    request_id: str | None
    ttft_ms: float | None
    tpot_ms: float | None
    mean_itl_ms: float | None
    tokens_per_second: float | None
    sources: dict[str, str]
    gpus: list[GPUReading]
    gpu_sampled_at: datetime | None
    unavailable_reason: str | None


class ModelServerMetrics(CacheTokenMetrics):
    status: Literal["available", "partial", "unavailable"]
    unavailable_reason: str | None
    model_calls_total: int | None
    observed_model_calls: int
    measured_model_calls: int
    cache_measured_model_calls: int
    cache_usage_complete: bool
    cache_unavailable_reason: Literal["CACHE_USAGE_NOT_AVAILABLE", "ZERO_CACHE_QUERY_TOKENS"] | None
    aggregation: str
    ttft_ms: MetricAggregate
    tpot_ms: MetricAggregate
    mean_itl_ms: MetricAggregate
    tokens_per_second: MetricAggregate
    gpus: list[LatestGPUReading]
    requests: list[ModelRequestMetrics]
    gpu_scope: str


class TaskMetrics(BaseModel):
    schema_version: Literal["task-metrics-v1"]
    evaluation: EvaluationMetrics
    agent: AgentMetrics
    model_server: ModelServerMetrics
