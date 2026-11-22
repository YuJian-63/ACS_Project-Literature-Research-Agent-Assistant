from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agent_bridge.contracts import AgentResult, ResearchOptions
from app.api.schemas import Error, TaskStatus


class AgentResearchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=8000)
    paper_ids: list[UUID] = Field(default_factory=list, max_length=20)
    allow_search: bool = Field(default=True, strict=True)

    research: ResearchOptions | None = Field(default=None, exclude_if=lambda value: value is None)

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        value = value.strip()
        if not value or "\x00" in value:
            raise ValueError("A research question without NUL characters is required")
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise ValueError("The question must be valid UTF-8") from None
        return value

    @model_validator(mode="after")
    def validate_sources(self):
        if len(set(self.paper_ids)) != len(self.paper_ids):
            raise ValueError("paper_ids must be unique")
        if not self.paper_ids and not self.allow_search:
            raise ValueError("Select papers or enable search")
        return self


class QueueConcurrency(BaseModel):
    model_config = ConfigDict(extra="forbid")
    concurrency: int = Field(strict=True, ge=1, le=4)


class AgentResearchAccepted(BaseModel):
    task_id: UUID
    status: TaskStatus


class ResearchPaperReference(BaseModel):
    id: UUID
    title: str


class ExternalResearchPaper(BaseModel):
    id: None
    title: str
    source_id: str
    paper_id: str
    url: str
    version: str | int | None = None


class AgentResearchSummary(BaseModel):
    id: UUID
    question: str
    paper_ids: list[UUID]
    papers: list[ResearchPaperReference | ExternalResearchPaper]
    status: TaskStatus
    created_at: datetime


class AgentResearchRecord(BaseModel):
    task_id: UUID
    question: str
    status: TaskStatus
    paper_ids: list[UUID]
    result: AgentResult | None
    error: Error | None
