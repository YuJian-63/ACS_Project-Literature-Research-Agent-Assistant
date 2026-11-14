import unittest
from types import SimpleNamespace

from app.research.retrieval import EvidenceChunk, build_messages


def settings(**overrides):
    return SimpleNamespace(**(dict(evidence_context_chars=24000, research_context_tokens=32768,
        research_output_tokens=8192, research_task_tokens=100000, research_call_timeout_seconds=180) | overrides))


def chunks(size=1000, count=1):
    return [EvidenceChunk(chunk_id=str(index), paper_id="paper", paper_title="Paper", chunk_index=index,
        page_number=index + 1, content="evidence method result " * (size // 23)) for index in range(count)]


class TaskPolicyTests(unittest.TestCase):
    def test_budget_grows_with_evidence_and_question(self):
        from app.research.task_policy import build_task_plan
        small, _ = build_task_plan("summary", None, chunks(), settings())
        large, _ = build_task_plan("summary", None, chunks(4000, 5), settings())
        self.assertGreater(large["max_tokens"], small["max_tokens"])
        self.assertGreater(large["max_output_tokens"], small["max_output_tokens"])
        self.assertGreater(large["timeout_seconds"], small["timeout_seconds"])
        short, _ = build_task_plan("qa", "method", chunks(), settings())
        long, _ = build_task_plan("qa", "method " * 100, chunks(), settings())
        self.assertGreater(long["max_tokens"], short["max_tokens"])
        self.assertEqual(large["max_steps"], 1)

    def test_context_and_total_caps_reduce_evidence_before_execution(self):
        from app.research.task_policy import build_task_plan
        config = settings(research_context_tokens=7000, research_task_tokens=7500, research_output_tokens=2048)
        plan, evidence = build_task_plan("summary", None, chunks(3000, 8), config)
        self.assertTrue(evidence)
        self.assertLess(len(evidence), 8)
        self.assertLessEqual(plan["max_tokens"], config.research_task_tokens)
        self.assertLessEqual(plan["estimated_input_tokens"] + plan["max_output_tokens"], config.research_context_tokens)
        self.assertLessEqual(plan["max_output_tokens"], config.research_output_tokens)
        self.assertLessEqual(plan["model_timeout_seconds"], config.research_call_timeout_seconds)

    def test_multilingual_prompt_is_conservatively_reserved(self):
        from app.research.task_policy import build_task_plan
        source = chunks()
        source[0] = source[0].model_copy(update={"content": "方法与结果。" * 100})
        plan, evidence = build_task_plan("summary", "中文问题", source, settings())
        messages = build_messages("summary", "中文问题", evidence, prompt_version="evidence-v4")
        self.assertGreaterEqual(plan["estimated_input_tokens"], sum(len(message["content"].encode("utf-8")) for message in messages))

    def test_no_matching_evidence_does_not_invent_a_match(self):
        from app.research.task_policy import build_task_plan
        plan, evidence = build_task_plan("qa", "unmatchedterm", chunks(), settings())
        self.assertEqual(evidence, [])
        self.assertEqual(plan["estimated_input_tokens"], 0)
        self.assertGreater(plan["max_tokens"], 0)

    def test_impossible_prompt_is_rejected_instead_of_creating_underfunded_job(self):
        from app.research.task_policy import build_task_plan
        with self.assertRaises(ValueError):
            build_task_plan("summary", "问题" * 4000, chunks(), settings(research_context_tokens=4096))


if __name__ == "__main__":
    unittest.main()
