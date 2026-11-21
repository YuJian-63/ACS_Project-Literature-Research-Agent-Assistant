import unittest


class AnswerLanguageTests(unittest.TestCase):

    def test_server_labels_ignore_english_technical_terms_inside_chinese_questions(self):
        from app.tasks.language import uses_english_labels

        self.assertFalse(uses_english_labels(None))
        self.assertFalse(uses_english_labels("请比较 English benchmark 和 Rust agents。"))
        self.assertTrue(uses_english_labels("Compare the Rust agents."))
