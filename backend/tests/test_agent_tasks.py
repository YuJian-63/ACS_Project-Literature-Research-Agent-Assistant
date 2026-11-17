import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import JSON, Column, DateTime, MetaData, Table, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=timezone.utc) if value is not None else None


from app.api.schemas import AgentTaskCreate
from app.db.base import Base
from app.db.models import Task
from app.errors import APIError
from app.tasks.agent import complete_agent, submit_agent_task
from app.tasks.lifecycle import claim_task


def result(task_id, reason="completed"):
    return dict(
        task_id=str(task_id),
        question="Compare methods",
        answer="Answer",
        comparison_table="",
        citations=[],
        unresolved=["Coverage incomplete"] if reason == "partial" else [],
        stop_reason=reason,
        usage=dict(
            agent_steps=1,
            model_calls=2,
            tool_calls=3,
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
            token_usage_complete=False,
            elapsed_seconds=1.2,
        ),
        sources=[],
        trace=[],
        errors=[],
        configuration={},
    )


class AgentTaskTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        metadata = MetaData()
        for table in Base.metadata.sorted_tables:
            Table(
                table.name,
                metadata,
                *(
                    Column(
                        c.name,
                        JSON()
                        if isinstance(c.type, JSONB)
                        else UTCDateTime()
                        if isinstance(c.type, DateTime)
                        else c.type,
                        primary_key=c.primary_key,
                    )
                    for c in table.columns
                ),
            )
        metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        from sqlalchemy import event

        @event.listens_for(Task, "load")
        def normalize_dates(task, context):
            for field in (
                "created_at",
                "updated_at",
                "started_at",
                "finished_at",
                "lease_expires_at",
            ):
                value = getattr(task, field)
                if value is not None and value.tzinfo is None:
                    setattr(task, field, value.replace(tzinfo=timezone.utc))

        self.addCleanup(lambda: event.remove(Task, "load", normalize_dates))
        self.user = uuid4()
        self.owner = uuid4()
        self.now = datetime.now(timezone.utc)
        self.settings = SimpleNamespace(
            agent_python="/private/tmp/fixture-python",
            user_active_tasks=2,
            user_daily_tasks=20,
        )
        self.request = AgentTaskCreate(
            question="Compare methods", sources=["1706.03762v7"]
        )
        self.patches = [
            patch("app.tasks.agent.lock_active_user"),
            patch("app.tasks.agent.check_task_capacity"),
            patch("app.tasks.agent.agent_available", return_value=True),
            patch("app.tasks.lifecycle.database_time", return_value=self.now),
            patch("app.tasks.agent.database_time", return_value=self.now),
        ]
        for item in self.patches:
            item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(self.patches)])
        self.addCleanup(self.engine.dispose)

    def submit(self, key="fixture"):
        accepted, replayed = submit_agent_task(
            self.sessions, self.settings, self.request, key, user_id=self.user
        )
        return accepted["id"], replayed

    def test_sources_and_search_validation(self):
        with self.assertRaises(ValidationError):
            AgentTaskCreate(question="   ", sources=["x"])
        with self.assertRaises(ValidationError):
            AgentTaskCreate(question="Q")
        with self.assertRaises(ValidationError):
            AgentTaskCreate(question="Q", sources=["x"], budget={})
        self.assertTrue(AgentTaskCreate(question="Q", allow_search=True).allow_search)

    def test_submit_replay_and_conflict(self):
        identity, replayed = self.submit()
        self.assertFalse(replayed)
        self.assertEqual(self.submit(), (identity, True))
        self.request = self.request.model_copy(update={"question": "Different"})
        with self.assertRaises(APIError) as caught:
            self.submit()
        self.assertEqual(caught.exception.status_code, 409)
        with self.sessions() as session:
            task = session.get(Task, identity)
            self.assertEqual(task.runner_type, "agent")
            self.assertNotIn("task_type", task.agent_input)
            self.assertNotIn("budget", task.agent_input)
            self.assertEqual(task.agent_input["task_id"], str(identity))
            self.assertIsNone(task.max_tokens)

    def test_user_scoped_idempotency(self):
        first, _ = self.submit()
        self.user = uuid4()
        second, _ = self.submit()
        self.assertNotEqual(first, second)

    def test_unconfigured_environment_does_not_create_task(self):
        with patch("app.tasks.agent.agent_available", return_value=False):
            with self.assertRaises(APIError) as caught:
                self.submit()
        self.assertEqual(caught.exception.error["code"], "RUNNER_NOT_CONFIGURED")
        with self.sessions() as session:
            self.assertIsNone(session.scalar(select(Task)))

    def test_completed_partial_and_failed_results_are_persisted(self):
        for reason in ("completed", "partial", "step_limit", "model_error"):
            identity, _ = self.submit(reason)
            self.assertEqual(claim_task(self.sessions, self.owner, "agent"), identity)
            self.assertTrue(
                complete_agent(
                    self.sessions, identity, self.owner, result(identity, reason)
                )
            )
            with self.sessions() as session:
                task = session.get(Task, identity)
                self.assertEqual(
                    task.status,
                    "succeeded" if reason in {"completed", "partial"} else "failed",
                )
                self.assertEqual(task.agent_result["stop_reason"], reason)
                self.assertEqual(task.tool_calls, 3)
                self.assertIsNone(task.input_tokens)

    def test_legacy_retry_uses_frozen_identity_before_current_runner_conversion(self):
        from app.api.schemas import TaskCreate
        from app.tasks.service import request_hash, submit_task

        request = TaskCreate(
            task_type="qa", question="Compare methods", paper_ids=[uuid4()]
        )
        identity, _ = self.submit()
        with self.sessions.begin() as session:
            task = session.get(Task, identity)
            task.runner_type = "mock"
            task.run_config = {"budget_mode": "automatic"}
            task.request_hash = request_hash(request, automatic=True)
        self.settings.task_runner = "agent"
        accepted, replayed = submit_task(
            self.sessions, self.settings, request, "fixture", user_id=self.user
        )
        self.assertTrue(replayed)
        self.assertEqual(accepted["id"], identity)
        changed = request.model_copy(update={"question": "Different"})
        with self.assertRaises(APIError) as caught:
            submit_task(
                self.sessions, self.settings, changed, "fixture", user_id=self.user
            )
        self.assertEqual(caught.exception.status_code, 409)

    def test_late_or_mismatched_result_cannot_be_written(self):
        identity, _ = self.submit()
        claim_task(self.sessions, self.owner, "agent")
        self.assertFalse(
            complete_agent(self.sessions, identity, uuid4(), result(identity))
        )
        with self.assertRaises(ValueError):
            complete_agent(self.sessions, identity, self.owner, result(uuid4()))
        with self.sessions() as session:
            self.assertIsNone(session.get(Task, identity).agent_result)


class AgentHTTPTests(AgentTaskTests):
    def setUp(self):
        super().setUp()
        from app.auth.dependencies import require_user
        from app.config import Settings
        from app.main import create_app
        from fastapi.testclient import TestClient

        self.app = create_app(
            Settings(
                database_url="postgresql+psycopg://fixture@127.0.0.1/fixture",
                task_monitor_enabled=False,
                agent_python=self.settings.agent_python,
            )
        )
        self.app.state.sessions = self.sessions
        self.app.dependency_overrides[require_user] = lambda: SimpleNamespace(
            id=self.user
        )
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def test_http_create_native_result_and_owner_scope(self):
        response = self.client.post("/api/v1/tasks", json=self.request.model_dump())
        self.assertEqual(response.status_code, 202, response.text)
        identity = UUID(response.json()["id"])
        detail = self.client.get(f"/api/v1/tasks/{identity}").json()
        self.assertEqual(detail["result_format"], "agent-v1")
        self.assertIsNone(detail["budget"]["max_tokens"])
        self.assertIsNone(
            self.client.get(f"/api/v1/tasks/{identity}/agent-result").json()
        )
        claim_task(self.sessions, self.owner, "agent")
        payload = result(identity, "partial")
        payload["configuration"] = {"api_key": "must-not-show", "temperature": 0}
        complete_agent(self.sessions, identity, self.owner, payload)
        public = self.client.get(f"/api/v1/tasks/{identity}/agent-result").json()
        self.assertEqual(public["stop_reason"], "partial")
        self.assertNotIn("configuration", public)
        self.assertEqual(
            self.client.get(f"/api/v1/tasks/{identity}/agent-trace").json()[
                "configuration"
            ]["api_key"],
            "[redacted]",
        )
        self.user = uuid4()
        for path in ("", "/agent-result", "/agent-trace"):
            self.assertEqual(
                self.client.get(f"/api/v1/tasks/{identity}{path}").status_code, 404
            )

    def test_failed_native_result_is_still_readable(self):
        identity, _ = self.submit()
        claim_task(self.sessions, self.owner, "agent")
        complete_agent(
            self.sessions, identity, self.owner, result(identity, "step_limit")
        )
        response = self.client.get(f"/api/v1/tasks/{identity}/agent-result")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["stop_reason"], "step_limit")

    def test_worker_runs_native_job(self):
        from app.workers.agent import AgentWorker

        identity, _ = self.submit()
        calls = []

        def run(payload, **kwargs):
            calls.append(payload)
            return result(identity)

        worker = AgentWorker(self.sessions, self.settings, runner=run)
        self.assertTrue(worker.run_once())
        with self.sessions() as session:
            self.assertEqual(session.get(Task, identity).status, "succeeded")
        self.assertEqual(len(calls), 1)
