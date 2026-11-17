"""Native isolated PostgreSQL acceptance; never use an application database."""

import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from app.api.schemas import AgentTaskCreate
from app.config import Settings
from app.db.models import Task, User
from app.tasks.agent import complete_agent, submit_agent_task
from app.tasks.lifecycle import claim_task
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

URL = os.environ.get("AGENT_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not URL,
    reason="Set AGENT_TEST_DATABASE_URL to dedicated agent_tests on private socket port55437",
)


def test_native_migration_and_agent_transactions():
    url = make_url(URL)
    if (
        url.database != "agent_tests"
        or url.query.get("port") != "55437"
        or not str(url.query.get("host", "")).startswith("/private/tmp/agent-v1-pg.")
    ):
        raise RuntimeError("Refused non-isolated Agent test database")
    engine = create_engine(URL)
    sessions = sessionmaker(engine, expire_on_commit=False)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    try:
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            command.check(config)
        user_id = uuid4()
        with sessions.begin() as session:
            session.add(
                User(
                    id=user_id,
                    username="agent_" + user_id.hex[:12],
                    username_key="agent_" + user_id.hex[:12],
                    email=user_id.hex + "@example.com",
                    email_key=user_id.hex + "@example.com",
                    password_hash="unused",
                    status="active",
                    email_verified_at=datetime.now(timezone.utc),
                )
            )
        settings = Settings(
            database_url=URL,
            agent_python=os.environ.get(
                "AGENT_TEST_PYTHON", "/private/tmp/agent-v1-env/bin/python"
            ),
        )
        request = AgentTaskCreate(question="Explain method", sources=["1706.03762v7"])
        identity = None
        for reason in ("completed", "partial", "step_limit"):
            key = uuid4().hex
            accepted, replay = submit_agent_task(
                sessions, settings, request, key, user_id=user_id
            )
            identity = accepted["id"]
            assert not replay
            assert submit_agent_task(sessions, settings, request, key, user_id=user_id)[
                1
            ]
            owner = uuid4()
            assert claim_task(sessions, owner, "agent") == identity
            native = dict(
                task_id=str(identity),
                question=request.question,
                answer="Supported answer [arxiv:1706.03762v7:p1:c1]",
                comparison_table="",
                citations=[
                    dict(
                        chunk_id="arxiv:1706.03762v7:p1:c1",
                        source_id="arxiv:1706.03762v7",
                        paper_id="arxiv:1706.03762",
                        page=1,
                        source_text="Original source",
                        url="https://arxiv.org/abs/1706.03762v7",
                        title="Fixture",
                    )
                ],
                unresolved=["Incomplete"] if reason == "partial" else [],
                stop_reason=reason,
                usage=dict(
                    agent_steps=2,
                    model_calls=3,
                    tool_calls=1,
                    input_tokens=100,
                    output_tokens=20,
                    total_tokens=120,
                    token_usage_complete=True,
                    elapsed_seconds=1,
                ),
                trace=[],
                errors=[],
                sources=[],
                configuration={},
            )
            assert not complete_agent(sessions, identity, uuid4(), native)
            assert complete_agent(sessions, identity, owner, native)
            with sessions() as session:
                task = session.get(Task, identity)
                assert task.max_tokens is None
                assert task.status == (
                    "succeeded" if reason in {"completed", "partial"} else "failed"
                )
                assert task.agent_result["stop_reason"] == reason
                assert task.tool_calls == 1
        # Legacy paper_ids requests can switch to Agent without requiring parsed chunks.
        from app.api.schemas import TaskCreate
        from app.db.models import Paper, PaperSource
        from app.tasks.service import submit_task

        paper_id = uuid4()
        with sessions.begin() as session:
            session.add(
                Paper(
                    id=paper_id,
                    user_id=user_id,
                    title="Fixture",
                    original_filename="fixture.pdf",
                    storage_key=f"uploads/{paper_id}.pdf",
                    size_bytes=100,
                    sha256="a" * 64,
                    status="uploaded",
                )
            )
            session.flush()
            session.add(
                PaperSource(
                    user_id=user_id,
                    paper_id=paper_id,
                    provider="arxiv",
                    external_id="1706.03762v7",
                    source_metadata={},
                )
            )
        legacy = TaskCreate(task_type="summary", paper_ids=[paper_id])
        legacy_settings = settings.model_copy(update={"task_runner": "agent"})
        key = uuid4().hex
        converted, _ = submit_task(
            sessions, legacy_settings, legacy, key, user_id=user_id
        )
        with sessions() as session:
            converted_task = session.get(Task, converted["id"])
            assert converted_task.agent_input["sources"] == ["1706.03762v7"]
            converted_question = converted_task.question
        assert submit_task(sessions, settings, legacy, key, user_id=user_id)[1]
        owner = uuid4()
        assert claim_task(sessions, owner, "agent") == converted["id"]
        complete_agent(
            sessions,
            converted["id"],
            owner,
            dict(
                native,
                task_id=str(converted["id"]),
                question=converted_question,
                stop_reason="completed",
                unresolved=[],
            ),
        )
        # Real authentication, CSRF, quota, queue/Worker and native result HTTP path.
        from datetime import timedelta
        from fastapi.testclient import TestClient
        from app.auth.security import csrf_token, token_hash
        from app.db.models import AuthSession
        from app.main import create_app
        from app.workers.agent import AgentWorker

        raw = "fixture-agent-session-" + uuid4().hex
        with sessions.begin() as session:
            session.add(
                AuthSession(
                    id=uuid4(),
                    user_id=user_id,
                    token_hash=token_hash(raw),
                    auth_version=1,
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                )
            )
        http_settings = Settings(
            database_url=URL,
            agent_python=settings.agent_python,
            task_monitor_enabled=False,
            auth_rate_key="r" * 32,
            auth_csrf_key="c" * 32,
        )
        application = create_app(http_settings)
        application.state.sessions = sessions
        with TestClient(application) as client:
            # TestClient lifespan sets its own engine; replace the sessions with our isolated fixture.
            application.state.sessions = sessions
            client.cookies.set("lra_dev_session", raw)
            client.headers.update(
                {
                    "Origin": http_settings.frontend_public_url,
                    "X-CSRF-Token": csrf_token(http_settings, raw),
                }
            )
            response = client.post(
                "/api/v1/tasks",
                json=request.model_dump(),
                headers={"Idempotency-Key": uuid4().hex},
            )
            assert response.status_code == 202, response.text
            http_id = response.json()["id"]

            def offline_runner(task, **kwargs):
                payload = dict(
                    native,
                    task_id=task["task_id"],
                    question=task["question"],
                    stop_reason="completed",
                    unresolved=[],
                )
                return payload

            worker = AgentWorker(sessions, http_settings, runner=offline_runner)
            assert worker.run_once()
            assert (
                client.get(f"/api/v1/tasks/{http_id}").json()["status"] == "succeeded"
            )
            output = client.get(f"/api/v1/tasks/{http_id}/agent-result")
            assert output.status_code == 200
            assert (
                output.json()["citations"][0]["chunk_id"] == "arxiv:1706.03762v7:p1:c1"
            )
            assert "trace" not in output.json()
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            with pytest.raises(Exception, match="Refusing downgrade"):
                command.downgrade(config, "20261115_0005")
            connection.rollback()
    finally:
        engine.dispose()
