import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path
from uuid import UUID

from app.papers.storage import controlled_path


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


def prepare_evidence(payload: dict, settings) -> dict:
    citations = payload["citations"]
    sources = {f"local:{source['paper_id']}@{source['sha256']}": source for source in payload["original_sources"]}
    specification, locations, limitations = {}, {}, set()
    for citation in citations:
        source = sources.get(citation.get("source_id"))
        if not source:
            limitations.add("originals_unavailable")
            continue
        location = (source["paper_id"], citation["page"])
        if location not in locations:
            try:
                path = controlled_path(settings.storage_root, UUID(source["paper_id"]), source["storage_key"])
            except (ValueError, OSError):
                limitations.add("original_path_unavailable")
                continue
            item = specification.setdefault(source["paper_id"], {"paper_id": source["paper_id"],
                "sha256": source["sha256"], "path": str(path), "pages": []})
            item["pages"].append(citation["page"])
            locations[location] = []
        locations[location].append(citation)
    pages = []
    if specification:
        with tempfile.TemporaryDirectory(prefix="evaluation-evidence-") as temporary:
            request_path, result_path = Path(temporary) / "request.json", Path(temporary) / "result.json"
            request_path.write_text(json.dumps(list(specification.values())), encoding="utf-8")
            environment = {key: value for key, value in os.environ.items()
                if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP"}}
            environment["PYTHONUTF8"] = "1"
            try:
                subprocess.run([sys.executable, "-B", "-m", "app.evaluations.pdf_context", str(request_path), str(result_path)],
                    env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=settings.evaluation_evidence_timeout_seconds, check=True)
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
        "checks": checks, "reference_checks": reference_checks(payload), "limitations": sorted(limitations)}
