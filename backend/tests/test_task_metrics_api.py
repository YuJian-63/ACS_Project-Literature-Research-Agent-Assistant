import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.auth.dependencies import require_user
from app.config import Settings
from app.main import create_app
from test_task_metrics import model_entry


class TaskMetricsAPITests(unittest.TestCase):
    def setUp(self):
        self.task_id = uuid4()
        settings = Settings(_env_file=None, database_url="postgresql+psycopg://offline@127.0.0.1/offline")
        app = create_app(settings)
        app.dependency_overrides[require_user] = lambda: SimpleNamespace(id=uuid4())
        self.session = MagicMock()
        self.session.__enter__.return_value = self.session
        self.session.scalar.return_value = None
        app.state.sessions = lambda: self.session
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        now = datetime.now(timezone.utc)
        self.task = SimpleNamespace(id=self.task_id, question="Explain", task_type="qa", workflow_type="baseline",
            runner_type="agent", status="succeeded", stage="done", error_code=None, error_message=None,
            created_at=now, updated_at=now, started_at=now, finished_at=now, max_steps=10, max_tokens=1000,
            timeout_seconds=180, model_id=None, workflow_version="test", prompt_version=None,
            dataset_version=None, input_tokens=10, output_tokens=5, model_calls=1, tool_calls=0,
            review_state={}, run_config={"agent_limits": {"max_steps": 10}}, last_event_seq=1)
        self.run = SimpleNamespace(dispatch_id=uuid4(), remote_job_id="123", stop_reason="completed", result={
            "task_id": str(self.task_id), "question": "Explain", "answer": "Answer", "stop_reason": "completed",
            "usage": {"agent_steps": 1, "model_calls": 1, "tool_calls": 0, "input_tokens": 10,
                "output_tokens": 5, "total_tokens": 15, "token_usage_complete": True}, "trace": [model_entry()]})
        self.session.get.return_value = self.run
        for target, value in (("app.api.tasks.get_task", self.task),
            ("app.api.tasks.selected_papers", {self.task_id: []}),
            ("app.api.agent_research.get_research", self.task),
            ("app.api.agent_research.research_references", {self.task_id: []})):
            patcher = patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def details(self):
        result = []
        for prefix in ("/api/v1/tasks", "/api/v1/agent-research"):
            response = self.client.get(f"{prefix}/{self.task_id}")
            self.assertEqual(response.status_code, 200, response.text)
            result.append(response.json()["metrics"])
        self.assertEqual(result[0], result[1])
        self.session.add.assert_not_called()
        self.session.commit.assert_not_called()
        return result[0]

    def test_detail_response_models_keep_all_metrics_and_original_fields(self):
        view = self.details()
        self.assertEqual(view["schema_version"], "task-metrics-v1")
        self.assertEqual(view["model_server"]["status"], "available")
        self.assertEqual(view["agent"]["total_tokens"], 15)
        self.assertEqual(view["evaluation"]["status"], "not_requested")
        self.assertEqual(view["model_server"]["gpus"][0]["sampled_at"], "2026-11-22T12:00:00Z")
        self.assertEqual(view["model_server"]["cache_hit_tokens"], 40)
        self.assertEqual(view["model_server"]["cache_query_tokens"], 100)
        self.assertEqual(view["model_server"]["cache_hit_ratio"], 0.4)
        self.assertTrue(view["model_server"]["cache_usage_complete"])
        self.assertEqual(view["model_server"]["requests"][0]["cache_hit_tokens"], 40)

    def test_queued_detail_returns_null_metrics(self):
        self.task.status = "queued"
        self.run.result = None
        self.run.stop_reason = None
        self.task.started_at = self.task.finished_at = None
        view = self.details()
        self.assertIsNone(view["agent"]["total_tokens"])
        self.assertEqual(view["model_server"]["status"], "unavailable")
        self.assertIsNone(view["model_server"]["cache_hit_tokens"])
        self.assertIsNone(view["model_server"]["cache_hit_ratio"])
        self.assertFalse(view["model_server"]["cache_usage_complete"])

    def test_details_return_tpot_from_historical_mean_itl_without_writing(self):
        capture = self.run.result["trace"][0]["response"]["response_metadata"]["server_metrics"]
        capture.pop("tpot_ms")
        capture["sources"].pop("tpot_ms")
        view = self.details()["model_server"]
        self.assertEqual(view["tpot_ms"]["mean"], 6)
        self.assertEqual(view["tpot_ms"]["source"], "metrics.mean_itl_ms")
        self.assertEqual(view["requests"][0]["tpot_ms"], 6)
        self.assertNotIn("tpot_ms", capture)

    def test_details_return_cache_from_saved_agent_usage_metadata(self):
        self.run.result["trace"] = [{"kind": "model", "response": {
            "usage_metadata": {"input_tokens": 100, "input_token_details": {"cache_read": 25}}}}]
        view = self.details()
        self.assertEqual(view["model_server"]["cache_hit_tokens"], 25)
        self.assertEqual(view["model_server"]["cache_hit_ratio"], 0.25)
        self.assertEqual(view["model_server"]["cache_measured_model_calls"], 1)
        self.assertTrue(view["model_server"]["cache_usage_complete"])

    def test_detail_response_keeps_scoring_dimensions(self):
        self.session.scalar.return_value = SimpleNamespace(id=uuid4(), status="succeeded", error_code=None,
            config={"provider": "deepseek", "model": "deepseek-chat", "rubric_version": "research-v1"},
            report={"assessment": "scored", "overall_score": 80,
                "dimensions": {key: {"score": 4, "reason": "Supported"} for key in (
                    "grounded_correctness", "citation_support", "task_completion", "analysis_quality", "clarity")}})
        view = self.details()
        self.assertEqual(view["evaluation"]["overall_score"], 80)
        self.assertEqual(view["evaluation"]["dimensions"]["citation_support"]["score"], 4)


if __name__ == "__main__":
    unittest.main()
