import unittest
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import test_agent_postgres as fixtures
from app.agent_bridge.contracts import ResultEnvelope
from app.agent_bridge.store import complete_delivery
from app.db.models import AgentRun, Task, TaskEvaluation
from app.evaluations.service import enqueue_evaluation, claim_evaluation, finish_evaluation
from app.evaluations.contracts import EvaluationFailure
from sqlalchemy import select, text
from pydantic import SecretStr


@unittest.skipUnless(fixtures.TEST_URL, "Set AGENT_TEST_DATABASE_URL to isolated agent_bridge_tests")
class EvaluationPostgresTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.AgentPostgresTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.AgentPostgresTests.tearDownClass.__func__)
    setUp = fixtures.AgentPostgresTests.setUp
    create_and_claim = fixtures.AgentPostgresTests.create_and_claim
    envelope = fixtures.AgentPostgresTests.envelope
    research_client = fixtures.AgentPostgresTests.research_client

    def ready(self, *, auto=False, reason="completed"):
        self.settings.evaluation_enabled = auto
        self.settings.evaluation_model = "test-judge"
        self.settings.evaluation_api_key = SecretStr("test-key")
        task_id, manifest, digest = self.create_and_claim()
        delivery = ResultEnvelope.model_validate(self.envelope(manifest, digest, reason))
        self.assertTrue(complete_delivery(self.sessions, task_id, self.owner, manifest, delivery, settings=self.settings))
        return task_id

    def enqueue(self, task_id):
        with self.sessions.begin() as session:
            task = session.get(Task, task_id, with_for_update=True)
            return enqueue_evaluation(session, task, self.settings).id

    def test_automatic_scoring_is_atomic_and_off_by_default(self):
        task_id = self.ready()
        with self.sessions() as session:
            self.assertIsNone(session.scalar(select(TaskEvaluation)))
        evaluation_id = self.enqueue(task_id)
        self.assertEqual(self.enqueue(task_id), evaluation_id)
        with self.sessions.begin() as session:
            session.delete(session.get(Task, task_id))
        with self.sessions() as session:
            self.assertIsNone(session.get(TaskEvaluation, evaluation_id))

    def test_new_results_enqueue_when_enabled(self):
        task_id = self.ready(auto=True, reason="partial")
        with self.sessions() as session:
            evaluation = session.scalar(select(TaskEvaluation).where(TaskEvaluation.task_id == task_id))
            self.assertEqual(evaluation.status, "pending")
            self.assertEqual(evaluation.input_payload["stop_reason"], "partial")
            self.assertEqual(evaluation.input_payload["question"], self.request.question)
            self.assertEqual(session.get(Task, task_id).status, "succeeded")

    def test_imported_arxiv_alias_uses_the_owned_original_without_a_download(self):
        import hashlib
        from pathlib import Path
        from app.db.models import Paper, PaperSource
        from app.evaluations.evidence import prepare_evidence
        from app.evaluations.service import result_input

        pdf = (Path(__file__).resolve().parents[2] / "frontend/checks/fixtures/Orchid Calibration Report.pdf").read_bytes()
        (self.settings.storage_root / "uploads" / f"{self.paper_id}.pdf").write_bytes(pdf)
        with self.sessions.begin() as session:
            paper = session.get(Paper, self.paper_id)
            paper.sha256, paper.size_bytes = hashlib.sha256(pdf).hexdigest(), len(pdf)
            session.add(PaperSource(user_id=self.user_id, paper_id=self.paper_id, provider="arxiv",
                external_id="2601.00001v1", source_metadata={}))
        task_id = self.ready()
        with self.sessions() as session:
            run = session.get(AgentRun, task_id)
            run.result = run.result | {"citations": [{"chunk_id": "native", "source_id": "arxiv:2601.00001v1",
                "page": 2, "source_text": "LUMEN-472"}]}
            payload = result_input(session, session.get(Task, task_id), run)
        evidence = prepare_evidence(payload, self.settings)
        self.assertEqual(evidence["scope"], "original_pages")
        self.assertEqual(evidence["checks"][0]["status"], "matched")

    def test_modified_snapshot_is_rejected_before_provider_call(self):
        from app.evaluations.worker import EvaluationWorker
        for index, field in enumerate(("config", "input_payload", "evidence")):
            with self.subTest(field=field):
                if index:
                    self.setUp()
                task_id = self.ready(auto=True)
                with self.sessions.begin() as session:
                    row = session.scalar(select(TaskEvaluation).where(TaskEvaluation.task_id == task_id))
                    if field == "config":
                        row.config = row.config | {"base_url": "https://invalid.example"}
                    elif field == "input_payload":
                        row.input_payload = row.input_payload | {"answer": "Replaced answer"}
                    else:
                        row.evidence, row.evidence_sha256 = {"pages": []}, "f" * 64
                with patch("app.evaluations.worker.prepare_evidence") as prepare:
                    from unittest.mock import Mock
                    judge = Mock(side_effect=AssertionError("No provider request permitted"))
                    self.assertTrue(EvaluationWorker(self.sessions, self.settings, judge=judge).run_once())
                    judge.assert_not_called()
                    prepare.assert_not_called()
                with self.sessions() as session:
                    row = session.scalar(select(TaskEvaluation).where(TaskEvaluation.task_id == task_id))
                    self.assertEqual(row.status, "failed")
                    self.assertEqual(row.error_code, f"EVALUATION_{field.upper().replace('_PAYLOAD', '')}_CHANGED")

    def test_concurrent_claims_have_one_owner(self):
        from concurrent.futures import ThreadPoolExecutor
        self.ready(auto=True)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(claim_evaluation, self.sessions, self.settings) for _ in range(2)]
            claims = [future.result(timeout=10) for future in futures]
        self.assertEqual(sum(claim is not None for claim in claims), 1)

    def test_last_expired_lease_fails_and_manual_retry_cannot_reset_budget(self):
        from app.errors import APIError
        task_id = self.ready(auto=True)
        claim = claim_evaluation(self.sessions, self.settings)
        with self.sessions.begin() as session:
            row = session.get(TaskEvaluation, claim.id)
            row.attempts = self.settings.evaluation_max_attempts
            row.lease_expires_at = row.started_at - timedelta(seconds=1)
        self.assertIsNone(claim_evaluation(self.sessions, self.settings))
        with self.assertRaises(APIError) as raised:
            self.enqueue(task_id)
        self.assertEqual(raised.exception.error["code"], "EVALUATION_ATTEMPTS_EXHAUSTED")
        with self.sessions() as session:
            self.assertEqual(session.get(TaskEvaluation, claim.id).status, "failed")
            self.assertEqual(session.get(Task, task_id).status, "succeeded")

    def test_disabled_worker_does_not_claim_or_call_provider(self):
        from app.evaluations.worker import EvaluationWorker
        from unittest.mock import Mock
        task_id = self.ready(auto=True)
        self.settings.evaluation_enabled = False
        judge = Mock()
        self.assertFalse(EvaluationWorker(self.sessions, self.settings, judge=judge).run_once())
        judge.assert_not_called()
        with self.sessions() as session:
            row = session.scalar(select(TaskEvaluation).where(TaskEvaluation.task_id == task_id))
            self.assertEqual(row.attempts, 0)
            self.assertEqual(row.status, "pending")

    def test_recovery_fences_stale_completion_and_caps_attempts(self):
        task_id = self.ready(auto=True)
        claim = claim_evaluation(self.sessions, self.settings)
        self.assertIsNotNone(claim)
        self.assertIsNone(claim_evaluation(self.sessions, self.settings))
        with self.sessions.begin() as session:
            row = session.get(TaskEvaluation, claim.id)
            row.lease_expires_at = row.started_at - timedelta(seconds=1)
        replacement = claim_evaluation(self.sessions, self.settings)
        self.assertNotEqual(claim.lease_token, replacement.lease_token)
        self.assertFalse(finish_evaluation(self.sessions, claim, error=EvaluationFailure("OLD")))
        self.assertTrue(finish_evaluation(self.sessions, replacement, error=EvaluationFailure("RATE", retryable=True)))
        with self.sessions.begin() as session:
            row = session.get(TaskEvaluation, claim.id)
            row.next_attempt_at = row.started_at - timedelta(seconds=1)
        final = claim_evaluation(self.sessions, self.settings)
        self.assertEqual(final.attempts, 3)
        finish_evaluation(self.sessions, final, error=EvaluationFailure("RATE", retryable=True))
        with self.sessions() as session:
            self.assertEqual(session.get(TaskEvaluation, final.id).status, "failed")
            self.assertEqual(session.get(Task, task_id).status, "succeeded")

    def test_api_isolates_users_and_reuses_existing_evaluation(self):
        task_id = self.ready()
        self.settings.evaluation_enabled = True
        client = self.research_client()
        url = f"/api/v1/tasks/{task_id}/evaluation"
        self.assertEqual(client.get(url).json()["status"], "not_requested")
        first = client.post(url)
        self.assertEqual(first.status_code, 202, first.text)
        second = client.post(url)
        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(client.get(url).json()["id"], first.json()["id"])
        other = self.research_client(self.other_user)
        self.assertEqual(other.get(url).status_code, 404)
        self.assertEqual(other.post(url).status_code, 404)
        self.assertEqual(client.get(url + f"?evaluation_id={uuid4()}").status_code, 404)

    def test_refresh_evidence_creates_a_quota_limited_version_and_preserves_the_old_report(self):
        task_id = self.ready(auto=True)
        self.settings.evaluation_daily_limit = 2
        claim = claim_evaluation(self.sessions, self.settings)
        old_report = {"assessment": "insufficient_evidence", "overall_score": None, "summary": "Originals unavailable"}
        finish_evaluation(self.sessions, claim, report=old_report)
        client = self.research_client()
        url = f"/api/v1/tasks/{task_id}/evaluation"
        refreshed = client.post(url, json={"refresh_evidence": True})
        self.assertEqual(refreshed.status_code, 202, refreshed.text)
        new_id = refreshed.json()["id"]
        self.assertNotEqual(new_id, str(claim.id))
        self.assertEqual(refreshed.json()["revision"], 1)
        self.assertEqual(client.post(url, json={"refresh_evidence": True}).json()["id"], new_id)
        self.assertEqual(client.get(url + f"?evaluation_id={claim.id}").json()["report"], old_report)
        next_claim = claim_evaluation(self.sessions, self.settings)
        self.assertIsNone(next_claim.evidence)
        finish_evaluation(self.sessions, next_claim, error=EvaluationFailure("EVALUATION_INVALID_RESPONSE"))
        self.assertEqual(client.post(url, json={"refresh_evidence": True}).status_code, 429)

    def test_exhausted_failure_can_request_a_fresh_evaluation_without_resetting_history(self):
        task_id = self.ready(auto=True)
        with self.sessions.begin() as session:
            old = session.scalar(select(TaskEvaluation).where(TaskEvaluation.task_id == task_id))
            old_id = old.id
            old.status, old.error_code, old.attempts = "failed", "EVALUATION_INTERNAL_ERROR", 3
        response = self.research_client().post(f"/api/v1/tasks/{task_id}/evaluation", json={"refresh_evidence": True})
        self.assertEqual(response.status_code, 202, response.text)
        self.assertNotEqual(response.json()["id"], str(old_id))
        self.assertEqual(response.json()["attempts"], 0)
        with self.sessions() as session:
            old = session.get(TaskEvaluation, old_id)
            self.assertEqual((old.status, old.attempts, old.error_code), ("failed", 3, "EVALUATION_INTERNAL_ERROR"))

    def test_failed_agent_is_skipped_instead_of_scored(self):
        task_id = self.ready(auto=True, reason="model_error")
        with self.sessions() as session:
            row = session.scalar(select(TaskEvaluation).where(TaskEvaluation.task_id == task_id))
            self.assertEqual(row.status, "skipped")
            self.assertEqual(row.error_code, "NO_USABLE_RESULT")
            self.assertIsNone(row.report)

    def test_default_allowance_accepts_fifty_versions_then_rejects_a_new_version(self):
        from app.errors import APIError

        task_id = self.ready()
        self.assertEqual(self.settings.evaluation_daily_limit, 50)
        versions = set()
        for number in range(50):
            self.settings.evaluation_model = f"test-judge-{number}"
            versions.add(self.enqueue(task_id))
        self.assertEqual(len(versions), 50)
        self.assertIn(self.enqueue(task_id), versions)
        self.settings.evaluation_model = "test-judge-51"
        with self.assertRaises(APIError) as raised:
            self.enqueue(task_id)
        self.assertEqual(raised.exception.status_code, 429)

    def test_configuration_versions_and_daily_limit(self):
        task_id = self.ready()
        self.settings.evaluation_daily_limit = 1
        evaluation_id = self.enqueue(task_id)
        self.assertEqual(self.enqueue(task_id), evaluation_id)
        self.settings.evaluation_model = "other-judge"
        from app.errors import APIError
        with self.assertRaises(APIError) as raised:
            self.enqueue(task_id)
        self.assertEqual(raised.exception.status_code, 429)
        self.settings.evaluation_daily_limit = 2
        self.assertNotEqual(self.enqueue(task_id), evaluation_id)

    def test_task_deletion_does_not_refund_daily_allowance(self):
        from app.errors import APIError
        self.settings.evaluation_daily_limit = 1
        task_id = self.ready()
        self.enqueue(task_id)
        with self.sessions.begin() as session:
            session.delete(session.get(Task, task_id))
        next_task = self.ready()
        with self.assertRaises(APIError) as raised:
            self.enqueue(next_task)
        self.assertEqual(raised.exception.error["code"], "DAILY_EVALUATION_LIMIT")

    def test_quota_skipped_version_can_be_requested_when_allowance_recovers(self):
        from app.errors import APIError
        task_id = self.ready()
        self.settings.evaluation_daily_limit = 1
        self.enqueue(task_id)
        self.settings.evaluation_model = "new-judge"
        with self.sessions.begin() as session:
            task = session.get(Task, task_id, with_for_update=True)
            row = enqueue_evaluation(session, task, self.settings, automatic=True)
            skipped_id = row.id
            self.assertEqual(row.error_code, "DAILY_EVALUATION_LIMIT")
        with self.assertRaises(APIError):
            self.enqueue(task_id)
        self.settings.evaluation_daily_limit = 2
        self.assertEqual(self.enqueue(task_id), skipped_id)
        self.assertEqual(self.enqueue(task_id), skipped_id)
        with self.sessions() as session:
            self.assertEqual(session.get(TaskEvaluation, skipped_id).status, "pending")

    def test_parallel_enqueue_is_compatible_with_user_foreign_key_locks(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from app.db.models import User
        first = self.ready()
        with self.sessions.begin() as session:
            session.get(Task, first).idempotency_key = None
        second = self.ready()
        barrier = Barrier(2)
        def enqueue_with_foreign_key_lock(task_id):
            with self.sessions.begin() as session:
                session.execute(text("SET LOCAL lock_timeout = '3s'"))
                task = session.get(Task, task_id, with_for_update=True)
                session.scalar(select(User).where(User.id == self.user_id).with_for_update(read=True, key_share=True))
                barrier.wait(timeout=5)
                return enqueue_evaluation(session, task, self.settings).id
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(enqueue_with_foreign_key_lock, task_id) for task_id in (first, second)]
            self.assertEqual(len({future.result(timeout=10) for future in futures}), 2)

    def test_worker_saves_report_and_usage_without_changing_research(self):
        import json
        import httpx
        from app.evaluations.worker import EvaluationWorker
        from app.evaluations.judge import evaluate
        from app.evaluations.service import digest
        from test_evaluations import judge_report
        task_id = self.ready(auto=True)
        with self.sessions.begin() as session:
            row = session.scalar(select(TaskEvaluation).where(TaskEvaluation.task_id == task_id))
            row.input_payload = row.input_payload | {"answer": "Universally better [C2]",
                "citations": [{"key": "C2", "source_id": "arxiv:2601.00001v1", "source_text": "Evidence", "page": 1}]}
            row.input_sha256 = digest(row.input_payload)
        def provider(request):
            return httpx.Response(200, json={"model": "test-judge", "choices": [{"finish_reason": "stop",
                "message": {"content": json.dumps(judge_report())}}], "usage": {"total_tokens": 100}})
        with httpx.Client(transport=httpx.MockTransport(provider)) as client:
            worker = EvaluationWorker(self.sessions, self.settings,
                judge=lambda settings, payload, evidence, config: evaluate(settings, payload, evidence, config, client=client))
            self.assertTrue(worker.run_once())
            self.assertFalse(worker.run_once())
        with self.sessions() as session:
            row = session.scalar(select(TaskEvaluation).where(TaskEvaluation.task_id == task_id))
            self.assertEqual(row.status, "succeeded")
            self.assertEqual(row.report["overall_score"], 74.0)
            self.assertEqual(row.usage["total_tokens"], 100)
            self.assertIsNotNone(row.evidence_sha256)
            self.assertEqual(session.get(Task, task_id).status, "succeeded")

    def test_worker_recovers_network_errors_and_reuses_evidence(self):
        from app.evaluations.worker import EvaluationWorker
        task_id = self.ready(auto=True)
        def provider(*args):
            raise EvaluationFailure("EVALUATION_PROVIDER_TIMEOUT", retryable=True)
        worker = EvaluationWorker(self.sessions, self.settings, judge=provider)
        self.assertTrue(worker.run_once())
        with self.sessions.begin() as session:
            row = session.scalar(select(TaskEvaluation).where(TaskEvaluation.task_id == task_id))
            self.assertEqual(row.status, "pending")
            self.assertEqual(row.error_code, "EVALUATION_PROVIDER_TIMEOUT")
            self.assertIsNotNone(row.evidence)
            row.next_attempt_at = row.started_at - timedelta(seconds=1)
        with patch("app.evaluations.worker.prepare_evidence", side_effect=AssertionError("Evidence was already frozen")):
            self.assertTrue(worker.run_once())

    def test_disabled_api_and_real_session_csrf_enforcement(self):
        task_id = self.ready()
        client = self.research_client()
        url = f"/api/v1/tasks/{task_id}/evaluation"
        self.assertEqual(client.post(url).status_code, 503)
        from datetime import datetime, timezone
        from app.auth.security import cookie_name, csrf_token, new_token, token_hash
        from app.db.models import AuthSession
        self.settings.evaluation_enabled = True
        raw = new_token()
        with self.sessions.begin() as session:
            session.add(AuthSession(id=uuid4(), user_id=self.user_id, token_hash=token_hash(raw), auth_version=1,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
        client.app.dependency_overrides.clear()
        self.assertEqual(client.get(url).status_code, 401)
        client.cookies.set(cookie_name(self.settings), raw)
        self.assertEqual(client.post(url).status_code, 403)
        headers = {"Origin": self.settings.frontend_public_url, "X-CSRF-Token": csrf_token(self.settings, raw)}
        self.assertEqual(client.post(url, headers=headers).status_code, 202)
