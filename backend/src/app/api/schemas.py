from datetime import datetime
from typing import Generic, Literal, TypeVar
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
PaperStatus = Literal["uploaded", "processing", "ready", "failed"]
TaskStatus = Literal["queued", "running", "succeeded", "failed"]
Item = TypeVar("Item")
class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Error(BaseModel):
    code: str
    message: str
    details: dict = Field(default_factory=dict)
class ErrorResponse(BaseModel):
    error: Error

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


class HealthResponse(BaseModel):
    status: Literal["ok", "ready"]
