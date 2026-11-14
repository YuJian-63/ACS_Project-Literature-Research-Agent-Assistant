import os
import re
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.api.schemas import TaskCreate
from app.auth.security import csrf_token, token_hash
from app.config import Settings
from app.db.models import AuthSession, Base, Paper, PaperChunk, PaperImport, PaperSource, Task, TaskPaper, User
from app.main import create_app
from app.reset_data import planned_files, reset
from app.sources.arxiv import ArxivPaper, ArxivPage, DownloadReceipt
from app.sources.imports import claim_import, complete_import, fail_import, retry_import, staging_path, submit_import
from app.tasks.service import submit_task


class ResetFileTests(unittest.TestCase):
    def test_generated_only_and_unknown_file_refusal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            uploads = root / "uploads"
            uploads.mkdir()
            generated = uploads / f"{uuid4()}.pdf"
            generated.write_bytes(b"%PDF-fixture")
            self.assertEqual(planned_files(root), [generated])
            unknown = uploads / "precious.txt"
            unknown.write_text("keep")
            with self.assertRaises(ValueError):
                planned_files(root)
            self.assertTrue(generated.exists())
            self.assertTrue(unknown.exists())


TEST_URL = os.environ.get("OWNERSHIP_TEST_DATABASE_URL")


@unittest.skipUnless(TEST_URL, "Set OWNERSHIP_TEST_DATABASE_URL to isolated ownership_tests")
class OwnershipPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        target = make_url(TEST_URL)
        if target.host != "127.0.0.1" or not re.fullmatch(r"ownership_tests(?:_[0-9a-f]{32})?", target.database or ""):
            raise RuntimeError("Use isolated ownership_tests on loopback")
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
        self.root = Path(self.temporary.name).resolve()
        self.settings = Settings(_env_file=None, database_url=TEST_URL, storage_root=self.root,
            task_monitor_enabled=False, task_runner="mock", auth_rate_key="r" * 32,
            auth_csrf_key="c" * 32, arxiv_enabled=True, arxiv_contact_email="fixture@example.com")
        from cryptography.fernet import Fernet
        self.settings = self.settings.model_copy(update={"smtp_username": "fixture@qq.com", "smtp_from": "fixture@qq.com",
            "smtp_auth_code": __import__("pydantic").SecretStr("fixture-only"),
            "mail_outbox_key": __import__("pydantic").SecretStr(Fernet.generate_key().decode())})
        self.users = []
        self.tokens = []
        now = datetime.now(timezone.utc)
        from datetime import timedelta
        with self.sessions.begin() as session:
            for index in range(2):
                user = User(id=uuid4(), username=f"fixture{index}", username_key=f"fixture{index}",
                    email=f"fixture{index}@example.com", email_key=f"fixture{index}@example.com",
                    password_hash="unused", status="active", email_verified_at=now)
                session.add(user)
                session.flush()
                raw = "fixture-session-token-" + str(uuid4())
                session.add(AuthSession(id=uuid4(), user_id=user.id, token_hash=token_hash(raw), auth_version=1,
                    expires_at=now + timedelta(days=1)))
                self.users.append(user.id)
                self.tokens.append(raw)
        self.clients = []
        application = create_app(self.settings, self.engine, arxiv_client=self.arxiv_fixture())
        for raw in self.tokens:
            client = TestClient(application)
            client.__enter__()
            client.cookies.set("lra_dev_session", raw)
            client.headers.update({"Origin": self.settings.frontend_public_url, "X-CSRF-Token": csrf_token(self.settings, raw)})
            self.clients.append(client)

    def arxiv_fixture(self):
        from unittest.mock import Mock
        source = Mock()
        source.search.return_value = ArxivPage(total=1, offset=0, limit=10, items=[ArxivPaper(
            external_id="1706.03762v1", title="Fixture paper", authors=["Fixture author"],
            abstract="Fixture abstract", published_at=datetime.now(timezone.utc), source_updated_at=datetime.now(timezone.utc),
            categories=["cs.SE"])])
        return source

    def tearDown(self):
        for client in self.clients:
            client.__exit__(None, None, None)
        self.temporary.cleanup()

    def upload(self, index=0):
        response = self.clients[index].post("/api/v1/papers", files={"file": ("fixture.pdf", b"%PDF-fixture", "application/pdf")})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def task(self, paper, index=0, key="same-key"):
        return self.clients[index].post("/api/v1/tasks", json={"task_type": "summary", "question": "Summarize", "paper_ids": [paper]}, headers={"Idempotency-Key": key})

    def test_single_paper_tasks_freeze_server_budget_and_replay_ignores_client_budget(self):
        from app.api.views import task_view
        from app.tasks.lifecycle import claim_task
        from app.workers.research import load_research_job
        self.settings.task_runner = "langgraph"
        self.settings.llm_base_url = "https://fixture.invalid"
        self.settings.llm_model_id = "fixture"
        from pydantic import SecretStr
        self.settings.llm_api_key = SecretStr("fixture-key")
        self.settings.user_active_tasks = 10
        paper_id = UUID(self.upload())
        with self.sessions.begin() as session:
            paper = session.get(Paper, paper_id)
            paper.status = "ready"
            paper.page_count = 1
            paper.parser_version = "fixture"
            session.add(PaperChunk(paper_id=paper_id, chunk_index=0, page_number=1,
                content="method and results " * 500, content_sha256="b" * 64, parser_version="fixture"))
        for task_type in ("summary", "qa"):
            request = TaskCreate(task_type=task_type, question="method", paper_ids=[paper_id],
                budget={"max_steps": 1, "max_tokens": 1, "timeout_seconds": 1})
            accepted, replayed = submit_task(self.sessions, self.settings, request, task_type, user_id=self.users[0])
            self.assertFalse(replayed)
            with self.sessions() as session:
                task = session.get(Task, accepted["id"])
                self.assertEqual(task_view(task, [paper_id])["budget_mode"], "automatic")
                self.assertGreater(task.max_tokens, 1)
                self.assertGreater(task.timeout_seconds, 1)
                frozen_evidence = task.review_state["evidence"]
                frozen_budget = task.max_tokens
                self.assertGreater(task.run_config["max_output_tokens"], 2048)
            request.budget.max_tokens = 100000
            self.settings.research_output_tokens = 1024
            repeated, replayed = submit_task(self.sessions, self.settings, request, task_type, user_id=self.users[0])
            self.assertTrue(replayed)
            self.assertEqual(repeated["id"], accepted["id"])
            with self.sessions() as session:
                self.assertEqual(session.get(Task, accepted["id"]).max_tokens, frozen_budget)
            self.settings.research_output_tokens = 8192
            with self.sessions.begin() as session:
                session.add(PaperChunk(paper_id=paper_id, chunk_index=1 if task_type == "summary" else 2,
                    page_number=1, content="New method evidence after submission.", content_sha256="c" * 64, parser_version="fixture"))
            owner = uuid4()
            claim_task(self.sessions, owner, "langgraph")
            job = load_research_job(self.sessions, accepted["id"])
            self.assertEqual([chunk.model_dump() for chunk in job.evidence], frozen_evidence)
            from unittest.mock import Mock
            from app.research.model_client import ModelCompletion
            from app.workers.research import RunnerWorker
            model = Mock()
            model.complete.return_value = ModelCompletion('{"paragraphs":[{"content_markdown":"Supported method.","evidence_ids":["E1"]}]}', 100, 50, "stop")
            worker = RunnerWorker(self.sessions, self.settings, model_factory=lambda *args: model)
            worker.owner = owner
            worker.execute(accepted["id"])
            with self.sessions() as session:
                task = session.get(Task, accepted["id"])
                self.assertEqual(task.status, "succeeded", task.error_message)
            self.assertEqual(model.complete.call_args.kwargs["max_tokens"], job.max_output_tokens)

    def test_mock_budget_is_automatic_and_legacy_replay_still_checks_manual_budget(self):
        from app.api.views import task_view
        from app.errors import APIError
        from app.tasks.service import request_hash
        request = TaskCreate(task_type="summary", paper_ids=[self.upload()],
            budget={"max_steps": 1, "max_tokens": 1, "timeout_seconds": 1})
        accepted, _ = submit_task(self.sessions, self.settings, request, "auto-mock", user_id=self.users[0])
        with self.sessions.begin() as session:
            task = session.get(Task, accepted["id"])
            self.assertEqual(task_view(task, request.paper_ids)["budget_mode"], "automatic")
            self.assertEqual(task.max_steps, 2)
            task.run_config = {"mock_step_delay_seconds": 0}
            task.request_hash = request_hash(request)
        request.budget.max_tokens = 2
        with self.assertRaises(APIError) as caught:
            submit_task(self.sessions, self.settings, request, "auto-mock", user_id=self.users[0])
        self.assertEqual(caught.exception.error["code"], "IDEMPOTENCY_CONFLICT")

    def test_reference_sql_matches_current_metadata(self):
        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext
        script = (Path(__file__).resolve().parents[1] / "sql/schema.sql").read_text(encoding="utf-8")
        script = script.removeprefix("BEGIN;").rsplit("COMMIT;", 1)[0]
        with self.engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text("CREATE SCHEMA reference_schema"))
                connection.execute(text("SET LOCAL search_path TO reference_schema"))
                connection.exec_driver_sql(script)
                context = MigrationContext.configure(connection, opts={"compare_type": True, "compare_server_default": True})
                self.assertEqual(compare_metadata(context, Base.metadata), [])
                self.assertEqual(connection.scalar(text("SELECT count(*) FROM source_request_gates")), 1)
            finally:
                transaction.rollback()

    def test_every_private_route_requires_session(self):
        with TestClient(create_app(self.settings, self.engine)) as client:
            for path in ("papers", "tasks", "paper-imports", "paper-search?q=test"):
                result = client.get("/api/v1/" + path)
                self.assertEqual(result.status_code, 401)
                self.assertEqual(result.headers.get("cache-control"), "no-store")
            self.assertEqual(client.get("/health").status_code, 200)

    def test_cross_user_lists_ids_files_tasks_events_artifacts_are_private(self):
        paper = self.upload()
        result = self.task(paper)
        self.assertEqual(result.status_code, 202, result.text)
        identity = result.json()["id"]
        other = self.clients[1]
        for path in (f"papers/{paper}", f"papers/{paper}/file", f"tasks/{identity}", f"tasks/{identity}/events", f"tasks/{identity}/artifacts"):
            self.assertEqual(other.get("/api/v1/" + path).status_code, 404, path)
        for path in ("papers", "tasks", "paper-imports"):
            self.assertEqual(other.get("/api/v1/" + path).json()["total"], 0)
        self.assertEqual(self.task(paper, index=1).status_code, 404)
        self.assertEqual(self.clients[0].get(f"/api/v1/papers/{paper}/file").content, b"%PDF-fixture")

    def test_same_key_is_scoped_replay_does_not_consume_quota(self):
        first = self.upload()
        second = self.upload(1)
        accepted = self.task(first)
        replay = self.task(first)
        other = self.task(second, index=1)
        self.assertEqual(accepted.status_code, 202)
        self.assertEqual(replay.json()["id"], accepted.json()["id"])
        self.assertEqual(other.status_code, 202)
        self.assertNotEqual(other.json()["id"], accepted.json()["id"])
        self.assertEqual(self.task(first, key="second").status_code, 202)
        self.assertEqual(self.task(first, key="third").status_code, 429)
        self.assertEqual(self.task(first).status_code, 202)

    def test_daily_limit_counts_only_new_tasks_and_replays_remain_available(self):
        paper = self.upload()
        self.settings.user_daily_tasks = 1
        first = self.task(paper)
        self.assertEqual(first.status_code, 202)
        rejected = self.task(paper, key="another-key")
        self.assertEqual(rejected.status_code, 429)
        self.assertEqual(rejected.json()["error"]["code"], "DAILY_TASK_LIMIT")
        self.assertEqual(self.task(paper).json()["id"], first.json()["id"])

    def test_concurrent_imports_enforce_capacity_without_charging_replay(self):
        def submit(index):
            from app.errors import APIError
            try:
                return submit_import(self.sessions, "arxiv", f"1706.03762v{index + 1}", user_id=self.users[0], settings=self.settings)
            except APIError as error:
                return error.status_code
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(submit, range(4)))
        winners = [result for result in results if isinstance(result, dict)]
        self.assertEqual(len(winners), 2)
        self.assertEqual(results.count(429), 2)
        replay = submit_import(self.sessions, "arxiv", winners[0]["external_id"], user_id=self.users[0], settings=self.settings)
        self.assertEqual(replay["id"], winners[0]["id"])

    def test_concurrent_tasks_share_one_user_quota_lock(self):
        paper = self.upload()
        body = TaskCreate(task_type="summary", question="Summarize", paper_ids=[paper])
        def submit(index):
            from app.errors import APIError
            try:
                return submit_task(self.sessions, self.settings, body, str(index), user_id=self.users[0])[0]
            except APIError as error:
                return error.status_code
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(submit, range(4)))
        self.assertEqual(sum(isinstance(result, dict) for result in results), 2)
        self.assertEqual(results.count(429), 2)

    def test_import_identity_cache_annotations_and_retry_are_scoped(self):
        body = {"provider": "arxiv", "external_id": "1706.03762v1"}
        first = self.clients[0].post("/api/v1/paper-imports", json=body)
        self.assertEqual(first.status_code, 202, first.text)
        identity = first.json()["id"]
        self.assertEqual(self.clients[1].get(f"/api/v1/paper-imports/{identity}").status_code, 404)
        self.assertEqual(self.clients[1].post(f"/api/v1/paper-imports/{identity}/retry", json={"expected_attempt": 1}).status_code, 404)
        self.assertEqual(self.clients[0].get("/api/v1/paper-search?q=fixture").json()["items"][0]["import_id"], identity)
        self.assertIsNone(self.clients[1].get("/api/v1/paper-search?q=fixture").json()["items"][0]["import_id"])
        second = self.clients[1].post("/api/v1/paper-imports", json=body)
        self.assertEqual(second.status_code, 202)
        self.assertNotEqual(second.json()["id"], identity)
        self.assertEqual(self.clients[0].post("/api/v1/paper-imports", json=body).json()["id"], identity)

    def test_mutations_reject_missing_csrf_and_wrong_origin(self):
        client = self.clients[0]
        client.headers.pop("X-CSRF-Token")
        self.assertEqual(client.post("/api/v1/papers", files={"file": ("fixture.pdf", b"%PDF-fixture")}).status_code, 403)
        client.headers["X-CSRF-Token"] = csrf_token(self.settings, self.tokens[0])
        client.headers["Origin"] = "https://evil.example"
        self.assertEqual(client.post("/api/v1/papers", files={"file": ("fixture.pdf", b"%PDF-fixture")}).status_code, 403)

    def test_database_rejects_cross_owner_source_and_task_paper(self):
        paper = UUID(self.upload())
        task = UUID(self.task(str(paper)).json()["id"])
        other_paper = UUID(self.upload(1))
        other_task = UUID(self.task(str(other_paper), index=1).json()["id"])
        with self.sessions() as session:
            paper_sha = session.get(Paper, paper).sha256
            other_sha = session.get(Paper, other_paper).sha256
        with self.assertRaises(IntegrityError), self.sessions.begin() as session:
            session.add(PaperSource(paper_id=paper, user_id=self.users[1], provider="arxiv", external_id="1706.03762v1", source_metadata={}))
        with self.assertRaises(IntegrityError), self.sessions.begin() as session:
            session.add(TaskPaper(task_id=other_task, paper_id=paper, user_id=self.users[1], paper_sha256=paper_sha, selection_order=1))
        with self.assertRaises(IntegrityError), self.sessions.begin() as session:
            session.add(TaskPaper(task_id=task, paper_id=other_paper, user_id=self.users[1], paper_sha256=other_sha, selection_order=1))

    def test_real_auth_router_register_verify_login_and_reset(self):
        from app.auth.mail import decrypt_payload
        from app.db.models import AuthEmailToken, AuthMailOutbox
        from app.auth.security import cookie_name
        from urllib.parse import unquote
        client = self.clients[0]
        password = "a long fixture password"
        credentials = {"username": "RegisteredUser", "email": "new@example.com", "password": password}
        response = client.post("/api/v1/auth/register", json=credentials)
        self.assertEqual(response.status_code, 202, response.text)
        def latest(purpose):
            with self.sessions() as session:
                mail = session.scalar(select(AuthMailOutbox).join(AuthEmailToken, AuthEmailToken.id == AuthMailOutbox.token_id)
                    .where(AuthEmailToken.purpose == purpose).order_by(AuthMailOutbox.created_at.desc()))
                body = decrypt_payload(self.settings, mail.payload_ciphertext)["body"]
                return unquote(body.split("#token=", 1)[1].split()[0])
        self.assertEqual(client.post("/api/v1/auth/verify-email", json={"token": latest("verify_email"), "password": password}).status_code, 200)
        response = client.post("/api/v1/auth/login", json={"username": "registereduser", "password": password})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        csrf = response.json()["csrf_token"]
        client.headers["X-CSRF-Token"] = csrf
        raw = response.cookies[cookie_name(self.settings)]
        client.cookies.clear()
        client.cookies.set(cookie_name(self.settings), raw, domain="testserver.local", path="/")
        self.assertEqual(client.get("/api/v1/auth/me").json()["user"]["username"], "RegisteredUser")
        self.upload()
        self.assertEqual(client.get("/api/v1/papers").json()["total"], 1)
        with self.sessions.begin() as session:
            session.execute(text("UPDATE auth_rate_buckets SET expires_at=clock_timestamp()-interval '1 second'"))
        self.assertEqual(client.post("/api/v1/auth/forgot-password", json={"email": "new@example.com"}).status_code, 202)
        token = latest("reset_password")
        response = client.post("/api/v1/auth/reset-password", json={"token": token, "password": "a different long password"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(client.get("/api/v1/papers").status_code, 401)
        self.assertEqual(client.post("/api/v1/auth/reset-password", json={"token": token, "password": "another long password"}).status_code, 400)

    def test_import_worker_inherits_owner_and_retry_replays_at_capacity(self):
        import hashlib
        result = submit_import(self.sessions, "arxiv", "1706.03762v1", user_id=self.users[0], settings=self.settings)
        job = claim_import(self.sessions, uuid4())
        self.assertTrue(fail_import(self.sessions, job, "FIXTURE", "retryable fixture", True))
        retried = retry_import(self.sessions, job.import_id, 1, user_id=self.users[0], settings=self.settings)
        submit_import(self.sessions, "arxiv", "1706.03762v2", user_id=self.users[0], settings=self.settings)
        self.assertEqual(retry_import(self.sessions, job.import_id, 1, user_id=self.users[0], settings=self.settings)["attempt"], 2)
        self.assertEqual(retried["attempt"], 2)
        job = claim_import(self.sessions, uuid4())
        data = b"%PDF-fixture-import"
        staged = staging_path(self.root, job)
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(data)
        source = self.arxiv_fixture().search.return_value.items[0]
        receipt = DownloadReceipt(size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        self.assertTrue(complete_import(self.sessions, job, source, receipt, root=self.root))
        with self.sessions() as session:
            paper = session.get(Paper, job.import_id)
            self.assertEqual(paper.user_id, self.users[0])
            self.assertEqual(paper.source.user_id, self.users[0])
        self.assertEqual(self.clients[1].get(f"/api/v1/papers/{job.import_id}/file").status_code, 404)

    def test_successful_reset_preserves_schema_and_unrelated_storage(self):
        paper = self.upload()
        unrelated = self.root / "keep.txt"
        unrelated.write_text("keep")
        for client in self.clients:
            client.__exit__(None, None, None)
        self.clients = []
        self.engine.dispose()
        result = reset(self.settings, database=make_url(TEST_URL).database, storage=self.root, execute=True)
        self.assertTrue(result["executed"])
        self.assertEqual(result["files"], 1)
        self.assertFalse((self.root / "uploads" / f"{paper}.pdf").exists())
        self.assertTrue(unrelated.exists())
        from app.sources.access import acquire_source_permit, release_source_permit
        permit = acquire_source_permit(self.sessions, "arxiv")
        self.assertIsNotNone(permit, "Reset must restore the shared source gate seed")
        release_source_permit(self.sessions, permit)
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(text("SELECT version_num FROM alembic_version")), "20261114_0004")
            self.assertEqual(connection.scalar(text("SELECT count(*) FROM users")), 0)
            self.assertEqual(connection.scalar(text("SELECT count(*) FROM papers")), 0)

    def test_import_completion_does_not_deadlock_with_retry_quota_lock(self):
        import hashlib
        from threading import Event
        from sqlalchemy import event
        from sqlalchemy.exc import SQLAlchemyError
        from app.errors import APIError
        submit_import(self.sessions, "arxiv", "1706.03762v1", user_id=self.users[0], settings=self.settings)
        job = claim_import(self.sessions, uuid4())
        staged = staging_path(self.root, job)
        staged.parent.mkdir(parents=True, exist_ok=True)
        data = b"%PDF-lock-fixture"
        staged.write_bytes(data)
        receipt = DownloadReceipt(size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        source = self.arxiv_fixture().search.return_value.items[0]
        paper_insert, quota_locked = Event(), Event()
        def before_execute(connection, cursor, statement, parameters, context, executemany):
            if statement.startswith("INSERT INTO papers "):
                paper_insert.set()
                if not quota_locked.wait(timeout=5):
                    raise TimeoutError("Retry did not acquire its quota lock")
        def after_execute(connection, cursor, statement, parameters, context, executemany):
            if "FROM users" in statement and "FOR " in statement:
                quota_locked.set()
        def complete():
            try:
                return complete_import(self.sessions, job, source, receipt, root=self.root)
            except SQLAlchemyError:
                return "database-lock-failure"
        def retry():
            try:
                retry_import(self.sessions, job.import_id, 1, user_id=self.users[0], settings=self.settings)
                return 200
            except APIError as error:
                return error.status_code
            except SQLAlchemyError:
                return "database-lock-failure"
        event.listen(self.engine, "before_cursor_execute", before_execute)
        event.listen(self.engine, "after_cursor_execute", after_execute)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                completion = pool.submit(complete)
                self.assertTrue(paper_insert.wait(timeout=5))
                retried = pool.submit(retry)
                self.assertIs(completion.result(timeout=10), True)
                self.assertEqual(retried.result(timeout=10), 409)
        finally:
            event.remove(self.engine, "before_cursor_execute", before_execute)
            event.remove(self.engine, "after_cursor_execute", after_execute)

    def test_reset_guards_leave_files_and_schema_intact(self):
        paper = self.upload()
        with self.assertRaises(ValueError):
            reset(self.settings, database="wrong", storage=self.root, execute=True)
        self.assertTrue((self.root / "uploads" / f"{paper}.pdf").exists())
        with self.assertRaises(ValueError):
            reset(self.settings, database=make_url(TEST_URL).database, storage=self.root, execute=True)
        self.assertEqual(self.clients[0].get("/api/v1/papers").json()["total"], 1)


def run_postgres_tests():
    settings = Settings()
    base = make_url(settings.database_url.get_secret_value())
    if base.host != "127.0.0.1":
        raise RuntimeError("Native tests require a loopback PostgreSQL server")
    database = "ownership_tests_" + uuid4().hex
    target = base.set(database=database)
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    created = False
    try:
        with admin.connect() as connection:
            version = connection.scalar(text("SELECT version()"))
            if "PGlite" in version:
                raise RuntimeError("Native PostgreSQL required")
            connection.exec_driver_sql('CREATE DATABASE "' + database + '"')
            created = True
        environment = dict(os.environ, OWNERSHIP_TEST_DATABASE_URL=target.render_as_string(hide_password=False))
        return subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "-v"], env=environment, timeout=120).returncode
    finally:
        if created:
            with admin.connect() as connection:
                connection.exec_driver_sql('DROP DATABASE "' + database + '" WITH (FORCE)')
        admin.dispose()


if __name__ == "__main__":
    if sys.argv[1:] == ["--postgres"]:
        raise SystemExit(run_postgres_tests())
    unittest.main()
