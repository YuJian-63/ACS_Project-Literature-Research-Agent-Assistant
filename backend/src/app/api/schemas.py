from datetime import datetime
from typing import Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agent_bridge.contracts import AgentResult, StopReason

PaperStatus = Literal["uploaded", "processing", "ready", "failed"]
TaskStatus = Literal["queued", "running", "succeeded", "failed"]
TaskType = Literal["summary", "qa", "review"]
WorkflowType = Literal["baseline", "extended"]
Item = TypeVar("Item")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Error(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: Error


class Budget(StrictModel):
    max_steps: int = Field(default=10, ge=1, le=200, strict=True)
    max_tokens: int = Field(default=8000, ge=1, le=100000, strict=True)
    timeout_seconds: int = Field(default=120, ge=1, le=1800, strict=True)


class TaskCreate(StrictModel):
    task_type: TaskType
    question: str | None = None
    paper_ids: list[UUID] = Field(min_length=1, max_length=20)
    workflow_type: WorkflowType = "baseline"
    budget: Budget = Field(default_factory=Budget)

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if len(value) > 8000 or "\x00" in value:
            raise ValueError("问题长度不得超过 8000，且不能含空字节")
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise ValueError("问题必须是有效的 UTF-8 文本") from None
        return value or None

    @model_validator(mode="after")
    def validate_selection(self) -> "TaskCreate":
        if len(set(self.paper_ids)) != len(self.paper_ids):
            raise ValueError("paper_ids 不能重复")
        if self.task_type in {"summary", "qa"} and len(self.paper_ids) != 1:
            raise ValueError("summary/qa 必须选择一篇论文")
        if self.task_type == "review" and len(self.paper_ids) < 2:
            raise ValueError("review 至少选择两篇论文")
        if self.task_type in {"qa", "review"} and self.question is None:
            raise ValueError("qa/review 的问题不能为空")
        self.paper_ids = sorted(self.paper_ids)
        return self


class PaperSourceResponse(BaseModel):
    provider: Literal["arxiv"]
    external_id: str
    title: str
    authors: list[str]
    abstract: str
    doi: str | None
    categories: list[str]
    published_at: datetime
    source_updated_at: datetime
    abstract_url: str
    pdf_url: str


class PaperResponse(BaseModel):
    source: PaperSourceResponse | None = None
    id: UUID
    title: str
    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    status: PaperStatus
    page_count: int | None
    parser_version: str | None
    error: Error | None
    created_at: datetime
    updated_at: datetime


class Page(BaseModel, Generic[Item]):
    items: list[Item]
    total: int
    limit: int
    offset: int


class TaskAccepted(BaseModel):
    id: UUID
    task_type: TaskType
    workflow_type: WorkflowType
    is_mock: bool
    status: TaskStatus
    stage: str
    created_at: datetime


class TaskSummary(TaskAccepted):
    question: str | None
    paper_ids: list[UUID]
    error: Error | None
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class Versions(BaseModel):
    model_id: str | None
    workflow_version: str
    prompt_version: str | None
    dataset_version: str | None


class TaskStats(BaseModel):
    usage_estimated: bool = False
    queue_ms: int | None
    execution_ms: int | None
    end_to_end_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    model_calls: int | None
    tool_calls: int | None


class AgentExecution(BaseModel):
    dispatch_id: UUID
    transport: Literal["file-exchange-v1", "local-process-v1", "tacc-ssh-slurm-v1", "tcloud-v1"] = "file-exchange-v1"
    remote_job_id: str | None = None
    stop_reason: StopReason | None = None
    unresolved: list[str] = Field(default_factory=list)
    limits: dict[str, int | float]


class NativeAgentResponse(BaseModel):
    task_id: UUID
    dispatch_id: UUID
    input_sha256: str
    status: TaskStatus
    remote_job_id: str | None
    result: AgentResult | None


class TaskResponse(TaskSummary):
    budget_mode: Literal["manual", "automatic"] = "manual"
    budget: Budget
    versions: Versions
    stats: TaskStats
    last_event_seq: int
    retrieval: None = None
    agent: AgentExecution | None = None


class EventResponse(BaseModel):
    task_id: UUID
    seq: int
    event_type: Literal["status", "stage", "warning", "error"]
    status: TaskStatus
    stage: str
    message: str
    payload: dict[str, Any]
    created_at: datetime


class EventPage(BaseModel):
    items: list[EventResponse]
    next_after_seq: int
    has_more: bool


class CitationResponse(BaseModel):
    id: UUID
    citation_key: str
    paper_id: UUID
    paper_title: str
    chunk_id: UUID | str
    agent_source_id: str | None = None
    page_number: int
    quote: str


class ArtifactResponse(BaseModel):
    id: UUID
    task_id: UUID
    task_type: TaskType
    schema_version: int
    is_mock: bool
    title: str
    content_markdown: str
    comparison_table: dict[str, Any] | None
    comparison_markdown: str | None = None
    agent_stop_reason: StopReason | None = None
    unresolved: list[str] = Field(default_factory=list)
    citations: list[CitationResponse]
    created_at: datetime


class ArtifactList(BaseModel):
    items: list[ArtifactResponse]


class HealthResponse(BaseModel):
    status: Literal["ok", "ready"]
