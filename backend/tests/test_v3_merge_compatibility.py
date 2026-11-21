"""Regression checks for the v3/main boundary; no network or database writes."""
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from app.api.agent_research import get_record, delete_record, list_records
from app.api.agent_research_schemas import AgentResearchRecord
from app.api.papers import delete_paper
from app.config import Settings
from app.errors import APIError
from app.main import create_app


class V3MergeCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.session = MagicMock()
        @contextmanager
        def scope():
            yield self.session
        class Sessions:
            def __call__(inner): return scope()
            def begin(inner): return scope()
        self.request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
        self.request.app.state.sessions = Sessions()
        self.user = SimpleNamespace(id=uuid4())
        self.identifier = uuid4()
        self.previous = SimpleNamespace(id=self.identifier, question='Existing research',
            status='succeeded', result={'answer': 'Preserved answer'}, error=None)

    def test_application_checks_the_isolated_v3_migration_head(self):
        settings = Settings(_env_file=None, database_url='postgresql://unused@localhost/literature_v3_test_unused')
        app = create_app(settings)
        self.assertEqual(app.state.migration_heads, {'v3_0002'})
        self.assertNotIn('/api/v1/tasks', app.openapi()['paths'])

    def test_existing_v3_result_is_readable_through_unified_contract(self):
        self.session.scalar.return_value = self.previous
        self.session.execute.return_value = []
        record = AgentResearchRecord.model_validate(get_record(self.identifier, self.request, self.user))
        self.assertEqual(record.result.answer, 'Preserved answer')
        self.assertEqual(record.result.task_id, str(self.identifier))
        self.assertEqual(record.result.question, 'Existing research')

    def test_existing_v3_record_deletion_and_running_protection(self):
        self.session.scalar.return_value = self.previous
        self.assertEqual(delete_record(self.identifier, self.request, self.user).status_code, 204)
        self.session.delete.assert_called_once_with(self.previous)
        self.session.delete.reset_mock()
        self.previous.status = 'running'
        with self.assertRaises(APIError):
            delete_record(self.identifier, self.request, self.user)
        self.session.delete.assert_not_called()

    def test_list_includes_both_storage_generations_in_one_page(self):
        current = uuid4()
        now = datetime.now(timezone.utc)
        rows = [SimpleNamespace(id=current, question='New', status='queued', created_at=now, legacy=False),
            SimpleNamespace(id=self.identifier, question='Existing', status='succeeded', created_at=now, legacy=True)]
        page = MagicMock()
        page.all.return_value = rows
        self.session.scalar.return_value = 2
        self.session.execute.side_effect = [page, [], []]
        result = list_records(self.request, self.user, limit=20, offset=0)
        self.assertEqual(result['total'], 2)
        self.assertEqual([item['id'] for item in result['items']], [current, self.identifier])

    def test_existing_v3_reference_still_blocks_paper_deletion(self):
        self.session.scalar.side_effect = [SimpleNamespace(id=self.identifier), None, self.identifier]
        with self.assertRaises(APIError) as raised:
            delete_paper(self.request, self.identifier, self.user)
        self.assertEqual(raised.exception.code if hasattr(raised.exception, 'code') else raised.exception.error['code'], 'PAPER_IN_USE')
        self.session.delete.assert_not_called()
