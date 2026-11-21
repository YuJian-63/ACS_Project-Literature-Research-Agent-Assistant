"""Fetch and verify a PDF served by the local origin through a tunnel."""

import hashlib
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

import pymupdf


def main() -> None:
    config = json.loads(Path("target.json").read_text())
    job_id = os.environ["SLURM_JOB_ID"]
    report = {"job_id": job_id, "url": config["url"], "status": "fail"}
    runs_dir = Path(os.environ["TACC_USERDIR"]) / "api-probe" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    report_path = runs_dir / f"tunnel-probe-{job_id}.json"

    try:
        request = Request(config["url"], headers={"X-TACC-Probe-Job": job_id})
        with urlopen(request, timeout=30) as response:
            report["http_status"] = response.status
            report["content_type"] = response.headers.get_content_type()
            pdf = response.read(1024 * 1024 + 1)

        report["bytes"] = len(pdf)
        report["sha256"] = hashlib.sha256(pdf).hexdigest()
        if report["http_status"] != 200 or report["content_type"] != "application/pdf":
            raise ValueError("Unexpected HTTP response")
        if not pdf.startswith(b"%PDF-") or report["sha256"] != config["sha256"]:
            raise ValueError("Response bytes do not match the local fixture")

        with pymupdf.open(stream=pdf, filetype="pdf") as document:
            report["pages"] = len(document)
            report["text"] = document[0].get_text().strip()
        if report["pages"] != 1 or "TACC backend probe" not in report["text"]:
            raise ValueError("Unexpected PDF content")
        report["status"] = "pass"
    except Exception as error:
        report["error"] = str(error)
        raise
    finally:
        output = json.dumps(report, indent=2) + "\n"
        report_path.write_text(output)
        print(f"Report: {report_path}")
        print(output, end="")


if __name__ == "__main__":
    main()
