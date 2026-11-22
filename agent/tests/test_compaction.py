"""Evidence and budget boundaries for the optional history compaction policy."""

import json
from copy import deepcopy

import pytest
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from test_baseline import CHUNK, ScriptedModel, call, final, message, observations, paper
from test_extension import SECOND_CHUNK, SOURCE, embed_texts

import baseline
import extension
from context import CompactHistory, TokenCounter
from schemas import Task


def tool_result(call_id, payload):
    return ToolMessage(content=json.dumps(payload, ensure_ascii=False), tool_call_id=call_id)


def duplicate_history():
    first, second = paper(SOURCE, page_count=2)["chunks"]
    first["source_text"] = "The result holds only under the stated experimental conditions. " * 50
    original = {"source_id": first["source_id"], "chunks": [first]}
    hits = {**original, "chunks": [first, second]}
    return [
        SystemMessage(content="System instructions"),
        HumanMessage(content="Original research task"),
        message(calls=[call(call_id="read")]),
        tool_result("read", original),
        message(
            calls=[
                call("retrieve", call_id="search", source=SOURCE, query="result"),
                call("open_paper", call_id="open", source=SOURCE),
            ]
        ),
        tool_result("search", hits),
        tool_result("open", {"source_id": first["source_id"], "page_count": 2}),
    ]


def test_compaction_threshold_includes_output_and_is_idempotent_on_canonical_history():
    history = duplicate_history()
    original = deepcopy(history)
    counter = TokenCounter()
    tokens, _ = counter.estimate(history, [])
    reserve = 80
    window = 2 * (tokens + reserve)
    policy = CompactHistory(trigger_ratio=0.5)
    options = {"tools": [], "context_window": window, "counter": counter}

    below = policy(history, max_output_tokens=reserve - 1, **options)
    assert below.messages == original
    assert below.compaction is None
    compact = policy(history, max_output_tokens=reserve, **options)
    assert compact.compaction["outcome"] == "applied"
    assert compact.input_tokens_estimate < tokens
    assert compact.messages[:5] == original[:5]
    assert compact.messages[6:] == original[6:]
    updated = json.loads(compact.messages[5].content)
    assert "source_text" not in updated["chunks"][0]
    assert updated["chunks"][0]["chunk_id"] == CHUNK
    assert updated["chunks"][1] == json.loads(original[5].content)["chunks"][1]
    assert compact.messages[5].tool_call_id == "search"
    again = policy(history, max_output_tokens=reserve, **options)
    assert again.messages == compact.messages
    assert again.compaction is None or again.compaction["outcome"] != "applied"
    assert history == original


def test_partial_tool_batch_and_nonidentical_quoted_text_are_kept():
    history = duplicate_history()
    first = json.loads(history[3].content)["chunks"][0]
    changed = {**first, "source_text": first["source_text"] + " Correction."}
    same_words_other_page = {**first, "page": 3, "chunk_id": "arxiv:1706.03762v7:p3:c1"}
    history += [
        message(calls=[call("retrieve", call_id="variants", source=SOURCE, query="variants")]),
        tool_result(
            "variants",
            {"source_id": first["source_id"], "chunks": [changed, same_words_other_page]},
        ),
        message(
            calls=[
                call("read_paper", call_id="pending_read"),
                call("open_paper", call_id="pending_open", source=SOURCE),
            ]
        ),
        tool_result("pending_read", {"source_id": first["source_id"], "chunks": [first]}),
    ]
    before = deepcopy(history)
    prepared = CompactHistory()(
        history, tools=[], context_window=1, max_output_tokens=80, counter=TokenCounter()
    )
    assert prepared.messages[-4:] == before[-4:]
    assert history == before


def test_compaction_keeps_the_calibrated_view_if_the_candidate_estimate_is_higher():
    history = duplicate_history()
    counter = TokenCounter()
    counter.observe(history, [], 100)
    prepared = CompactHistory()(
        history, tools=[], context_window=200, max_output_tokens=80, counter=counter
    )
    assert prepared.messages == history
    assert prepared.input_tokens_estimate == 100
    assert prepared.count_method == "usage_anchored_estimate"
    attempt = prepared.compaction
    assert attempt["outcome"] == "no_gain"
    assert attempt["heuristic_tokens_saved"] > 0
    assert attempt["after_method"] == "heuristic"
    assert attempt["after_tokens"] > attempt["before_tokens"]


def test_compaction_releases_pressure_after_rewriting_an_api_counted_prefix():
    history = duplicate_history()
    counter = TokenCounter()
    counter.observe(history, [], 1400)
    history += [
        message(calls=[call("open_paper", call_id="last", source=SOURCE)]),
        tool_result("last", {"source_id": SOURCE, "page_count": 2}),
    ]
    window, reserve = 1700, 100
    policy = CompactHistory()
    prepared = policy(
        history, tools=[], counter=counter, context_window=window, max_output_tokens=reserve
    )

    attempt = prepared.compaction
    assert attempt["before_method"] == "usage_anchored_estimate"
    assert attempt["after_method"] == "heuristic"
    assert attempt["outcome"] == "applied"
    input_threshold = window * policy.trigger_ratio - reserve
    assert prepared.input_tokens_estimate < input_threshold <= attempt["before_tokens"]


@pytest.mark.parametrize(
    "name,empty,pages,ids,status",
    [
        ("read_paper", "chunks", "pages_read", "previously_read_chunk_ids", "already_read"),
        (
            "summarize_paper",
            "summaries",
            "pages_summarized",
            "previously_summarized_chunk_ids",
            "already_summarized",
        ),
    ],
)
def test_receipt_preserves_pages_and_ids_missing_from_the_visible_evidence(
    name, empty, pages, ids, status
):
    history = duplicate_history()
    receipt = {
        "source_id": f"arxiv:{SOURCE}",
        empty: [],
        pages: [1, 2],
        ids: [CHUNK, SECOND_CHUNK],
        "status": status,
    }
    missing_id = "arxiv:1706.03762v7:p3:c1"
    unseen = {**receipt, pages: [1, 2, 3], ids: [CHUNK, SECOND_CHUNK, missing_id]}
    history += [
        message(calls=[call(name, call_id="known"), call(name, call_id="other")]),
        tool_result("known", receipt),
        tool_result("other", unseen),
    ]
    prepared = CompactHistory()(
        history, tools=[], context_window=1, max_output_tokens=80, counter=TokenCounter()
    )
    known_result = json.loads(prepared.messages[-2].content)
    assert all(known_result[key] == receipt[key] for key in (empty, pages, "source_id", "status"))
    assert ids not in known_result
    assert prepared.messages[-1] == history[-1]


def test_selected_search_snippet_can_shrink_while_other_leads_and_summary_stay_intact():
    picked = {
        "source": SOURCE,
        "title": "Selected paper",
        "url": f"https://arxiv.org/abs/{SOURCE}",
        "snippet": "Discovery text. " * 140,
    }
    pending = {
        **picked,
        "source": "2106.09685",
        "title": "Other candidate",
        "url": "https://arxiv.org/abs/2106.09685",
    }
    results = {"results": [picked, pending], "evidence_status": "discovery_only"}
    summary = {
        "source_id": f"arxiv:{SOURCE}",
        "summaries": [{"summary": f"Condition [{CHUNK}]", "chunk_ids": [CHUNK]}],
    }
    history = [
        HumanMessage(content="Original comparison"),
        message(calls=[call("search_papers", call_id="discover", query="candidate")]),
        tool_result("discover", results),
        message(calls=[call("open_paper", call_id="opened", source=SOURCE)]),
        tool_result(
            "opened",
            {"source_id": f"arxiv:{SOURCE}", "version": "v7", "page_count": 2, "outline": []},
        ),
        message(calls=[call("summarize_paper", call_id="summary")]),
        tool_result("summary", summary),
    ]
    prepared = CompactHistory()(
        history, tools=[], context_window=1, max_output_tokens=80, counter=TokenCounter()
    )
    assert prepared.compaction["outcome"] == "applied"
    visible = json.loads(prepared.messages[2].content)
    selected, unselected = visible["results"]
    assert visible["evidence_status"] == "discovery_only"
    assert all(selected[key] == picked[key] for key in ("source", "title", "url"))
    assert selected.get("snippet") != picked["snippet"]
    assert unselected == pending
    assert prepared.messages[-1] == history[-1]
    assert json.loads(history[2].content) == results


@pytest.mark.parametrize(
    "runner", [baseline.run_task, extension.run_task], ids=["baseline", "extension"]
)
def test_full_default_and_explicit_modes_leave_the_normal_request_unchanged(runner):
    task = Task(task_id="defaults", question="What was measured?", sources=[SOURCE])
    requests = []
    for options in (
        {},
        {"context_policy": "full"},
        {"context_policy": "compact", "context_window": None},
    ):
        model = ScriptedModel([message(calls=[call(call_id="read")]), final()])
        result = runner(task, reader=paper, model_factory=model.factory, **options)
        assert result.stop_reason == "completed"
        assert result.configuration["context_finalize_ratio"] == 0.9
        assert not any(entry.get("action") == "compact" for entry in result.trace)
        requests.append(model.inputs)
    assert requests[0] == requests[1] == requests[2]


@pytest.mark.parametrize("over_hard_limit", [True, False], ids=["above_window", "near_window"])
def test_compact_without_reclaimable_content_finalizes(over_hard_limit):
    text = "A necessary experimental condition. " * 480

    def reader(source, **kwargs):
        parsed = paper(source)
        parsed["chunks"][0]["source_text"] = parsed["pages"][0]["text"] = text
        return parsed

    def run(mode, window):
        task = Task(
            task_id="fallback",
            question="What was measured?",
            sources=[SOURCE],
            max_output_tokens=80,
        )
        model = ScriptedModel([message(calls=[call()], usage=False), final()])
        result = baseline.run_task(
            task,
            model_factory=model.factory,
            reader=reader,
            context_policy=mode,
            context_window=window,
        )
        return result, model

    full, _ = run("full", None)
    demand = full.trace[-1]["context"]["input_tokens_estimate"] + full.trace[-1]["output_limit"]
    window = demand - 1 if over_hard_limit else int(demand / 0.9)
    result, model = run("compact", window)
    events = [t for t in result.trace if t.get("action") == "compact"]
    assert len(events) == 1 and events[0]["outcome"] == "no_gain"
    assert result.stop_reason == "completed"
    assert len(model.inputs) == 2
    assert result.trace[-1]["purpose"] == "finalize"
    assert not model.invocations[-1]["bound"]
    assert result.citations[0].source_text == text


def test_compaction_rescues_a_hard_overflow_without_an_extra_model_call(tmp_path):
    task = Task(
        task_id="compact", question="What was measured?", sources=[SOURCE], max_output_tokens=80
    )
    passage = "The effect appeared only in the small-model experiment. " * 80

    def reader(source, **kwargs):
        parsed = paper(source, page_count=2)
        parsed["chunks"][0]["source_text"] = parsed["pages"][0]["text"] = passage
        return parsed

    def run(mode, window):
        replies = [
            message(calls=[call(call_id="read")], usage=False),
            message(
                calls=[call("retrieve", call_id="hits", source=SOURCE, query="method", top_k=2)],
                usage=False,
            ),
            final(answer=f"Different conditions [{CHUNK}] [{SECOND_CHUNK}]"),
        ]
        model = ScriptedModel(replies)
        result = extension.run_task(
            task,
            model_factory=model.factory,
            reader=reader,
            embed=embed_texts,
            index_dir=tmp_path,
            context_policy=mode,
            context_window=window,
            context_finalize_ratio=None,
        )
        return result, model

    unrestricted, _ = run("full", None)
    final_request = unrestricted.trace[-1]
    assert final_request["purpose"] == "agent"
    window = final_request["context"]["input_tokens_estimate"] + task.max_output_tokens - 1
    stopped, stopped_model = run("full", window)
    assert stopped.stop_reason == "context_limit"
    assert len(stopped_model.inputs) == 2

    reusable = CompactHistory(trigger_ratio=1)
    for mode in ("compact", reusable, reusable):
        result, model = run(mode, window)
        assert result.stop_reason == "completed"
        assert len(model.inputs) == result.usage.agent_steps == result.usage.model_calls == 3
        assert all(invocation["bound"] for invocation in model.invocations)
        assert result.usage.tool_calls == 2
        applied = [entry for entry in result.trace if entry.get("action") == "compact"]
        assert len(applied) == 1 and applied[0]["outcome"] == "applied"
        assert not any(entry.get("action") == "finalize" for entry in result.trace)
        assert [citation.chunk_id for citation in result.citations] == [CHUNK, SECOND_CHUNK]
        assert result.citations[0].source_text == passage
        assert observations(result)[1]["chunks"][0]["source_text"] == passage
        view = [m for m in model.inputs[-1] if isinstance(m, ToolMessage)]
        assert [m.tool_call_id for m in view] == ["read", "hits"]
        assert sum(m.content.count(passage) for m in view) == 1
        assert json.loads(view[-1].content)["chunks"][1]["chunk_id"] == SECOND_CHUNK
