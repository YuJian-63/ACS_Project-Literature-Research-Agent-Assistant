import json
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import Mock
from uuid import uuid4

from app.research.model_client import ModelCompletion, ModelTimeoutError
from app.research.search_policy import build_search_plan
from app.research.search_runner import prepare_search, run_single_search, supplement_review, validate_answer
from app.research.review_runner import run_staged_review
from app.research.review_store import ReviewLimitError
from app.workers.research import ResearchJob
from test_document_search import document
from test_search_policy import settings


class SearchMemoryStore:
    def __init__(self, policy):
        self.state = {"units": {}, "search": {}}
        self.policy = policy
        self.events = []

    def read(self):
        return deepcopy(self.state)

    def reserve(self, key, input_tokens, output_tokens, stage, message, payload):
        units = self.state["units"]
        attempts = units.setdefault(key, {"attempts": []})["attempts"]
        all_attempts = [attempt for unit in units.values() for attempt in unit["attempts"]]
        if len(all_attempts) >= self.policy["max_steps"] or sum(attempt["input_tokens"] + attempt["output_tokens"] for attempt in all_attempts) + input_tokens + output_tokens > self.policy["max_tokens"]:
            raise ReviewLimitError("Budget exhausted")
        attempts.append({"input_tokens": input_tokens, "output_tokens": output_tokens})
        return str(len(attempts))

    def settle(self, key, identity, completion, diagnostic, result=None):
        attempt = self.state["units"][key]["attempts"][-1]
        if completion and completion.input_tokens is not None and completion.output_tokens is not None:
            attempt.update(input_tokens=completion.input_tokens, output_tokens=completion.output_tokens)
        attempt["diagnostic"] = diagnostic
        if result is not None:
            self.state["units"][key]["result"] = result

    def save_search(self, key, value, **event):
        self.state["search"].setdefault(key, deepcopy(value))
        self.events.append(event)

    def skip(self, key, result):
        self.state["units"][key] = {"result": result, "attempts": []}


def make_job(task_type="qa", question="这篇论文采用什么方法？", source=None, papers=None):
    source = source if source is not None else document("Abstract: We propose a Rust debugging agent.", "Conclusion: It resolves issues.")
    if papers is None:
        paper_id = str(uuid4())
        source = [chunk.model_copy(update={"paper_id": paper_id}) for chunk in source]
        papers = [{"paper_id": paper_id, "paper_title": "Rust agents"}]
    policy, plan, evidence = build_search_plan(task_type, question, papers, source, settings())
    return ResearchJob(task_id=uuid4(), task_type=task_type, question=question, model_id="fixture",
        model_base_url="https://fixture.invalid", model_timeout_seconds=plan.get("model_timeout_seconds", 90),
        evidence_context_chars=plan.get("evidence_context_chars", 24000), max_tokens=policy["max_tokens"],
        timeout_seconds=policy["timeout_seconds"], started_at=datetime.now(timezone.utc), paper_title=papers[0]["paper_title"],
        evidence=evidence, selected_papers=papers, max_output_tokens=plan.get("max_output_tokens", 2048),
        review_plan=plan if task_type == "review" else None, search_policy=policy, source_evidence=source)


def completion(data):
    return ModelCompletion(json.dumps(data, ensure_ascii=False), 100, 50, "stop")


class SearchRunnerTests(unittest.TestCase):
    def test_summary_supplements_once_and_replays_without_calls(self):
        job = make_job("summary", "Summarize contributions and limitations", source=document(*[f"Background {index}: agent design." for index in range(24)]))
        store, model = SearchMemoryStore(job.search_policy), Mock()
        model.complete.side_effect = [completion({"status": "partial", "missing_aspects": ["limitations"],
            "paragraphs": [{"content_markdown": "Supported overview", "evidence_ids": ["E1"]}]}),
            completion({"status": "answered", "paragraphs": [{"content_markdown": "Complete summary", "evidence_ids": ["E1"]}]})]
        result = run_single_search(prepare_search(job, model, store), model, store)
        self.assertEqual(model.complete.call_count, 2)
        self.assertEqual(store.read()["search"]["outcome"]["status"], "answered")
        self.assertEqual(run_single_search(prepare_search(job, model, store), model, store), result)
        self.assertEqual(model.complete.call_count, 2)

    def test_supplement_reads_other_window_of_same_source_chunk(self):
        from app.research.search_runner import _supplement_source
        source = document("Introduction: agent design. " * 80 + "Limitations: evaluation excludes private repositories. " * 25)
        job = make_job("qa", "Explain the method", source=source)
        previous = [job.source_evidence[0].model_copy(update={"content": job.source_evidence[0].content[:1000]})]
        fresh = _supplement_source(job, {"intent": "specific", "question": job.question, "queries": ["agent design method"]},
            ["局限性"], 1000, 1, previous)
        self.assertTrue(fresh)
        self.assertIn("private repositories", fresh[0].content)
        self.assertIn(fresh[0].content, job.source_evidence[0].content)

    def test_summary_with_old_budget_does_not_add_calls(self):
        job = make_job("summary", "Summarize", source=document("Abstract: an agent."))
        job.search_policy.pop("supplement_rounds", None)
        store, model = SearchMemoryStore(job.search_policy), Mock()
        model.complete.return_value = completion({"status": "partial", "missing_aspects": ["limitations"],
            "paragraphs": [{"content_markdown": "Supported", "evidence_ids": ["E1"]}]})
        run_single_search(prepare_search(job, model, store), model, store)
        self.assertEqual(model.complete.call_count, 1)

    def test_partial_supplement_keeps_previously_supported_paragraphs(self):
        job = make_job("qa", "Explain contributions and limitations", source=document(*[f"Agent evaluation {index}." for index in range(24)]))
        store, model = SearchMemoryStore(job.search_policy), Mock()
        model.complete.side_effect = [completion({"status": "partial", "missing_aspects": ["limitations"],
            "paragraphs": [{"content_markdown": "Original supported contribution", "evidence_ids": ["E1"]}]}),
            completion({"status": "partial", "missing_aspects": ["quantitative results"],
                "paragraphs": [{"content_markdown": "New supported limitation", "evidence_ids": ["E1"]}]})]
        result = run_single_search(prepare_search(job, model, store), model, store)
        self.assertIn("Original supported contribution", result.content_markdown)
        self.assertIn("New supported limitation", result.content_markdown)
        self.assertEqual(len(result.citations), 2)

    def test_review_supplement_keeps_filled_cells(self):
        from test_staged_review import fixture
        papers, groups = fixture(2)
        job = make_job("review", "Compare methods and limitations", source=[chunk for group in groups.values() for chunk in group], papers=papers)
        store, model = SearchMemoryStore(job.search_policy), Mock()
        def respond(messages, **options):
            data = json.loads(messages[1]["content"])
            if "paper" in data:
                first = model.complete.call_count == 1
                columns = data["columns"]
                return completion({"cells": {column["key"]: {"value": "Original method" if first and index == 0 else "New finding" if not first and index == 1 else None,
                    "evidence_ids": [data["evidence"][0]["evidence_id"]] if (first and index == 0) or (not first and index == 1) else []} for index, column in enumerate(columns)}})
            return completion({"paragraphs": [{"content_markdown": "Supported", "evidence_ids": [data["evidence"][0]["evidence_id"]]}]})
        model.complete.side_effect = respond
        result = run_staged_review(prepare_search(job, model, store), model, store, supplement=supplement_review)
        values = [cell["value"] for cell in result.comparison_table["rows"][0]["cells"].values()]
        self.assertIn("Original method", values)
        self.assertIn("New finding", values)

    def test_summary_unknown_usage_fits_automatic_supplement_budget(self):
        job = make_job("summary", "Summarize limitations", source=document(*["Agent evaluation. " * 100 for unused in range(24)]))
        store, model = SearchMemoryStore(job.search_policy), Mock()
        draft = {"status": "partial", "missing_aspects": ["limitations"],
            "paragraphs": [{"content_markdown": "Supported", "evidence_ids": ["E1"]}]}
        model.complete.return_value = ModelCompletion(json.dumps(draft), None, None, "stop")
        run_single_search(prepare_search(job, model, store), model, store)
        self.assertEqual(model.complete.call_count, 2)
        self.assertLessEqual(sum(a["input_tokens"] + a["output_tokens"] for u in store.read()["units"].values() for a in u["attempts"]), job.max_tokens)

    def test_supplement_failure_keeps_valid_first_answer(self):
        job = make_job("qa", "Explain methods and limitations", source=document(*[f"Agent design {index}." for index in range(24)]))
        store, model = SearchMemoryStore(job.search_policy), Mock()
        model.complete.side_effect = [completion({"status": "partial", "missing_aspects": ["limitations"],
            "paragraphs": [{"content_markdown": "Supported method", "evidence_ids": ["E1"]}]}),
            ModelTimeoutError("fixture"), ModelTimeoutError("fixture")]
        result = run_single_search(prepare_search(job, model, store), model, store)
        self.assertIn("Supported method", result.content_markdown)
        self.assertEqual(store.read()["search"]["outcome"]["status"], "partial")

    def test_cross_language_answer_preserves_original_question_and_quotes(self):
        job = make_job()
        store, model = SearchMemoryStore(job.search_policy), Mock()
        model.complete.side_effect = [completion({"intent": "specific", "queries": ["proposed Rust debugging method"]}),
            completion({"status": "answered", "paragraphs": [{"content_markdown": "提出 Rust 调试代理。", "evidence_ids": ["E1"]}]})]
        prepared = prepare_search(job, model, store)
        result = run_single_search(prepared, model, store)
        self.assertEqual(model.complete.call_count, 2)
        self.assertEqual(json.loads(model.complete.call_args.args[0][1]["content"])["question"], job.question)
        self.assertTrue(result.citations)
        self.assertTrue(any(result.citations[0].quote in chunk.content for chunk in job.source_evidence))
        self.assertEqual(store.read()["search"]["outcome"]["status"], "answered")

    def test_expansion_failure_degrades_once_and_recovery_reuses_checkpoints(self):
        job = make_job()
        store, model = SearchMemoryStore(job.search_policy), Mock()
        model.complete.side_effect = ModelTimeoutError("fixture")
        first = prepare_search(job, model, store)
        second = prepare_search(job, model, store)
        self.assertEqual(model.complete.call_count, 1)
        self.assertEqual(first.evidence, second.evidence)
        self.assertTrue(store.read()["search"]["query"]["degraded"])
        self.assertEqual(len(store.read()["units"]["search:expand"]["attempts"]), 1)

    def test_interrupted_expansion_is_not_reissued(self):
        job = make_job()
        store, model = SearchMemoryStore(job.search_policy), Mock()
        store.reserve("search:expand", 100, 512, "retrieving", "fixture", {})
        prepared = prepare_search(job, model, store)
        model.complete.assert_not_called()
        self.assertTrue(prepared.evidence)
        self.assertEqual(store.read()["search"]["query"]["degraded"], "interrupted_expansion")

    def test_specific_unknown_question_supplements_once_then_reports_scope(self):
        job = make_job(question="What is the quuxspecificnumber?", source=document(*[f"Background section {index}: agents." for index in range(25)]))
        store, model = SearchMemoryStore(job.search_policy), Mock()
        model.complete.side_effect = [completion({"status": "needs_more_evidence", "missing_aspects": ["quuxspecificnumber"], "paragraphs": []})] * 2
        prepared = prepare_search(job, model, store)
        result = run_single_search(prepared, model, store)
        self.assertEqual(model.complete.call_count, 2)
        self.assertEqual(result.citations, [])
        self.assertIn("retrieved passages", result.content_markdown)
        self.assertEqual(store.read()["search"]["outcome"]["status"], "insufficient_selected_evidence")
        again = run_single_search(prepare_search(job, model, store), model, store)
        self.assertEqual(model.complete.call_count, 2)
        self.assertEqual(again, result)

    def test_no_parsed_text_does_not_call_model(self):
        job = make_job(source=[])
        store, model = SearchMemoryStore(job.search_policy), Mock()
        result = run_single_search(prepare_search(job, model, store), model, store)
        model.complete.assert_not_called()
        self.assertIn("解析文本", result.content_markdown)

    def test_unknown_evidence_is_rejected(self):
        job = make_job()
        with self.assertRaises(ValueError):
            validate_answer(json.dumps({"status": "answered", "paragraphs": [{"content_markdown": "Claim", "evidence_ids": ["E9999"]}]}), job)
        with self.assertRaises(ValueError):
            validate_answer(json.dumps({"status": "answered", "paragraphs": [{"content_markdown": "42 percent", "evidence_ids": []}]}), job)

    def test_review_supplement_preserves_ids_and_other_papers_on_resume(self):
        from test_staged_review import fixture
        papers, groups = fixture(2)
        source = [chunk for group in groups.values() for chunk in group]
        job = make_job("review", "Compare cost", source=source, papers=papers)
        store, model = SearchMemoryStore(job.search_policy), Mock()
        prepared = prepare_search(job, model, store)
        initial = deepcopy(prepared.review_plan["registry"])
        analysis = {"cells": {column["key"]: {"value": None, "evidence_ids": []} for column in prepared.review_plan["columns"]}}
        updated, changed = supplement_review(prepared, analysis, papers[0], store)
        self.assertTrue(changed)
        self.assertEqual(updated.review_plan["registry"][:len(initial)], initial)
        resumed = prepare_search(job, model, store)
        self.assertEqual(resumed.evidence, updated.evidence)
        self.assertEqual(resumed.review_plan["registry"], updated.review_plan["registry"])
        before = {chunk.chunk_id for chunk in prepared.evidence if chunk.paper_id == papers[1]["paper_id"]}
        self.assertEqual(before, {chunk.chunk_id for chunk in updated.evidence if chunk.paper_id == papers[1]["paper_id"]})

    def test_six_paper_chinese_review_completes_offline(self):
        from test_staged_review import fixture
        papers, groups = fixture(6)
        job = make_job("review", "比较这些论文的目标、方法和结果", source=[chunk for group in groups.values() for chunk in group], papers=papers)
        store, model = SearchMemoryStore(job.search_policy), Mock()
        def respond(messages, **options):
            data = json.loads(messages[1]["content"])
            if "titles" in data:
                return completion({"intent": "comparison", "queries": ["research objective agent method evaluation limitations"]})
            if "paper" in data:
                identity = data["evidence"][0]["evidence_id"]
                return completion({"cells": {column["key"]: {"value": "Supported", "evidence_ids": [identity]} for column in data["columns"]}})
            return completion({"paragraphs": [{"content_markdown": "Supported comparison", "evidence_ids": [data["evidence"][0]["evidence_id"]]}]})
        model.complete.side_effect = respond
        prepared = prepare_search(job, model, store)
        result = run_staged_review(prepared, model, store, supplement=supplement_review)
        self.assertEqual(len(result.comparison_table["rows"]), 6)
        self.assertEqual(model.complete.call_count, 10)
        self.assertTrue(result.citations)

    def test_all_papers_can_supplement_with_unknown_usage_within_reserved_budget(self):
        from test_staged_review import fixture
        papers, groups = fixture(6)
        job = make_job("review", "比较论文的方法和成本", source=[chunk for group in groups.values() for chunk in group], papers=papers)
        store, model = SearchMemoryStore(job.search_policy), Mock()
        seen = set()
        def respond(messages, **options):
            data = json.loads(messages[1]["content"])
            if "titles" in data:
                payload = {"intent": "comparison", "queries": ["agent method cost evaluation limitations"]}
            elif "paper" in data:
                paper_id = data["paper"]["paper_id"]
                first = paper_id not in seen
                seen.add(paper_id)
                payload = {"cells": {column["key"]: {"value": None if first else "Supported",
                    "evidence_ids": [] if first else [data["evidence"][0]["evidence_id"]]} for column in data["columns"]}}
            else:
                payload = {"paragraphs": [{"content_markdown": "Supported", "evidence_ids": [data["evidence"][0]["evidence_id"]]}]}
            return ModelCompletion(json.dumps(payload), None, None, "stop")
        model.complete.side_effect = respond
        prepared = prepare_search(job, model, store)
        result = run_staged_review(prepared, model, store, supplement=supplement_review)
        self.assertEqual(model.complete.call_count, 16)
        self.assertEqual(len(result.comparison_table["rows"]), 6)
        self.assertTrue(all(cell["value"] is not None for row in result.comparison_table["rows"] for cell in row["cells"].values()))
        calls = model.complete.call_count
        resumed = prepare_search(job, model, store)
        repeated = run_staged_review(resumed, model, store, supplement=supplement_review)
        self.assertEqual(model.complete.call_count, calls)
        self.assertEqual(result, repeated)


if __name__ == "__main__":
    unittest.main()
