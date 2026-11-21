from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.papers.limits import MAX_PDF_BYTES


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentTask(Contract):
    task_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,100}$")
    question: str = Field(min_length=1)
    sources: list[str] = Field(default_factory=list)
    allow_search: bool = False
    max_papers: int = Field(default=3, ge=1, le=20, strict=True)
    max_steps: int = Field(default=40, ge=1, strict=True)
    timeout_seconds: float | None = Field(default=600, gt=0, allow_inf_nan=False)
    max_output_tokens: int = Field(default=4096, ge=1, strict=True)

    @model_validator(mode="after")
    def require_sources(self):
        if not self.allow_search and not self.sources:
            raise ValueError("Provide sources or enable allow_search")
        return self


class SourceFile(Contract):
    source_id: str
    paper_id: UUID
    title: str = Field(min_length=1)
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(gt=0, le=MAX_PDF_BYTES, strict=True)
    page_count: int | None = Field(default=None, ge=1, strict=True)

    @model_validator(mode="after")
    def controlled_source(self):
        if self.path != f"papers/{self.paper_id}.pdf":
            raise ValueError("Source path must be the assigned relative PDF path")
        if self.source_id != f"local:{self.paper_id}@{self.sha256}":
            raise ValueError("Source identity must bind the selected PDF and digest")
        return self


class RuntimeOptions(Contract):
    context_window: int = Field(ge=4096, strict=True)
    persist: Literal[False] = False


class DispatchManifest(Contract):
    schema_version: Literal["agent-dispatch-v1"] = "agent-dispatch-v1"
    dispatch_id: UUID
    task: AgentTask
    sources: list[SourceFile] = Field(default_factory=list, max_length=20)
    runtime: RuntimeOptions

    @model_validator(mode="after")
    def selected_sources_only(self):
        identities = [source.source_id for source in self.sources]
        if len(set(identities)) != len(identities) or len({source.paper_id for source in self.sources}) != len(self.sources):
            raise ValueError("Duplicate source identity")
        if (self.task.sources != identities or self.task.max_papers < len(identities)
            or (not self.task.allow_search and self.task.max_papers != len(identities))):
            raise ValueError("Task and source manifest must identify the same selected PDFs")
        return self


class AgentEvidence(Contract):
    chunk_id: str = Field(min_length=1, max_length=512)
    source_id: str = Field(min_length=1, max_length=256)
    paper_id: str = Field(min_length=1, max_length=256)
    version: str | int | None = None
    page: int = Field(ge=1, le=2147483647, strict=True)
    source_text: str = Field(min_length=1)
    url: str
    title: str


class AgentUsage(Contract):
    agent_steps: int = Field(default=0, ge=0, le=9223372036854775807, strict=True)
    model_calls: int = Field(default=0, ge=0, le=9223372036854775807, strict=True)
    tool_calls: int = Field(default=0, ge=0, le=9223372036854775807, strict=True)
    input_tokens: int | None = Field(default=0, ge=0, le=9223372036854775807, strict=True)
    output_tokens: int | None = Field(default=0, ge=0, le=9223372036854775807, strict=True)
    total_tokens: int | None = Field(default=0, ge=0, le=9223372036854775807, strict=True)
    token_usage_complete: bool = Field(default=True, strict=True)
    elapsed_seconds: float = Field(default=0, ge=0, allow_inf_nan=False)


StopReason = Literal["completed", "partial", "step_limit", "time_limit", "context_limit",
    "model_error", "invalid_tool_call", "output_truncated", "invalid_output",
    "invalid_citations", "insufficient_evidence"]


class AgentResult(Contract):
    task_id: str
    question: str
    answer: str = ""
    comparison_table: str = ""
    citations: list[AgentEvidence] = Field(default_factory=list, max_length=10000)
    unresolved: list[str] = Field(default_factory=list)
    stop_reason: StopReason
    usage: AgentUsage
    sources: list[dict[str, Any]] = Field(default_factory=list)
    trace: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, str]] = Field(default_factory=list)
    configuration: dict[str, Any] = Field(default_factory=dict)


class ResultEnvelope(Contract):
    schema_version: Literal["agent-result-v1"]
    dispatch_id: UUID
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    remote_job_id: str | None = Field(default=None, min_length=1, max_length=256)
    result: AgentResult
