import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from app.agent_bridge.contracts import ResearchOptions
from app.agent_bridge.policy import build_manifest, build_research_manifest
from app.agent_bridge.submission import create_research_task
from app.config import Settings


class AgentOutputBudgetTests(unittest.TestCase):
    def settings(self, **overrides):
        return Settings(_env_file=None, database_url="postgresql://unused@127.0.0.1/unused", **overrides)

    def papers(self, count):
        return [{"paper_id": str(uuid4()), "title": f"Paper {index}", "sha256": "a" * 64,
            "size_bytes": 12, "page_count": 1} for index in range(count)]

    def research_submission(self, settings, provider):
        research = ResearchOptions(model_provider=provider,
            endpoint_url="http://10.0.3.11:8000/v1" if provider == "custom" else None)
        request = SimpleNamespace(question="Compare the methods", allow_search=True, research=research)
        session = Mock()
        session.get.return_value = SimpleNamespace(state="ready", stop_requested=False, generation=uuid4())
        with patch("app.agent_bridge.submission._save_agent_task") as save:
            create_research_task(session, settings, request, [], user_id=uuid4(), key=None,
                digest="a" * 64, interface="agent-research")
        return save.call_args.args[2]

    def test_legacy_tasks_use_the_default_budget_for_any_paper_count(self):
        with patch.dict("os.environ", {}, clear=True):
            settings = self.settings()
        for count in (1, 2, 20):
            with self.subTest(count=count):
                manifest = build_manifest(uuid4(), uuid4(), "review", "Compare", self.papers(count), settings)
                self.assertEqual(manifest.task.max_output_tokens, 16384)

    def test_research_tasks_use_the_configured_budget_with_and_without_search(self):
        settings = self.settings(agent_output_tokens=16384)
        for count, allow_search in ((0, True), (1, False), (2, False), (2, True), (20, False)):
            with self.subTest(count=count, allow_search=allow_search):
                manifest = build_research_manifest(uuid4(), uuid4(), "Compare", self.papers(count),
                    settings, allow_search=allow_search)
                self.assertEqual(manifest.task.max_output_tokens, 16384)

    def test_manifest_budgets_respect_configuration_and_reserve_context_for_input(self):
        papers = self.papers(2)
        for configured, context, expected in ((1024, 32000, 1024), (16384, 8192, 6144),
                (32768, 32000, 29952), (16384, 4096, 2048)):
            settings = self.settings(agent_output_tokens=configured, agent_context_tokens=context)
            with self.subTest(configured=configured, context=context):
                legacy = build_manifest(uuid4(), uuid4(), "review", "Compare", papers, settings)
                research = build_research_manifest(uuid4(), uuid4(), "Compare", papers,
                    settings, allow_search=False)
                for manifest in (legacy, research):
                    self.assertEqual(manifest.task.max_output_tokens, expected)
                    self.assertLessEqual(manifest.task.max_output_tokens + 2048, manifest.runtime.context_window)

    def test_tacc_and_custom_submissions_preserve_output_and_context_caps(self):
        for provider in ("tacc", "custom"):
            for configured, context, expected_output, expected_context in (
                    (16384, 32000, 16384, 32000),
                    (32768, 64000, 16384, 36864), (8192, 32000, 8192, 32000),
                    (16384, 8192, 6144, 8192)):
                with self.subTest(provider=provider, configured=configured, context=context):
                    settings = self.settings(agent_transport="tcloud", agent_output_tokens=configured,
                        agent_context_tokens=context)
                    manifest = self.research_submission(settings, provider)
                    self.assertEqual(manifest.task.max_output_tokens, expected_output)
                    self.assertEqual(manifest.runtime.context_window, expected_context)
                    self.assertLessEqual(manifest.task.max_output_tokens + 2048, expected_context)
