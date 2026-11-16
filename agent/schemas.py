"""Task and result contracts for the local baseline."""

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Task(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(
        default_factory=lambda: uuid4().hex, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,100}$"
    )
    question: str = Field(min_length=1)
    sources: list[str] = Field(default_factory=list)
    allow_search: bool = False
    max_papers: int = Field(default=3, ge=1, le=20)
    max_steps: int = Field(default=40, ge=1)
    timeout_seconds: float | None = Field(default=600, gt=0)
    max_output_tokens: int = Field(default=4096, ge=1)

    @model_validator(mode="after")
    def require_sources(self):
        if not self.allow_search and not self.sources:
            raise ValueError("Provide sources or enable allow_search")
        return self


class Evidence(BaseModel):
    chunk_id: str
    source_id: str
    paper_id: str
    version: str | int | None = None
    page: int
    source_text: str
    url: str
    title: str


class Usage(BaseModel):
    agent_steps: int = 0
    model_calls: int = 0
    tool_calls: int = 0
    input_tokens: int | None = 0
    output_tokens: int | None = 0
    total_tokens: int | None = 0
    token_usage_complete: bool = True
    elapsed_seconds: float = 0


class TaskResult(BaseModel):
    task_id: str
    question: str
    answer: str = ""
    comparison_table: str = ""
    citations: list[Evidence] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    stop_reason: str
    usage: Usage
    sources: list[dict[str, Any]] = Field(default_factory=list)
    trace: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, str]] = Field(default_factory=list)
    configuration: dict[str, Any] = Field(default_factory=dict)
