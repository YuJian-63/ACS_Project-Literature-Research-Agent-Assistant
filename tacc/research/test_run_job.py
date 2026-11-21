import hashlib
import json
import os
import sys
import time
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

import pytest
import run_job


@pytest.fixture
def staged(tmp_path, monkeypatch, request):
    old_mask = os.umask(0o077)
    request.addfinalizer(lambda: os.umask(old_mask))
    for name in ("MODEL_BASE_URL", "BAILIAN_API_KEY", "MODEL_PROVIDER"):
        monkeypatch.setenv(name, "test")
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "agent"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TACC_USERDIR", str(tmp_path))
    monkeypatch.setenv("SLURM_JOB_ID", "123")
    monkeypatch.setenv("ACS_MODEL_CONFIG", str(tmp_path / "model.env"))
    (tmp_path / "model.env").write_text(
        "MODEL_BASE_URL=https://example.test/v1\nBAILIAN_API_KEY=temporary\n"
    )
    (tmp_path / "library-access.json").write_text(
        json.dumps({"base_url": "https://library.test", "token": "temporary"})
    )
    dispatch_id, paper_id = str(uuid4()), str(uuid4())
    source_id = f"local:{paper_id}@{'0' * 64}"
    task = {
        "task_id": "test",
        "question": "Read this paper",
        "sources": [source_id],
        "max_papers": 1,
    }
    sources = [
        {
            "source_id": source_id,
            "paper_id": paper_id,
            "sha256": "0" * 64,
            "size_bytes": 64,
            "path": f"papers/{paper_id}.pdf",
            "title": "Fixture",
        }
    ]
    manifest = {
        "schema_version": "agent-dispatch-v1",
        "dispatch_id": dispatch_id,
        "task": task,
        "sources": sources,
        "runtime": {"persist": False, "context_window": 16000},
    }
    raw = json.dumps(manifest).encode()
    with ZipFile("input.zip", "w") as archive:
        archive.writestr("manifest.json", raw)
        archive.writestr("sources.json", json.dumps(sources))
        archive.writestr("task.json", json.dumps(task))
    dispatch = {
        "dispatch_id": dispatch_id,
        "input_sha256": hashlib.sha256(raw).hexdigest(),
        "deadline": time.time() + 300,
    }
    Path("dispatch.json").write_text(json.dumps(dispatch))
    monkeypatch.setattr(sys, "argv", ["run_job.py", "--start"])
    assert run_job.main() == 0
    monkeypatch.setattr(sys, "argv", ["run_job.py"])
    return dispatch, tmp_path / "acs-research" / "jobs" / dispatch_id


def test_metadata_only_job_publishes_result(staged, monkeypatch):
    import baseline
    from schemas import TaskResult, Usage

    dispatch, out = staged

    def run(task, *, library, persist, context_window):
        assert (
            library.base_url == "https://library.test" and library.token == "temporary"
        )
        assert (
            not persist and context_window == 16000 and 0 < task.timeout_seconds <= 300
        )
        return TaskResult(
            task_id=task.task_id,
            question=task.question,
            stop_reason="completed",
            answer="answer",
            usage=Usage(),
        )

    monkeypatch.setattr(baseline, "run_task", run)
    assert run_job.main() == 0
    envelope = json.loads((out / "result.json").read_text())
    assert (
        envelope["schema_version"] == "agent-result-v1"
        and envelope["remote_job_id"] == "123"
    )
    assert envelope["input_sha256"] == dispatch["input_sha256"]
    assert (
        envelope["result"]["task_id"] == "test"
        and envelope["result"]["answer"] == "answer"
    )
    assert json.loads((out / "status.json").read_text())["state"] == "succeeded"


def test_other_job_cannot_overwrite_status(staged, monkeypatch):
    _, out = staged
    before = (out / "status.json").read_bytes()
    monkeypatch.setenv("SLURM_JOB_ID", "456")
    monkeypatch.setattr(sys, "argv", ["run_job.py", "--start"])
    assert run_job.main() == os.EX_CANTCREAT
    assert (out / "status.json").read_bytes() == before


def test_expired_job_skips_model(staged):
    dispatch, out = staged
    dispatch["deadline"] = time.time() - 1
    Path("dispatch.json").write_text(json.dumps(dispatch))
    assert run_job.main() == 1
    assert (
        json.loads((out / "status.json").read_text())["error"]["code"]
        == "AGENT_PLATFORM_TIMEOUT"
    )
    assert not (out / "result.json").exists()
