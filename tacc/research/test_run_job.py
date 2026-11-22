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
    if getattr(request, "param", None) == "custom":
        manifest["runtime"]["research"] = {"model_provider": "custom", "endpoint_url": "http://10.0.3.10:8000/v1"}
        (tmp_path / "model.env").write_text("MODEL_PROVIDER=tacc\nMODEL_BASE_URL=http://10.0.3.10:8000/v1\n")
    if getattr(request, "param", None) == "extension":
        manifest["runtime"].update(persist=True, research={"workflow": "extension", "planner": True,
            "reflection": True, "context_policy": "compact", "context_finalize_ratio": 0.8})
        task["allow_search"] = True
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

@pytest.mark.parametrize("staged", ["extension"], indirect=True)
def test_extension_search_and_persistence_cross_job_boundary(staged, monkeypatch):
    import extension
    from schemas import TaskResult, Usage

    _, out = staged
    def run(task, *, library, search, persist, context_window, index_dir, **options):
        assert search == library.search_arxiv and task.allow_search
        assert context_window == 16000 and index_dir.name == "retrieval"
        assert options == dict(context_policy="compact", context_finalize_ratio=0.8, planner=True, reflection=True)
        persist([{"source_id": task.sources[0], "pages": [{"text": "original"}]}])
        return TaskResult(task_id=task.task_id, question=task.question, stop_reason="partial", usage=Usage())
    monkeypatch.setattr(extension, "run_task", run)
    assert run_job.main() == 0
    envelope = json.loads((out / "result.json").read_text())
    assert envelope["parsed_papers"][0]["pages"][0]["text"] == "original"
    assert envelope["result"]["configuration"]["workflow"] == "extension"

@pytest.mark.parametrize("staged", ["custom"], indirect=True)
def test_custom_endpoint_discovers_name_and_uses_non_streaming_chat(staged, monkeypatch):
    import baseline
    import httpx
    from apis.model import make_model
    from schemas import TaskResult, Usage

    _, out = staged
    def get_models(client, url):
        assert url == "http://10.0.3.10:8000/v1/models"
        assert "authorization" not in client.headers
        return httpx.Response(200, request=httpx.Request("GET", url), json={"data": [{"id": "team-model"}]})

    def run(task, **kwargs):
        model = make_model()
        assert model.model_name == "team-model" and model.streaming is False
        assert model.openai_api_key.get_secret_value() == "EMPTY"
        return TaskResult(task_id=task.task_id, question=task.question, answer="answer", stop_reason="completed", usage=Usage())

    monkeypatch.setattr(httpx.Client, "get", get_models)
    monkeypatch.setattr(baseline, "run_task", run)
    for name in ("MODEL_API_KEY", "MODEL_NAME", "NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "")
    assert run_job.main() == 0
    result = json.loads((out / "result.json").read_text())["result"]
    assert result["configuration"]["model_provider"] == "custom"
