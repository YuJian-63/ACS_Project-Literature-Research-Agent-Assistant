"""Exercise the optional Planner through the Extension's normal task entry point."""

import time

import pytest
from test_baseline import CHUNK, ScriptedModel, call, final, message, paper

from extension import EXTENSION_SYSTEM, run_task
from schemas import Task

TASK = Task(
    question="Identify the method and its evaluation conditions.",
    sources=["1706.03762v7"],
    max_steps=2,
    timeout_seconds=30,
    max_output_tokens=128,
)
TASK_JSON = TASK.model_dump_json(exclude={"max_steps", "timeout_seconds", "max_output_tokens"})
PLAN = "Identify the method.\nCheck how the authors measured it."


def execute(replies, **options):
    model = ScriptedModel(replies)
    result = run_task(TASK, model_factory=model.factory, reader=paper, **options)
    return result, model


def test_extension_skips_planning_by_default():
    result, model = execute([message(calls=[call()]), final()])

    assert result.stop_reason == "completed"
    assert result.configuration["planner"] is False
    assert not any(entry["kind"] == "planner" for entry in result.trace)
    assert all(entry["bound"] for entry in model.invocations)
    assert result.usage.model_calls == result.usage.agent_steps == 2
    assert model.inputs[0][-1].content == TASK_JSON


def test_planner_flag_rejects_a_string_before_model_setup():
    model = ScriptedModel([])
    with pytest.raises(TypeError, match="planner"):
        run_task(TASK, model_factory=model.factory, planner="false")
    assert not model.settings
    assert not model.inputs


def test_planner_appends_advice_and_counts_costs_without_spending_an_agent_step():
    result, model = execute([message(PLAN), message(calls=[call()]), final()], planner=True)

    assert result.stop_reason == "completed"
    assert result.citations[0].chunk_id == CHUNK
    assert result.configuration["planner"] is True
    assert result.configuration["context_finalize_ratio"] == 0.9
    assert result.usage.agent_steps == 2
    assert result.usage.tool_calls == 1
    assert result.usage.model_calls == 3
    assert result.usage.total_tokens == 360
    calls = [entry for entry in result.trace if entry["kind"] == "model"]
    assert [entry["purpose"] for entry in calls] == ["planner", "agent", "agent"]
    assert [entry["bound"] for entry in model.invocations] == [False, True, True]
    assert model.inputs[0][-1].content == TASK_JSON
    assert 0 < model.invocations[0]["timeout"] <= TASK.timeout_seconds
    assert 0 < model.invocations[0]["max_tokens"] <= TASK.max_output_tokens
    system, human = model.inputs[1]
    assert system.type == "system" and system.content == EXTENSION_SYSTEM
    assert human.type == "human" and human.content.startswith(TASK_JSON)
    assert human.content.endswith(PLAN)
    assert "reference plan" in human.content[len(TASK_JSON) : -len(PLAN)].lower()
    plans = [entry["plan"] for entry in result.trace if entry["kind"] == "planner"]
    assert plans == [PLAN]


@pytest.mark.parametrize(
    "reply,outcome",
    [
        (message("   "), "empty"),
        (message("NO_PLAN"), "empty"),
        (message("one\ntwo\nthree\nfour"), "invalid"),
        (message("Partial plan", finish_reason="length"), "invalid"),
        (message(calls=[call()]), "invalid"),
        (RuntimeError("private endpoint"), "model_error"),
    ],
)
def test_empty_or_failed_planner_continues_with_only_the_original_task(reply, outcome):
    result, model = execute([reply, message(calls=[call()]), final()], planner=True)

    assert result.stop_reason == "completed"
    assert model.inputs[1][-1].content == TASK_JSON
    assert result.usage.model_calls == 3
    assert result.usage.tool_calls == 1
    events = [entry for entry in result.trace if entry["kind"] == "planner"]
    assert [(e["outcome"], e["plan"]) for e in events] == [(outcome, "")]
    if outcome == "model_error":
        assert not result.usage.token_usage_complete
        assert result.usage.total_tokens is None
        assert "private endpoint" not in result.model_dump_json()


def test_pressure_after_planning_still_finalizes_once_with_the_acquired_evidence():
    read = message(calls=[call()])
    # The full-history policy uses this API input count to estimate the next round.
    read.usage_metadata.update(input_tokens=9000, total_tokens=9020)
    result, model = execute(
        [message(PLAN), read, final()],
        planner=True,
        context_policy="full",
        context_window=10000,
        context_finalize_ratio=0.9,
    )

    assert result.stop_reason == "completed"
    assert result.citations[0].chunk_id == CHUNK
    calls = [entry["purpose"] for entry in result.trace if entry["kind"] == "model"]
    assert calls == ["planner", "agent", "finalize"]
    assert [entry["bound"] for entry in model.invocations] == [False, True, False]
    assert result.usage.agent_steps == 2
    assert result.usage.model_calls == 3


def test_planner_respects_the_shared_task_deadline(monkeypatch):
    clock = [time.monotonic()]
    monkeypatch.setattr("baseline.time.monotonic", lambda: clock[0])

    def late_plan():
        clock[0] += TASK.timeout_seconds
        return message(PLAN)

    result, model = execute([late_plan], planner=True)

    assert result.stop_reason == "time_limit"
    assert result.usage.model_calls == len(model.inputs) == 1
    assert result.usage.agent_steps == result.usage.tool_calls == 0
    assert result.usage.total_tokens == 120
