import json
import unittest

from app.research.retrieval import EvidenceChunk, build_messages
from app.research.review_protocol import analysis_messages, synthesis_messages
from app.research.search_policy import answer_messages


class AnswerLanguageTests(unittest.TestCase):
    def test_legacy_summary_and_qa_follow_question_language(self):
        evidence = [EvidenceChunk(chunk_id="chunk", paper_id="paper", paper_title="English paper",
            chunk_index=0, page_number=1, content="A method is described.")]
        for question in (None, "What is the method?", "请解释 English benchmark 的方法。"):
            for task_type in ("summary", "qa"):
                with self.subTest(question=question, task_type=task_type):
                    for build in (build_messages, answer_messages):
                        messages = build(task_type, question, evidence)
                        instruction = messages[0]["content"]
                        self.assertIn("same language as the user question" if question else "answer in Chinese", instruction)
                        self.assertEqual(json.loads(messages[1]["content"])["question"], question)

    def test_staged_review_follows_the_actual_question(self):
        plan = {"cell_chars": 100, "paragraph_chars": 200, "columns": [], "registry": []}
        for question in ("Compare the methods.", "请比较 English benchmark 的结果。"):
            analysis = analysis_messages({"paper_id": "paper"}, [], question, plan)
            synthesis = synthesis_messages({"key": "overview"}, [], [], question, plan)
            for messages in (analysis, synthesis):
                self.assertIn("same language as the user question", messages[0]["content"])

    def test_server_labels_ignore_english_technical_terms_inside_chinese_questions(self):
        from app.tasks.language import uses_english_labels

        self.assertFalse(uses_english_labels(None))
        self.assertFalse(uses_english_labels("请比较 English benchmark 和 Rust agents。"))
        self.assertTrue(uses_english_labels("Compare the Rust agents."))
