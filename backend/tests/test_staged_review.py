import json
import unittest
from types import SimpleNamespace
from uuid import uuid4

from app.research.model_client import ModelCompletion
from app.research.retrieval import EvidenceChunk
from app.research.review_policy import build_review_plan
from app.research.review_protocol import analysis_messages, validate_analysis, assemble_review, synthesis_messages, validate_section, token_estimate


def fixture(count=6, content_size=12000):
    papers = [{"paper_id": str(uuid4()), "paper_title": "Rust agent research"} for unused in range(count)]
    groups = {}
    for paper in papers:
        groups[paper["paper_id"]] = [EvidenceChunk(
            chunk_id=str(uuid4()), paper_id=paper["paper_id"], paper_title=paper["paper_title"],
            chunk_index=index, page_number=index + 1,
            content=("Repository agents evaluate methods and limitations. " * 50)[:2000],
        ) for index in range(max(1, content_size // 2000))]
    return papers, groups


def settings(**overrides):
    values = dict(review_context_tokens=32768, review_output_tokens=4096,
                  review_task_tokens=100000, review_timeout_seconds=1800,
                  review_call_timeout_seconds=90, review_evidence_chars=4000)
    return SimpleNamespace(**(values | overrides))


class ReviewPolicyTests(unittest.TestCase):
    def test_two_six_twenty_papers_fit_and_grow(self):
        totals = []
        for count in (2, 6, 20):
            papers, groups = fixture(count)
            if count == 20:
                groups = {identity: [chunk.model_copy(update={"content": "Agent methods and evaluation."}) for chunk in chunks[:1]] for identity, chunks in groups.items()}
            plan, evidence = build_review_plan(papers, groups, "Compare these papers", settings())
            self.assertLessEqual(plan["max_tokens"], 100000)
            self.assertLessEqual(plan["max_steps"], 100)
            self.assertLessEqual(plan["timeout_seconds"], 1800)
            self.assertEqual({chunk.paper_id for chunk in evidence}, set(groups))
            self.assertLessEqual(len(evidence), 100)
            self.assertGreaterEqual(plan["max_steps"], count + 3)
            totals.append(plan["max_tokens"])
        self.assertGreater(totals[2], totals[0])

    def test_large_twenty_paper_review_is_rejected_before_execution(self):
        papers, groups = fixture(20)
        with self.assertRaises(ValueError):
            build_review_plan(papers, groups, "Compare these papers", settings())

    def test_long_multilingual_question_is_planned_or_rejected_before_calls(self):
        papers, groups = fixture(20)
        try:
            plan, evidence = build_review_plan(papers, groups, "比较方法与结果" * 1000, settings())
        except ValueError:
            return
        self.assertLessEqual(plan["max_tokens"], 100000)

    def test_token_reservation_covers_each_utf8_byte(self):
        messages = [{"role": "user", "content": "🧪\x01漢" * 500}]
        self.assertGreaterEqual(token_estimate(messages), len(messages[0]["content"].encode("utf-8")))

    def test_analysis_serialized_size_is_bounded(self):
        papers, groups = fixture(2)
        plan, evidence = build_review_plan(papers, groups, "Compare", settings())
        identity = plan["registry"][0]["evidence_id"]
        draft = {"cells": {column["key"]: {"value": "\x01" * plan["cell_chars"], "evidence_ids": [identity]} for column in plan["columns"]}}
        with self.assertRaises(ValueError):
            validate_analysis(json.dumps(draft), papers[0], plan)

    def test_synthesis_includes_exact_deduplicated_source_passages(self):
        papers, groups = fixture(2)
        plan, evidence = build_review_plan(papers, groups, "Compare", settings())
        entry = plan["registry"][0]
        analyses = [{"cells": {column["key"]: {"value": "Supported", "evidence_ids": [entry["evidence_id"]]} for column in plan["columns"]}}]
        payload = json.loads(synthesis_messages(plan["sections"][0], analyses, papers, "Compare", plan)[1]["content"])
        self.assertEqual(payload["evidence"], [{"evidence_id": entry["evidence_id"], "quote": entry["quote"]}])

    def test_widest_accepted_unicode_fits_synthesis_and_total_reservations(self):
        papers, groups = fixture(6)
        plan, evidence = build_review_plan(papers, groups, "Compare", settings())
        analyses, reserves = [], []
        for paper in papers:
            entries = [entry for entry in plan["registry"] if entry["paper_id"] == paper["paper_id"]]
            identity = entries[0]["evidence_id"]
            value = "🧪" * (plan["cell_chars"] * 3 // 4)
            raw = {"cells": {column["key"]: {"value": value, "evidence_ids": [identity]} for column in plan["columns"]}}
            analyses.append(validate_analysis(json.dumps(raw), paper, plan))
            reserves.append(token_estimate(analysis_messages(paper, entries, "Compare", plan)) + plan["analysis_output_tokens"])
        for section in plan["sections"]:
            size = token_estimate(synthesis_messages(section, analyses, papers, "Compare", plan)) + plan["section_output_tokens"]
            self.assertLessEqual(size, plan["context_tokens"])
            reserves.append(size)
        self.assertLessEqual(sum(reserves) + plan["retry_reserve"] * max(reserves), plan["max_tokens"])

    def test_impossible_cap_rejected(self):
        papers, groups = fixture()
        with self.assertRaises(ValueError):
            build_review_plan(papers, groups, "Compare", settings(review_task_tokens=1000))

    def test_sampling_covers_start_and_end_without_keyword_overlap(self):
        papers, groups = fixture(2)
        plan, evidence = build_review_plan(papers, groups, "比较这些论文", settings())
        for paper in papers:
            selected = [chunk for chunk in evidence if chunk.paper_id == paper["paper_id"]]
            self.assertEqual(selected[0].chunk_index, 0)
            self.assertEqual(selected[-1].chunk_index, 5)


class ReviewProtocolTests(unittest.TestCase):
    def setUp(self):
        self.papers, groups = fixture(2)
        self.plan, self.evidence = build_review_plan(self.papers, groups, "比较研究方法", settings())
        self.registry = self.plan["registry"]

    def analysis(self, paper):
        identity = next(item["evidence_id"] for item in self.registry if item["paper_id"] == paper["paper_id"])
        return {"cells": {column["key"]: {"value": "Supported finding", "evidence_ids": [identity]} for column in self.plan["columns"]}}

    def test_source_owned_assembly(self):
        analyses = [validate_analysis(json.dumps(self.analysis(paper)), paper, self.plan) for paper in self.papers]
        sections = [{"paragraphs": [{"content_markdown": "Comparison", "evidence_ids": [self.registry[0]["evidence_id"]]}]}]
        result = assemble_review(analyses, sections, self.papers, self.evidence, self.plan)
        self.assertEqual(len(result.comparison_table["rows"]), 2)
        self.assertTrue(result.citations)
        self.assertEqual(result.citations[0].quote, self.evidence[0].content)

    def test_cross_paper_ids_rejected(self):
        draft = self.analysis(self.papers[0])
        draft["cells"]["objective"]["evidence_ids"] = [next(item["evidence_id"] for item in self.registry if item["paper_id"] == self.papers[1]["paper_id"])]
        with self.assertRaises(ValueError):
            validate_analysis(json.dumps(draft), self.papers[0], self.plan)

    def test_invalid_json_duplicate_unknown_and_unsupported_claim_rejected(self):
        for ids in (["E999"], ["E1", "E1"], []):
            draft = self.analysis(self.papers[0])
            draft["cells"]["objective"]["evidence_ids"] = ids
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                validate_analysis(json.dumps(draft), self.papers[0], self.plan)
        with self.assertRaises(ValueError):
            validate_analysis('{"cells":', self.papers[0], self.plan)

    def test_section_rejects_evidence_absent_from_its_prompt(self):
        analysis = self.analysis(self.papers[0])
        identity = analysis["cells"]["method"]["evidence_ids"][0]
        for key, cell in analysis["cells"].items():
            if key != "method":
                cell.update(value=None, evidence_ids=[])
        overview = self.plan["sections"][0]
        raw = json.dumps({"paragraphs": [{"content_markdown": "Unsupported overview", "evidence_ids": [identity]}]})
        with self.assertRaises(ValueError):
            validate_section(raw, [analysis], self.plan, overview)
        empty = json.dumps({"paragraphs": [{"content_markdown": "Insufficient evidence", "evidence_ids": []}]})
        self.assertTrue(validate_section(empty, [analysis], self.plan, overview))

    def test_synthesis_must_use_only_validated_analysis_ids(self):
        analyses = [validate_analysis(json.dumps(self.analysis(paper)), paper, self.plan) for paper in self.papers]
        unused_id = next(item["evidence_id"] for item in self.registry if item["evidence_id"] not in {identity for analysis in analyses for cell in analysis["cells"].values() for identity in cell["evidence_ids"]})
        with self.assertRaises(ValueError):
            validate_section(json.dumps({"paragraphs": [{"content_markdown": "Unsupported", "evidence_ids": [unused_id]}]}), analyses, self.plan)


if __name__ == "__main__":
    unittest.main()
