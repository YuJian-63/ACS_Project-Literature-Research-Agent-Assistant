import importlib.util
import os
import re
import unittest
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError


BACKEND = Path(__file__).resolve().parents[1]
TEST_URL = os.environ.get("AGENT_MERGE_TEST_DATABASE_URL")


class MigrationGraphTests(unittest.TestCase):
    def test_main_and_agent_revisions_have_one_unique_head(self):
        config = Config(str(BACKEND / "alembic.ini"))
        script = ScriptDirectory.from_config(config)
        revisions = list(script.walk_revisions())
        self.assertEqual(len(revisions), len({revision.revision for revision in revisions}))
        self.assertEqual(script.get_heads(), ["20261121_0008"])
        self.assertEqual(script.get_revision("20261118_0006").path,
            str(BACKEND / "alembic/versions/20261118_0006_import_metadata.py"))


@unittest.skipUnless(TEST_URL, "Set AGENT_MERGE_TEST_DATABASE_URL to isolated agent_merge_tests")
class MergeMigrationPostgresTests(unittest.TestCase):
    def setUp(self):
        target = make_url(TEST_URL)
        if target.host != "127.0.0.1" or not re.fullmatch(r"agent_merge_tests_[0-9a-f]{32}", target.database or ""):
            raise RuntimeError("Use an isolated agent_merge_tests database on loopback")
        self.admin = create_engine(TEST_URL)
        self.schema = "merge_" + uuid4().hex
        with self.admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.engine = create_engine(TEST_URL, connect_args={"options": "-csearch_path=" + self.schema})
        self.config = Config(str(BACKEND / "alembic.ini"))

    def tearDown(self):
        self.engine.dispose()
        with self.admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        self.admin.dispose()

    def check_head(self, connection):
        self.assertEqual(connection.scalar(text("SELECT version_num FROM alembic_version")), "20261121_0008")
        self.assertIn("source_metadata", {column["name"] for column in inspect(connection).get_columns("paper_imports")})
        self.assertTrue(inspect(connection).has_table("agent_runs"))
        command.check(self.config)

    def test_clean_database_upgrade_and_safe_downgrade(self):
        with self.engine.connect() as connection:
            self.config.attributes["connection"] = connection
            command.upgrade(self.config, "head")
            self.check_head(connection)
            command.downgrade(self.config, "20261118_0006")
            self.assertFalse(inspect(connection).has_table("agent_runs"))
            self.assertIn("source_metadata", {column["name"] for column in inspect(connection).get_columns("paper_imports")})
            command.upgrade(self.config, "head")
            self.check_head(connection)

    def test_main_metadata_database_upgrade(self):
        with self.engine.connect() as connection:
            self.config.attributes["connection"] = connection
            command.upgrade(self.config, "20261118_0006")
            self.assertFalse(inspect(connection).has_table("agent_runs"))
            command.upgrade(self.config, "head")
            self.check_head(connection)

    def test_pdf_limit_upgrade_preserves_existing_paper_and_enforces_boundary(self):
        with self.engine.connect() as connection:
            self.config.attributes["connection"] = connection
            command.upgrade(self.config, "20261120_0007")
            user_id, paper_id = uuid4(), uuid4()
            connection.execute(text("INSERT INTO users (id, username, username_key, email, email_key, password_hash) "
                "VALUES (:id, 'pdffixture', 'pdffixture', 'pdf@example.com', 'pdf@example.com', 'unused')"), {"id": user_id})
            connection.execute(text("INSERT INTO papers (id, user_id, title, original_filename, storage_key, size_bytes, sha256) "
                "VALUES (:id, :user, 'Existing paper', 'existing.pdf', :key, 1024, :digest)"),
                {"id": paper_id, "user": user_id, "key": f"uploads/{paper_id}.pdf", "digest": "c" * 64})
            command.upgrade(self.config, "head")
            self.check_head(connection)
            self.assertEqual(connection.execute(text("SELECT title, original_filename, size_bytes, sha256 FROM papers WHERE id = :id"),
                {"id": paper_id}).one(), ("Existing paper", "existing.pdf", 1024, "c" * 64))
            connection.execute(text("UPDATE papers SET size_bytes = 52428800 WHERE id = :id"), {"id": paper_id})
            with self.assertRaises(IntegrityError), connection.begin_nested():
                connection.execute(text("UPDATE papers SET size_bytes = 52428801 WHERE id = :id"), {"id": paper_id})
            self.assertEqual(connection.scalar(text("SELECT size_bytes FROM papers WHERE id = :id"), {"id": paper_id}), 52_428_800)
            connection.execute(text("UPDATE papers SET size_bytes = 1024 WHERE id = :id"), {"id": paper_id})
            command.downgrade(self.config, "20261120_0007")
            with self.assertRaises(IntegrityError), connection.begin_nested():
                connection.execute(text("UPDATE papers SET size_bytes = 20971521 WHERE id = :id"), {"id": paper_id})
            command.upgrade(self.config, "head")
            self.check_head(connection)

    def test_historical_agent_database_upgrade_preserves_records(self):
        with self.engine.connect() as connection:
            self.config.attributes["connection"] = connection
            command.upgrade(self.config, "20261115_0005")
            migration_path = BACKEND / "alembic/versions/20261120_0007_agent_bridge.py"
            spec = importlib.util.spec_from_file_location("agent_merge_fixture", migration_path)
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
            connection.execute(text("ALTER TABLE paper_imports DROP COLUMN source_metadata"))
            user_id, task_id, dispatch_id = uuid4(), uuid4(), uuid4()
            connection.execute(text("INSERT INTO users (id, username, username_key, email, email_key, password_hash) "
                "VALUES (:id, 'mergefixture', 'mergefixture', 'merge@example.com', 'merge@example.com', 'unused')"), {"id": user_id})
            connection.execute(text("INSERT INTO tasks (id, user_id, task_type, runner_type, workflow_version, request_hash) "
                "VALUES (:id, :user, 'summary', 'agent', 'agent-io-v1', :digest)"),
                {"id": task_id, "user": user_id, "digest": "a" * 64})
            connection.execute(text("INSERT INTO agent_runs (task_id, dispatch_id, input_sha256, manifest) "
                "VALUES (:task, :dispatch, :digest, '{}'::jsonb)"),
                {"task": task_id, "dispatch": dispatch_id, "digest": "b" * 64})
            command.stamp(self.config, "20261118_0006")
            command.upgrade(self.config, "head")
            self.check_head(connection)
            self.assertEqual(connection.scalar(text("SELECT dispatch_id FROM agent_runs WHERE task_id = :task"), {"task": task_id}), dispatch_id)
            self.assertEqual(connection.scalar(text("SELECT runner_type FROM tasks WHERE id = :task"), {"task": task_id}), "agent")
