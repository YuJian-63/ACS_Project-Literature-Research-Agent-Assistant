import unittest
from uuid import uuid4

from app.research.retrieval import EvidenceChunk


def document(*texts):
    return [EvidenceChunk(chunk_id=str(uuid4()), paper_id="paper", paper_title="Rust agents",
        chunk_index=index, page_number=index + 1, content=text) for index, text in enumerate(texts)]


class DocumentSearchTests(unittest.TestCase):
    def test_chinese_contribution_has_english_retrieval_terms(self):
        from app.research.document_search import local_query_plan, search_terms
        plan = local_query_plan("论文的创新点和贡献是什么？")
        terms = search_terms(" ".join(plan["queries"]))
        self.assertIn("contribution", terms)
        self.assertIn("novelty", terms)

    def test_chinese_overview_retrieves_english_sections(self):
        from app.research.document_search import local_query_plan, select_document_evidence
        source = document("Abstract: We address repository issue resolution.",
            "Methods: We propose a Rust debugging agent.", "References: unrelated material",
            "Conclusion: The agent improves issue resolution.")
        question = "这篇论文要解决什么问题？提出什么方法，主要结论是什么？"
        plan = local_query_plan(question)
        evidence = select_document_evidence(source, "qa", plan, 4000)
        self.assertEqual(plan["intent"], "overview")
        self.assertTrue(any("Methods" in chunk.content for chunk in evidence))
        self.assertTrue(any("Conclusion" in chunk.content for chunk in evidence))

    def test_expanded_fact_query_selects_relevant_original_window(self):
        from app.research.document_search import select_document_evidence
        source = document("Introduction: general context", "unrelated background " * 100 +
            "Results: Rust benchmark success rate is 42 percent.", "References: bibliography")
        plan = {"intent": "specific", "queries": ["Rust benchmark success rate"], "question": "成功率是多少"}
        evidence = select_document_evidence(source, "qa", plan, 1000, max_chunks=2)
        self.assertTrue(any("42 percent" in chunk.content for chunk in evidence))
        originals = {chunk.chunk_id: chunk for chunk in source}
        self.assertTrue(all(chunk.content in originals[chunk.chunk_id].content for chunk in evidence))
        self.assertLessEqual(sum(len(chunk.content) for chunk in evidence), 1000)

    def test_no_overlap_uses_context_without_claiming_a_match(self):
        from app.research.document_search import local_query_plan, select_document_evidence, retrieval_diagnostic
        source = document("Abstract: A debugging agent.", "Conclusion: More evaluation is needed.")
        plan = local_query_plan("quuxspecificnumber")
        evidence = select_document_evidence(source, "qa", plan, 2000)
        self.assertTrue(evidence)
        diagnostic = retrieval_diagnostic(source, evidence, plan)
        self.assertEqual(diagnostic["lexical_matches"], 0)
        self.assertEqual(diagnostic["status"], "context_fallback")

    def test_summary_and_review_cover_structure_and_focus(self):
        from app.research.document_search import local_query_plan, select_document_evidence
        source = document("Abstract: Overview", "Method: Agent design",
            "Results: Latency and token cost are reduced.", "Conclusion: Further work remains.")
        for kind in ("summary", "review"):
            evidence = select_document_evidence(source, kind, local_query_plan("比较成本"), 4000, max_chunks=4)
            self.assertTrue(any("token cost" in chunk.content for chunk in evidence))
            self.assertTrue(any("Abstract" in chunk.content for chunk in evidence))

    def test_supplement_uses_new_chunks_and_respects_scope(self):
        from app.research.document_search import local_query_plan, select_document_evidence
        source = document("Abstract: agent", "Results: success rate is 42 percent", "Limitations: Rust only")
        evidence = select_document_evidence(source, "qa", local_query_plan("成功率"), 1000,
            exclude_ids={source[0].chunk_id}, max_chunks=2)
        self.assertNotIn(source[0].chunk_id, {chunk.chunk_id for chunk in evidence})
        self.assertEqual({chunk.paper_id for chunk in evidence}, {"paper"})

    def test_query_plan_is_strict_and_does_not_accept_answers(self):
        from app.research.document_search import validate_query_plan
        valid = validate_query_plan(
            '{"intent":"specific","queries":["Rust success rate"]}', "成功率是多少")
        self.assertEqual(valid["question"], "成功率是多少")
        for raw in ('{"intent":"specific","queries":[]}',
            '{"intent":"specific","queries":["x"],"answer":"42"}'):
            with self.assertRaises(ValueError):
                validate_query_plan(raw, "问题")


if __name__ == "__main__":
    unittest.main()
