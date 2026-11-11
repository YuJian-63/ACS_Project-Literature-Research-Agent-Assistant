import json
import re
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.retrieval import EvidenceChunk


class CitationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: UUID
    quote: str = Field(min_length=1, max_length=2000)

    @field_validator("quote")
    @classmethod
    def validate_quote(cls, value: str) -> str:
        if not value.strip() or "\x00" in value:
            raise ValueError("Quote must contain visible text")
        return value


class ResearchDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_markdown: str = Field(min_length=1, max_length=2 * 1024 * 1024)
    citations: list[CitationDraft] = Field(max_length=100)

    @field_validator("content_markdown")
    @classmethod
    def validate_content(cls, value: str) -> str:
        if not value.strip() or "\x00" in value:
            raise ValueError("Result content must contain visible text")
        value.encode("utf-8")
        return value


class ValidatedCitation(BaseModel):
    citation_key: str
    chunk_id: UUID
    paper_id: UUID
    page_number: int
    quote: str


class ValidatedResult(BaseModel):
    content_markdown: str
    citations: list[ValidatedCitation]


def validate_result(raw: str, evidence: list[EvidenceChunk]) -> ValidatedResult:
    try:
        draft = ResearchDraft.model_validate(json.loads(raw))
    except (ValueError, ValidationError) as error:
        raise ValueError("Model result does not match the required result schema") from error
    by_id = {UUID(chunk.chunk_id): chunk for chunk in evidence}
    marker_pattern = re.compile(r"\[\[cite:(\d+)\]\]")
    marker_ids = [int(value) for value in marker_pattern.findall(draft.content_markdown)]
    if "[[cite:" in marker_pattern.sub("", draft.content_markdown):
        raise ValueError("Model result contains an invalid citation marker")
    if any(marker < 1 or marker > len(draft.citations) for marker in marker_ids):
        raise ValueError("Model result references an unknown citation")
    if set(marker_ids) != set(range(1, len(draft.citations) + 1)):
        raise ValueError("Every citation must be referenced in the result")
    seen: set[tuple[UUID, str]] = set()
    citations: list[ValidatedCitation] = []
    for index, candidate in enumerate(draft.citations, start=1):
        chunk = by_id.get(candidate.chunk_id)
        if chunk is None:
            raise ValueError("Citation references evidence outside the task context")
        if candidate.quote not in chunk.content:
            raise ValueError("Citation quote is not an exact source substring")
        identity = (candidate.chunk_id, candidate.quote)
        if identity in seen:
            raise ValueError("Duplicate citation")
        seen.add(identity)
        citations.append(ValidatedCitation(
            citation_key=f"C{index}", chunk_id=candidate.chunk_id,
            paper_id=UUID(chunk.paper_id), page_number=chunk.page_number, quote=candidate.quote,
        ))
    content = marker_pattern.sub(lambda match: f"[C{int(match.group(1))}]", draft.content_markdown)
    if len(content.encode("utf-8")) > 2 * 1024 * 1024:
        raise ValueError("Result content exceeds the byte limit")
    return ValidatedResult(content_markdown=content, citations=citations)
