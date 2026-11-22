import hashlib
import json
import os
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

from alembic import command
from alembic.config import Config
from app.agent_bridge.contracts import AgentEvidence, DispatchManifest, ResultEnvelope
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

    def research_client(self, user_id=None):
        from types import SimpleNamespace
        from fastapi.testclient import TestClient
        from app.auth.dependencies import require_user
        from app.main import create_app

        app = create_app(self.settings)
        app.state.sessions = self.sessions
        app.dependency_overrides[require_user] = lambda: SimpleNamespace(id=user_id or self.user_id)
        client = TestClient(app)
        self.addCleanup(client.close)
        return client

    def test_research_create_list_detail_and_delete_use_frontend_shapes(self):
        client = self.research_client()
        second_id = uuid4()
        with self.sessions.begin() as session:
            session.add(Paper(id=second_id, user_id=self.user_id, title="Second paper",
                original_filename="second.pdf", storage_key=f"uploads/{second_id}.pdf",
                size_bytes=12, sha256="b" * 64, status="ready", page_count=1, parser_version="test-v1"))
        body = {"question": "比较研究方法", "paper_ids": [str(second_id), str(self.paper_id)], "allow_search": True}
        response = client.post("/api/v1/agent-research", json=body,
            headers={"Idempotency-Key": "research-key"})
        self.assertEqual(response.status_code, 202, response.text)
        task_id = response.json()["task_id"]
        self.assertEqual(response.headers["location"], f"/api/v1/agent-research/{task_id}")
        replay = client.post("/api/v1/agent-research", json=body, headers={"Idempotency-Key": "research-key"})
        self.assertEqual(replay.json()["task_id"], task_id)
        self.assertEqual(replay.headers["idempotency-replayed"], "true")
        conflict = client.post("/api/v1/agent-research", json={**body, "question": "Different"},
            headers={"Idempotency-Key": "research-key"})
        self.assertEqual(conflict.status_code, 409)
        records = client.get("/api/v1/agent-research?status=queued&limit=10&offset=0").json()
        self.assertEqual(records["total"], 1)
        self.assertEqual(records["items"][0]["papers"], [
            {"id": str(second_id), "title": "Second paper"}, {"id": str(self.paper_id), "title": "Uploaded PDF"}])
        detail = client.get(f"/api/v1/agent-research/{task_id}").json()
        self.assertEqual(detail["paper_ids"], body["paper_ids"])
        self.assertEqual(detail["question"], body["question"])
        self.assertIsNone(detail["result"])
        self.assertEqual(client.delete(f"/api/v1/agent-research/{task_id}").status_code, 204)
        self.assertEqual(client.get(f"/api/v1/agent-research/{task_id}").status_code, 404)
        with self.sessions() as session:
            self.assertIsNotNone(session.get(Paper, self.paper_id))

    def test_research_isolates_users_and_legacy_tasks(self):
        client = self.research_client()
        record = client.post("/api/v1/agent-research", json={"question": "Explain"}).json()
        task_id = record["task_id"]
        foreign = self.research_client(self.other_user)
        self.assertEqual(foreign.get("/api/v1/agent-research").json()["total"], 0)
        for response in (foreign.get(f"/api/v1/agent-research/{task_id}"),
            foreign.delete(f"/api/v1/agent-research/{task_id}"),
            foreign.post("/api/v1/agent-research", json={"question": "Explain", "paper_ids": [str(self.paper_id)]})):
            self.assertEqual(response.status_code, 404)
        legacy, _ = submit_task(self.sessions, self.settings, self.request, "legacy", user_id=self.user_id)
        self.assertEqual(client.get("/api/v1/agent-research").json()["total"], 1)
        self.assertEqual(client.get(f"/api/v1/agent-research/{legacy['id']}").status_code, 404)
        self.assertEqual(client.delete(f"/api/v1/agent-research/{legacy['id']}").status_code, 404)

    def test_research_requires_session_origin_and_csrf(self):
        from app.auth.security import cookie_name, csrf_token, new_token, token_hash
        from app.db.models import AuthSession

        client = self.research_client()
        client.app.dependency_overrides.clear()
        self.assertEqual(client.get("/api/v1/agent-research").status_code, 401)
        raw = new_token()
        with self.sessions.begin() as session:
            session.add(AuthSession(id=uuid4(), user_id=self.user_id, token_hash=token_hash(raw),
                auth_version=1, expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
        client.cookies.set(cookie_name(self.settings), raw)
        self.assertEqual(client.get("/api/v1/agent-research").status_code, 200)
        body = {"question": "Explain"}
        self.assertEqual(client.post("/api/v1/agent-research", json=body).status_code, 403)
        headers = {"Origin": self.settings.frontend_public_url}
        self.assertEqual(client.post("/api/v1/agent-research", json=body, headers=headers).status_code, 403)
        headers["X-CSRF-Token"] = csrf_token(self.settings, raw)
        self.assertEqual(client.post("/api/v1/agent-research", json=body, headers=headers).status_code, 202)

    def test_research_enforces_server_runner_quotas_and_shared_idempotency(self):
        client = self.research_client()
        self.settings.agent_dispatch_enabled = False
        self.assertEqual(client.post("/api/v1/agent-research", json={"question": "Explain"}).status_code, 503)
        self.settings.agent_dispatch_enabled = True
        self.settings.task_runner = "mock"
        self.assertEqual(client.post("/api/v1/agent-research", json={"question": "Explain"}).status_code, 503)
        self.settings.task_runner = "agent"
        submit_task(self.sessions, self.settings, self.request, "legacy", user_id=self.user_id)
        self.assertEqual(client.post("/api/v1/agent-research", json={"question": "Explain"},
            headers={"Idempotency-Key": "legacy"}).status_code, 409)
        self.settings.user_active_tasks = 1
        response = client.post("/api/v1/agent-research", json={"question": "Explain"})
        self.assertEqual(response.status_code, 429, response.text)

    def test_research_running_and_recovered_jobs_cannot_be_deleted(self):
        client = self.research_client()
        accepted = client.post("/api/v1/agent-research", json={"question": "Explain"}).json()
        task_id = claim_task(self.sessions, self.owner, "agent")
        self.assertEqual(str(task_id), accepted["task_id"])
        path = f"/api/v1/agent-research/{task_id}"
        self.assertEqual(client.delete(path).status_code, 409)
        with self.sessions.begin() as session:
            task = session.get(Task, task_id)
            task.status, task.stage = "queued", "queued"
            task.worker_id, task.lease_expires_at = None, None
        self.assertEqual(client.delete(path).status_code, 409)

    def test_research_preserves_search_results_partial_and_failed_outcomes(self):
        from uuid import UUID

        client = self.research_client()
        for reason in ("completed", "partial", "model_error"):
            accepted = client.post("/api/v1/agent-research", json={"question": "Explain methods"}).json()
            task_id = UUID(accepted["task_id"])
            self.assertEqual(claim_task(self.sessions, self.owner, "agent"), task_id)
            self.assertTrue(set_task_stage(self.sessions, task_id, self.owner,
                "agent_packaging", "agent_waiting", "waiting"))
            with self.sessions() as session:
                run = session.get(AgentRun, task_id)
                manifest = DispatchManifest.model_validate(run.manifest)
                envelope = self.envelope(manifest, run.input_sha256, reason)
            source_id = "arxiv:1706.03762v7"
            metadata = {"source_id": source_id, "paper_id": "arxiv:1706.03762", "title": "External",
                "url": "https://arxiv.org/abs/1706.03762v7"}
            envelope.result.sources = [metadata]
            envelope.result.citations = [AgentEvidence(**metadata, page=1, source_text="Evidence",
                chunk_id=source_id + ":p1:c1")]
            self.assertTrue(complete_delivery(self.sessions, task_id, self.owner, manifest, envelope))
            detail = client.get(f"/api/v1/agent-research/{task_id}")
            self.assertEqual(detail.status_code, 200, detail.text)
            record = detail.json()
            self.assertEqual(record["result"], envelope.result.model_dump(mode="json"))
            self.assertEqual(record["status"], "failed" if reason == "model_error" else "succeeded")
            self.assertEqual(record["result"]["stop_reason"], reason)
            with self.sessions() as session:
                self.assertEqual(list(session.scalars(select(Citation).where(Citation.task_id == task_id))), [])
            self.assertEqual(client.delete(f"/api/v1/agent-research/{task_id}").status_code, 204)

    def envelope(self, manifest, digest, reason="completed"):
        return ResultEnvelope.model_validate({"schema_version": "agent-result-v1",
            "dispatch_id": str(manifest.dispatch_id), "input_sha256": digest,
            "result": {"task_id": manifest.task.task_id, "question": manifest.task.question,
                "answer": "An answer", "stop_reason": reason,
                "usage": {"model_calls": 2, "tool_calls": 3},
                "unresolved": ["missing evidence"] if reason == "partial" else []}})

    def test_history_includes_matching_imports_added_after_research(self):
        from app.db.models import PaperSource

        client = self.research_client()
        path = "/api/v1/agent-research"
        client.post(path, json={"question": "Compare", "paper_ids": [str(self.paper_id)]}).raise_for_status()
        task_id = claim_task(self.sessions, self.owner, "agent")
        self.assertTrue(set_task_stage(self.sessions, task_id, self.owner, "agent_packaging", "agent_waiting", "waiting"))
        with self.sessions() as session:
            run = session.get(AgentRun, task_id)
            manifest = DispatchManifest.model_validate(run.manifest)
            envelope = self.envelope(manifest, run.input_sha256)
        opened = [("1706.03762", "v7"), ("1810.04805", "@" + "a" * 12)]
        envelope.result.sources = [
            {"source_id": "arxiv:" + base + suffix, "paper_id": "arxiv:" + base, "title": base,
             "url": "https://arxiv.org/abs/" + base + (suffix if suffix.startswith("v") else ""),
             "version": 7 if suffix == "v7" else 1} for base, suffix in opened]
        envelope.result.trace = [{"kind": "tool", "name": "search_papers", "observation": {"results": [
            {"source": "1706.03762", "title": "[1706.03762] Attention Is All You Need"},
            {"source": "1810.04805v2", "title": "Different version"}]}}]
        self.assertTrue(complete_delivery(self.sessions, task_id, self.owner, manifest, envelope))

        def add_import(user_id, external_id, sha):
            paper_id = uuid4()
            with self.sessions.begin() as session:
                session.add(Paper(id=paper_id, user_id=user_id, title=external_id, original_filename="import.pdf",
                    storage_key=f"uploads/{paper_id}.pdf", size_bytes=20, sha256=sha, status="uploaded"))
                session.flush()
                session.add(PaperSource(user_id=user_id, paper_id=paper_id, provider="arxiv",
                    external_id=external_id, source_metadata={}))
            return str(paper_id)

        def check_history(first=None, second=None):
            record = client.get(path).json()["items"][0]
            self.assertEqual(record["paper_ids"], [str(self.paper_id)])
            self.assertEqual([p["id"] for p in record["papers"]], [str(self.paper_id), first, second])
            for paper, source in zip(record["papers"][1:], envelope.result.sources):
                if paper["id"] is None:
                    title = "Attention Is All You Need" if source["paper_id"] == "arxiv:1706.03762" else source["title"]
                    self.assertEqual(paper, {**source, "id": None, "title": title})

        add_import(self.other_user, "1706.03762v7", "a" * 64)
        add_import(self.user_id, "1706.03762v6", "b" * 64)
        check_history()
        second = add_import(self.user_id, "1810.04805v1", "a" * 64)
        check_history(second=second)
        first = add_import(self.user_id, "1706.03762v7", "c" * 64)
        check_history(first, second)

    def test_discovered_library_citation_checks_owner_digest_and_page_without_changing_selection(self):
        from io import BytesIO
        from uuid import UUID
        from pypdf import PdfWriter
        from app.db.models import TaskPaper

        client = self.research_client()
        data = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        writer.write(data)
        upload = {"file": ("discovery.pdf", data.getvalue(), "application/pdf")}
        paper = client.post("/api/v1/papers", files=upload).json()
        foreign = self.research_client(self.other_user).post("/api/v1/papers", files=upload).json()
        self.assertIsNone(paper["page_count"])

        for selected in ([], [str(self.paper_id)]):
            task_id = UUID(client.post("/api/v1/agent-research",
                json={"question": "Explain", "paper_ids": selected}).json()["task_id"])
            self.assertEqual(claim_task(self.sessions, self.owner), task_id)
            self.assertTrue(set_task_stage(self.sessions, task_id, self.owner, "agent_packaging", "agent_waiting", "waiting"))
            with self.sessions() as session:
                run = session.get(AgentRun, task_id)
                manifest = DispatchManifest.model_validate(run.manifest)
                envelope = self.envelope(manifest, run.input_sha256)

            def deliver(id_string, sha, page):
                source = f"local:{id_string}@{sha}"
                metadata = {"source_id": source, "paper_id": id_string, "url": "", "title": "Discovered"}
                chunk = f"{source}:p{page}:c1"
                envelope.result.sources = [metadata]
                envelope.result.citations = [AgentEvidence(**metadata, page=page, source_text="Evidence", chunk_id=chunk)]
                envelope.result.answer = f"Evidence [{chunk}]"
                return complete_delivery(self.sessions, task_id, self.owner, manifest, envelope, settings=self.settings)

            with self.assertRaisesRegex(ValueError, "owner"):
                deliver(foreign["id"], foreign["sha256"], 1)
            with self.assertRaisesRegex(ValueError, "changed"):
                deliver(paper["id"], "0" * 64, 1)
            with self.assertRaisesRegex(ValueError, "pages"):
                deliver(paper["id"], paper["sha256"], 2)
            self.assertTrue(deliver(paper["id"], paper["sha256"], 1))
            response = client.get(f"/api/v1/agent-research/{task_id}").json()
            self.assertEqual(response["paper_ids"], selected)
            summary = next(row for row in client.get("/api/v1/agent-research").json()["items"] if row["id"] == str(task_id))
            self.assertEqual([p["id"] for p in summary["papers"]], [*selected, paper["id"]])
            self.assertEqual(response["result"], envelope.result.model_dump(mode="json"))
            with self.sessions() as session:
                stored = session.get(TaskPaper, (task_id, UUID(paper["id"])))
                self.assertIsNone(stored.selection_order)
                self.assertEqual(stored.paper_sha256, paper["sha256"])
                self.assertEqual(session.scalar(select(Citation.paper_id).where(Citation.task_id == task_id)), UUID(paper["id"]))
                self.assertIn("[C1]", session.scalar(select(Artifact.content_markdown).where(Artifact.task_id == task_id)))

    def test_uploaded_pdf_without_backend_chunks_can_be_dispatched_and_replayed(self):
        from app.db.models import PaperChunk

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
            self.assertIsNone(session.scalar(select(PaperChunk.id)))

    def test_monitor_retires_pending_local_runs_and_preserves_terminal_history(self):
        from app.db.models import TaskEvent

        now = datetime.now(timezone.utc)
        pending, history = [], uuid4()
        with self.sessions.begin() as session:
            for runner in ("mock", "langgraph"):
                for status in ("queued", "running"):
                    task = Task(id=uuid4(), user_id=self.user_id, task_type="summary", runner_type=runner,
                        workflow_version="langgraph-v1", status=status, stage=status, request_hash="a" * 64,
                        created_at=now - timedelta(seconds=20), updated_at=now)
                    if status == "running":
                        task.started_at = now
                        task.worker_id = uuid4()
                        task.lease_expires_at = now + timedelta(seconds=60)
                    session.add(task)
                    pending.append(task.id)
            session.add(Task(id=history, user_id=self.user_id, task_type="summary", runner_type="langgraph",
                workflow_version="langgraph-v1", status="succeeded", stage="completed", request_hash="b" * 64,
                created_at=now - timedelta(seconds=20), updated_at=now,
                started_at=now - timedelta(seconds=10), finished_at=now))
            session.flush()
            session.add(Artifact(task_id=history, title="Historical result", content_markdown="Preserved research"))
        self.assertIsNone(claim_task(self.sessions, self.owner))
        self.assertEqual(reap_expired(self.sessions), 4)
        self.assertEqual(reap_expired(self.sessions), 0)
        with self.sessions() as session:
            for task_id in pending:
                task = session.get(Task, task_id)
                self.assertEqual((task.status, task.error_code), ("failed", "RUNNER_RETIRED"))
                self.assertIsNone(task.worker_id)
                self.assertIsNone(task.lease_expires_at)
                self.assertEqual(session.scalar(select(TaskEvent).where(TaskEvent.task_id == task_id)).event_type, "error")
            self.assertEqual(session.get(Task, history).status, "succeeded")
        client = self.research_client()
        response = client.get(f"/api/v1/tasks/{history}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()["retrieval"])
        response = client.get(f"/api/v1/tasks/{history}/artifacts")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["items"][0]["content_markdown"], "Preserved research")

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
            original_start = datetime.now(timezone.utc) - timedelta(seconds=30)
            task.started_at = original_start
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
            self.assertEqual(session.get(Task, task_id).started_at, original_start)

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

    def test_concurrent_claims_share_two_slots_across_users(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier

        for user_id in (self.user_id, self.other_user):
            client = self.research_client(user_id)
            for question in ("First", "Second"):
                self.assertEqual(client.post("/api/v1/agent-research", json={"question": question}).status_code, 202)
        ready = Barrier(4)

        def claim(owner):
            ready.wait(timeout=5)
            return claim_task(self.sessions, owner)

        with ThreadPoolExecutor(max_workers=4) as pool:
            claimed = list(pool.map(claim, (uuid4() for _ in range(4))))
        self.assertEqual(claimed.count(None), 2)
        with self.sessions() as session:
            first_two = session.scalars(select(Task.id).order_by(Task.created_at, Task.id).limit(2))
            self.assertEqual(set(claimed) - {None}, set(first_two))

    def test_history_changes_live_queue_limit_without_restarting_runner(self):
        from threading import Thread
        from time import monotonic, sleep

        from app.agent_bridge.bundles import exchange_directory
        from app.agent_bridge.files import atomic_write
        from app.agent_bridge.worker import AgentWorker

        client = self.research_client()
        for question in ("First", "Second", "Third", "Fourth", "Fifth"):
            response = client.post("/api/v1/agent-research", json={"question": question})
            self.assertEqual(response.status_code, 202, response.text)
        with self.sessions() as session:
            tasks = session.scalars(select(Task).order_by(Task.created_at, Task.id)).all()
            runs = [session.get(AgentRun, task.id) for task in tasks]

        def deliver(run):
            envelope = self.envelope(DispatchManifest.model_validate(run.manifest), run.input_sha256)
            inbox = exchange_directory(self.settings.resolved_agent_exchange_root, "inbox", run.dispatch_id)
            atomic_write(inbox / "result.json", envelope.model_dump_json().encode())

        def wait_for_stages(*expected):
            deadline = monotonic() + 10
            while monotonic() < deadline:
                with self.sessions() as session:
                    stages = tuple(session.scalars(select(Task.stage).order_by(Task.created_at, Task.id)))
                if stages == expected:
                    return
                sleep(0.05)
            self.assertEqual(stages, expected)

        url = "/api/v1/agent-research/queue/concurrency"
        other = self.research_client(self.other_user)
        self.assertEqual(client.get(url).json(), {"concurrency": 2})
        for invalid in (0, 5, True, "4", 1.5):
            self.assertEqual(client.put(url, json={"concurrency": invalid}).status_code, 422)

        def change(limit):
            response = client.put(url, json={"concurrency": limit})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(other.get(url).json(), {"concurrency": limit})

        change(1)
        self.settings.agent_poll_seconds = 0.1
        runner = AgentWorker(self.sessions, self.settings)
        thread = Thread(target=runner.run)
        thread.start()
        try:
            for limit in range(1, 5):
                if limit > 1:
                    change(limit)
                wait_for_stages(*(["agent_waiting"] * limit + ["queued"] * (5 - limit)))
                self.assertIsNone(claim_task(self.sessions, uuid4()))
            change(1)
            for index in range(3):
                deliver(runs[index])
            wait_for_stages("completed", "completed", "completed", "agent_waiting", "queued")
            self.assertIsNone(claim_task(self.sessions, uuid4()))
            deliver(runs[3])
            wait_for_stages("completed", "completed", "completed", "completed", "agent_waiting")
            deliver(runs[4])
            wait_for_stages(*(["completed"] * 5))
        finally:
            runner.stopped.set()
            thread.join()

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
