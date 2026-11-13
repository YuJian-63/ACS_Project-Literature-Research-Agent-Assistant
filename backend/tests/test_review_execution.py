import json
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.research.model_client import ModelCompletion
from app.research.review_store import ReviewStore, ReviewOwnershipLost, ReviewLimitError
from app.research.review_runner import run_staged_review
from test_staged_review import fixture, settings
from app.research.review_policy import build_review_plan


class ReviewStoreTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.owner = uuid4()
        self.task = SimpleNamespace(id=uuid4(), status="running", stage="retrieving", worker_id=self.owner,
            started_at=self.now, lease_expires_at=self.now + timedelta(seconds=60), timeout_seconds=900,
            max_steps=9, max_tokens=50000, review_state={"units": {}}, last_event_seq=0,
            run_config={"review_policy": {"retry_reserve": 2}}, input_tokens=None, output_tokens=None, model_calls=None, tool_calls=None)
        self.sessions = MagicMock()
        self.store = ReviewStore(self.sessions, self.task.id, self.owner)
        self.lock_patch = patch("app.research.review_store.locked_task", return_value=self.task)
        self.time_patch = patch("app.research.review_store.database_time", return_value=self.now)
        self.lock_patch.start()
        self.time_patch.start()
        self.addCleanup(self.lock_patch.stop)
        self.addCleanup(self.time_patch.stop)

    def test_reservation_survives_unknown_outcome_and_counts_retries(self):
        first = self.store.reserve("paper:1", 100, 200, "analyzing", "Analyzing", {})
        self.assertEqual((self.task.input_tokens, self.task.output_tokens, self.task.model_calls), (100, 200, 1))
        self.store.settle("paper:1", first, None, {"reason": "network"})
        second = self.store.reserve("paper:1", 100, 200, "analyzing", "Retrying", {})
        self.store.settle("paper:1", second, ModelCompletion("{}", 90, 50, "stop"), None)
        self.assertEqual((self.task.input_tokens, self.task.output_tokens, self.task.model_calls), (190, 250, 2))
        self.assertTrue(self.task.review_state["usage_estimated"])
        with self.assertRaises(ReviewLimitError):
            self.store.reserve("paper:1", 100, 200, "analyzing", "Again", {})

    def test_stale_owner_cannot_reserve_settle_or_checkpoint(self):
        attempt = self.store.reserve("paper:1", 100, 200, "analyzing", "Analyzing", {})
        self.task.worker_id = uuid4()
        for operation in (lambda: self.store.reserve("paper:2", 100, 200, "analyzing", "Analyzing", {}),
                          lambda: self.store.settle("paper:1", attempt, None, None),
                          lambda: self.store.checkpoint("paper:1", attempt, {"cells": {}})):
            with self.assertRaises(ReviewOwnershipLost):
                operation()

    def test_global_retry_limit_and_partial_usage_remain_reserved(self):
        for key in ("paper:1", "paper:2"):
            first = self.store.reserve(key, 100, 200, "analyzing", "Analyzing", {})
            self.store.settle(key, first, ModelCompletion("bad", 50, None, "stop"), {"validation_reason": "invalid_json"})
            self.store.reserve(key, 100, 200, "analyzing", "Retrying", {})
        third = self.store.reserve("paper:3", 100, 200, "analyzing", "Analyzing", {})
        with self.assertRaises(ReviewLimitError):
            self.store.reserve("paper:3", 100, 200, "analyzing", "Retrying", {})
        self.assertEqual(self.task.input_tokens, 500)
        self.assertEqual(self.task.output_tokens, 1000)
        self.assertTrue(self.task.review_state["usage_estimated"])

    def test_budget_prevents_network_reservation(self):
        self.task.max_tokens = 200
        with self.assertRaises(ReviewLimitError):
            self.store.reserve("paper:1", 100, 200, "analyzing", "Analyzing", {})
        self.assertFalse(self.task.review_state["units"])

    def test_second_attempt_success_is_saved_with_usage_in_one_transaction(self):
        first = self.store.reserve("paper:1", 100, 200, "analyzing", "Analyzing", {})
        self.store.settle("paper:1", first, ModelCompletion("bad", 50, 40, "stop"), {"validation_reason": "invalid_json"})
        second = self.store.reserve("paper:1", 100, 200, "analyzing", "Retrying", {})
        self.sessions.begin.reset_mock()
        self.store.settle("paper:1", second, ModelCompletion("{}", 40, 30, "stop"), None, result={"cells": {}})
        self.assertEqual(self.sessions.begin.call_count, 1)
        saved = self.store.read()["units"]["paper:1"]
        self.assertEqual(saved["result"], {"cells": {}})
        self.assertEqual(saved["attempts"][-1]["status"], "succeeded")
        self.assertEqual((self.task.input_tokens, self.task.output_tokens), (90, 70))

    def test_valid_checkpoint_and_reported_usage_persist(self):
        attempt = self.store.reserve("paper:1", 100, 200, "analyzing", "Analyzing", {})
        self.store.settle("paper:1", attempt, ModelCompletion("{}", 50, 40, "stop"), None)
        self.store.checkpoint("paper:1", attempt, {"cells": {}})
        self.assertEqual(self.store.read()["units"]["paper:1"]["result"], {"cells": {}})
        self.assertFalse(self.task.review_state["usage_estimated"])


class MemoryStore:
    def __init__(self):
        self.state = {"units": {}}
        self.calls = 0

    def read(self):
        return deepcopy(self.state)

    def reserve(self, key, input_tokens, output_tokens, stage, message, payload):
        unit = self.state["units"].setdefault(key, {"attempts": []})
        if len(unit["attempts"]) >= 2:
            raise ReviewLimitError("No retries")
        self.calls += 1
        unit["attempts"].append({"finish_reason": None})
        return str(self.calls)

    def settle(self, key, identity, completion, diagnostic, result=None):
        self.state["units"][key]["attempts"][-1]["finish_reason"] = completion.finish_reason if completion else None
        if result is not None:
            self.checkpoint(key, identity, result)

    def checkpoint(self, key, identity, result):
        self.state["units"][key]["result"] = result

    def skip(self, key, result):
        self.state["units"][key] = {"result": result, "attempts": []}


class StagedRunnerTests(unittest.TestCase):
    def job(self, count=6):
        papers, groups = fixture(count)
        if count == 20:
            groups = {identity: [chunk.model_copy(update={"content": "Agent methods and evaluation."}) for chunk in chunks[:1]] for identity, chunks in groups.items()}
        plan, evidence = build_review_plan(papers, groups, "Compare methods", settings())
        return SimpleNamespace(selected_papers=papers, review_plan=plan, evidence=evidence, question="Compare methods",
            model_id="fixture", started_at=datetime.now(timezone.utc), timeout_seconds=1800)

    def model(self, bad_first=None):
        recorded = []
        def complete(messages, **kwargs):
            recorded.append(kwargs)
            payload = json.loads(messages[-1]["content"])
            if bad_first and len(recorded) == 1:
                return ModelCompletion('{"cells":', 30, 40, bad_first)
            if "paper" in payload:
                identity = payload["evidence"][0]["evidence_id"]
                raw = {"cells": {column["key"]: {"value": "Supported method", "evidence_ids": [identity]} for column in payload["columns"]}}
            else:
                identities = [next(iter(analysis["cells"].values()))["evidence_ids"][0] for analysis in payload["analyses"]]
                raw = {"paragraphs": [{"content_markdown": "Evidence-backed comparison.", "evidence_ids": identities[:8]}]}
            return ModelCompletion(json.dumps(raw), 30, 50, "stop")
        return SimpleNamespace(complete=complete), recorded

    def test_runner_atomically_settles_validated_results(self):
        job, store = self.job(2), MemoryStore()
        model, recorded = self.model()
        original = store.settle
        checkpoints = []
        def atomic_settle(key, identity, completion, diagnostic, result=None):
            original(key, identity, completion, diagnostic)
            if result is not None:
                checkpoints.append(key)
                store.checkpoint(key, identity, result)
        store.settle = atomic_settle
        result = run_staged_review(job, model, store)
        self.assertEqual(len(checkpoints), 5)
        self.assertEqual(len(result.comparison_table["rows"]), 2)

    def test_two_six_twenty_run_without_full_artifact_generation(self):
        for count in (2, 6, 20):
            job, store = self.job(count), MemoryStore()
            model, recorded = self.model()
            result = run_staged_review(job, model, store)
            self.assertEqual(len(recorded), count + 3)
            self.assertEqual(len(result.comparison_table["rows"]), count)
            run_staged_review(job, model, store)
            self.assertEqual(len(recorded), count + 3, "Resume must reuse completed units")

    def test_stop_invalid_json_and_length_retry_only_current_unit(self):
        for finish in ("stop", "length"):
            job, store = self.job(2), MemoryStore()
            model, recorded = self.model(finish)
            result = run_staged_review(job, model, store)
            self.assertEqual(len(recorded), 6)
            self.assertEqual(len(result.comparison_table["rows"]), 2)

    def test_sections_without_relevant_evidence_are_explicit_and_skip_calls(self):
        job, store = self.job(2), MemoryStore()
        model, recorded = self.model()
        original = model.complete
        def only_objectives(messages, **kwargs):
            response = original(messages, **kwargs)
            payload = json.loads(response.content)
            if "cells" in payload:
                for key, cell in payload["cells"].items():
                    if key != "objective":
                        cell.update(value=None, evidence_ids=[])
                return ModelCompletion(json.dumps(payload), 30, 40, "stop")
            return response
        model.complete = only_objectives
        result = run_staged_review(job, model, store)
        self.assertEqual(len(recorded), 3)
        self.assertIn("Insufficient evidence", result.content_markdown)

    def test_all_empty_evidence_uses_no_model_calls(self):
        job, store = self.job(2), MemoryStore()
        job.review_plan["registry"] = []
        job.evidence = []
        model = SimpleNamespace(complete=MagicMock())
        result = run_staged_review(job, model, store)
        model.complete.assert_not_called()
        self.assertFalse(result.citations)
        self.assertEqual(len(result.comparison_table["rows"]), 2)

    def test_repeated_invalid_output_stops_after_two_attempts(self):
        job, store = self.job(2), MemoryStore()
        model = SimpleNamespace(complete=MagicMock(return_value=ModelCompletion('{"cells":', 30, 40, "stop")))
        with self.assertRaises(ValueError):
            run_staged_review(job, model, store)
        self.assertEqual(model.complete.call_count, 2)
        self.assertNotIn("result", store.state["units"]["paper:" + job.selected_papers[0]["paper_id"]])


if __name__ == "__main__":
    unittest.main()
