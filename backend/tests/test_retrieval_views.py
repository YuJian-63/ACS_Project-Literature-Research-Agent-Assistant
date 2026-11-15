import unittest
from unittest.mock import Mock
from uuid import uuid4

from app.api.schemas import RetrievalDiagnostics
from app.api.views import task_view


class RetrievalViewTests(unittest.TestCase):
    def test_review_exposes_missing_dimensions_with_frozen_title(self):
        paper_id = str(uuid4())
        task = Mock(input_tokens=None, output_tokens=None, created_at=None, started_at=None, finished_at=None,
            error_code=None, workflow_version="langgraph-search-v1",
            run_config={"search_policy": {}, "review_policy": {"columns": [{"key": "limitations", "label": "局限性"}]}})
        task.run_config["search_policy"] = {"version": "fixture"}
        task.review_state = {"source_snapshot": {"papers": [{"paper_id": paper_id, "paper_title": "Frozen title"}]},
            "search": {"outcome": {"status": "partial", "papers": [{"paper_id": paper_id, "columns": ["limitations"]}]}}}
        retrieval = RetrievalDiagnostics.model_validate(task_view(task, [paper_id])["retrieval"])
        self.assertEqual(retrieval.papers[0].paper_title, "Frozen title")
        self.assertEqual(retrieval.papers[0].columns, ["局限性"])

    def test_old_diagnostic_has_empty_paper_gaps(self):
        result = RetrievalDiagnostics.model_validate({"status": "partial", "missing_aspects": ["Detailed results"]})
        self.assertEqual(result.papers, [])
        self.assertEqual(result.missing_aspects, ["Detailed results"])
