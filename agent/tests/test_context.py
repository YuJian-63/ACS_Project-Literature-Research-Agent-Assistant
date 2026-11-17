"""Offline contracts for context estimates, capacity checks and model views."""

from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from test_baseline import CHUNK, ScriptedModel, call, final, message, paper

from baseline import SUMMARY_SYSTEM, SYSTEM, run_task
from context import PreparedContext, TokenCounter, prepare_context
from schemas import Task

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_paper",
            "description": "Read original paper evidence.",
            "parameters": {
                "type": "object",
                "properties": {"source": {"type": "string"}},
                "required": ["source"],
            },
        },
    }
]


def execute(replies, *, max_output_tokens=4096, **options):
    model = ScriptedModel(replies)
    result = run_task(
        Task(question="Q", sources=["1706.03762v7"], max_output_tokens=max_output_tokens),
        model_factory=model.factory,
        reader=paper,
        **options,
    )
    return result, model


def test_default_policy_preserves_complete_messages_and_labels_estimates():
    messages = [SystemMessage(content="Instructions"), HumanMessage(content="原始证据" * 1000)]
    before = deepcopy(messages)
    prepared = prepare_context(
        messages, tools=TOOLS, context_window=10, max_output_tokens=5, counter=TokenCounter()
    )

    assert prepared.messages == messages == before
    assert prepared.input_tokens_estimate > 10
    assert prepared.count_method == "heuristic"


def test_counter_counts_tool_definitions_chinese_calls_and_results():
    counter = TokenCounter()
    messages = [HumanMessage(content="Question")]
    initial, method = counter.estimate(messages, [])
    with_tools, _ = counter.estimate(messages, TOOLS)
    with_chinese, _ = counter.estimate(
        messages + [HumanMessage(content="中文论文证据" * 100)], TOOLS
    )
    called = messages + [AIMessage(content="", tool_calls=[call()])]
    with_call, _ = counter.estimate(called, TOOLS)
    with_result, _ = counter.estimate(
        called + [ToolMessage(content="正文和证据" * 100, tool_call_id="call_1")], TOOLS
    )

    assert method == "heuristic"
    assert initial > 0
    assert with_tools > initial
    assert with_chinese > with_tools
    assert with_call > with_tools
    assert with_result > with_call


def test_usage_anchor_adds_only_new_messages_and_excludes_response_metadata():
    counter = TokenCounter()
    prefix = [HumanMessage(content="Question")]
    counter.observe(prefix, TOOLS, 700)
    assert counter.estimate(prefix, TOOLS) == (700, "usage_anchored_estimate")

    assistant = message(calls=[call()])
    extended = prefix + [assistant, ToolMessage(content="Evidence", tool_call_id="call_1")]
    tokens, method = counter.estimate(extended, TOOLS)
    assert tokens > 700
    assert method == "usage_anchored_estimate"

    assistant.usage_metadata = {
        "input_tokens": 999999,
        "output_tokens": 8888,
        "total_tokens": 1008887,
    }
    assistant.response_metadata = {"provider_internal_data": "not model input" * 1000}
    assert counter.estimate(extended, TOOLS) == (tokens, method)


@pytest.mark.parametrize("changed", ["tools", "prefix", "shortened"])
def test_usage_anchor_is_not_reused_for_a_changed_request(changed):
    counter = TokenCounter()
    messages = [SystemMessage(content="Instructions"), HumanMessage(content="Question")]
    tools = deepcopy(TOOLS)
    counter.observe(messages, tools, 100000)
    if changed == "tools":
        tools[0]["function"]["description"] = "Different tool instructions"
    elif changed == "prefix":
        messages[0].content = "Different instructions"
    else:
        messages.pop()

    assert counter.estimate(messages, tools) == TokenCounter().estimate(messages, tools)
    assert counter.estimate(messages, tools)[1] == "heuristic"


@pytest.mark.parametrize("invalid", [None, -1, True, 1.5, "100"])
def test_invalid_provider_counts_do_not_replace_a_valid_zero_anchor(invalid):
    counter = TokenCounter()
    messages = [HumanMessage(content="Question")]
    counter.observe(messages, TOOLS, 0)
    counter.observe(messages, TOOLS, invalid)
    assert counter.estimate(messages, TOOLS) == (0, "usage_anchored_estimate")


@pytest.mark.parametrize("estimate,expected_calls", [(40, 1), (41, 0)])
def test_window_includes_output_reserve_and_stops_before_model_call(estimate, expected_calls):
    def fixed_policy(messages, **kwargs):
        return PreparedContext(messages, estimate, "heuristic")

    result, model = execute(
        [final()], max_output_tokens=10, context_window=50, context_policy=fixed_policy
    )

    assert len(model.inputs) == result.usage.model_calls == expected_calls
    assert result.usage.agent_steps == expected_calls
    assert result.usage.tool_calls == 0
    assert result.configuration["context_window"] == 50
    assert "fixed_policy" in result.configuration["context_policy"]
    entry = result.trace[0]
    assert entry["context"] == {
        "window": 50,
        "input_tokens_estimate": estimate,
        "count_method": "heuristic",
    }
    assert entry["output_limit"] == 10
    if expected_calls:
        assert entry["kind"] == "model"
        assert result.stop_reason != "context_limit"
    else:
        assert result.stop_reason == entry["stop_reason"] == "context_limit"
        assert entry["kind"] == "context"
        assert entry["purpose"] == "agent"
        assert entry["messages"]
        assert result.usage.total_tokens == 0
        assert not result.answer


def test_missing_usage_keeps_estimates_separate_from_actual_usage():
    result, model = execute([message(calls=[call()], usage=False), final()])

    assert result.stop_reason == "completed"
    assert len(model.inputs) == 2
    assert not result.usage.token_usage_complete
    assert result.usage.input_tokens is None
    assert result.usage.output_tokens is None
    assert result.usage.total_tokens is None
    measured = [entry["context"] for entry in result.trace if entry["kind"] == "model"]
    assert all(entry["count_method"] == "heuristic" for entry in measured)
    assert measured[1]["input_tokens_estimate"] > measured[0]["input_tokens_estimate"]


@pytest.mark.parametrize("output_limit", [768, 4096])
@pytest.mark.parametrize("excess", [0, 1])
def test_summary_checks_its_own_output_reserve(monkeypatch, output_limit, excess):
    window = output_limit + 100
    summary_limit = min(1200, output_limit)

    def estimate(self, messages, tools):
        tokens = window - summary_limit + excess if messages[0].content == SUMMARY_SYSTEM else 100
        return tokens, "heuristic"

    monkeypatch.setattr(TokenCounter, "estimate", estimate)
    result, model = execute(
        [message(calls=[call("summarize_paper")]), message(f"Summary [{CHUNK}]"), final()],
        max_output_tokens=output_limit,
        context_window=window,
    )

    entries = [entry for entry in result.trace if entry.get("purpose") == "chunk_summary"]
    assert len(entries) == 1
    assert entries[0]["output_limit"] == summary_limit
    if excess:
        assert result.stop_reason == "context_limit"
        assert entries[0]["kind"] == "context"
        assert result.usage.model_calls == len(model.inputs) == 1
    else:
        assert result.stop_reason == "completed"
        assert entries[0]["kind"] == "model"
        assert result.usage.model_calls == len(model.inputs) == 3
        assert model.invocations[1]["max_tokens"] == summary_limit


def test_summary_usage_does_not_replace_agent_anchor_or_use_custom_policy():
    policy_inputs = []

    def tracking_policy(messages, **kwargs):
        policy_inputs.append(deepcopy(messages))
        return prepare_context(messages, **kwargs)

    summary = message(f"Brief summary [{CHUNK}]")
    summary.usage_metadata = {"input_tokens": 50000, "output_tokens": 20, "total_tokens": 50020}
    result, model = execute(
        [message(calls=[call("summarize_paper")]), summary, final()],
        context_window=None,
        context_policy=tracking_policy,
    )

    assert result.stop_reason == "completed"
    assert len(policy_inputs) == 2
    assert all(messages[0].content == SYSTEM for messages in policy_inputs)
    entries = [entry for entry in result.trace if entry["kind"] == "model"]
    assert [entry["purpose"] for entry in entries] == ["agent", "chunk_summary", "agent"]
    assert entries[1]["context"]["count_method"] == "heuristic"
    assert entries[2]["context"]["count_method"] == "usage_anchored_estimate"
    assert entries[2]["context"]["input_tokens_estimate"] < 50000
    assert result.usage.input_tokens == 50200
    assert len(model.inputs) == 3


def test_context_stop_preserves_previous_tool_result_and_source():
    calls = 0

    def stop_after_read(messages, **kwargs):
        nonlocal calls
        calls += 1
        return PreparedContext(messages, 100 if calls == 1 else 1000, "heuristic")

    result, model = execute(
        [message(calls=[call()]), final()],
        max_output_tokens=64,
        context_window=200,
        context_policy=stop_after_read,
    )

    assert result.stop_reason == "context_limit"
    assert result.usage.model_calls == result.usage.tool_calls == len(model.inputs) == 1
    assert len(result.sources) == 1
    tool_entry = next(entry for entry in result.trace if entry["kind"] == "tool")
    assert tool_entry["observation"]["chunks"][0]["chunk_id"] == CHUNK
    stopped = result.trace[-1]
    assert stopped["kind"] == "context"
    assert stopped["messages"][-1]["type"] == "tool"
    assert "Original evidence on page 1." in stopped["messages"][-1]["content"]
    assert not result.answer


def test_custom_policy_can_replace_model_view_without_mutating_canonical_history():
    histories = []

    def view_policy(messages, **kwargs):
        histories.append(deepcopy(messages))
        messages[0].content = "Policy mutated its private input"
        return PreparedContext([HumanMessage(content="Prepared model view")], 10, "heuristic")

    result, model = execute(
        [
            message(calls=[call()]),
            message(calls=[call("open_paper", source="1706.03762v7")]),
            final(),
        ],
        context_policy=view_policy,
    )

    assert result.stop_reason == "completed"
    assert len(histories) == len(model.inputs) == 3
    assert all(history[0].content == SYSTEM for history in histories)
    assert all([item.content for item in view] == ["Prepared model view"] for view in model.inputs)
    original_results = [item for item in histories[-1] if isinstance(item, ToolMessage)]
    assert len(original_results) == 2
    assert "Original evidence on page 1." in original_results[0].content
    assert result.citations[0].source_text == "Original evidence on page 1."
