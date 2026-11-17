from datetime import datetime
from typing import Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    max_steps: int = Field(default=10, ge=1, le=100, strict=True)
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


class AgentTaskCreate(StrictModel):
    question: str = Field(min_length=1, max_length=8000)
    sources: list[str] = Field(default_factory=list, max_length=100)
    allow_search: bool = False
    max_papers: int = Field(default=3, ge=1, le=20, strict=True)
    max_steps: int = Field(default=40, ge=1, le=100, strict=True)
    timeout_seconds: int = Field(default=600, ge=1, le=1800, strict=True)
    max_output_tokens: int = Field(default=4096, ge=1, le=32768, strict=True)
    task_type: TaskType = "qa"

    @field_validator("question")
    @classmethod
    def nonempty_question(cls, value: str) -> str:
        value = value.strip()
        if not value or "\x00" in value:
            raise ValueError("问题不能为空")
        return value

    @field_validator("sources")
    @classmethod
    def arxiv_sources(cls, values: list[str]) -> list[str]:
        import re
        pattern = r"(?:\d{4}\.\d{4,5}|[a-zA-Z][a-zA-Z.\-]*/\d{7})(?:v[1-9]\d*)?"
        normalized = []
        for value in values:
            value = value.strip()
            candidate = re.sub(r"^https?://(?:www\.)?arxiv\.org/(?:abs|pdf|html)/", "", value)
            candidate = re.sub(r"\.pdf$", "", candidate)
            if not re.fullmatch(pattern, candidate):
                raise ValueError("当前仅支持 arXiv ID 或 arXiv abs/pdf/html URL")
            normalized.append(value)
        return normalized

    @model_validator(mode="after")
    def require_sources(self):
        if not self.allow_search and not self.sources:
            raise ValueError("请提供 arXiv 来源或开启搜索")
        return self


class AgentBudget(Budget):
    max_tokens: int | None = None


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


class EvidenceChunkResponse(BaseModel):
    chunk_id: UUID
    paper_id: UUID
    chunk_index: int = Field(ge=0)
    page_number: int = Field(ge=1, description="PDF physical page number, starting at 1")
    content: str
    content_sha256: str
    parser_version: str


class EvidencePage(BaseModel):
    paper_id: UUID
    paper_sha256: str
    page_count: int = Field(ge=1)
    parser_version: str
    items: list[EvidenceChunkResponse]
    has_more: bool
    next_after_index: int = Field(ge=-1)


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


class MissingPaperEvidence(BaseModel):
    paper_id: UUID
    paper_title: str
    columns: list[str]


class RetrievalDiagnostics(BaseModel):
    status: str
    expansion_degraded: bool = False
    selected_chunks: int = 0
    lexical_matches: int = 0
    missing_aspects: list[str] = Field(default_factory=list)
    papers: list[MissingPaperEvidence] = Field(default_factory=list)


class TaskResponse(TaskSummary):
    budget_mode: Literal["manual", "automatic"] = "manual"
    budget: AgentBudget
    result_format: Literal["legacy", "agent-v1"] = "legacy"
    agent_input: dict[str, Any] | None = None
    versions: Versions
    stats: TaskStats
    last_event_seq: int
    retrieval: RetrievalDiagnostics | None = None


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
    chunk_id: UUID
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
    citations: list[CitationResponse]
    created_at: datetime


class ArtifactList(BaseModel):
    items: list[ArtifactResponse]


class HealthResponse(BaseModel):
    status: Literal["ok", "ready"]
