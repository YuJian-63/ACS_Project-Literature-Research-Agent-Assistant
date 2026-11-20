import unittest
from uuid import uuid4
from unittest.mock import MagicMock

from app.tasks.service import selected_paper_titles


class TaskPaperTitlesTests(unittest.TestCase):
    def test_groups_titles_preserving_selection_order_and_empty_tasks(self):
        first, second, a, b = [uuid4() for _ in range(4)]
        session = MagicMock()
        session.execute.return_value = [(first, b, 'Second paper'), (first, a, 'First paper')]
        result = selected_paper_titles(session, [first, second])
        self.assertEqual(result[first], [{'id': b, 'title': 'Second paper'}, {'id': a, 'title': 'First paper'}])
        self.assertEqual(result[second], [])
        statement = str(session.execute.call_args.args[0])
        self.assertIn('selection_order', statement)
        self.assertIn('papers.user_id = task_papers.user_id', statement)

    def test_empty_page_does_not_query(self):
        session = MagicMock()
        self.assertEqual(selected_paper_titles(session, []), {})
        session.execute.assert_not_called()
