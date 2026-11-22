"""Run the research baseline and publish files read by the backend's TACC transport."""

import argparse
import fcntl
import hashlib
import json
import math
import os
import re
import signal
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID


class DeadlineExpired(BaseException):
    """Interrupt a blocking library/model call without being caught inside the graph."""


def interrupt_at_deadline(signum, frame):
    raise DeadlineExpired


def publish(path, document):
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            json.dump(document, handle, ensure_ascii=False, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_status(directory, identity, state, **outcome):
    publish(
        directory / "status.json",
        {
            "schema_version": "agent-job-status-v1",
            **identity,
            "state": state,
            "updated_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017 - bootstrap uses Python 3.10.
            **outcome,
        },
    )


def read_manifest(identity):
    with zipfile.ZipFile("input.zip") as archive:
        for name in ("manifest.json", "sources.json", "task.json"):
            if archive.getinfo(name).file_size > 2 * 1024 * 1024:
                raise ValueError("Oversized manifest")
        raw = archive.read("manifest.json")
        if hashlib.sha256(raw).hexdigest() != identity["input_sha256"]:
            raise ValueError("Wrong manifest")
        manifest = json.loads(raw)
        task, sources = manifest["task"], manifest["sources"]
        if (
            manifest["schema_version"] != "agent-dispatch-v1"
            or manifest["dispatch_id"] != identity["dispatch_id"]
            or type(manifest["runtime"]["persist"]) is not bool
            or task != json.loads(archive.read("task.json"))
            or sources != json.loads(archive.read("sources.json"))
            or len(sources) > 20
            or task["sources"] != [s["source_id"] for s in sources]
        ):
            raise ValueError("Dispatch identity or manifest mismatch")
        expected = {"manifest.json", "task.json", "sources.json"}
        members = archive.namelist()
        with_attachments = any(name.startswith("papers/") for name in members)
        for source in sources:
            paper_id = str(UUID(source["paper_id"]))
            name = f"papers/{paper_id}.pdf"
            digest = source["sha256"]
            if (
                name != source["path"]
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or source["source_id"] != f"local:{paper_id}@{digest}"
                or not 0 < source["size_bytes"] <= 50 * 1024 * 1024
            ):
                raise ValueError("Invalid PDF manifest")
            if not with_attachments:
                continue
            expected.add(name)
            if archive.getinfo(name).file_size != source["size_bytes"]:
                raise ValueError("Invalid PDF size")
            actual = hashlib.sha256()
            with archive.open(name) as pdf:
                while block := pdf.read(65536):
                    actual.update(block)
            if actual.hexdigest() != digest:
                raise ValueError("Invalid PDF digest")
        if len(members) != len(expected) or set(members) != expected:
            raise ValueError("Unexpected ZIP member")
    return manifest


def run_research(identity, deadline, papers):
    from apis.library import LibraryClient
    from dotenv import dotenv_values
    from schemas import Task

    manifest = read_manifest(identity)
    settings = dotenv_values(os.environ["ACS_MODEL_CONFIG"], interpolate=False)
    for name in ("MODEL_BASE_URL", "MODEL_NAME", "BAILIAN_API_KEY", "EMBEDDING_BASE_URL", "EMBEDDING_MODEL", "EMBEDDING_DIMENSIONS"):
        if settings.get(name):
            os.environ[name] = settings[name]
    if not settings.get("MODEL_BASE_URL", "").startswith(
        "https://"
    ) or not settings.get("BAILIAN_API_KEY"):
        raise ValueError("Missing Bailian endpoint or credential")
    os.environ["MODEL_PROVIDER"] = "bailian"
    task = Task.model_validate(manifest["task"])
    library = None
    access_path = Path("library-access.json")
    if access_path.is_file():
        access = json.loads(access_path.read_text())
        if not access["base_url"].startswith("https://") or not access["token"]:
            raise ValueError("Invalid library access")
        library = LibraryClient(access["base_url"], access["token"])
    elif task.sources:
        raise ValueError("Missing authorized library access for the selected papers")
    remaining = deadline - time.time()
    if remaining <= 0:
        raise DeadlineExpired
    task.timeout_seconds = min(task.timeout_seconds or remaining, remaining)
    runtime = manifest["runtime"]
    research = runtime.get("research") or {}
    workflow = research.get("workflow", "baseline")
    options = {key: research[key] for key in ("context_policy", "context_finalize_ratio") if key in research}
    if workflow == "extension":
        from extension import run_task
        options["index_dir"] = Path(os.environ["TACC_USERDIR"]) / "acs-research" / "retrieval"
        options.update(planner=research.get("planner", False), reflection=research.get("reflection", False))
    elif workflow == "baseline":
        from baseline import run_task
    else:
        raise ValueError("Unknown research workflow")
    if task.allow_search and library:
        options["search"] = library.search_arxiv
    result = run_task(
        task,
        library=library,
        persist=papers.extend if runtime["persist"] else False,
        context_window=runtime["context_window"],
        **options,
    ).model_dump(mode="json")
    result["configuration"]["workflow"] = workflow
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    phases = parser.add_mutually_exclusive_group()
    phases.add_argument("--start", action="store_true")
    phases.add_argument("--bootstrap-failed", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    dispatch = json.loads(Path("dispatch.json").read_text())
    dispatch_id = str(UUID(dispatch["dispatch_id"]))
    digest = dispatch["input_sha256"]
    job_id = os.environ["SLURM_JOB_ID"]
    deadline = float(dispatch["deadline"])
    if (
        not math.isfinite(deadline)
        or not re.fullmatch(r"\d{1,20}", job_id)
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
    ):
        raise ValueError("Invalid dispatch")
    identity = {
        "dispatch_id": dispatch_id,
        "input_sha256": digest,
        "remote_job_id": job_id,
    }
    directory = Path(os.environ["TACC_USERDIR"]) / "acs-research" / "jobs" / dispatch_id
    directory.mkdir(parents=True, exist_ok=True)
    status = directory / "status.json"
    with (directory / "job.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if status.exists():
            previous = json.loads(status.read_text())
            if any(previous[key] != value for key, value in identity.items()):
                return os.EX_CANTCREAT
            if previous["state"] != "running":
                return 0 if args.bootstrap_failed else 1
        elif not args.start:
            return 1
        if args.start:
            write_status(directory, identity, "running")
        if time.time() >= deadline:
            write_status(
                directory,
                identity,
                "failed",
                error={"code": "AGENT_PLATFORM_TIMEOUT", "type": "TimeoutError"},
            )
            return 1
        if args.start:
            print(max(1, math.ceil(deadline - time.time())))
            return 0
        if args.bootstrap_failed:
            write_status(
                directory,
                identity,
                "failed",
                error={"code": "AGENT_RUNTIME_FAILED", "type": "RuntimeError"},
            )
            return 1
        signal.signal(signal.SIGALRM, interrupt_at_deadline)
        try:
            signal.setitimer(signal.ITIMER_REAL, max(0.001, deadline - time.time()))
            papers = []
            result = run_research(identity, deadline, papers)
            signal.setitimer(signal.ITIMER_REAL, 0)
            envelope = {"schema_version": "agent-result-v1", **identity, "result": result}
            if papers:
                envelope["parsed_papers"] = papers
                limit = dispatch.get("max_result_bytes", 16 * 1024 * 1024)
                if len(json.dumps(envelope, ensure_ascii=False).encode()) > limit:
                    del envelope["parsed_papers"]
                    result["errors"].append({"stage": "persistence", "type": "PaperBundleTooLarge"})
            publish(directory / "result.json", envelope)
            reason = result["stop_reason"]
            state = "succeeded" if reason in {"completed", "partial"} else "failed"
            write_status(directory, identity, state, stop_reason=reason)
            print(f"{state} {job_id} {reason}", flush=True)
            return 0
        except DeadlineExpired:
            write_status(
                directory,
                identity,
                "failed",
                error={"code": "AGENT_PLATFORM_TIMEOUT", "type": "TimeoutError"},
            )
        except Exception as error:  # noqa: BLE001 - only publish the error class, never credentials.
            write_status(
                directory,
                identity,
                "failed",
                error={"code": "AGENT_WRAPPER_FAILED", "type": type(error).__name__},
            )
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
