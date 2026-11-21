"""Check a synthetic PDF through the authenticated library API on a TACC CPU."""

import json
import os
import platform
from pathlib import Path
from uuid import UUID

import httpx
from apis.library import LibraryClient, read_library_paper, search_library


def check(report: dict) -> None:
    target = json.loads(Path("target.json").read_text())
    access = json.loads(Path("library-access.json").read_text())
    base = httpx.URL(access["base_url"])
    if base.scheme != "https" or not base.host or base.username or base.password:
        raise ValueError("Expected a trusted HTTPS backend")
    client = LibraryClient(access["base_url"], access["token"])
    report["step"] = "search"
    page = search_library(client.base_url, client.token, target["query"], limit=2)
    if page["total"] != 1 or len(page["items"]) != 1:
        raise ValueError("Expected exactly one fixture in the search results")
    item = page["items"][0]
    if item["id"] != target["paper_id"] or item["sha256"] != target["sha256"]:
        raise ValueError("Search returned a different fixture")
    report["search_total"] = page["total"]

    report["step"] = "download"
    source = f"local:{target['paper_id']}@{target['sha256']}"
    paper = read_library_paper(client, source, item, timeout=30)
    report.update(bytes=item["size_bytes"], sha256=paper["sha256"])
    report["step"] = "page"
    matches = [page["page"] for page in paper["pages"] if target["marker"] in page["text"]]
    if matches != [target["page"]]:
        raise ValueError("Expected the fixture marker only on the specified physical page")
    pages = len(paper["pages"])
    if "page_count" in target and pages != target["page_count"]:
        raise ValueError("Expected the fixture page count")
    report.update(pages=pages, verified_page=matches[0])
    if "foreign_paper_id" in target:
        report["step"] = "ownership"
        other = UUID(target["foreign_paper_id"])
        url = f"{client.base_url.rstrip('/')}/api/v1/agent/papers/{other}/pdf"
        with httpx.stream(
            "GET", url, headers={"Authorization": f"Bearer {client.token}"}, timeout=30
        ) as response:
            report["foreign_pdf_status"] = response.status_code
            if response.status_code != 404:
                raise ValueError("Expected the other user's fixture to be hidden")


def main() -> int:
    job_id = os.environ["SLURM_JOB_ID"]
    report = {"job_id": job_id, "python": platform.python_version(), "status": "fail", "step": "setup"}
    try:
        check(report)
        report.update(status="pass", step="complete")
    except Exception as error:  # noqa: BLE001 - keep URLs and credentials out of batch logs.
        report["error"] = type(error).__name__
        if isinstance(error, httpx.HTTPStatusError):
            report["http_status"] = error.response.status_code

    directory = Path(os.environ["TACC_USERDIR"]) / "api-probe" / "runs"
    directory.mkdir(parents=True, exist_ok=True)
    result = directory / f"library-probe-{job_id}.json"
    temporary = result.with_suffix(".part")
    temporary.write_text(json.dumps(report, indent=2) + "\n")
    temporary.replace(result)
    print(f"{report['status']}: {result.name}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
