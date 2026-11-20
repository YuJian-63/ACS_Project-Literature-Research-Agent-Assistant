import argparse
import subprocess
import time
from pathlib import Path

from app.agent_bridge.bundles import canonical_json, read_json
from app.agent_bridge.files import atomic_write, controlled


def supervise(spec: Path) -> int:
    spec = controlled(spec)
    record = read_json(spec, 65536)
    directory = spec.parent
    identity = {
        name: record[name] for name in ("dispatch_id", "input_sha256", "remote_job_id")
    }
    receipt = {
        "schema_version": "agent-local-exit-v1",
        **identity,
        "returncode": None,
        "error": None,
    }
    command = [
        record["python"],
        "-B",
        str(Path(record["agent_root"]) / "run_dispatch.py"),
        "--input",
        str(directory / "input.zip"),
        "--dispatch-id",
        identity["dispatch_id"],
        "--input-sha256",
        identity["input_sha256"],
        "--remote-job-id",
        identity["remote_job_id"],
        "--work-root",
        str(directory / "work"),
        "--output-dir",
        str(directory),
        "--max-result-bytes",
        str(record["max_result_bytes"]),
    ]
    process = None
    try:
        remaining = min(
            record["timeout_seconds"],
            record.get("deadline", time.time() + record["timeout_seconds"])
            - time.time(),
        )
        if (directory / "cancel.request").exists() or remaining <= 0:
            receipt["error"] = (
                "AGENT_PROCESS_CANCELLED"
                if (directory / "cancel.request").exists()
                else "AGENT_PROCESS_TIMEOUT"
            )
            return 1
        deadline = time.monotonic() + remaining
        process = subprocess.Popen(
            command,
            cwd=record["agent_root"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        while process.poll() is None:
            if (directory / "cancel.request").exists() or time.monotonic() >= deadline:
                receipt["error"] = (
                    "AGENT_PROCESS_CANCELLED"
                    if (directory / "cancel.request").exists()
                    else "AGENT_PROCESS_TIMEOUT"
                )
                process.kill()
                break
            time.sleep(0.1)
        receipt["returncode"] = process.wait()
    except OSError:
        receipt["error"] = "AGENT_LAUNCH_FAILED"
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        atomic_write(directory / "exit.json", canonical_json(receipt))
    return 0 if receipt["returncode"] == 0 and receipt["error"] is None else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Supervise one local Agent without backend lifetime coupling"
    )
    parser.add_argument("--spec", type=Path, required=True)
    return supervise(parser.parse_args().spec)


if __name__ == "__main__":
    raise SystemExit(main())
