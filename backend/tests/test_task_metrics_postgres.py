import unittest
from datetime import timedelta

from sqlalchemy import func, select

import test_agent_postgres as fixtures
import test_evaluation_postgres as evaluation_fixtures
from test_evaluations import judge_report
from test_task_metrics import model_entry
from app.db.models import AgentRun, Task, TaskEvaluation


@unittest.skipUnless(fixtures.TEST_URL, "Set AGENT_TEST_DATABASE_URL to isolated agent_bridge_tests")
class TaskMetricsPostgresTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.AgentPostgresTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.AgentPostgresTests.tearDownClass.__func__)
    setUp = fixtures.AgentPostgresTests.setUp
    create_and_claim = fixtures.AgentPostgresTests.create_and_claim
    envelope = fixtures.AgentPostgresTests.envelope
    research_client = fixtures.AgentPostgresTests.research_client
    ready = evaluation_fixtures.EvaluationPostgresTests.ready
    enqueue = evaluation_fixtures.EvaluationPostgresTests.enqueue

    def detail_views(self, task_id):
        client = self.research_client()
        views = []
        for path in (f"/api/v1/tasks/{task_id}", f"/api/v1/agent-research/{task_id}"):
            response = client.get(path)
            self.assertEqual(response.status_code, 200, response.text)
            views.append(response.json()["metrics"])
        self.assertEqual(views[0], views[1])
        return views[0]

    def mark_unified(self, task_id):
        with self.sessions.begin() as session:
            task = session.get(Task, task_id)
            task.run_config = {**task.run_config, "interface": "agent-research-v1"}

    def test_details_match_latest_evaluation_and_preserve_native_result(self):
        task_id = self.ready()
        self.mark_unified(task_id)
        first_id = self.enqueue(task_id)
        self.settings.evaluation_model = "new-judge"
        latest_id = self.enqueue(task_id)
        with self.sessions.begin() as session:
            first = session.get(TaskEvaluation, first_id)
            latest = session.get(TaskEvaluation, latest_id)
            latest.created_at = first.created_at + timedelta(seconds=1)
            latest.status = "succeeded"
            latest.report = {**judge_report(), "overall_score": 74.0}
            run = session.get(AgentRun, task_id)
            run.result = {**run.result, "trace": [model_entry(), model_entry()],
                "usage": {**run.result["usage"], "agent_steps": 1, "input_tokens": 10,
                    "output_tokens": 5, "total_tokens": 15}}
        view = self.detail_views(task_id)
        self.assertEqual(view["evaluation"]["evaluation_id"], str(latest_id))
        self.assertEqual(view["evaluation"]["overall_score"], 74)
        self.assertEqual(view["evaluation"]["dimensions"]["grounded_correctness"]["score"], 4)
        self.assertEqual(view["agent"]["agent_steps"], 1)
        self.assertEqual(view["agent"]["total_tokens"], 15)
        self.assertEqual(view["model_server"]["ttft_ms"]["mean"], 24)
        self.assertEqual(view["model_server"]["status"], "available")
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(TaskEvaluation)), 2)
        native = self.research_client().get(f"/api/v1/tasks/{task_id}/agent-result").json()
        self.assertEqual(len(native["result"]["trace"]), 2)

    def test_pending_failed_and_insufficient_evidence_have_no_score(self):
        task_id = self.ready()
        self.mark_unified(task_id)
        evaluation_id = self.enqueue(task_id)
        for status in ("pending", "running", "failed", "skipped", "succeeded"):
            with self.subTest(status=status):
                with self.sessions.begin() as session:
                    row = session.get(TaskEvaluation, evaluation_id)
                    row.status = status
                    report = judge_report()
                    report.update(assessment="insufficient_evidence", overall_score=None)
                    for dimension in report["dimensions"].values():
                        dimension["score"] = None
                    row.report = report
                view = self.detail_views(task_id)
                self.assertEqual(view["evaluation"]["status"], status)
                self.assertIsNone(view["evaluation"]["overall_score"])
                self.assertTrue(all(item["score"] is None for item in view["evaluation"]["dimensions"].values()))

    def test_queued_reads_are_passive_and_owned(self):
        client = self.research_client()
        response = client.post("/api/v1/agent-research", json={"question": "Explain this paper"})
        self.assertEqual(response.status_code, 202, response.text)
        task_id = response.json()["task_id"]
        view = self.detail_views(task_id)
        self.assertEqual(view["evaluation"]["status"], "not_requested")
        self.assertIsNone(view["agent"]["agent_steps"])
        self.assertEqual(view["model_server"]["status"], "unavailable")
        foreign = self.research_client(self.other_user)
        for path in (f"/api/v1/tasks/{task_id}", f"/api/v1/agent-research/{task_id}"):
            self.assertEqual(foreign.get(path).status_code, 404)
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(TaskEvaluation)), 0)

    def test_failed_task_saved_usage_remains_available_without_telemetry(self):
        task_id = self.ready(reason="step_limit")
        self.mark_unified(task_id)
        view = self.detail_views(task_id)
        self.assertTrue(view["agent"]["available"])
        self.assertEqual(view["agent"]["model_calls"], 2)
        self.assertEqual(view["model_server"]["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
