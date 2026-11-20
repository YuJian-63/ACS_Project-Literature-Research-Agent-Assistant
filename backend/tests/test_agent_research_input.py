import unittest
from pydantic import ValidationError
from app.api.agent_research_schemas import AgentResearchCreate

class AgentResearchInputTests(unittest.TestCase):
    def test_question_only_defaults_to_search(self):
        request = AgentResearchCreate(question='  What evidence supports this?  ')
        self.assertEqual(request.question, 'What evidence supports this?')
        self.assertEqual(request.paper_ids, [])
        self.assertTrue(request.allow_search)

    def test_empty_papers_with_search_is_valid(self):
        self.assertTrue(AgentResearchCreate(question='Question', paper_ids=[], allow_search=True).allow_search)

    def test_blank_question_or_no_evidence_path_is_invalid(self):
        for body in ({'question':'   '}, {'paper_ids':[]}, {'question':'Question','allow_search':False}):
            with self.subTest(body=body), self.assertRaises(ValidationError):
                AgentResearchCreate(**body)

    def test_selected_papers_keep_limit_and_search(self):
        from uuid import uuid4
        request = AgentResearchCreate(question='Question', paper_ids=[uuid4()])
        self.assertTrue(request.allow_search)
        with self.assertRaises(ValidationError):
            AgentResearchCreate(question='Question',paper_ids=[uuid4() for _ in range(21)])
