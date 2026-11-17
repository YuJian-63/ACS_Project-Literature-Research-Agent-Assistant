"""Offline contracts for the ReAct loop, evidence and execution limits."""

import json
import time

import httpx
import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_openai import ChatOpenAI

from baseline import run_task
from schemas import Task

CHUNK = "arxiv:1706.03762v7:p1:c1"


def paper(source, *, page_count=1, **kwargs):
    chunks = [
        {
            "chunk_id": f"arxiv:1706.03762v7:p{page}:c1",
            "paper_id": "arxiv:1706.03762",
            "source_id": "arxiv:1706.03762v7",
            "version": "v7",
            "page": page,
            "source_text": f"Original evidence on page {page}.",
        }
        for page in range(1, page_count + 1)
    ]
    return {
        "paper_id": "arxiv:1706.03762",
        "source_id": "arxiv:1706.03762v7",
        "title": "Attention Is All You Need",
        "url": "https://arxiv.org/abs/1706.03762v7",
        "version": "v7",
        "outline": [],
        "pages": [{"page": chunk["page"], "text": chunk["source_text"]} for chunk in chunks],
        "chunks": chunks,
    }


def message(content="", calls=None, *, usage=True, finish_reason="stop"):
    return AIMessage(
        content=content,
        tool_calls=calls or [],
        usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}
        if usage
        else None,
        response_metadata={"finish_reason": finish_reason},
    )


def call(name="read_paper", *, call_id="call_1", **args):
    return {
        "name": name,
        "id": call_id,
        "args": args or {"source": "1706.03762v7", "page_start": 1, "page_end": 1},
    }


def final(citation=CHUNK, *, answer=None, unresolved=None):
    return message(
        json.dumps(
            {
                "answer": answer if answer is not None else f"Supported answer [{citation}]",
                "comparison_table": "",
                "unresolved": unresolved or [],
            }
        )
    )


class BoundModel:
    def __init__(self, model):
        self.model = model

    def invoke(self, messages, **kwargs):
        return self.model.respond(messages, bound=True, **kwargs)


class ScriptedModel:
    model_name = "scripted-model"
    temperature = 0

    def __init__(self, replies):
        self.replies = iter(replies)
        self.inputs = []
        self.invocations = []
        self.settings = []
        self.bound_tools = []

    def factory(self, **kwargs):
        self.settings.append(kwargs)
        return self

    def bind_tools(self, tools):
        self.bound_tools.append(list(tools))
        return BoundModel(self)

    def invoke(self, messages, **kwargs):
        return self.respond(messages, bound=False, **kwargs)

    def respond(self, messages, *, bound, **kwargs):
        self.inputs.append(list(messages))
        self.invocations.append({"bound": bound, **kwargs})
        reply = next(self.replies)
        if callable(reply):
            reply = reply()
        if isinstance(reply, Exception):
            raise reply
        return reply


def run(replies, *, reader=paper, search=None, context_window=32000, **task_fields):
    model = ScriptedModel(replies)
    task = Task(
        **{"question": "What does the paper say?", "sources": ["1706.03762v7"], **task_fields}
    )
    dependencies = {
        "model_factory": model.factory,
        "reader": reader,
        "context_window": context_window,
    }
    if search is not None:
        dependencies["search"] = search
    return run_task(task, **dependencies), model


def observations(result):
    return [entry["observation"] for entry in result.trace if entry["kind"] == "tool"]


def test_natural_completion_consumes_tool_result_and_preserves_cited_original():
    result, model = run([message(calls=[call()]), final()], max_steps=2)

    assert result.stop_reason == "completed"
    assert result.citations[0].source_text == "Original evidence on page 1."
    assert result.citations[0].page == 1
    assert result.usage.agent_steps == result.usage.model_calls == 2
    assert result.usage.tool_calls == 1
    assert result.usage.total_tokens == 240
    assert isinstance(model.inputs[1][-1], ToolMessage)
    assert result.configuration["model"] == "scripted-model"
    assert len(model.settings) == len(model.bound_tools) == 1
    assert all(item["bound"] for item in model.invocations)


def test_chatopenai_tool_round_trip_serializes_only_public_arguments():
    requests = []

    def respond(request):
        payload = json.loads(request.content)
        requests.append((payload, request.extensions["timeout"]))
        if len(requests) <= 2:
            opening = len(requests) == 1
            response = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "open_source" if opening else "read_original",
                        "type": "function",
                        "function": {
                            "name": "open_paper" if opening else "read_paper",
                            "arguments": json.dumps(
                                {"source": "1706.03762v7"} if opening else call()["args"]
                            ),
                        },
                    }
                ],
            }
            finish_reason = "tool_calls"
        else:
            response = {"role": "assistant", "content": final().content}
            finish_reason = "stop"
        return httpx.Response(
            200,
            json={
                "id": f"completion-{len(requests)}",
                "object": "chat.completion",
                "created": 1,
                "model": "offline-model",
                "choices": [{"index": 0, "message": response, "finish_reason": finish_reason}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:

        def model_factory(**kwargs):
            return ChatOpenAI(
                model="offline-model",
                api_key="offline-test-key",
                base_url="https://model.invalid/v1",
                http_client=client,
                use_responses_api=False,
                max_retries=0,
                **kwargs,
            )

        result = run_task(
            Task(
                question="Q",
                sources=["1706.03762v7"],
                max_steps=3,
                timeout_seconds=30,
                max_output_tokens=768,
            ),
            model_factory=model_factory,
            reader=paper,
        )

    assert result.stop_reason == "completed"
    assert result.usage.total_tokens == 360
    assert len(requests) == 3
    for payload, timeout in requests:
        assert payload.get("max_completion_tokens", payload.get("max_tokens")) == 768
        assert all(0 < value <= 30 for value in timeout.values())
        for item in payload["tools"]:
            parameters = item["function"]["parameters"]
            expected = (
                {"source"}
                if item["function"]["name"] == "open_paper"
                else {"source", "page_start", "page_end"}
            )
            assert set(parameters["properties"]) == expected
    open_result = requests[1][0]["messages"][-1]
    assert open_result["role"] == "tool"
    assert open_result["tool_call_id"] == "open_source"
    assert json.loads(open_result["content"])["outline"] == []
    tool_result = requests[2][0]["messages"][-1]
    assert tool_result["role"] == "tool"
    assert tool_result["tool_call_id"] == "read_original"
    assert json.loads(tool_result["content"])["chunks"][0]["chunk_id"] == CHUNK


def test_open_returns_navigation_without_publishing_evidence():
    outline = [{"title": "Introduction", "level": 1, "page_start": 1}]

    def reader(source, **kwargs):
        return {**paper(source, page_count=2), "outline": outline}

    result, _ = run(
        [message(calls=[call("open_paper", source="1706.03762v7")]), final()],
        reader=reader,
    )

    assert observations(result) == [
        {
            "source_id": "arxiv:1706.03762v7",
            "title": "Attention Is All You Need",
            "version": "v7",
            "page_count": 2,
            "outline": outline,
        }
    ]
    assert result.stop_reason == "invalid_citations"
    assert not result.citations


@pytest.mark.parametrize("outline", [[], [{"title": "Introduction", "level": 1, "page_start": 1}]])
def test_open_then_summarize_and_read_reuses_resolved_paper(outline):
    downloads = []

    def reader(source, **kwargs):
        downloads.append(source)
        return {**paper(source), "outline": outline}

    result, _ = run(
        [
            message(calls=[call("open_paper", source="1706.03762")]),
            message(
                calls=[
                    call(
                        "summarize_paper",
                        source="arxiv:1706.03762v7",
                        page_start=1,
                        page_end=1,
                    )
                ]
            ),
            message(f"Relevant summary [{CHUNK}]"),
            message(calls=[call()]),
            final(),
        ],
        reader=reader,
        sources=["1706.03762"],
    )

    assert result.stop_reason == "completed"
    assert downloads == ["1706.03762"]
    opened, summarized, read = observations(result)
    assert opened["outline"] == outline
    assert summarized["summaries"][0]["chunk_ids"] == [CHUNK]
    assert read["chunks"][0]["chunk_id"] == CHUNK
    assert not read["previously_read_chunk_ids"]
    assert result.citations[0].source_text == "Original evidence on page 1."
    assert len(result.sources) == 1


def test_summary_uses_plain_model_and_counts_usage_without_spending_agent_steps():
    result, model = run(
        [
            message(calls=[call("summarize_paper")]),
            message(f"Relevant summary [{CHUNK}]"),
            final(),
        ],
        max_steps=2,
    )

    assert result.stop_reason == "completed"
    assert result.usage.agent_steps == 2
    assert result.usage.model_calls == 3
    assert result.usage.total_tokens == 360
    assert result.citations[0].source_text == "Original evidence on page 1."
    assert [item["bound"] for item in model.invocations] == [True, False, True]
    assert [entry["purpose"] for entry in result.trace if entry["kind"] == "model"] == [
        "agent",
        "chunk_summary",
        "agent",
    ]


def test_repeated_reads_do_not_force_final_and_keep_only_one_copy_of_evidence():
    result, model = run([message(calls=[call()]) for _ in range(4)] + [final()])

    assert result.stop_reason == "completed"
    assert result.usage.agent_steps == 5
    assert result.usage.tool_calls == 4
    assert observations(result)[0]["chunks"][0]["chunk_id"] == CHUNK
    assert all(item["chunks"] == [] for item in observations(result)[1:])
    assert all(item["bound"] for item in model.invocations)
    tool_messages = [item for item in model.inputs[-1] if isinstance(item, ToolMessage)]
    assert sum(item.content.count("Original evidence on page 1.") for item in tool_messages) == 1


@pytest.mark.parametrize("max_steps", [1, 2])
def test_step_limit_stops_without_extra_tools_or_a_forced_final_answer(max_steps):
    result, model = run([message(calls=[call()])] * max_steps + [final()], max_steps=max_steps)

    assert result.stop_reason == "step_limit"
    assert result.usage.agent_steps == result.usage.model_calls == max_steps
    assert result.usage.tool_calls == max_steps - 1
    assert len(model.inputs) == max_steps
    assert not result.answer
    assert result.unresolved
    if max_steps > 1:
        assert observations(result)[0]["chunks"][0]["chunk_id"] == CHUNK


def test_task_deadline_stops_after_a_late_tool_and_retains_trace(monkeypatch):
    clock = [time.monotonic()]
    monkeypatch.setattr("baseline.time.monotonic", lambda: clock[0])

    def reader(source, **kwargs):
        clock[0] += 31.0
        return paper(source)

    result, model = run([message(calls=[call()]), final()], reader=reader, timeout_seconds=30)

    assert result.stop_reason == "time_limit"
    assert len(model.inputs) == 1
    assert result.usage.model_calls == result.usage.tool_calls == 1
    assert result.usage.elapsed_seconds >= 30
    assert observations(result)
    assert not result.answer


def test_model_and_reader_receive_time_remaining_and_fixed_output_cap():
    timeouts = []

    def reader(source, **kwargs):
        timeouts.append(kwargs["timeout"])
        return paper(source)

    result, model = run(
        [message(calls=[call()]), final()],
        reader=reader,
        timeout_seconds=30,
        max_output_tokens=768,
    )

    assert result.stop_reason == "completed"
    assert 0 < timeouts[0] <= 30
    assert all(0 < options["timeout"] <= 30 for options in model.invocations)
    assert all(options["max_tokens"] == 768 for options in model.invocations)


class ContextExceeded(Exception):
    code = "context_length_exceeded"


@pytest.mark.parametrize(
    "error,reason",
    [
        (RuntimeError("secret endpoint"), "model_error"),
        (ContextExceeded("secret endpoint"), "context_limit"),
    ],
)
def test_model_errors_are_explicit_and_do_not_leak_provider_messages(error, reason):
    result, _ = run([error])

    assert result.stop_reason == reason
    assert result.usage.model_calls == 1
    assert result.errors
    assert result.trace
    assert "secret" not in result.model_dump_json()


def test_missing_provider_usage_is_reported_without_inventing_token_counts():
    result, _ = run([message(calls=[call()], usage=False), final()])

    assert result.stop_reason == "completed"
    assert not result.usage.token_usage_complete
    assert result.usage.input_tokens is None
    assert result.usage.output_tokens is None
    assert result.usage.total_tokens is None


@pytest.mark.parametrize(
    "reply,reason",
    [
        (message("not JSON"), "invalid_output"),
        (message([{"type": "text", "text": "A content block"}]), "invalid_output"),
        (message("unfinished", finish_reason="length"), "output_truncated"),
    ],
)
def test_invalid_or_truncated_final_outputs_are_failures(reply, reason):
    result, _ = run([reply])
    assert result.stop_reason == reason
    assert not result.answer


def test_malformed_tool_call_stops_without_dispatch():
    malformed = AIMessage(
        content="",
        invalid_tool_calls=[{"name": "read_paper", "args": "{", "id": "bad", "error": "JSON"}],
    )
    result, _ = run([malformed])
    assert result.stop_reason == "invalid_tool_call"
    assert result.usage.tool_calls == 0


def test_registered_tools_supply_names_and_public_argument_schemas():
    _, model = run([message(calls=[call()]), final()])
    tools = {item.name: item for item in model.bound_tools[0]}

    assert set(tools) == {"open_paper", "read_paper", "summarize_paper"}
    for item in tools.values():
        schema = item.tool_call_schema.model_json_schema()
        expected = {"source"} if item.name == "open_paper" else {"source", "page_start", "page_end"}
        assert set(schema["properties"]) == expected
        assert item.description


@pytest.mark.parametrize("page_start", [True, "1", 1.5])
def test_invalid_page_types_are_rejected_before_accessing_reader(page_start):
    reads = []
    result, _ = run(
        [message(calls=[call(source="1706.03762v7", page_start=page_start, page_end=1)]), final()],
        reader=lambda *args, **kwargs: reads.append(args),
    )
    assert not reads
    assert "error" in observations(result)[0]
    assert result.stop_reason == "invalid_citations"


@pytest.mark.parametrize("source", ["2305.14314", "1706.03762v6"])
@pytest.mark.parametrize("tool_name", ["open_paper", "read_paper", "summarize_paper"])
def test_source_and_pinned_version_restrictions_apply_before_download(source, tool_name):
    reads = []
    args = {"source": source}
    if tool_name != "open_paper":
        args.update(page_start=1, page_end=1)
    result, _ = run(
        [message(calls=[call(tool_name, **args)]), final()],
        reader=lambda *args, **kwargs: reads.append(args),
    )
    assert not reads
    assert "outside" in observations(result)[0]["error"]
    assert result.stop_reason == "invalid_citations"


def test_search_admits_only_returned_arxiv_sources():
    requests = []

    def search(query, **kwargs):
        requests.append((query, kwargs))
        return {
            "results": [
                {"url": "https://arxiv.org/abs/1706.03762v7", "title": "Paper"},
                {"url": "https://example.com/paper", "title": "Not arXiv"},
            ]
        }

    result, model = run(
        [
            message(calls=[call("search_papers", query="attention")]),
            message(calls=[call()]),
            final(),
        ],
        sources=[],
        allow_search=True,
        search=search,
    )
    assert result.stop_reason == "completed"
    assert requests[0][1]["include_domains"] == ["arxiv.org"]
    assert len(observations(result)[0]["results"]) == 1
    assert "search_papers" in {item.name for item in model.bound_tools[0]}


def test_unknown_or_disabled_tool_error_is_returned_then_agent_can_recover():
    result, model = run(
        [
            message(calls=[call("search_papers", query="attention")]),
            message(calls=[call()]),
            final(),
        ]
    )
    assert result.stop_reason == "completed"
    assert "error" in observations(result)[0]
    assert isinstance(model.inputs[1][-1], ToolMessage)
    assert result.usage.tool_calls == 2


@pytest.mark.parametrize("tool_name", ["open_paper", "read_paper"])
def test_paper_limit_prevents_a_second_download(tool_name):
    downloads = []

    def reader(source, **kwargs):
        downloads.append(source)
        return paper(source)

    args = {"source": "2305.14314"}
    if tool_name == "read_paper":
        args.update(page_start=1, page_end=1)
    result, _ = run(
        [
            message(calls=[call()]),
            message(calls=[call(tool_name, **args)]),
            final(),
        ],
        reader=reader,
        sources=["1706.03762v7", "2305.14314"],
        max_papers=1,
    )
    assert result.stop_reason == "completed"
    assert downloads == ["1706.03762v7"]
    assert "error" in observations(result)[1]


@pytest.mark.parametrize(
    "reply,reason",
    [
        (final("arxiv:1706.03762v7:p9:c1"), "invalid_citations"),
        (final(answer="Unsupported answer"), "insufficient_evidence"),
        (final(unresolved=["Experiments were not fully read."]), "partial"),
    ],
)
def test_final_evidence_validation_and_unresolved_status(reply, reason):
    result, _ = run([message(calls=[call()]), reply])
    assert result.stop_reason == reason
    assert result.unresolved


def test_citation_normalization_preserves_math_and_bibliography_brackets():
    second = "arxiv:1706.03762v7:p2:c1"
    answer = (
        f"Array [a, b], interval [−1, 1] and reference [3]; evidence [chunk_id: {CHUNK}, {second}]."
    )
    result, _ = run(
        [
            message(calls=[call(page_start=1, page_end=2, source="1706.03762v7")]),
            final(answer=answer),
        ],
        reader=lambda source, **kwargs: paper(source, page_count=2),
    )
    assert result.stop_reason == "completed"
    assert "[a, b], interval [−1, 1] and reference [3]" in result.answer
    assert f"[{CHUNK}] [{second}]" in result.answer
    assert {item.chunk_id for item in result.citations} == {CHUNK, second}


def test_summary_and_original_deduplicate_independently():
    result, model = run(
        [
            message(calls=[call("summarize_paper")]),
            message(f"Brief summary [{CHUNK}]"),
            message(calls=[call()]),
            message(calls=[call("summarize_paper")]),
            final(),
        ]
    )
    assert result.stop_reason == "completed"
    assert observations(result)[1]["chunks"][0]["chunk_id"] == CHUNK
    assert observations(result)[2]["summaries"] == []
    assert result.usage.agent_steps == 4
    assert result.usage.model_calls == 5
    assert sum(not item["bound"] for item in model.invocations) == 1


@pytest.mark.parametrize("retry", [False, True])
def test_failed_summary_does_not_publish_partial_evidence_or_block_retry(retry):
    def two_batches(source, **kwargs):
        result = paper(source, page_count=2)
        for chunk in result["chunks"]:
            chunk["source_text"] *= 250
        return result

    replies = [
        message(calls=[call("summarize_paper", source="1706.03762v7", page_start=1, page_end=2)]),
        message(f"First summary [{CHUNK}]"),
        message("Second summary without citations."),
    ]
    if retry:
        replies.extend([message(calls=[call("summarize_paper")]), message(f"Retry [{CHUNK}]")])
    result, _ = run(replies + [final()], reader=two_batches)

    assert "error" in observations(result)[0]
    if retry:
        assert result.stop_reason == "completed"
        assert observations(result)[1]["summaries"][0]["summary"] == f"Retry [{CHUNK}]"
    else:
        assert result.stop_reason == "invalid_citations"
        assert not result.citations


def test_history_is_passed_through_without_compaction_or_forced_synthesis():
    history = "Earlier reasoning and evidence. " * 4000
    result, model = run([message(history, calls=[call()]), final()], context_window=100000)
    assert result.stop_reason == "completed"
    assert any(item.content == history for item in model.inputs[-1])
    assert all(item["bound"] for item in model.invocations)
    assert not any(entry["kind"] == "context" for entry in result.trace)


def test_each_tool_call_gets_a_matching_response_in_the_same_round():
    result, model = run([message(calls=[call(call_id="first"), call(call_id="second")]), final()])
    assert result.stop_reason == "completed"
    responses = [item for item in model.inputs[-1] if isinstance(item, ToolMessage)]
    assert [item.tool_call_id for item in responses] == ["first", "second"]
    assert result.usage.agent_steps == 2
    assert result.usage.tool_calls == 2


def test_runs_do_not_share_acquired_evidence_or_usage():
    first, _ = run([message(calls=[call()]), final()])
    second, _ = run([final()])
    assert first.stop_reason == "completed"
    assert second.stop_reason == "invalid_citations"
    assert second.usage.model_calls == 1
    assert not second.sources
    assert not second.citations


def test_persistence_failure_preserves_result_without_exposing_credentials(monkeypatch):
    import apis.database

    def fail(_):
        raise RuntimeError("postgresql://secret")

    monkeypatch.setattr(apis.database, "save_paper", fail)
    model = ScriptedModel([message(calls=[call()]), final()])
    result = run_task(
        Task(question="Q", sources=["1706.03762v7"]),
        model_factory=model.factory,
        reader=paper,
        persist=True,
    )
    assert result.stop_reason == "completed"
    assert result.answer
    assert result.errors[-1] == {"stage": "persistence", "type": "RuntimeError"}
    assert "secret" not in result.model_dump_json()
