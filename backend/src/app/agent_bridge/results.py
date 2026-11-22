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
LIBRARY_SOURCE = re.compile(
    r"local:(?P<paper>[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})@(?P<sha>[0-9a-f]{64})"
)


def _search_sources(manifest, result):
    selected = {source.source_id for source in manifest.sources}
    selected_ids = {source.paper_id for source in manifest.sources}
    external = {}
    discovered = {}
    for source in result.sources:
        identity = source.get("source_id")
        if isinstance(identity, str) and identity in selected:
            continue
        if not manifest.task.allow_search or not isinstance(identity, str) or identity in external:
            raise ValueError("Result source is outside authorized inputs")
        library = LIBRARY_SOURCE.fullmatch(identity)
        if library:
            paper_id = library["paper"]
            local_id = UUID(paper_id)
            if local_id in discovered or local_id in selected_ids:
                raise ValueError("Conflicting library source for one PDF")
            discovered[local_id] = library["sha"]
            url = ""
        else:
            match = ARXIV_SOURCE.fullmatch(identity)
            if match is None:
                raise ValueError("Unknown search source")
            paper_id = "arxiv:" + match["base"]
            url = "https://arxiv.org/abs/" + match["base"] + (match["version"] or "")
        if source.get("paper_id") != paper_id or source.get("url") != url:
            raise ValueError("Search source identity or URL does not match")
        external[identity] = source
    if len(selected) + len({source["paper_id"] for source in external.values()}) > manifest.task.max_papers:
        raise ValueError("Result exceeds the authorized paper limit")
    return external, discovered


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


def validate_delivery(manifest: DispatchManifest, envelope: ResultEnvelope) -> dict[UUID, str]:
    """Validate the wire result and return discovered PDFs for database ownership checks."""
    if envelope.dispatch_id != manifest.dispatch_id or envelope.input_sha256 != manifest_digest(manifest):
        raise ValueError("Result belongs to a different dispatch input")
    result = envelope.result
    if result.task_id != manifest.task.task_id or result.question != manifest.task.question:
        raise ValueError("Result task identity does not match dispatch")
    research = manifest.runtime.research
    if research and result.configuration.get("workflow", "baseline") != research.workflow:
        raise ValueError("Delivered workflow differs from requested workflow")
    if research and research.workflow == "extension" and any(
        result.configuration.get(flag) is not getattr(research, flag) for flag in ("planner", "reflection")
    ):
        raise ValueError("Delivered extension options differ from requested options")
    sources = {source.source_id: source for source in manifest.sources}
    external, discovered = _search_sources(manifest, result)
    if envelope.parsed_papers or manifest.runtime.persist:
        expected = {source.get("source_id"): source.get("paper_id") for source in result.sources}
        if any(not isinstance(identity, str) or not isinstance(paper_id, str) for identity, paper_id in expected.items()):
            raise ValueError("Invalid result source for persistence")
        seen = set()
        for paper in envelope.parsed_papers:
            identity = paper.get("source_id")
            if (not isinstance(identity, str) or identity in seen or identity not in expected
                or paper.get("paper_id") != expected[identity]):
                raise ValueError("Parsed paper does not match opened sources")
            library = LIBRARY_SOURCE.fullmatch(identity)
            if library and (paper["paper_id"] != library["paper"] or paper.get("sha256") != library["sha"]):
                raise ValueError("Persisted document differs from the authorized PDF")
            seen.add(identity)
        failed = any(e.get("stage") == "persistence" for e in result.errors)
        if not manifest.runtime.persist or (not failed and seen != expected.keys()):
            raise ValueError("Unexpected or missing persistence payload")
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
    return discovered


def normalize_citation_references(markdown: str, keys: dict[str, str]) -> str:
    def replace_reference(match):
        parts = re.split(r"\s*[,;，；]\s*", match[1].strip())
        normalized = [re.sub(r"^chunk_id\s*:\s*", "", part, flags=re.IGNORECASE) for part in parts]
        if not normalized or any(part not in keys for part in normalized):
            return match[0]
        return " ".join(f"[{keys[part]}]" for part in normalized)

    return re.sub(r"\[([^\]\n]+)\](?!\()", replace_reference, markdown)


def present_result(manifest: DispatchManifest, result: AgentResult, discovered: dict[UUID, str] | None = None) -> PresentedResult:
    sources = {source.source_id: source.paper_id for source in manifest.sources}
    if discovered:
        sources.update({f"local:{paper_id}@{sha}": paper_id for paper_id, sha in discovered.items()})
    local_citations = [citation for citation in result.citations if citation.source_id in sources]
    keys = {citation.chunk_id: f"C{index}" for index, citation in enumerate(local_citations, 1)}
    markdown = normalize_citation_references(
        "\n\n".join(part.strip() for part in (result.answer, result.comparison_table) if part.strip()), keys)
    citations = [PresentedCitation(citation_key=keys[item.chunk_id], paper_id=sources[item.source_id],
        page_number=item.page, quote=item.source_text, agent_chunk_id=item.chunk_id,
        agent_source_id=item.source_id) for item in local_citations]
    return PresentedResult(content_markdown=markdown, citations=citations)
