"""Backend validation of the Agent v1 envelope, independent of Agent dependencies."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Evidence(BaseModel):
    chunk_id: str
    source_id: str
    paper_id: str
    version: str | int | None = None
    page: int = Field(ge=1)
    source_text: str
    url: str
    title: str


class Usage(BaseModel):
    agent_steps: int = Field(ge=0)
    model_calls: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    token_usage_complete: bool
    elapsed_seconds: float = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def consistent_usage(self):
        if not self.token_usage_complete:
            self.input_tokens = self.output_tokens = self.total_tokens = None
        elif None in (self.input_tokens, self.output_tokens, self.total_tokens):
            raise ValueError("Complete usage requires all token values")
        elif self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("Inconsistent token total")
        return self


class AgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    question: str
    answer: str = ""
    comparison_table: str = ""
    citations: list[Evidence] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    stop_reason: Literal[
        "completed",
        "partial",
        "step_limit",
        "time_limit",
        "context_limit",
        "model_error",
        "invalid_tool_call",
        "output_truncated",
        "invalid_output",
        "invalid_citations",
        "insufficient_evidence",
    ]
    usage: Usage
    sources: list[dict[str, Any]] = Field(default_factory=list)
    trace: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, str]] = Field(default_factory=list)
    configuration: dict[str, Any] = Field(default_factory=dict)
