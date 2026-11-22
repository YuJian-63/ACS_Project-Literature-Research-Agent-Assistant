"""Offline contracts for finalizing once under context pressure."""

import time
from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from test_baseline import CHUNK, ScriptedModel, call, final, message, paper

import extension
from baseline import SUMMARY_SYSTEM, run_task
from context import PreparedContext, TokenCounter
from schemas import Task


def execute(replies, *, estimate=8900, reader=paper, task_fields=None, **options):
    model = ScriptedModel(replies)
    histories = []

    def pressure_policy(messages, **kwargs):
        histories.append(deepcopy(messages))
        return PreparedContext(messages, 100 if len(histories) == 1 else estimate, "heuristic")

    task = Task(
        **{
            "question": "What does the paper say?",
            "sources": ["1706.03762v7"],
            "max_output_tokens": 100,
            **(task_fields or {}),
        }
    )
    result = run_task(
        task,
        model_factory=model.factory,
        reader=reader,
        **{"context_window": 10000, "context_policy": pressure_policy, **options},
    )
    return result, model, histories


def triggers(result):
    return [entry for entry in result.trace if entry.get("action") == "finalize"]


@pytest.mark.parametrize(
    "estimate,finalizing", [(8899, False), (8900, True), (9900, True), (9901, True)]
)
def test_soft_boundary_reserves_output_and_finalizes_without_tools(estimate, finalizing):
    result, model, histories = execute(
        [message(calls=[call(call_id="read_original")]), final()],
        estimate=estimate,
        task_fields={"max_steps": 2},
    )

    assert result.stop_reason == "completed"
    assert result.citations[0].chunk_id == CHUNK
    assert result.citations[0].source_text == "Original evidence on page 1."
    assert result.usage.agent_steps == result.usage.model_calls == 2
    assert result.usage.tool_calls == 1
    assert result.usage.total_tokens == 240
    assert result.configuration["context_finalize_ratio"] == 0.9
    assert [item["bound"] for item in model.invocations] == [True, not finalizing]
    assert len(histories) == 2
    entries = [entry for entry in result.trace if entry["kind"] == "model"]
    assert [entry["purpose"] for entry in entries] == [
        "agent",
        "finalize" if finalizing else "agent",
    ]
    assert all(entry["output_limit"] == 100 for entry in entries)
    observations = [item for item in model.inputs[-1] if isinstance(item, ToolMessage)]
    assert [item.tool_call_id for item in observations] == ["read_original"]
    assert len(triggers(result)) == int(finalizing)
    if finalizing:
        assert triggers(result)[0]["kind"] == "context"
        assert triggers(result)[0]["reason"] == "context_pressure"
        assert model.inputs[-1][:-1] == histories[-1]


@pytest.mark.parametrize("options", [{"context_finalize_ratio": None}, {"context_window": None}])
def test_disabled_ratio_or_window_keeps_normal_agent_calls(options):
    result, model, _ = execute([message(calls=[call()]), final()], **options)

    assert result.stop_reason == "completed"
    assert all(item["bound"] for item in model.invocations)
    assert not triggers(result)
    assert all(entry.get("purpose") != "finalize" for entry in result.trace)


@pytest.mark.parametrize("estimate,finalizing", [(7899, False), (7900, True)])
def test_custom_ratio_controls_the_context_threshold(estimate, finalizing):
    result, model, _ = execute(
        [message(calls=[call()]), final()], estimate=estimate, context_finalize_ratio=0.8
    )

    assert result.stop_reason == "completed"
    assert result.configuration["context_finalize_ratio"] == 0.8
    assert len(triggers(result)) == int(finalizing)
    assert model.invocations[-1]["bound"] is not finalizing


@pytest.mark.parametrize("ratio", [0, -0.1, 1.1, True, "0.8", float("nan"), float("inf")])
def test_invalid_ratio_is_rejected_before_model_setup(ratio):
    model = ScriptedModel([])

    with pytest.raises(ValueError, match="context_finalize_ratio"):
        run_task(
            Task(question="Q", sources=["1706.03762v7"]),
            model_factory=model.factory,
            reader=paper,
            context_finalize_ratio=ratio,
        )

    assert model.settings == []
    assert model.inputs == []


def test_ratio_one_finalizes_at_the_hard_limit():
    result, model, _ = execute(
        [message(calls=[call()]), final()], estimate=9900, context_finalize_ratio=1
    )

    assert result.stop_reason == "completed"
    assert len(triggers(result)) == 1
    assert not model.invocations[-1]["bound"]
    entry = result.trace[-1]
    assert (
        entry["context"]["input_tokens_estimate"]
        == TokenCounter().estimate(model.inputs[-1], [])[0]
    )
    assert entry["context"]["input_tokens_estimate"] + entry["output_limit"] <= 10000


@pytest.mark.parametrize("runner", [run_task, extension.run_task], ids=["baseline", "extension"])
def test_overflow_fits_complete_evidence_and_preserves_the_original_trace(runner):
    large_text = "An oversized passage. " * 800

    def reader(source, **kwargs):
        parsed = paper(source, page_count=2)
        parsed["chunks"][1]["source_text"] = parsed["pages"][1]["text"] = large_text
        return parsed

    read = call(source="1706.03762v7", page_start=1, page_end=2)
    model = ScriptedModel([message(calls=[read]), final()])
    result = runner(
        Task(question="What does the paper say?", sources=["1706.03762v7"], max_output_tokens=100),
        reader=reader,
        model_factory=model.factory,
        context_window=2500,
    )

    assert result.stop_reason == "completed"
    assert len(triggers(result)) == 1
    assert triggers(result)[0]["context"]["input_tokens_estimate"] > 2500
    assert model.inputs[-1][:2] == model.inputs[0][:2]
    assert CHUNK in str(model.inputs[-1]) and "Original evidence on page 1." in str(
        model.inputs[-1]
    )
    request, reply = model.inputs[-1][2:4]
    assert [c["id"] for c in request.tool_calls] == [read["id"]]
    assert isinstance(reply, ToolMessage) and reply.tool_call_id == read["id"]
    assert large_text not in str(model.inputs[-1])
    read_result = next(entry["observation"] for entry in result.trace if entry["kind"] == "tool")
    assert read_result["chunks"][1]["source_text"] == large_text
    assert TokenCounter().estimate(model.inputs[-1], [])[0] + 100 <= 2500
    assert result.usage.model_calls == 2 and not model.invocations[-1]["bound"]


def test_unfit_task_and_output_reserve_still_stop_before_model_call():
    result, model, _ = execute([], context_window=100)

    assert result.stop_reason == "context_limit"
    assert len(triggers(result)) == 1
    assert result.trace[-1]["purpose"] == "finalize"
    assert result.usage.model_calls == len(model.inputs) == 0


def test_finalization_uses_prepared_view_once_without_restoring_full_history():
    histories = []

    def view_policy(messages, **kwargs):
        histories.append(deepcopy(messages))
        return PreparedContext(
            [HumanMessage(content="Prepared research view")],
            100 if len(histories) == 1 else 8900,
            "heuristic",
        )

    result, model, _ = execute([message(calls=[call()]), final()], context_policy=view_policy)

    assert result.stop_reason == "completed"
    assert len(histories) == 2
    assert any(isinstance(item, ToolMessage) for item in histories[-1])
    assert model.inputs[-1][:-1] == [HumanMessage(content="Prepared research view")]
    assert not any(isinstance(item, ToolMessage) for item in model.inputs[-1])
    assert "Original evidence" not in str(model.inputs[-1])
    assert model.invocations[-1]["bound"] is False
    assert result.citations[0].source_text == "Original evidence on page 1."
    assert len(triggers(result)) == 1


class ContextExceeded(Exception):
    code = "context_length_exceeded"


@pytest.mark.parametrize(
    "reply,reason",
    [
        (RuntimeError("secret endpoint"), "model_error"),
        (ContextExceeded("secret endpoint"), "context_limit"),
        (message("not JSON"), "invalid_output"),
        (message("unfinished", finish_reason="length"), "output_truncated"),
        (message(calls=[call(call_id="unexpected_tool")]), "invalid_tool_call"),
        (
            AIMessage(
                content="",
                invalid_tool_calls=[
                    {"name": "read_paper", "args": "{", "id": "bad", "error": "JSON"}
                ],
            ),
            "invalid_tool_call",
        ),
        (final("arxiv:1706.03762v7:p9:c1"), "invalid_citations"),
        (final(unresolved=["The experimental conditions remain unclear."]), "partial"),
    ],
)
def test_finalization_failures_do_not_retry_or_dispatch_tools(reply, reason):
    result, model, _ = execute([message(calls=[call()]), reply, final()])

    assert result.stop_reason == reason
    assert result.usage.agent_steps == result.usage.model_calls == len(model.inputs) == 2
    assert result.usage.tool_calls == 1
    assert len(triggers(result)) == 1
    assert model.invocations[-1]["bound"] is False
    assert "secret" not in result.model_dump_json()


def test_missing_finalization_usage_stays_unknown():
    result, model, _ = execute([message(calls=[call()]), message(final().content, usage=False)])

    assert result.stop_reason == "completed"
    assert result.usage.model_calls == result.usage.agent_steps == len(model.inputs) == 2
    assert not result.usage.token_usage_complete
    assert result.usage.input_tokens is None
    assert result.usage.output_tokens is None
    assert result.usage.total_tokens is None


@pytest.mark.parametrize("summary_estimate,reason", [(8900, "completed"), (9901, "context_limit")])
@pytest.mark.parametrize("mode", ["injected", "compact"])
def test_summary_pressure_never_triggers_finalization(monkeypatch, summary_estimate, reason, mode):
    def estimate(self, messages, tools):
        if messages[0].content == SUMMARY_SYSTEM:
            return summary_estimate, "heuristic"
        assert mode == "compact"
        return 100, "heuristic"

    monkeypatch.setattr(TokenCounter, "estimate", estimate)
    result, model, _ = execute(
        [message(calls=[call("summarize_paper")]), message(f"Summary [{CHUNK}]"), final()],
        estimate=100,
        **({"context_policy": "compact"} if mode == "compact" else {}),
    )

    assert result.stop_reason == reason
    assert not triggers(result)
    assert all(entry.get("purpose") != "finalize" for entry in result.trace)
    assert not any(entry.get("action") == "compact" for entry in result.trace)
    assert result.usage.tool_calls == 1
    assert result.usage.model_calls == (3 if reason == "completed" else 1)
    assert len(model.inputs) == result.usage.model_calls


def test_step_limit_does_not_add_a_finalization_call():
    result, model, _ = execute([message(calls=[call()]), final()], task_fields={"max_steps": 1})

    assert result.stop_reason == "step_limit"
    assert result.usage.agent_steps == result.usage.model_calls == len(model.inputs) == 1
    assert result.usage.tool_calls == 0
    assert not triggers(result)


def test_expired_deadline_does_not_add_a_finalization_call(monkeypatch):
    clock = [time.monotonic()]
    monkeypatch.setattr("baseline.time.monotonic", lambda: clock[0])

    def late_reader(source, **kwargs):
        clock[0] += 31
        return paper(source)

    result, model, _ = execute(
        [message(calls=[call()]), final()],
        reader=late_reader,
        task_fields={"timeout_seconds": 30},
    )

    assert result.stop_reason == "time_limit"
    assert result.usage.agent_steps == result.usage.model_calls == len(model.inputs) == 1
    assert result.usage.tool_calls == 1
    assert not triggers(result)
