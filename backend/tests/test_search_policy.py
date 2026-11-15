import unittest
from types import SimpleNamespace

from test_document_search import document
from app.research.search_policy import build_search_plan, read_snapshot, source_snapshot


def settings(**overrides):
    return SimpleNamespace(**(dict(evidence_context_chars=24000, research_context_tokens=32768,
        research_output_tokens=8192, research_task_tokens=100000, research_call_timeout_seconds=180,
        review_context_tokens=32768, review_output_tokens=4096, review_task_tokens=100000,
        review_timeout_seconds=1800, review_call_timeout_seconds=90, review_evidence_chars=4000) | overrides))


class SearchPolicyTests(unittest.TestCase):
    def test_snapshot_survives_reparse_and_checks_integrity_and_scope(self):
        source = document("Abstract: Rust methods and results.")
        papers = [{"paper_id": "paper", "paper_title": "Rust agents", "sha256": "a" * 64, "parser_version": "parser-v1"}]
        snapshot = source_snapshot(papers, source)
        source[0] = source[0].model_copy(update={"content": "reparsed"})
        self.assertIn("Abstract", read_snapshot(snapshot, papers)[0].content)
        with self.assertRaises(ValueError):
            read_snapshot(snapshot, [{"paper_id": "other"}])
        snapshot["chunks"][0]["content"] = "tampered"
        with self.assertRaises(ValueError):
            read_snapshot(snapshot, papers)

    def test_snapshot_has_explicit_size_limit(self):
        with self.assertRaises(ValueError):
            source_snapshot([{"paper_id": "paper"}], document("text" * 100), max_bytes=10)

    def test_single_plan_reserves_expansion_supplement_and_recovery(self):
        source = document(*["方法与结果 🧪 " * 300 for unused in range(12)])
        policy, plan, evidence = build_search_plan("qa", "实验成功率是多少？",
            [{"paper_id": "paper", "paper_title": "Rust"}], source, settings())
        self.assertTrue(policy["expand"])
        self.assertEqual(policy["max_steps"], 4)
        self.assertLessEqual(policy["max_tokens"], 100000)
        self.assertLessEqual(plan["input_cap"] + plan["max_output_tokens"], policy["context_tokens"])
        self.assertGreaterEqual(policy["max_tokens"], 3 * (plan["input_cap"] + plan["max_output_tokens"]) + 512)
        self.assertTrue(evidence)

    def test_review_budget_includes_per_paper_supplement(self):
        from test_staged_review import fixture
        papers, groups = fixture(6)
        policy, plan, evidence = build_search_plan("review", "比较方法、成本与实验结果", papers,
            [chunk for group in groups.values() for chunk in group], settings())
        self.assertLessEqual(policy["max_tokens"], 100000)
        self.assertGreaterEqual(policy["max_steps"], 6 * 2 + 3 + 1)
        self.assertEqual({chunk.paper_id for chunk in evidence}, set(groups))

    def test_impossible_prompt_is_rejected(self):
        with self.assertRaises(ValueError):
            build_search_plan("qa", "问题" * 5000, [{"paper_id": "paper", "paper_title": "Rust"}],
                document("evidence"), settings(research_context_tokens=4096))


if __name__ == "__main__":
    unittest.main()
