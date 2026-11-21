import unittest
from types import SimpleNamespace
from pydantic import ValidationError
from app.config import Settings
from app.db.base import Base
import app.db.models
from app.auth.security import cookie_name

class V3IsolationTests(unittest.TestCase):
    def test_schema_retains_v3_records_and_adds_agent_execution_tables(self):
        self.assertTrue({'tasks','task_papers','task_events','artifacts','citations','agent_runs'} <= set(Base.metadata.tables))
        self.assertIn('agent_research', Base.metadata.tables)

    def test_v2_database_is_rejected(self):
        with self.assertRaises(ValidationError):
            Settings(_env_file=None, database_url='postgresql+psycopg://localhost/literature_dev')

    def test_session_cookie_is_v3_only(self):
        self.assertEqual(cookie_name(SimpleNamespace(auth_cookie_secure=False)), 'lra_v3_session')

    def test_connection_query_cannot_override_the_database_target(self):
        for query in ('dbname=literature_dev', 'database=literature_dev', 'service=old', 'host=old', 'hostaddr=127.0.0.1', 'port=55433', 'user=other'):
            with self.subTest(query=query), self.assertRaises(ValidationError):
                Settings(_env_file=None, database_url='postgresql+psycopg://localhost/literature_v3?' + query)

    def test_default_storage_uses_v3_directory(self):
        from pathlib import Path
        settings = Settings(_env_file=None, database_url='postgresql+psycopg://localhost/literature_v3')
        self.assertEqual(settings.storage_root, Path(__file__).resolve().parents[1] / 'runtime/v3/storage')
