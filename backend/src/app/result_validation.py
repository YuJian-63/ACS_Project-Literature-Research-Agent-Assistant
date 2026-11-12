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
    comparison_table: dict | None = None


class ReviewColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    label: str = Field(min_length=1, max_length=80)

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        if not value.strip() or "\x00" in value:
            raise ValueError("Column labels must contain valid visible text")
        value.encode("utf-8")
        return value


class ReviewCell(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str | None = Field(max_length=4000)
    citation_indexes: list[int] = Field(max_length=100, strict=True)

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: str | None) -> str | None:
        if value is not None:
            if not value.strip() or "\x00" in value:
                raise ValueError("Cell values must contain valid visible text")
            value.encode("utf-8")
        return value

    @field_validator("citation_indexes", mode="before")
    @classmethod
    def validate_indexes(cls, value):
        if not isinstance(value, list) or any(type(index) is not int or index < 1 for index in value):
            raise ValueError("Citation indexes must be positive integers")
        if len(set(value)) != len(value):
            raise ValueError("Duplicate cell citation index")
        return value


class ReviewRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: UUID
    cells: dict[str, ReviewCell]


class ReviewTable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columns: list[ReviewColumn] = Field(min_length=1, max_length=12)
    rows: list[ReviewRow] = Field(min_length=2, max_length=20)


class ReviewDraft(ResearchDraft):
    comparison_table: ReviewTable


def evidence_insufficient_review(selected_papers: list[dict[str, str]]) -> ValidatedResult:
    return ValidatedResult(
        content_markdown="## 证据不足\n\n所选论文没有可用于综述的已解析证据，无法生成有来源支持的研究结论。",
        citations=[],
        comparison_table={
            "columns": [{"key": "evidence_status", "label": "证据状态"}],
            "rows": [{"paper_id": paper["paper_id"], "cells": {
                "evidence_status": {"value": "未检索到可用解析证据", "citation_keys": []},
            }} for paper in selected_papers],
        },
    )


def validate_review_result(
    raw: str, evidence: list[EvidenceChunk], selected_papers: list[dict[str, str]],
) -> ValidatedResult:
    draft = ReviewDraft.model_validate_json(raw)
    paper_ids = [UUID(paper["paper_id"]) for paper in selected_papers]
    if len(set(paper_ids)) != len(paper_ids) or [row.paper_id for row in draft.comparison_table.rows] != paper_ids:
        raise ValueError("Review rows must exactly match the selected papers in order")
    if any(UUID(chunk.paper_id) not in paper_ids for chunk in evidence):
        raise ValueError("Evidence belongs to an unselected paper")
    column_keys = [column.key for column in draft.comparison_table.columns]
    if len(set(column_keys)) != len(column_keys) or any(not column.label.strip() for column in draft.comparison_table.columns):
        raise ValueError("Review columns must be unique and nonempty")
    markers: list[str] = []
    for row in draft.comparison_table.rows:
        if set(row.cells) != set(column_keys):
            raise ValueError("Review cells do not match the columns")
        for cell in row.cells.values():
            if cell.value is None:
                if cell.citation_indexes:
                    raise ValueError("Unreported cells cannot have citations")
            elif not cell.value.strip() or "\x00" in cell.value or not cell.citation_indexes:
                raise ValueError("Research cells require content and citations")
            for index in cell.citation_indexes:
                if index > len(draft.citations):
                    raise ValueError("Review table references an unknown citation")
                markers.append(f"[[cite:{index}]]")
    combined = draft.content_markdown + "\n" + " ".join(markers)
    validated = validate_result(json.dumps({
        "content_markdown": combined,
        "citations": [citation.model_dump(mode="json") for citation in draft.citations],
    }), evidence)
    for row in draft.comparison_table.rows:
        for cell in row.cells.values():
            if any(validated.citations[index - 1].paper_id != row.paper_id for index in cell.citation_indexes):
                raise ValueError("Review cell cites a different paper")
    content = re.sub(r"\[\[cite:(\d+)\]\]", lambda match: f"[C{int(match.group(1))}]", draft.content_markdown)
    return ValidatedResult(
        content_markdown=content, citations=validated.citations,
        comparison_table={
            "columns": [column.model_dump() for column in draft.comparison_table.columns],
            "rows": [{"paper_id": str(row.paper_id), "cells": {
                key: {"value": cell.value, "citation_keys": [f"C{index}" for index in cell.citation_indexes]}
                for key, cell in row.cells.items()
            }} for row in draft.comparison_table.rows],
        },
    )


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
