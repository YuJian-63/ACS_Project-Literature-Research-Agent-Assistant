import json
import os
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.orm import sessionmaker

from app.api.schemas import TaskCreate
from app.api.views import task_view
from app.db.models import Artifact, Citation, Paper, PaperChunk, Task, User
from app.research.model_client import ModelCompletion
from app.research.review_protocol import validate_analysis
from app.research.review_store import ReviewOwnershipLost, ReviewStore
from app.tasks.lifecycle import claim_task, reap_expired
from app.tasks.service import request_hash, submit_task
from app.workers.research import RunnerWorker, load_research_job
import test_review_execution as execution_fixtures
from test_staged_review import settings

TEST_URL = os.environ.get("STAGED_REVIEW_TEST_URL")


@unittest.skipUnless(TEST_URL, "Set STAGED_REVIEW_TEST_URL to an isolated test database")
class ReviewPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sqlalchemy.engine import make_url
        target = make_url(TEST_URL)
        if target.host != "127.0.0.1" or target.database != "review_tests" or target.port not in {55432, 55433}:
            raise RuntimeError("Refused: this suite requires the isolated review_tests database on port 55432 or 55433")
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
        from datetime import datetime, timezone
        self.user_id = uuid4()
        with self.sessions.begin() as session:
            session.add(User(id=self.user_id, username=self.user_id.hex, username_key=self.user_id.hex,
                email=f"{self.user_id}@example.com", email_key=f"{self.user_id}@example.com",
                password_hash="fixture", status="active", email_verified_at=datetime.now(timezone.utc)))
        self.paper_ids = []
        self.task_ids = []
        self.settings = settings(task_runner="langgraph", real_runner_configured=True, llm_base_url="https://fixture.invalid",
            llm_model_id="fixture", llm_api_key=None, llm_thinking_mode="disabled", llm_timeout_seconds=60,
            evidence_context_chars=24000, mock_step_delay_seconds=0, user_active_tasks=100, user_daily_tasks=1000)

    def tearDown(self):
        with self.sessions.begin() as session:
            session.execute(delete(Citation).where(Citation.task_id.in_(self.task_ids)))
            session.execute(delete(Artifact).where(Artifact.task_id.in_(self.task_ids)))
            session.execute(delete(Task).where(Task.id.in_(self.task_ids)))
            session.execute(delete(Paper).where(Paper.id.in_(self.paper_ids)))
            session.execute(delete(User).where(User.id == self.user_id))

    def submit(self, count=2, budget=None, key=None):
        with self.sessions.begin() as session:
            for index in range(count):
                identity = uuid4()
                self.paper_ids.append(identity)
                session.add(Paper(id=identity, user_id=self.user_id, title=f"Rust agent paper {index}", original_filename="fixture.pdf", storage_key=f"uploads/{identity}.pdf",
                    size_bytes=100, sha256="a" * 64, status="ready", page_count=2, parser_version="fixture"))
                session.flush()
                session.add(PaperChunk(id=uuid4(), paper_id=identity, chunk_index=0, page_number=1,
                    content="Agents evaluate repository issue resolution methods and limitations.", content_sha256="b" * 64, parser_version="fixture"))
        request = TaskCreate(task_type="review", question="Compare methods", paper_ids=self.paper_ids,
                             **({"budget": budget} if budget else {}))
        accepted, unused = submit_task(self.sessions, self.settings, request, key, user_id=self.user_id)
        identity = UUID(accepted["id"]) if isinstance(accepted["id"], str) else accepted["id"]
        self.task_ids.append(identity)
        return identity, request

    def worker(self, model=None):
        generated, recorded = execution_fixtures.StagedRunnerTests().model()
        model = model or generated
        model.close = MagicMock()
        return RunnerWorker(self.sessions, self.settings, model_factory=lambda job, current: model), recorded

    def expire(self, identity):
        with self.sessions.begin() as session:
            session.execute(text("UPDATE tasks SET created_at=clock_timestamp()-interval '30 seconds', started_at=clock_timestamp()-interval '20 seconds', lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=:identity"), {"identity": identity})
            return session.get(Task, identity).started_at

    def test_automatic_budget_and_replay_ignore_client_budget(self):
        identity, request = self.submit(6, {"max_steps": 1, "max_tokens": 1, "timeout_seconds": 1}, "native-auto-" + str(uuid4()))
        with self.sessions() as session:
            task = session.get(Task, identity)
            key = task.idempotency_key
            self.assertEqual(task.workflow_version, "langgraph-search-v1")
            self.assertGreater(task.max_steps, 6)
            self.assertGreater(task.max_tokens, 8000)
        request.budget.max_tokens = 100000
        accepted, replayed = submit_task(self.sessions, self.settings, request, key, user_id=self.user_id)
        self.assertTrue(replayed)
        self.assertEqual(accepted["id"], identity)

    def test_six_paper_worker_publishes_complete_artifact(self):
        identity, request = self.submit(6)
        worker, recorded = self.worker()
        self.assertEqual(claim_task(self.sessions, worker.owner, "langgraph"), identity)
        worker.execute(identity)
        with self.sessions() as session:
            task = session.get(Task, identity)
            self.assertEqual(task.status, "succeeded", task.error_message)
            self.assertEqual(task.model_calls, 9)
            self.assertEqual(task.input_tokens, 270)
            artifact = session.scalar(select(Artifact).where(Artifact.task_id == identity))
            self.assertEqual(len(artifact.comparison_table["rows"]), 6)
            self.assertEqual(task_view(task, request.paper_ids)["budget_mode"], "automatic")
            self.assertFalse(task_view(task, request.paper_ids)["stats"]["usage_estimated"])
        self.assertEqual(len(recorded), 9)

    def test_interrupted_worker_preserves_checkpoint_deadline_and_fences_old_owner(self):
        identity, request = self.submit()
        first_owner = uuid4()
        claim_task(self.sessions, first_owner, "langgraph")
        job = load_research_job(self.sessions, identity)
        store = ReviewStore(self.sessions, identity, first_owner)
        paper = job.selected_papers[0]
        key = "paper:" + paper["paper_id"]
        attempt = store.reserve(key, 100, 200, "analyzing", "Analyzing", {})
        evidence_id = next(entry["evidence_id"] for entry in job.review_plan["registry"] if entry["paper_id"] == paper["paper_id"])
        raw = json.dumps({"cells": {column["key"]: {"value": "Supported finding", "evidence_ids": [evidence_id]} for column in job.review_plan["columns"]}})
        store.settle(key, attempt, ModelCompletion(raw, 50, 40, "stop"), None)
        store.checkpoint(key, attempt, validate_analysis(raw, paper, job.review_plan))
        started = self.expire(identity)
        self.assertEqual(reap_expired(self.sessions), 1)
        worker, recorded = self.worker()
        self.assertEqual(claim_task(self.sessions, worker.owner, "langgraph"), identity)
        with self.assertRaises(ReviewOwnershipLost):
            store.checkpoint(key, attempt, {"cells": {}})
        worker.execute(identity)
        with self.sessions() as session:
            task = session.get(Task, identity)
            self.assertEqual(task.status, "succeeded", task.error_message)
            self.assertEqual(task.started_at, started)
            self.assertEqual(task.model_calls, 5)
        self.assertEqual(len(recorded), 4)

    def test_uncertain_inflight_reservation_is_retained_after_recovery(self):
        identity, request = self.submit()
        owner = uuid4()
        claim_task(self.sessions, owner, "langgraph")
        job = load_research_job(self.sessions, identity)
        store = ReviewStore(self.sessions, identity, owner)
        key = "paper:" + job.selected_papers[0]["paper_id"]
        store.reserve(key, 100, 200, "analyzing", "Analyzing", {})
        self.expire(identity)
        reap_expired(self.sessions)
        worker, recorded = self.worker()
        claim_task(self.sessions, worker.owner, "langgraph")
        worker.execute(identity)
        with self.sessions() as session:
            task = session.get(Task, identity)
            self.assertEqual(task.status, "succeeded", task.error_message)
            self.assertEqual(task.model_calls, 6)
            self.assertTrue(task.review_state["usage_estimated"])
            self.assertGreaterEqual(task.input_tokens, 100)

    def test_invalid_json_has_no_artifact_and_includes_all_attempt_usage(self):
        identity, request = self.submit()
        model = MagicMock()
        model.complete.return_value = ModelCompletion('{"cells":', 100, 30, "stop")
        worker, recorded = self.worker(model)
        claim_task(self.sessions, worker.owner, "langgraph")
        worker.execute(identity)
        with self.sessions() as session:
            task = session.get(Task, identity)
            self.assertEqual(task.status, "failed")
            self.assertEqual(task.error_code, "INVALID_AGENT_RESULT")
            self.assertEqual(task.error_details["validation_reason"], "invalid_json")
            self.assertEqual(task.model_calls, 2)
            self.assertEqual(task.input_tokens, 200)
            self.assertIsNone(session.scalar(select(Artifact).where(Artifact.task_id == identity)))

    def test_concurrent_workers_only_one_claims_review(self):
        from concurrent.futures import ThreadPoolExecutor
        identity, request = self.submit()
        with ThreadPoolExecutor(max_workers=4) as pool:
            claimed = list(pool.map(lambda owner: claim_task(self.sessions, owner, "langgraph"), [uuid4() for unused in range(4)]))
        self.assertEqual(claimed.count(identity), 1)
        self.assertEqual(claimed.count(None), 3)

    def test_requeued_review_expires_at_original_deadline(self):
        identity, request = self.submit()
        owner = uuid4()
        claim_task(self.sessions, owner, "langgraph")
        self.expire(identity)
        reap_expired(self.sessions)
        with self.sessions.begin() as session:
            session.execute(text("UPDATE tasks SET created_at=clock_timestamp()-interval '2 hours', started_at=clock_timestamp()-interval '1 hour', timeout_seconds=60 WHERE id=:identity"), {"identity": identity})
        self.assertEqual(reap_expired(self.sessions), 1)
        with self.sessions() as session:
            task = session.get(Task, identity)
            self.assertEqual((task.status, task.error_code), ("failed", "TASK_TIMEOUT"))

    def test_legacy_replay_precedes_current_model_configuration(self):
        identity, request = self.submit(key="legacy-" + str(uuid4()))
        with self.sessions.begin() as session:
            task = session.get(Task, identity)
            task.workflow_version = "langgraph-review-v1"
            task.run_config = {name: value for name, value in task.run_config.items() if name != "budget_mode"}
            task.request_hash = request_hash(request)
            key = task.idempotency_key
        self.settings.real_runner_configured = False
        accepted, replayed = submit_task(self.sessions, self.settings, request, key, user_id=self.user_id)
        self.assertTrue(replayed)
        self.assertEqual(accepted["id"], identity)


if __name__ == "__main__":
    unittest.main()
