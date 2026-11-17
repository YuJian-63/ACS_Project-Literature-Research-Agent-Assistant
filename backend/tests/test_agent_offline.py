"""Optional real Agent 3.12 execution with injected offline model/reader, no API keys."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from app.agent_bridge import subprocess_client
from app.tasks.agent import validated_result


@pytest.mark.skipif(
    not os.environ.get("AGENT_TEST_PYTHON"),
    reason="Set AGENT_TEST_PYTHON to a locked Agent Python 3.12 environment",
)
def test_real_agent_function_through_bridge_with_offline_tools(tmp_path, monkeypatch):
    repo = Path(__file__).resolve().parents[2]
    wrapper = tmp_path / "offline_bridge.py"
    wrapper.write_text(f"""
import sys,runpy
sys.path.insert(0,{str(repo / "agent")!r})
sys.path.insert(0,{str(repo / "agent" / "tests")!r})
import baseline
from test_baseline import ScriptedModel,message,call,final,paper
original=baseline.run_task
model=ScriptedModel([message(calls=[call()]),final()])
def offline(task,*,persist=False):
    assert persist is False
    return original(task,model_factory=model.factory,reader=paper,persist=False)
baseline.run_task=offline
runpy.run_path({str(subprocess_client.BRIDGE_SCRIPT)!r},run_name='__main__')
""")
    monkeypatch.setattr(subprocess_client, "BRIDGE_SCRIPT", wrapper)
    identity = uuid4()
    payload = {
        "task_id": str(identity),
        "question": "Explain the method",
        "sources": ["1706.03762v7"],
        "max_steps": 4,
    }
    result = subprocess_client.run_agent(
        payload,
        python=os.environ["AGENT_TEST_PYTHON"],
        timeout_seconds=30,
        stopped=lambda: False,
    )
    result = validated_result(result, identity)
    assert result["stop_reason"] == "completed"
    assert result["citations"][0]["source_text"] == "Original evidence on page 1."
    assert result["usage"]["agent_steps"] == 2
    assert result["trace"]
