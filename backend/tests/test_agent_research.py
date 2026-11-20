import unittest
from uuid import uuid4

from pydantic import ValidationError

from app.config import Settings
from app.main import create_app


class AgentResearchContractTests(unittest.TestCase):
    def test_unified_routes_and_response_contract_are_registered(self):
        settings = Settings(_env_file=None, database_url="postgresql://unused@127.0.0.1/unused")
        schema = create_app(settings).openapi()
        for path, methods in {
            "/api/v1/agent-research": {"get", "post"},
            "/api/v1/agent-research/{task_id}": {"get", "delete"},
        }.items():
            self.assertTrue(methods <= set(schema["paths"].get(path, {})), path)
        operation = schema["paths"]["/api/v1/agent-research"]["post"]
        self.assertIn("202", operation["responses"])

    def test_question_only_and_selected_papers_follow_the_frontend_contract(self):
        from app.api.agent_research_schemas import AgentResearchCreate

        request = AgentResearchCreate(question="  研究方法是什么？  ")
        self.assertEqual(request.question, "研究方法是什么？")
        self.assertEqual(request.paper_ids, [])
        self.assertTrue(request.allow_search)
        identifiers = [uuid4(), uuid4()]
        request = AgentResearchCreate(question="Compare", paper_ids=identifiers, allow_search=False)
        self.assertEqual(request.paper_ids, identifiers)

    def test_invalid_inputs_and_client_budgets_are_rejected(self):
        from app.api.agent_research_schemas import AgentResearchCreate

        identifier = uuid4()
        for body in (
            {"question": "   "}, {"question": "a" * 8001}, {"question": "bad\x00text"},
            {"question": "Question", "allow_search": False},
            {"question": "Question", "paper_ids": [identifier, identifier]},
            {"question": "Question", "paper_ids": [uuid4() for _ in range(21)]},
            {"question": "Question", "budget": {"max_steps": 999}},
            {"question": "Question", "task_type": "summary"},
        ):
            with self.subTest(body=body), self.assertRaises(ValidationError):
                AgentResearchCreate(**body)

    def test_search_manifest_is_bounded_and_keeps_question_language(self):
        from app.agent_bridge.policy import build_research_manifest

        settings = Settings(_env_file=None, database_url="postgresql://unused@127.0.0.1/unused")
        manifest = build_research_manifest(uuid4(), uuid4(), "比较 Rust 调试方法", [], settings, allow_search=True)
        self.assertTrue(manifest.task.allow_search)
        self.assertEqual(manifest.sources, [])
        self.assertGreater(manifest.task.max_papers, 0)
        self.assertLessEqual(manifest.task.max_steps, settings.agent_max_steps)
        self.assertLessEqual(manifest.task.timeout_seconds, settings.agent_timeout_seconds)
        self.assertIn("比较 Rust 调试方法", manifest.task.question)
        self.assertIn("same language", manifest.task.question)
        self.assertNotIn("using only the selected paper", manifest.task.question)

    def test_mixed_manifest_keeps_selected_order_and_room_for_search(self):
        from app.agent_bridge.policy import build_research_manifest

        settings = Settings(_env_file=None, database_url="postgresql://unused@127.0.0.1/unused")
        papers = [{"paper_id": str(uuid4()), "title": f"Paper {index}", "sha256": "a" * 64,
            "size_bytes": 12, "page_count": 1} for index in range(2)]
        manifest = build_research_manifest(uuid4(), uuid4(), "Compare", papers, settings, allow_search=True)
        self.assertEqual([str(source.paper_id) for source in manifest.sources], [paper["paper_id"] for paper in papers])
        self.assertGreater(manifest.task.max_papers, len(papers))
        pinned = build_research_manifest(uuid4(), uuid4(), "Compare", papers, settings, allow_search=False)
        self.assertFalse(pinned.task.allow_search)
        self.assertEqual(pinned.task.max_papers, len(papers))

    def test_search_sources_remain_native_without_inventing_local_paper_ids(self):
        from app.agent_bridge.bundles import manifest_digest
        from app.agent_bridge.contracts import ResultEnvelope
        from app.agent_bridge.policy import build_research_manifest
        from app.agent_bridge.results import present_result, validate_delivery

        settings = Settings(_env_file=None, database_url="postgresql://unused@127.0.0.1/unused")
        manifest = build_research_manifest(uuid4(), uuid4(), "Explain", [], settings, allow_search=True)
        source_id = "arxiv:1706.03762v7"
        envelope = ResultEnvelope.model_validate({"schema_version": "agent-result-v1",
            "dispatch_id": str(manifest.dispatch_id), "input_sha256": manifest_digest(manifest),
            "result": {"task_id": manifest.task.task_id, "question": manifest.task.question,
                "answer": f"Evidence [{source_id}:p1:c1]", "stop_reason": "completed", "usage": {},
                "sources": [{"source_id": source_id, "paper_id": "arxiv:1706.03762", "title": "Paper",
                    "url": "https://arxiv.org/abs/1706.03762v7"}],
                "citations": [{"source_id": source_id, "paper_id": "arxiv:1706.03762", "title": "Paper",
                    "url": "https://arxiv.org/abs/1706.03762v7", "chunk_id": source_id + ":p1:c1",
                    "page": 1, "source_text": "Verbatim original evidence."}]}})
        validate_delivery(manifest, envelope)
        projected = present_result(manifest, envelope.result)
        self.assertEqual(projected.citations, [])
        self.assertIn("arxiv:1706.03762v7:p1:c1", projected.content_markdown)
        bad = envelope.model_copy(deep=True)
        bad.result.citations[0].source_id = "local:" + str(uuid4()) + "@" + "a" * 64
        with self.assertRaises(ValueError):
            validate_delivery(manifest, bad)
        bad = envelope.model_copy(deep=True)
        bad.result.citations[0].url = "https://example.com/foreign"
        with self.assertRaises(ValueError):
            validate_delivery(manifest, bad)
