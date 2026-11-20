"""Offline integration regressions; start Vite and set AGENT_PREVIEW_URL if needed."""
import copy
import os
import re
import runpy
import unittest
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / "runtime/pw-browsers"))
BASE = os.environ.get("AGENT_PREVIEW_URL", "http://127.0.0.1:5197")
FIXTURE = runpy.run_path(str(ROOT / "frontend/checks/review-browser.py"))
PAPERS = FIXTURE["PAPERS"][:2]
TASK_ID = FIXTURE["TASK_ID"]


class AgentIntegrationBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.driver = sync_playwright().start()
        cls.browser = cls.driver.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.driver.stop()

    def setUp(self):
        self.task = {**copy.deepcopy(FIXTURE["TASK"]), "status": "succeeded", "stage": "partial",
            "paper_ids": [paper["id"] for paper in PAPERS], "finished_at": FIXTURE["STAMP"],
            "retrieval": None, "agent": {"dispatch_id": "22222222-2222-4222-8222-222222222222",
                "transport": "local-process-v1", "remote_job_id": "local:fixture", "stop_reason": "partial",
                "unresolved": ["Audit evidence gap."], "limits": {}}}
        self.artifact = {"id": "33333333-3333-4333-8333-333333333333", "task_id": TASK_ID,
            "task_type": "review", "schema_version": 1, "is_mock": False, "title": "论文综述",
            "content_markdown": "## Audit answer\n\nSupported result. [C1]",
            "comparison_table": None,
            "comparison_markdown": "| Paper | Evidence |\n| --- | --- |\n| Example | [C2] |",
            "agent_stop_reason": "partial", "unresolved": ["Audit evidence gap."],
            "citations": [{"id": f"citation-{index}", "citation_key": f"C{index}",
                "paper_id": PAPERS[0]["id"], "paper_title": PAPERS[0]["title"],
                "chunk_id": f"native:p{index}:c1", "agent_source_id": "local:fixture",
                "page_number": index, "quote": f"Verbatim evidence {index}."} for index in (1, 2)],
            "created_at": FIXTURE["STAMP"]}
        self.posts = []
        self.errors = []
        self.signed_in = True
        self.context = self.browser.new_context(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
        self.addCleanup(self.context.close)
        self.context.add_init_script("localStorage.setItem('literature-ui-locale','en-US')")
        self.context.route("**/api/v1/**", self.api)
        self.page = self.context.new_page()
        self.page.set_default_timeout(7000)
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))

    def api(self, route):
        request = route.request
        path = urlparse(request.url).path
        if path == "/api/v1/auth/me":
            return route.fulfill(status=200 if self.signed_in else 401, json={"user": {
                "id": "audit-user", "username": "audit_user", "email": "audit@example.org"}, "csrf_token": "audit-csrf"})
        if path == "/api/v1/auth/login":
            self.signed_in = True
            return self.api_session(route)
        if path.endswith("/artifacts"):
            return route.fulfill(json={"items": [self.artifact]})
        if path == "/api/v1/tasks/" + TASK_ID:
            return route.fulfill(json=self.task)
        if path == "/api/v1/tasks":
            if request.method == "POST":
                self.posts.append((request.post_data_json, request.headers))
                return route.fulfill(status=202, json=self.task)
            return route.fulfill(json={"items": [self.task], "total": 1, "limit": 20, "offset": 0})
        if path == "/api/v1/papers":
            return route.fulfill(json={"items": PAPERS, "total": len(PAPERS), "limit": 20, "offset": 0})
        if path.endswith("/file"):
            return route.fulfill(content_type="application/pdf", body=b"%PDF-1.7\nfixture")
        if path.startswith("/api/v1/papers/"):
            paper = next((paper for paper in PAPERS if path.endswith(paper["id"])), None)
            return route.fulfill(status=200 if paper else 404, json=paper or {})
        return route.fulfill(status=404, json={})

    def api_session(self, route):
        return route.fulfill(json={"user": {"id": "audit-user", "username": "audit_user",
            "email": "audit@example.org"}, "csrf_token": "audit-csrf"})

    def open_task(self, query=""):
        self.page.goto(BASE + "/tasks/" + TASK_ID + query)
        expect(self.page.locator(".markdown")).to_be_visible()

    def test_partial_result_and_history_show_gaps(self):
        self.open_task()
        expect(self.page.locator(".task-overview .status-badge")).to_have_text("Partially completed")
        expect(self.page.get_by_text("Audit evidence gap.", exact=True)).to_be_visible()
        expect(self.page.locator(".ant-alert-warning")).to_be_visible()
        self.page.goto(BASE + "/tasks")
        expect(self.page.locator(".status-badge")).to_have_text("Partially completed")
        self.assertEqual(self.errors, [])

    def test_native_comparison_citation_returns_to_the_same_tab(self):
        self.open_task("?view=compare")
        expect(self.page.get_by_role("tab", name="Comparison", exact=True)).to_have_attribute("aria-selected", "true")
        self.page.locator(".markdown table .citation-trigger").click()
        expect(self.page.locator(".evidence-quote")).to_have_text("Verbatim evidence 2.")
        self.page.locator(".evidence-pdf-link").click()
        expect(self.page).to_have_url(re.compile(r"pdf_page=2"))
        self.page.locator(".reader-task-return").click()
        expect(self.page.get_by_role("tab", name="Comparison", exact=True)).to_have_attribute("aria-selected", "true")
        expect(self.page.locator(".evidence-quote")).to_have_text("Verbatim evidence 2.")
        self.assertEqual(self.errors, [])

    def test_english_interface_does_not_change_chinese_or_english_questions(self):
        for question in ("这篇论文提出了什么方法？", "What method does this paper propose?", "请比较 English benchmark 中的方法。"):
            with self.subTest(question=question):
                self.page.goto(BASE + "/tasks/new?paper_id=" + PAPERS[0]["id"])
                self.page.locator("textarea").fill(question)
                self.page.locator(".submission-summary button[type=submit]").click()
                expect(self.page.locator(".markdown")).to_be_visible()
                body, headers = self.posts[-1]
                self.assertEqual(body["question"], question)
                self.assertNotIn("output_language", body)
                self.assertEqual(headers["x-csrf-token"], "audit-csrf")
        self.assertEqual(self.errors, [])

    def test_legacy_comparison_and_retrieval_notice_remain_available(self):
        self.task["agent"] = None
        self.task["stage"] = "completed"
        self.task["retrieval"] = {"status": "partial", "missing_aspects": ["Legacy evidence gap."], "papers": []}
        self.artifact["comparison_markdown"] = None
        self.artifact["comparison_table"] = {"columns": [{"key": "method", "label": "Method"}],
            "rows": [{"paper_id": PAPERS[0]["id"], "cells": {
                "method": {"value": "Structured legacy result.", "citation_keys": ["C1"]}}}]}
        self.page.goto(BASE + "/tasks/" + TASK_ID + "?view=compare")
        expect(self.page.locator(".task-overview .status-badge")).to_have_text("Completed")
        expect(self.page.get_by_text("Legacy evidence gap.", exact=True)).to_be_visible()
        self.page.locator(".comparison-scroll .comparison-cell-trigger").click()
        expect(self.page.locator(".evidence-quote")).to_have_text("Verbatim evidence 1.")
        self.assertEqual(self.errors, [])

    def test_completed_agent_still_discloses_unresolved_items(self):
        self.task["stage"] = "completed"
        self.task["agent"]["stop_reason"] = "completed"
        self.open_task()
        expect(self.page.locator(".task-overview .status-badge")).to_have_text("Completed")
        expect(self.page.get_by_text("Audit evidence gap.", exact=True)).to_be_visible()
        expect(self.page.locator(".ant-alert-warning")).to_be_visible()
        self.assertEqual(self.errors, [])

    def test_public_http_login_and_task_submission(self):
        self.signed_in = False
        def proxy(route):
            parsed = urlparse(route.request.url)
            response = route.fetch(url=BASE + parsed.path + ("?" + parsed.query if parsed.query else ""))
            route.fulfill(response=response)
        self.context.route("http://acs-audit.invalid/**", proxy)
        self.context.route("**/api/v1/**", self.api)
        self.page.goto("http://acs-audit.invalid/login?next=/tasks/new?paper_id=" + PAPERS[0]["id"])
        self.page.locator("#auth-username").fill("audit_user")
        self.page.locator("#auth-password").fill("123456")
        self.page.locator(".auth-form button[type=submit]").click()
        expect(self.page.locator(".submission-summary button[type=submit]")).to_be_visible()
        self.assertFalse(self.page.evaluate("window.isSecureContext"))
        self.page.locator(".submission-summary button[type=submit]").click()
        expect(self.page.locator(".markdown")).to_be_visible()
        self.assertEqual(len(self.posts), 1)
        self.assertRegex(self.posts[0][1]["idempotency-key"], r"^[0-9a-f-]{36}$")
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
