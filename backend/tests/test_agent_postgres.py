import hashlib
import json
import os
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

from alembic import command
from alembic.config import Config
from app.agent_bridge.contracts import DispatchManifest, ResultEnvelope
from app.agent_bridge.store import complete_delivery, record_job
from app.api.schemas import TaskCreate
from app.config import Settings
from app.db.models import AgentRun, Artifact, Base, Citation, Paper, Task, User
from app.errors import APIError
from app.tasks.lifecycle import claim_task, reap_expired, set_task_stage
from app.tasks.service import submit_task
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

TEST_URL = os.environ.get("AGENT_TEST_DATABASE_URL")


@unittest.skipUnless(TEST_URL, "Set AGENT_TEST_DATABASE_URL to isolated agent_bridge_tests")
class AgentPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        target = make_url(TEST_URL)
        if target.host != "127.0.0.1" or not re.fullmatch(r"agent_bridge_tests(?:_[0-9a-f]{32})?", target.database or ""):
            raise RuntimeError("Use an isolated agent_bridge_tests database on loopback")
        cls.engine = create_engine(TEST_URL)
        cls.sessions = sessionmaker(cls.engine, expire_on_commit=False)
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        with cls.engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            command.check(config)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        with self.engine.begin() as connection:
            names = ", ".join('"' + name + '"' for name in Base.metadata.tables)
            connection.execute(text("TRUNCATE " + names))
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.settings = Settings(_env_file=None, database_url=TEST_URL, storage_root=Path(self.temporary.name),
            task_monitor_enabled=False, task_runner="agent", agent_dispatch_enabled=True,
            auth_rate_key="r" * 32, auth_csrf_key="c" * 32)
        self.user_id, self.other_user = uuid4(), uuid4()
        self.paper_id = uuid4()
        pdf = b"%PDF-1.7\ntransport fixture"
        directory = self.settings.storage_root / "uploads"
        directory.mkdir()
        (directory / f"{self.paper_id}.pdf").write_bytes(pdf)
        with self.sessions.begin() as session:
            for index, user_id in enumerate((self.user_id, self.other_user)):
                session.add(User(id=user_id, username=f"fixture{index}", username_key=f"fixture{index}",
                    email=f"fixture{index}@example.com", email_key=f"fixture{index}@example.com",
                    password_hash="unused", status="active", email_verified_at=datetime.now(timezone.utc)))
            session.flush()
            session.add(Paper(id=self.paper_id, user_id=self.user_id, title="Uploaded PDF",
                original_filename="paper.pdf", storage_key=f"uploads/{self.paper_id}.pdf",
                size_bytes=len(pdf), sha256=hashlib.sha256(pdf).hexdigest(), status="uploaded"))
        self.request = TaskCreate(task_type="qa", question="这篇论文的方法是什么？", paper_ids=[self.paper_id])
        self.owner = uuid4()

    def create_and_claim(self):
        accepted, _ = submit_task(self.sessions, self.settings, self.request, "fixture-key", user_id=self.user_id)
        task_id = claim_task(self.sessions, self.owner, "agent")
        self.assertEqual(task_id, accepted["id"])
        self.assertTrue(set_task_stage(self.sessions, task_id, self.owner, "agent_packaging", "agent_waiting", "waiting"))
        with self.sessions() as session:
            run = session.get(AgentRun, task_id)
            return task_id, DispatchManifest.model_validate(run.manifest), run.input_sha256

    def envelope(self, manifest, digest, reason="completed"):
        return ResultEnvelope.model_validate({"schema_version": "agent-result-v1",
            "dispatch_id": str(manifest.dispatch_id), "input_sha256": digest,
            "result": {"task_id": manifest.task.task_id, "question": manifest.task.question,
                "answer": "An answer", "stop_reason": reason,
                "usage": {"model_calls": 2, "tool_calls": 3},
                "unresolved": ["missing evidence"] if reason == "partial" else []}})

    def test_uploaded_pdf_submission_skips_old_retrieval_and_ignores_client_budget(self):
        with patch("app.tasks.service.source_snapshot", side_effect=AssertionError("Old retrieval must not run")), \
            patch("app.tasks.service.build_search_plan", side_effect=AssertionError("Old research must not run")):
            first, replayed = submit_task(self.sessions, self.settings, self.request, "same", user_id=self.user_id)
            self.assertFalse(replayed)
            changed_budget = self.request.model_copy(update={"budget": self.request.budget.model_copy(update={"max_steps": 1})})
            second, replayed = submit_task(self.sessions, self.settings, changed_budget, "same", user_id=self.user_id)
            self.assertTrue(replayed)
            self.assertEqual(first["id"], second["id"])
        with self.sessions() as session:
            task = session.get(Task, first["id"])
            self.assertEqual(task.runner_type, "agent")
            self.assertNotIn("search_policy", task.run_config)
            self.assertIsNotNone(session.get(AgentRun, task.id))

    def test_other_user_cannot_dispatch_selected_paper(self):
        with self.assertRaises(APIError) as caught:
            submit_task(self.sessions, self.settings, self.request, None, user_id=self.other_user)
        self.assertEqual(caught.exception.status_code, 404)

    def test_disabled_dispatch_refuses_to_queue(self):
        settings = self.settings.model_copy(update={"agent_dispatch_enabled": False})
        with self.assertRaises(APIError) as caught:
            submit_task(self.sessions, settings, self.request, None, user_id=self.user_id)
        self.assertEqual(caught.exception.status_code, 503)

    def delete_record(self, task_id):
        from app.api.tasks import delete_task
        request = Mock()
        request.app.state.sessions = self.sessions
        user = Mock()
        user.id = self.user_id
        return delete_task(request, task_id, user)

    def test_requeued_agent_cannot_be_deleted_while_remote_job_may_still_run(self):
        task_id, manifest, _digest = self.create_and_claim()
        with self.sessions.begin() as session:
            task = session.get(Task, task_id)
            task.status, task.stage = "queued", "queued"
            task.worker_id, task.lease_expires_at = None, None
        with self.assertRaises(APIError) as caught:
            self.delete_record(task_id)
        self.assertEqual(caught.exception.status_code, 409)
        with self.sessions() as session:
            self.assertEqual(session.get(AgentRun, task_id).dispatch_id, manifest.dispatch_id)

    def test_unstarted_agent_can_be_deleted_without_deleting_original_pdf(self):
        accepted, _ = submit_task(self.sessions, self.settings, self.request, None, user_id=self.user_id)
        self.delete_record(accepted["id"])
        with self.sessions() as session:
            self.assertIsNone(session.get(Task, accepted["id"]))
            self.assertIsNone(session.get(AgentRun, accepted["id"]))
            self.assertIsNotNone(session.get(Paper, self.paper_id))
        self.assertTrue((self.settings.storage_root / "uploads" / f"{self.paper_id}.pdf").exists())

    def test_finished_agent_deletion_cascades_result_and_keeps_original_paper(self):
        task_id, manifest, digest = self.create_and_claim()
        self.assertTrue(complete_delivery(self.sessions, task_id, self.owner, manifest, self.envelope(manifest, digest)))
        self.delete_record(task_id)
        with self.sessions() as session:
            self.assertIsNone(session.get(AgentRun, task_id))
            self.assertIsNone(session.scalar(select(Artifact).where(Artifact.task_id == task_id)))
            self.assertIsNotNone(session.get(Paper, self.paper_id))

    def test_failed_remote_job_cannot_be_deleted_before_stop_confirmation(self):
        from app.tasks.lifecycle import database_time, mark_failed

        task_id, manifest, _digest = self.create_and_claim()
        for transport in ("local-process-v1", "tacc-ssh-slurm-v1"):
            with self.subTest(transport=transport):
                with self.sessions.begin() as session:
                    task = session.get(Task, task_id)
                    task.run_config = {**task.run_config, "transport": transport}
                    mark_failed(session, task, database_time(session), "TASK_TIMEOUT", "Timeout fixture")
                with self.assertRaises(APIError) as caught:
                    self.delete_record(task_id)
                self.assertEqual(caught.exception.status_code, 409)
                self.assertEqual(caught.exception.error["code"], "AGENT_STOP_PENDING")
                with self.sessions() as session:
                    self.assertEqual(session.get(AgentRun, task_id).dispatch_id, manifest.dispatch_id)
        with self.sessions.begin() as session:
            task = session.get(Task, task_id)
            task.run_config = {**task.run_config, "agent_cancel_confirmed": True}
        self.delete_record(task_id)
        with self.sessions() as session:
            self.assertIsNone(session.get(Task, task_id))
            self.assertIsNotNone(session.get(Paper, self.paper_id))

    def test_delivered_failure_can_be_deleted_without_extra_cancellation(self):
        task_id, manifest, digest = self.create_and_claim()
        with self.sessions.begin() as session:
            task = session.get(Task, task_id)
            task.run_config = {**task.run_config, "transport": "local-process-v1"}
        self.assertTrue(complete_delivery(self.sessions, task_id, self.owner, manifest,
            self.envelope(manifest, digest, "output_truncated")))
        self.delete_record(task_id)
        with self.sessions() as session:
            self.assertIsNone(session.get(Task, task_id))

    def test_partial_result_preserves_raw_output_and_is_not_full_completion(self):
        task_id, manifest, digest = self.create_and_claim()
        envelope = self.envelope(manifest, digest, "partial")
        self.assertTrue(complete_delivery(self.sessions, task_id, self.owner, manifest, envelope))
        self.assertFalse(complete_delivery(self.sessions, task_id, self.owner, manifest, envelope))
        with self.sessions() as session:
            task = session.get(Task, task_id)
            self.assertEqual((task.status, task.stage, task.tool_calls), ("succeeded", "partial", 3))
            self.assertEqual(session.get(AgentRun, task_id).result["unresolved"], ["missing evidence"])
            self.assertIsNotNone(session.scalar(select(Artifact).where(Artifact.task_id == task_id)))

    def test_failed_agent_result_is_saved_without_creating_success_artifact(self):
        task_id, manifest, digest = self.create_and_claim()
        self.assertTrue(complete_delivery(self.sessions, task_id, self.owner, manifest, self.envelope(manifest, digest, "output_truncated")))
        with self.sessions() as session:
            task = session.get(Task, task_id)
            self.assertEqual(task.status, "failed")
            self.assertEqual(task.error_code, "AGENT_OUTPUT_TRUNCATED")
            self.assertEqual(session.get(AgentRun, task_id).stop_reason, "output_truncated")
            self.assertIsNone(session.scalar(select(Artifact).where(Artifact.task_id == task_id)))

    def test_lease_recovery_reuses_dispatch_and_rejects_stale_owner(self):
        task_id, manifest, digest = self.create_and_claim()
        with self.sessions.begin() as session:
            task = session.get(Task, task_id)
            task.created_at = datetime.now(timezone.utc) - timedelta(seconds=40)
            task.started_at = datetime.now(timezone.utc) - timedelta(seconds=30)
            task.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        self.assertEqual(reap_expired(self.sessions), 1)
        new_owner = uuid4()
        self.assertEqual(claim_task(self.sessions, new_owner, "agent"), task_id)
        self.assertTrue(set_task_stage(self.sessions, task_id, new_owner, "agent_packaging", "agent_waiting", "waiting"))
        envelope = self.envelope(manifest, digest)
        self.assertFalse(complete_delivery(self.sessions, task_id, self.owner, manifest, envelope))
        self.assertTrue(complete_delivery(self.sessions, task_id, new_owner, manifest, envelope))
        with self.sessions() as session:
            self.assertEqual(session.get(AgentRun, task_id).dispatch_id, manifest.dispatch_id)

    def test_native_citation_does_not_require_old_backend_chunk(self):
        task_id, manifest, digest = self.create_and_claim()
        envelope = self.envelope(manifest, digest)
        value = envelope.model_dump(mode="json")
        source = manifest.sources[0]
        value["result"]["citations"] = [{"chunk_id": source.source_id + ":p1:c1",
            "source_id": source.source_id, "paper_id": source.source_id, "page": 1,
            "source_text": "Agent-extracted text", "title": source.title, "url": ""}]
        self.assertTrue(complete_delivery(self.sessions, task_id, self.owner, manifest, ResultEnvelope.model_validate(value)))
        with self.sessions() as session:
            citation = session.scalar(select(Citation).where(Citation.task_id == task_id))
            self.assertIsNone(citation.chunk_id)
            self.assertEqual(citation.agent_source_id, source.source_id)

    def test_comparison_api_projects_citations_and_preserves_native_result(self):
        from app.api.tasks import task_artifacts

        task_id, manifest, digest = self.create_and_claim()
        value = self.envelope(manifest, digest, "partial").model_dump(mode="json")
        source = manifest.sources[0]
        chunk = source.source_id + ":p1:c1"
        comparison = f"| Paper | Evidence |\n| --- | --- |\n| Uploaded | [{chunk}] |"
        value["result"]["comparison_table"] = comparison
        value["result"]["citations"] = [{"chunk_id": chunk, "source_id": source.source_id,
            "paper_id": source.source_id, "page": 1, "source_text": "Original PDF evidence.",
            "title": source.title, "url": ""}]
        self.assertTrue(complete_delivery(self.sessions, task_id, self.owner, manifest,
            ResultEnvelope.model_validate(value)))
        request, user = Mock(), Mock()
        request.app.state.sessions = self.sessions
        user.id = self.user_id
        artifact = task_artifacts(request, task_id, user)["items"][0]
        self.assertIn("[C1]", artifact["comparison_markdown"])
        self.assertNotIn(chunk, artifact["comparison_markdown"])
        self.assertEqual(artifact["agent_stop_reason"], "partial")
        with self.sessions() as session:
            self.assertEqual(session.get(AgentRun, task_id).result["comparison_table"], comparison)

    def test_worker_publishes_only_one_dispatch_and_accepts_returned_result(self):
        from app.agent_bridge.bundles import exchange_directory
        from app.agent_bridge.worker import AgentWorker

        accepted, _ = submit_task(self.sessions, self.settings, self.request, "worker", user_id=self.user_id)
        with self.sessions() as session:
            run = session.get(AgentRun, accepted["id"])
            manifest = DispatchManifest.model_validate(run.manifest)
            envelope = self.envelope(manifest, run.input_sha256)
        incoming = exchange_directory(self.settings.resolved_agent_exchange_root, "inbox", manifest.dispatch_id)
        incoming.mkdir(parents=True)
        (incoming / "result.json").write_text(envelope.model_dump_json(), encoding="utf-8")
        worker = AgentWorker(self.sessions, self.settings)
        self.assertTrue(worker.run_once())
        self.assertFalse(worker.run_once())
        outgoing = exchange_directory(self.settings.resolved_agent_exchange_root, "outbox", manifest.dispatch_id)
        self.assertTrue((outgoing / "input.zip").exists())
        with self.sessions() as session:
            self.assertEqual(session.get(Task, accepted["id"]).status, "succeeded")

    def test_saved_platform_job_is_fenced_and_delivery_must_match(self):
        task_id, manifest, digest = self.create_and_claim()
        self.assertFalse(record_job(self.sessions, task_id, uuid4(), manifest, "8123"))
        self.assertTrue(record_job(self.sessions, task_id, self.owner, manifest, "8123"))
        self.assertTrue(record_job(self.sessions, task_id, self.owner, manifest, "8123"))
        with self.assertRaises(ValueError):
            record_job(self.sessions, task_id, self.owner, manifest, "9999")
        with self.assertRaises(ValueError):
            complete_delivery(self.sessions, task_id, self.owner, manifest, self.envelope(manifest, digest))
        value = self.envelope(manifest, digest).model_dump(mode="json") | {"remote_job_id": "8123"}
        self.assertTrue(complete_delivery(self.sessions, task_id, self.owner, manifest, ResultEnvelope.model_validate(value)))

    def test_worker_consumes_wrapper_failure_without_fabricating_result(self):
        from app.agent_bridge.bundles import exchange_directory
        from app.agent_bridge.worker import AgentWorker

        accepted, _ = submit_task(self.sessions, self.settings, self.request, "wrapper-failure", user_id=self.user_id)
        with self.sessions() as session:
            run = session.get(AgentRun, accepted["id"])
            status = {"schema_version": "agent-job-status-v1", "dispatch_id": str(run.dispatch_id),
                "input_sha256": run.input_sha256, "remote_job_id": "8123", "state": "failed", "stop_reason": None,
                "error": {"code": "EXECUTION_ERROR", "type": "ValueError"}, "updated_at": datetime.now(timezone.utc).isoformat()}
            directory = exchange_directory(self.settings.resolved_agent_exchange_root, "inbox", run.dispatch_id)
        directory.mkdir(parents=True)
        (directory / "status.json").write_text(json.dumps(status), encoding="utf-8")
        self.assertTrue(AgentWorker(self.sessions, self.settings).run_once())
        with self.sessions() as session:
            task = session.get(Task, accepted["id"])
            self.assertEqual(task.status, "failed")
            self.assertEqual(task.error_code, "AGENT_WRAPPER_FAILED")
            self.assertEqual(task.error_details["wrapper_code"], "EXECUTION_ERROR")
            self.assertIsNone(session.get(AgentRun, task.id).result)
            self.assertIsNone(session.scalar(select(Artifact).where(Artifact.task_id == task.id)))

    def test_terminal_cancellation_never_cancels_a_recovered_active_task(self):
        from app.agent_bridge.maintenance import cancel_terminal
        from app.tasks.lifecycle import fail_owned

        task_id, manifest, digest = self.create_and_claim()
        settings = self.settings.model_copy(update={"agent_transport": "local"})
        with self.sessions.begin() as session:
            task = session.get(Task, task_id)
            task.run_config = {**task.run_config, "transport": "local-process-v1"}
        transport = Mock()
        transport.cancel.return_value = True
        self.assertFalse(cancel_terminal(self.sessions, settings, task_id, transport))
        transport.cancel.assert_not_called()
        self.assertTrue(fail_owned(self.sessions, task_id, self.owner, "TASK_TIMEOUT", "timeout"))
        self.assertTrue(cancel_terminal(self.sessions, settings, task_id, transport))
        transport.cancel.assert_called_once_with(manifest, None)
        self.assertFalse(cancel_terminal(self.sessions, settings, task_id, transport))
        with self.sessions() as session:
            task = session.get(Task, task_id)
            self.assertEqual(task.status, "failed")
            self.assertTrue(task.run_config["agent_cancel_confirmed"])
