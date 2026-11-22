"""Exercise Reflection from the Extension entry point with offline model replies."""

import json
import time

import pytest
from test_baseline import CHUNK, ScriptedModel, call, final, message, paper
from test_extension import SECOND_CHUNK, SOURCE, embed_texts, retrieve

from extension import run_task
from schemas import Task

TASK = Task(
    question="Compare the result and experimental conditions.",
    sources=[SOURCE],
    max_steps=2,
    timeout_seconds=30,
    max_output_tokens=256,
)
MISSING = "arxiv:1706.03762v7:p9:c1"


def read(first=1, last=1):
    return message(calls=[call("read_paper", source=SOURCE, page_start=first, page_end=last)])


def execute(replies, **options):
    model = ScriptedModel(replies)
    result = run_task(
        TASK,
        model_factory=model.factory,
        reader=lambda source, **_: paper(source, page_count=3),
        embed=embed_texts,
        **options,
    )
    return result, model


def purposes(result):
    return [entry["purpose"] for entry in result.trace if entry["kind"] == "model"]


def test_reflection_is_disabled_by_default():
    result, model = execute([read(), final()])
    assert result.stop_reason == "completed"
    assert result.configuration["reflection"] is False
    assert purposes(result) == ["agent", "agent"]
    assert result.usage.model_calls == result.usage.agent_steps == 2
    assert len(model.bound_tools) == 1


def test_reflection_rejects_non_boolean_before_model_setup():
    model = ScriptedModel([])
    with pytest.raises(TypeError, match="reflection"):
        run_task(TASK, model_factory=model.factory, reflection="false")
    assert not model.settings


def test_accept_checks_originals_for_all_cited_fields_and_charges_one_call():
    draft = {
        "answer": f"Reported result [{CHUNK}].",
        "comparison_table": f"| Method | Condition |\n|---|---|\n| A | Condition [{SECOND_CHUNK}] |",
        "unresolved": [f"An independent comparison remains open [arxiv:{SOURCE}:p3:c1]."],
    }
    result, model = execute(
        [read(1, 3), message(json.dumps(draft)), message('{"decision":"accept"}')],
        reflection=True,
    )
    assert result.stop_reason == "partial"
    assert result.answer == draft["answer"]
    assert result.comparison_table == draft["comparison_table"]
    assert result.unresolved == draft["unresolved"]
    assert result.configuration["reflection"] is True
    assert result.configuration["planner"] is False
    assert purposes(result) == ["agent", "agent", "reflection"]
    assert result.usage.agent_steps == 2
    assert result.usage.tool_calls == 1
    assert result.usage.model_calls == 3
    assert (result.usage.input_tokens, result.usage.output_tokens) == (300, 60)
    assert {tool.name for tool in model.bound_tools[-1]} == {"read_paper", "retrieve"}
    payload = json.loads(model.inputs[-1][-1].content)
    assert payload["task"]["question"] == TASK.question
    assert payload["draft"] == draft
    assert {chunk["source_text"] for chunk in payload["cited_chunks"]} == {
        "Original evidence on page 1.",
        "Original evidence on page 2.",
        "Original evidence on page 3.",
    }
    assert result.trace[-1]["outcome"] == "accepted"


def test_direct_revision_can_correct_a_table_citation_before_validation_with_planner_enabled():
    draft = {
        "answer": f"Result [{CHUNK}]",
        "comparison_table": f"Condition [{MISSING}]",
        "unresolved": [],
    }
    revised = {**draft, "comparison_table": f"Corrected condition [{CHUNK}]"}
    reply = message(f"```json\n{json.dumps(revised)}\n```")
    result, model = execute(
        [message("NO_PLAN"), read(), message(json.dumps(draft)), reply],
        reflection=True,
        planner=True,
    )
    assert result.stop_reason == "completed"
    assert purposes(result) == ["planner", "agent", "agent", "reflection"]
    assert json.loads(model.inputs[-1][-1].content)["missing_citation_ids"] == [MISSING]
    assert result.comparison_table == revised["comparison_table"]
    assert [citation.chunk_id for citation in result.citations] == [CHUNK]
    assert result.usage.agent_steps == 2
    assert result.usage.tool_calls == 1
    assert result.trace[-1]["outcome"] == "revised"


@pytest.mark.parametrize(
    ("first_read", "supplement"),
    [
        (read(), read(2, 2)),
        (read(1, 2), read(2, 2)),
        (read(), retrieve("results")),
        (read(1, 2), retrieve("results")),
    ],
    ids=["new-page", "previously-read-uncited-page", "retrieve", "retrieve-previously-read"],
)
def test_single_supplement_supplies_original_before_one_tool_free_revision(
    first_read, supplement, tmp_path
):
    result, model = execute(
        [first_read, final(), supplement, final(SECOND_CHUNK)],
        reflection=True,
        index_dir=tmp_path,
    )
    assert result.stop_reason == "completed"
    assert purposes(result) == ["agent", "agent", "reflection", "reflection_revision"]
    assert result.usage.agent_steps == result.usage.tool_calls == 2
    assert result.usage.model_calls == 4
    assert result.usage.total_tokens == 480
    assert model.invocations[-1]["bound"] is False
    assert "Original evidence on page 2." in str(model.inputs[-1])
    assert [(c.chunk_id, c.source_text) for c in result.citations] == [
        (SECOND_CHUNK, "Original evidence on page 2.")
    ]
    assert result.trace[-1]["outcome"] == "revised_after_tool"


@pytest.mark.parametrize(
    ("draft", "check"),
    [
        (final(MISSING), [message('{"decision":"accept"}')]),
        (final(), [final(MISSING)]),
        (final(), [read(2, 2), final(MISSING)]),
    ],
    ids=["accepted", "revised", "supplemented"],
)
def test_every_reflection_path_still_validates_final_citations(draft, check):
    result, _ = execute([read(), draft, *check], reflection=True)
    assert result.stop_reason == "invalid_citations"
    assert not result.citations
    assert MISSING in " ".join(result.unresolved)


@pytest.mark.parametrize(
    ("check", "extra_tools"),
    [
        ([message(calls=[call("summarize_paper")])], 0),
        ([message(calls=[call(), call(call_id="second")])], 0),
        ([message('{"decision":"accept"}', finish_reason="length")], 0),
        ([message("not JSON")], 0),
        ([read(2, 2), read(3, 3)], 1),
    ],
    ids=["forbidden-tool", "multiple-tools", "truncated", "bad-json", "tool-during-revision"],
)
def test_invalid_reflection_keeps_draft_without_dispatching_an_extra_tool(check, extra_tools):
    original = final()
    result, model = execute([read(), original, *check], reflection=True)
    assert result.stop_reason == "completed"
    assert result.answer == json.loads(original.content)["answer"]
    assert result.usage.tool_calls == 1 + extra_tools
    assert result.usage.model_calls == len(model.inputs) == 2 + len(check)
    assert result.errors


def test_failed_evidence_request_respects_source_scope_and_allows_one_revision():
    forbidden_source = message(
        calls=[call("read_paper", source="2106.09685", page_start=1, page_end=1)]
    )
    result, model = execute(
        [read(), final(), forbidden_source, final(unresolved=["Comparison unavailable"])],
        reflection=True,
    )
    assert purposes(result) == ["agent", "agent", "reflection", "reflection_revision"]
    assert result.stop_reason == "partial"
    assert result.usage.tool_calls == 2
    assert [source["source_id"] for source in result.sources] == [f"arxiv:{SOURCE}"]
    assert [citation.chunk_id for citation in result.citations] == [CHUNK]
    assert "outside task inputs" in str(model.inputs[-1])
    assert model.invocations[-1]["bound"] is False


def test_reflection_model_failure_keeps_the_draft_and_marks_usage_unknown():
    result, _ = execute([read(), final(), RuntimeError("private endpoint")], reflection=True)
    assert result.stop_reason == "completed"
    assert result.usage.model_calls == 3
    assert result.usage.token_usage_complete is False
    assert result.usage.total_tokens is None
    assert "private endpoint" not in result.model_dump_json()
    assert [citation.chunk_id for citation in result.citations] == [CHUNK]


def test_pressure_finalization_skips_reflection():
    initial = read()
    initial.usage_metadata.update(input_tokens=9000, total_tokens=9020)
    result, _ = execute([initial, final()], context_window=10000, reflection=True)
    assert result.stop_reason == "completed"
    assert purposes(result) == ["agent", "finalize"]
    assert not any(entry["kind"] == "reflection" for entry in result.trace)
    assert result.usage.agent_steps == result.usage.model_calls == 2


def test_reflection_observes_shared_deadline_before_requesting_more_evidence(monkeypatch):
    now = [time.monotonic()]
    monkeypatch.setattr("baseline.time.monotonic", lambda: now[0])

    def late_request():
        now[0] += TASK.timeout_seconds
        return read(2, 2)

    result, model = execute([read(), final(), late_request], reflection=True)
    assert result.stop_reason == "time_limit"
    assert result.usage.model_calls == len(model.inputs) == 3
    assert result.usage.tool_calls == 1
    assert result.usage.total_tokens == 360
