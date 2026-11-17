"""Process boundary tests use small real subprocesses, never the model service."""

import sys
import time
from pathlib import Path

import pytest
from app.agent_bridge import subprocess_client as client


@pytest.fixture
def script(tmp_path, monkeypatch):
    def write(body):
        path = tmp_path / "fixture_bridge.py"
        path.write_text("import json, sys, time\nfrom pathlib import Path\n" + body)
        monkeypatch.setattr(client, "BRIDGE_SCRIPT", path)
        return path

    return write


def run(**kwargs):
    return client.run_agent(
        {"task_id": "task-1"},
        python=sys.executable,
        timeout_seconds=kwargs.pop("timeout_seconds", 3),
        stopped=kwargs.pop("stopped", lambda: False),
        **kwargs,
    )


def test_missing_interpreter():
    with pytest.raises(client.AgentProcessError) as exc:
        client.run_agent(
            {"task_id": "task-1"},
            python="/missing/python",
            timeout_seconds=1,
            stopped=lambda: False,
        )
    assert exc.value.code == "agent_unavailable"


def test_full_result_and_cleanup(script):
    script(
        "task = json.loads(Path(sys.argv[1]).read_text())\nprint('log noise')\nPath(sys.argv[2]).write_text(json.dumps({**task, 'answer': 'answer', 'usage': {'input_tokens': None}, 'trace': [{'message': 'ok'}]}))\n"
    )
    result = run()
    assert result == {
        "task_id": "task-1",
        "answer": "answer",
        "usage": {"input_tokens": None},
        "trace": [{"message": "ok"}],
    }


@pytest.mark.parametrize(
    "body,code",
    [
        ("raise RuntimeError('secret exception')\n", "agent_process_failed"),
        ("Path(sys.argv[2]).write_text('bad json')\n", "agent_invalid_result"),
        ("Path(sys.argv[2]).write_text('{}')\n", "agent_invalid_result"),
        (
            'Path(sys.argv[2]).write_text(\'{"task_id": "other"}\')\n',
            "agent_task_mismatch",
        ),
        ("pass\n", "agent_invalid_result"),
    ],
)
def test_invalid_result(script, body, code):
    script(body)
    with pytest.raises(client.AgentProcessError) as exc:
        run()
    assert exc.value.code == code
    assert "secret exception" not in str(exc.value)


def test_timeout(script):
    script("time.sleep(20)\n")
    started = time.monotonic()
    with pytest.raises(client.AgentProcessError) as exc:
        run(timeout_seconds=0.15)
    assert exc.value.code == "agent_timeout"
    assert time.monotonic() - started < 4


def test_cancel(script):
    script("time.sleep(20)\n")
    started = time.monotonic()
    with pytest.raises(client.AgentProcessError) as exc:
        run(stopped=lambda: time.monotonic() - started > 0.1)
    assert exc.value.code == "agent_cancelled"
    assert time.monotonic() - started < 4


def test_result_limit(script, monkeypatch):
    monkeypatch.setattr(client, "MAX_RESULT_BYTES", 100)
    script("Path(sys.argv[2]).write_text('x' * 101)\n")
    with pytest.raises(client.AgentProcessError) as exc:
        run()
    assert exc.value.code == "agent_output_limit"


def test_log_limit(script, monkeypatch):
    monkeypatch.setattr(client, "MAX_LOG_BYTES", 100)
    script("print('x' * 101, flush=True)\ntime.sleep(20)\n")
    with pytest.raises(client.AgentProcessError) as exc:
        run()
    assert exc.value.code == "agent_output_limit"


def test_timeout_kills_descendant(script, tmp_path):
    marker = tmp_path / "descendant-survived"
    script(
        "import subprocess\nsubprocess.Popen([sys.executable, '-c', "
        + repr(
            "import time; from pathlib import Path; time.sleep(.8); Path("
            + repr(str(marker))
            + ").write_text('alive')"
        )
        + "])\ntime.sleep(20)\n"
    )
    with pytest.raises(client.AgentProcessError):
        run(timeout_seconds=0.15)
    time.sleep(0.9)
    assert not marker.exists()


def test_temp_protocol_directory_removed(script, tmp_path):
    location = tmp_path / "location"
    script(
        "Path(" + repr(str(location)) + ").write_text(str(Path(sys.argv[1]).parent))\n"
        'Path(sys.argv[2]).write_text(\'{"task_id": "task-1"}\')\n'
    )
    run()
    assert not Path(location.read_text()).exists()
