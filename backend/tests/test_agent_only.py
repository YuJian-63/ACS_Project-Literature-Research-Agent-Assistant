import io
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError
from pypdf import PdfReader, PdfWriter
from pypdf._page import PageObject

from app.config import Settings
from app.papers.pdf_parser import ParseFailure, parse_pdf
from app.tasks.lifecycle import claim_task
from test_pdf_titles import paper_pdf


class AgentOnlyTests(unittest.TestCase):
    def test_retired_execution_modes_cannot_be_configured(self):
        for runner in ("mock", "langgraph"):
            with self.subTest(runner=runner), self.assertRaises(ValidationError):
                Settings(_env_file=None, database_url="postgresql://unused@127.0.0.1/unused", task_runner=runner)

    def test_unused_local_model_configuration_cannot_prevent_startup(self):
        settings = Settings(_env_file=None, database_url="postgresql://unused@127.0.0.1/unused",
            LLM_BASE_URL="", LLM_MODEL_ID="")
        self.assertEqual(settings.task_runner, "agent")
        self.assertFalse(settings.agent_dispatch_enabled)

    def test_worker_cannot_claim_retired_execution_types(self):
        for runner in ("mock", "langgraph"):
            with self.subTest(runner=runner), self.assertRaises(ValueError):
                claim_task(None, None, runner)

    def test_api_and_worker_import_without_a_local_research_engine(self):
        script = '''
import importlib.abc
import sys

class RetiredEngineBlocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "app.research" or fullname.split(".")[0] in {"langgraph", "langchain", "langchain_core"}:
            raise ImportError("Retired backend research engine was imported: " + fullname)

sys.meta_path.insert(0, RetiredEngineBlocker())
import app.main
import app.runner_worker
'''
        result = subprocess.run([sys.executable, "-B", "-c", script], capture_output=True,
            text=True, cwd=Path(__file__).resolve().parents[1], timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)


class PDFMetadataTests(unittest.TestCase):
    def test_metadata_result_does_not_include_full_text_chunks(self):
        result = parse_pdf(paper_pdf("Verified paper title"))
        self.assertEqual(result.title, "Verified paper title")
        self.assertEqual(result.page_count, 1)
        self.assertNotIn("chunks", result.model_dump())

    def test_pdfs_without_extractable_text_remain_available_to_the_agent(self):
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        writer.add_metadata({"/Title": "Scanned paper"})
        output = io.BytesIO()
        writer.write(output)
        result = parse_pdf(output.getvalue())
        self.assertEqual(result.title, "Scanned paper")
        self.assertEqual(result.page_count, 1)

    def test_unavailable_title_stream_does_not_prevent_metadata_readiness(self):
        with patch.object(PageObject, "get_contents", side_effect=ValueError("Unsupported content stream")):
            result = parse_pdf(paper_pdf())
        self.assertIsNone(result.title)
        self.assertEqual(result.page_count, 1)

    def test_metadata_extraction_preserves_pdf_validation_boundaries(self):
        empty, encrypted, long_paper = PdfWriter(), PdfWriter(), PdfWriter()
        encrypted.add_blank_page(width=595, height=842)
        encrypted.encrypt("fixture-password")
        for page in range(501):
            long_paper.add_blank_page(width=595, height=842)
        cases = [(b"not a PDF", "PDF_INVALID")]
        for writer, code in ((empty, "PDF_NO_PAGES"), (encrypted, "PDF_ENCRYPTED"),
            (long_paper, "PDF_LIMIT_EXCEEDED")):
            output = io.BytesIO()
            writer.write(output)
            cases.append((output.getvalue(), code))
        for content, code in cases:
            with self.subTest(code=code), self.assertRaises(ParseFailure) as caught:
                parse_pdf(content)
            self.assertEqual(caught.exception.code, code)

    def test_title_fallback_does_not_extract_later_pages(self):
        writer = PdfWriter()
        writer.append(PdfReader(io.BytesIO(paper_pdf())))
        writer.add_blank_page(width=595, height=842)
        output = io.BytesIO()
        writer.write(output)
        original = PageObject.extract_text

        def extract_first_page(page, *arguments, **options):
            if page.get("/Contents") is None:
                raise AssertionError("A metadata parser must not extract later pages")
            return original(page, *arguments, **options)

        with patch.object(PageObject, "extract_text", extract_first_page):
            result = parse_pdf(output.getvalue())
        self.assertEqual(result.page_count, 2)
        self.assertEqual(result.title, "Evidence-Grounded Research with Language Model Agents")


if __name__ == "__main__":
    unittest.main()
