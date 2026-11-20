"""Offline import-before-reading checks; every API response is a fixture."""
import os
import re
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / "runtime/pw-browsers"))
BASE = os.environ.get("AGENT_PREVIEW_URL", "http://127.0.0.1:5199")
TASK = "22222222-2222-4222-8222-222222222222"
PAPER = "11111111-1111-4111-8111-111111111111"
IMPORT = "33333333-3333-4333-8333-333333333333"


class SourceImportBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.driver = sync_playwright().start()
        cls.browser = cls.driver.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.driver.stop()

    def setUp(self):
        self.context = self.browser.new_context(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
        self.page = self.context.new_page()
        self.page.set_default_timeout(6000)
        self.calls, self.errors = [], []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.source = {"source_id": "arxiv:1706.03762v7", "paper_id": "arxiv:1706.03762",
            "title": "Attention Is All You Need", "version": "v7", "url": "https://arxiv.org/abs/1706.03762v7"}
        self.ready = self.parsed = self.local = self.download_failed = self.parse_failed = False
        self.wrong_version = self.poll_error = False
        self.paper_pages = 12
        self.context.route("**/api/v1/**", self.respond)

    def tearDown(self):
        self.context.close()
        self.assertFalse(self.errors)
        self.assertFalse([path for _, path, _ in self.calls if "/papers/arxiv" in path or "/papers/local" in path])

    def respond(self, route):
        request = route.request
        path = urlparse(request.url).path
        body = request.post_data_json if request.method == "POST" else None
        self.calls.append((request.method, path, body))
        if path.endswith("/auth/me"):
            return route.fulfill(json={"user": {"id": "fixture", "username": "fixture", "email": "fixture@example.com"}, "csrf_token": "fixture"})
        source = self.source if not self.local else {"source_id": "local:" + PAPER + "@" + "a" * 64,
            "paper_id": PAPER, "title": "Local PDF", "url": ""}
        if path == "/api/v1/agent-research/" + TASK:
            citation = {**source, "chunk_id": source["source_id"] + ":p3:c1", "page": 3,
                "source_text": "This is the original evidence sentence."}
            result = {"task_id": TASK, "question": "Explain", "answer": "Evidence [" + citation["chunk_id"] + "]",
                "comparison_table": "", "citations": [citation], "sources": [source], "unresolved": [],
                "stop_reason": "completed", "usage": {}, "trace": [], "errors": [], "configuration": {}}
            return route.fulfill(json={"task_id": TASK, "question": "Explain", "status": "succeeded",
                "paper_ids": [], "result": result, "error": None})
        if path == "/api/v1/paper-imports" and request.method == "POST":
            self.assertEqual(body, {"provider": "arxiv", "external_id": "1706.03762v7"})
            self.assertEqual(request.header_value("x-csrf-token"), "fixture")
        if path == "/api/v1/paper-imports/" + IMPORT + "/retry":
            self.assertEqual(body, {"expected_attempt": 1})
            self.download_failed = False
        if path == "/api/v1/paper-imports/" + IMPORT and self.poll_error:
            self.poll_error = False
            return route.fulfill(status=503, headers={"X-Request-ID": "fixture-poll-error"},
                json={"error": {"code": "SERVICE_NOT_READY", "message": "导入状态暂不可用", "details": {}}})
        if path.startswith("/api/v1/paper-imports"):
            return route.fulfill(json={"id": IMPORT, "provider": "arxiv", "external_id": "1706.03762v7", "attempt": 1,
                "status": "failed" if self.download_failed else "succeeded" if self.ready else "queued",
                "paper_id": PAPER if self.ready else None, "paper_status": "ready" if self.parsed else "uploaded" if self.ready else None,
                "error": {"code": "ARXIV_TIMEOUT", "message": "arXiv 请求超时", "details": {}} if self.download_failed else None})
        paper = {"id": PAPER, "title": source["title"], "original_filename": "paper.pdf", "content_type": "application/pdf",
            "status": "failed" if self.parse_failed else "ready" if self.parsed or self.local else "processing", "page_count": self.paper_pages,
            "size_bytes": 20, "sha256": "a" * 64, "parser_version": "fixture", "error": None,
            "source": None if self.local else {"provider": "arxiv", "external_id": "1706.03762v8" if self.wrong_version else "1706.03762v7"},
            "created_at": "2026-11-20T10:00:00Z", "updated_at": "2026-11-20T10:00:00Z"}
        if path == "/api/v1/papers/" + PAPER:
            return route.fulfill(json=paper)
        if path == "/api/v1/papers/" + PAPER + "/file":
            return route.fulfill(content_type="application/pdf", body=b"%PDF-1.4\n%%EOF\n")
        return route.fulfill(json={"items": [paper] if path == "/api/v1/papers" and (self.ready or self.local) else [], "total": 0, "limit": 20, "offset": 0})

    def open_evidence(self):
        self.page.goto(BASE + "/tasks/" + TASK)
        self.page.wait_for_load_state("networkidle")
        self.page.locator(".citation-trigger").click()
        self.page.get_by_role("button", name="查看 PDF 对应页", exact=True).click()

    def import_dialog(self):
        return self.page.get_by_role("dialog", name="导入论文后阅读", exact=True)

    def confirm_import(self):
        self.import_dialog().get_by_role("button", name="导入并阅读", exact=True).click()

    def test_import_waits_for_download_and_parse_then_restores_citation(self):
        self.open_evidence()
        expect(self.import_dialog()).to_be_visible()
        self.assertFalse([call for call in self.calls if call[0] == "POST"])
        self.confirm_import()
        expect(self.import_dialog().get_by_text("等待导入", exact=True)).to_be_visible()
        self.assertIn("/tasks/" + TASK, self.page.url)
        self.ready = True
        expect(self.import_dialog().get_by_text("正在解析论文", exact=True)).to_be_visible(timeout=10000)
        self.parsed = True
        self.page.wait_for_url("**/papers?**", timeout=10000)
        query = parse_qs(urlparse(self.page.url).query)
        self.assertEqual(query["paper_id"], [PAPER])
        self.assertEqual(query["pdf_page"], ["3"])
        self.assertEqual(query["return_research"], [TASK])
        self.assertEqual(query["return_citation"], [self.source["source_id"] + ":p3:c1"])
        self.page.get_by_role("button", name="返回研究", exact=True).click()
        expect(self.page.get_by_role("dialog", name="证据与来源", exact=True)).to_be_visible()

    def test_source_title_reuses_imported_version(self):
        self.ready = self.parsed = True
        self.page.goto(BASE + "/tasks/" + TASK)
        self.page.get_by_role("tab", name="引用与来源", exact=True).click()
        self.page.locator(".research-source-list").get_by_role("button", name=self.source["title"], exact=True).click()
        self.confirm_import()
        self.page.wait_for_url("**/papers?**")
        self.assertEqual(parse_qs(urlparse(self.page.url).query)["paper_id"], [PAPER])
        self.assertEqual(len([call for call in self.calls if call[:2] == ("POST", "/api/v1/paper-imports")]), 1)

    def test_local_pdf_opens_without_import(self):
        self.local = True
        self.open_evidence()
        self.page.wait_for_url("**/papers?**")
        self.assertFalse([call for call in self.calls if "/paper-imports" in call[1]])

    def test_missing_version_never_imports_latest(self):
        self.source.update(source_id="arxiv:1706.03762@012345abcdef", version=None)
        self.open_evidence()
        expect(self.import_dialog().get_by_text("来源缺少明确的 arXiv 版本，请先在搜索论文中确认版本。", exact=True)).to_be_visible()
        self.assertFalse([call for call in self.calls if call[0] == "POST"])

    def test_failed_download_requires_explicit_retry(self):
        self.download_failed = True
        self.open_evidence()
        self.confirm_import()
        retry = self.import_dialog().get_by_role("button", name=re.compile("重试导入$"))
        expect(retry).to_be_visible()
        expect(retry).to_be_enabled()
        self.assertFalse([call for call in self.calls if call[1].endswith("/retry")])
        self.ready = self.parsed = True
        retry.click()
        self.page.wait_for_url("**/papers?**")

    def test_parse_failure_does_not_open_reader(self):
        self.ready = self.parse_failed = True
        self.open_evidence()
        self.confirm_import()
        expect(self.import_dialog().get_by_text("论文解析失败，请前往论文库检查。", exact=True)).to_be_visible()
        self.assertIn("/tasks/" + TASK, self.page.url)
        self.assertFalse([call for call in self.calls if call[1].endswith("/file")])

    def test_wrong_imported_version_is_never_read(self):
        self.ready = self.parsed = self.wrong_version = True
        self.open_evidence()
        self.confirm_import()
        expect(self.import_dialog().get_by_text("导入论文的版本与引用来源不一致，无法打开对应页。", exact=True)).to_be_visible()
        self.assertFalse([call for call in self.calls if call[1].endswith("/file")])

    def test_closing_progress_stops_waiting_without_canceling_import(self):
        self.open_evidence()
        self.confirm_import()
        expect(self.import_dialog().get_by_text("等待导入", exact=True)).to_be_visible()
        self.import_dialog().get_by_role("button", name="停止等待", exact=True).click()
        expect(self.import_dialog()).not_to_be_visible()
        previous = len(self.calls)
        self.ready = self.parsed = True
        self.page.wait_for_timeout(2400)
        self.assertEqual(len(self.calls), previous)
        self.assertIn("/tasks/" + TASK, self.page.url)
        self.assertEqual(len([call for call in self.calls if call[0] != "GET"]), 1)

    def test_poll_failure_can_recheck_without_reimporting(self):
        self.poll_error = True
        self.open_evidence()
        self.confirm_import()
        expect(self.import_dialog().get_by_text("fixture-poll-error", exact=True)).to_be_visible(timeout=10000)
        self.ready = self.parsed = True
        self.import_dialog().get_by_role("button", name="重新检查", exact=True).click()
        self.page.wait_for_url("**/papers?**")
        self.assertEqual(len([call for call in self.calls if call[0] == "POST"]), 1)

    def test_imported_pdf_hash_must_match_evidence(self):
        self.source.update(source_id="arxiv:1706.03762@012345abcdef")
        self.ready = self.parsed = True
        self.open_evidence()
        self.confirm_import()
        expect(self.import_dialog().get_by_text("导入 PDF 的内容与引用来源不一致，无法打开对应页。", exact=True)).to_be_visible()
        self.assertFalse([call for call in self.calls if call[1].endswith("/file")])

    def test_cited_page_must_exist_in_imported_pdf(self):
        self.ready = self.parsed = True
        self.paper_pages = 2
        self.open_evidence()
        self.confirm_import()
        expect(self.import_dialog().get_by_text("引用页码超出了导入 PDF 的范围，无法打开对应页。", exact=True)).to_be_visible()
        self.assertFalse([call for call in self.calls if call[1].endswith("/file")])

    def test_english_mobile_prompt_and_cancel_do_not_import(self):
        self.page.add_init_script("localStorage.setItem('literature-v3-ui-locale','en-US')")
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.goto(BASE + "/tasks/" + TASK)
        self.page.locator(".citation-trigger").click()
        self.page.get_by_role("button", name="Open PDF page", exact=True).click()
        dialog = self.page.get_by_role("dialog", name="Import paper before reading", exact=True)
        expect(dialog).to_be_visible()
        dialog.get_by_role("button", name="Cancel", exact=True).click()
        expect(dialog).not_to_be_visible()
        self.assertFalse([call for call in self.calls if call[0] == "POST"])
        self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= innerWidth"))


if __name__ == "__main__":
    unittest.main()
