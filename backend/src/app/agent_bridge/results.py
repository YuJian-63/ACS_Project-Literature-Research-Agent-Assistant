import re
from dataclasses import dataclass
from uuid import UUID

from app.agent_bridge.bundles import manifest_digest
from app.agent_bridge.contracts import AgentResult, DispatchManifest, ResultEnvelope


ARXIV_SOURCE = re.compile(
    r"arxiv:(?P<base>(?:\d{2}(?:0[1-9]|1[0-2])\.\d{4,5}|"
    r"[A-Za-z][A-Za-z.-]*/\d{2}(?:0[1-9]|1[0-2])\d{3}))"
    r"(?:(?P<version>v[1-9]\d*)|@[0-9a-f]{12})"
)


def _search_sources(manifest, result):
    selected = {source.source_id for source in manifest.sources}
    external = {}
    for source in result.sources:
        identity = source.get("source_id")
        if isinstance(identity, str) and identity in selected:
            continue
        match = ARXIV_SOURCE.fullmatch(identity) if isinstance(identity, str) else None
        if not manifest.task.allow_search or match is None:
            raise ValueError("Result source is outside authorized inputs")
        paper_id = "arxiv:" + match["base"]
        url = "https://arxiv.org/abs/" + match["base"] + (match["version"] or "")
        if source.get("paper_id") != paper_id or source.get("url") != url or identity in external:
            raise ValueError("Search source identity or URL does not match arXiv")
        external[identity] = source
    if len(selected) + len({source["paper_id"] for source in external.values()}) > manifest.task.max_papers:
        raise ValueError("Result exceeds the authorized paper limit")
    return external


def _validate_search_citation(citation, external):
    source = external.get(citation.source_id)
    if (source is None or citation.paper_id != source["paper_id"] or citation.url != source["url"]
        or re.fullmatch(re.escape(citation.source_id) + rf":p{citation.page}:c[1-9]\d*", citation.chunk_id) is None):
        raise ValueError("Citation does not match an authorized search source")


@dataclass(frozen=True)
class PresentedCitation:
    citation_key: str
    paper_id: UUID
    page_number: int
    quote: str
    agent_chunk_id: str
    agent_source_id: str


@dataclass(frozen=True)
class PresentedResult:
    content_markdown: str
    citations: list[PresentedCitation]


def validate_delivery(manifest: DispatchManifest, envelope: ResultEnvelope) -> None:
    if envelope.dispatch_id != manifest.dispatch_id or envelope.input_sha256 != manifest_digest(manifest):
        raise ValueError("Result belongs to a different dispatch input")
    result = envelope.result
    if result.task_id != manifest.task.task_id or result.question != manifest.task.question:
        raise ValueError("Result task identity does not match dispatch")
    sources = {source.source_id: source for source in manifest.sources}
    external = _search_sources(manifest, result)
    chunks = set()
    for citation in result.citations:
        source = sources.get(citation.source_id)
        if source is None:
            _validate_search_citation(citation, external)
        elif citation.paper_id not in {source.source_id, str(source.paper_id)}:
            raise ValueError("Citation references a paper outside the selected inputs")
        if source is not None and source.page_count is not None and citation.page > source.page_count:
            raise ValueError("Citation page exceeds the selected PDF")
        if citation.chunk_id in chunks or not citation.source_text.strip():
            raise ValueError("Duplicate or empty citation")
        chunks.add(citation.chunk_id)
    if result.stop_reason in {"completed", "partial"} and not (result.answer.strip() or result.comparison_table.strip()):
        raise ValueError("Successful Agent result has no displayable content")


def normalize_citation_references(markdown: str, keys: dict[str, str]) -> str:
    def replace_reference(match):
        parts = re.split(r"\s*[,;，；]\s*", match[1].strip())
        normalized = [re.sub(r"^chunk_id\s*:\s*", "", part, flags=re.IGNORECASE) for part in parts]
        if not normalized or any(part not in keys for part in normalized):
            return match[0]
        return " ".join(f"[{keys[part]}]" for part in normalized)

    return re.sub(r"\[([^\]\n]+)\](?!\()", replace_reference, markdown)


def present_result(manifest: DispatchManifest, result: AgentResult) -> PresentedResult:
    sources = {source.source_id: source for source in manifest.sources}
    local_citations = [citation for citation in result.citations if citation.source_id in sources]
    keys = {citation.chunk_id: f"C{index}" for index, citation in enumerate(local_citations, 1)}
    markdown = normalize_citation_references(
        "\n\n".join(part.strip() for part in (result.answer, result.comparison_table) if part.strip()), keys)
    citations = [PresentedCitation(citation_key=keys[item.chunk_id], paper_id=sources[item.source_id].paper_id,
        page_number=item.page, quote=item.source_text, agent_chunk_id=item.chunk_id,
        agent_source_id=item.source_id) for item in local_citations]
    return PresentedResult(content_markdown=markdown, citations=citations)
