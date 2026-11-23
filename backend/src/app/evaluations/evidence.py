import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from app.papers.storage import controlled_path
from app.sources.arxiv import ArxivError, normalize_arxiv_id


def normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def reference_checks(payload: dict) -> dict:
    answer = payload.get("answer", "") + "\n" + payload.get("comparison_table", "")
    keys = {citation["key"] for citation in payload["citations"]}
    explicit = set(re.findall(r"\[((?:C|E)[1-9][0-9]*)\]", answer))
    referenced = {citation["key"] for citation in payload["citations"]
        if citation["key"] in explicit or citation.get("chunk_id", "\x00") in answer}
    return {"unresolved_references": sorted(explicit - keys), "referenced_citations": sorted(referenced),
        "unused_citations": sorted(keys - referenced)}


def arxiv_original(source_id: str, client, directory: Path, deadline: float) -> dict:
    if client is None or not source_id.startswith("arxiv:"):
        raise ValueError("Original source unavailable")
    external_id = normalize_arxiv_id(source_id[len("arxiv:"):])
    path = directory / (sha256(source_id.encode("utf-8")).hexdigest() + ".pdf")
    while time.monotonic() < deadline:
        try:
            receipt = client.download_pdf(external_id, path, deadline=deadline)
            return {"paper_id": source_id, "source_id": source_id, "sha256": receipt.sha256, "path": str(path)}
        except ArxivError as error:
            if error.code != "ARXIV_RATE_LIMITED":
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(error.retry_after or 3, remaining))
    raise ArxivError("ARXIV_TIMEOUT", "Original evidence download timed out")


def prepare_evidence(payload: dict, settings, *, arxiv_client=None) -> dict:
    citations = payload["citations"]
    sources = {}
    for source in payload["original_sources"]:
        sources[f"local:{source['paper_id']}@{source['sha256']}"] = source
        for source_id in source.get("source_ids", []):
            sources[source_id] = source
    specification, locations, limitations = {}, {}, set()
    pages, provenance = [], []
    started = time.monotonic()
    deadline = started + settings.evaluation_evidence_timeout_seconds
    download_deadline = started + settings.evaluation_evidence_timeout_seconds / 2
    with tempfile.TemporaryDirectory(prefix="evaluation-evidence-") as temporary:
        directory = Path(temporary)
        for citation in citations:
            source_id = citation.get("source_id", "")
            if source_id not in sources:
                try:
                    sources[source_id] = arxiv_original(source_id, arxiv_client, directory, download_deadline)
                    provenance.append({"source_id": source_id, "sha256": sources[source_id]["sha256"]})
                except (ValueError, OSError, ArxivError):
                    sources[source_id] = None
            source = sources[source_id]
            if not source:
                limitations.add("originals_unavailable")
                continue
            location = (source["paper_id"], citation["page"])
            if location not in locations:
                try:
                    path = Path(source["path"]) if "path" in source else controlled_path(
                        settings.storage_root, UUID(source["paper_id"]), source["storage_key"])
                except (ValueError, OSError):
                    limitations.add("original_path_unavailable")
                    continue
                item = specification.setdefault(source["paper_id"], {"paper_id": source["paper_id"],
                    "sha256": source["sha256"], "path": str(path), "pages": []})
                item["pages"].append(citation["page"])
                locations[location] = []
            locations[location].append(citation)
        if specification:
            request_path, result_path = directory / "request.json", directory / "result.json"
            request_path.write_text(json.dumps(list(specification.values())), encoding="utf-8")
            environment = {key: value for key, value in os.environ.items()
                if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP"}}
            environment["PYTHONUTF8"] = "1"
            try:
                subprocess.run([sys.executable, "-B", "-m", "app.evaluations.pdf_context", str(request_path), str(result_path)],
                    env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=max(.001, deadline - time.monotonic()), check=True)
                if result_path.stat().st_size > 1024 * 1024:
                    raise ValueError("Evidence result exceeds budget")
                extracted = json.loads(result_path.read_text(encoding="utf-8"))
                pages = extracted["pages"]
                limitations.update(extracted["limitations"])
            except (subprocess.SubprocessError, OSError, ValueError, KeyError):
                limitations.add("original_extraction_unavailable")
    checks = []
    for page in pages:
        matching = locations[(page["paper_id"], page["page"])]
        page["citation_keys"] = [citation["key"] for citation in matching]
        for citation in matching:
            matched = normalized(citation["source_text"]) in normalized(page["text"])
            checks.append({"citation_key": citation["key"], "status": "matched" if matched else "not_found"})
            if not matched:
                limitations.add("quote_not_matched_text_extraction_may_differ")
    checked = {check["citation_key"] for check in checks}
    checks.extend({"citation_key": citation["key"], "status": "unavailable"}
        for citation in citations if citation["key"] not in checked)
    if not citations:
        limitations.add("no_citation_evidence")
    limitations.add("original_context_is_limited_to_cited_pages")
    return {"scope": "original_pages" if pages else "evidence_only", "pages": pages,
        "checks": checks, "reference_checks": reference_checks(payload), "limitations": sorted(limitations),
        "excerpt_citation_keys": [citation["key"] for citation in citations if citation["source_text"].strip()],
        "source_provenance": provenance}
