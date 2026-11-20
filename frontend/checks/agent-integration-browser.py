"""Offline V3 API regressions; no legacy fixtures or live services are used."""
import copy
import os
import re
import unittest
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(ROOT / 'runtime/pw-browsers'))
BASE = os.environ.get('AGENT_PREVIEW_URL', 'http://127.0.0.1:5199')
TASK_ID = '22222222-2222-4222-8222-222222222222'
PAPER_ID = '11111111-1111-4111-8111-111111111111'
PAPER = dict(id=PAPER_ID, title='Native Agent fixture', original_filename='fixture.pdf',
    status='ready', page_count=3, size_bytes=100, source=None,
    created_at='2026-11-20T10:00:00Z', updated_at='2026-11-20T10:00:00Z')
RESULT = dict(task_id=TASK_ID, question='Fixture question', answer='## Audit answer\n\nSupported result. [chunk-1]',
    comparison_table='| Paper | Evidence |\n| --- | --- |\n| Example | [chunk-2] |',
    citations=[dict(chunk_id='chunk-' + str(index), source_id='source-1', paper_id=PAPER_ID,
        title=PAPER['title'], page=index, source_text='Verbatim evidence ' + str(index) + '.', url='') for index in (1, 2)],
    sources=[dict(paper_id=PAPER_ID, source_id='source-1', title=PAPER['title'], url='')],
    unresolved=['Audit evidence gap.'], stop_reason='partial', usage={}, trace=[], errors=[], configuration={})


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
        self.record = dict(task_id=TASK_ID, status='succeeded', question='Fixture question',
            paper_ids=[PAPER_ID], result=copy.deepcopy(RESULT), error=None)
        self.posts = []
        self.errors = []
        self.signed_in = True
        self.context = self.browser.new_context(viewport=dict(width=1440, height=1000), reduced_motion='reduce')
        self.addCleanup(self.context.close)
        self.context.add_init_script("localStorage.setItem('literature-v3-ui-locale','en-US')")
        self.context.route('**/api/v1/**', self.api)
        self.page = self.context.new_page()
        self.page.set_default_timeout(7000)
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def api(self, route):
        request = route.request
        path = urlparse(request.url).path
        if path == '/api/v1/auth/me':
            return self.session(route) if self.signed_in else route.fulfill(status=401, json={})
        if path == '/api/v1/auth/login':
            self.signed_in = True
            return self.session(route)
        if path == '/api/v1/agent-research':
            if request.method == 'POST':
                self.posts.append((request.post_data_json, request.headers))
                return route.fulfill(status=202, json=dict(task_id=TASK_ID, status='queued'))
            return route.fulfill(json=dict(items=[dict(id=TASK_ID, question=self.record['question'],
                paper_ids=[PAPER_ID], papers=[dict(id=PAPER_ID, title=PAPER['title'])],
                status=self.record['status'], created_at=PAPER['created_at'])], total=1, limit=20, offset=0))
        if path == '/api/v1/agent-research/' + TASK_ID:
            return route.fulfill(json=self.record)
        if path == '/api/v1/papers':
            return route.fulfill(json=dict(items=[PAPER], total=1, limit=20, offset=0))
        if path == '/api/v1/papers/' + PAPER_ID:
            return route.fulfill(json=PAPER)
        if path == '/api/v1/papers/' + PAPER_ID + '/file':
            return route.fulfill(content_type='application/pdf', body=b'%PDF-1.7\nfixture')
        raise AssertionError('Unexpected API: ' + request.method + ' ' + path)

    def session(self, route):
        return route.fulfill(json=dict(user=dict(id='audit-user', username='audit_user', email='audit@example.org'), csrf_token='audit-csrf'))

    def open_task(self):
        self.page.goto(BASE + '/tasks/' + TASK_ID)
        expect(self.page.get_by_role('heading', name='Audit answer', exact=True)).to_be_visible()

    def test_partial_results_disclose_gaps_and_history(self):
        self.open_task()
        expect(self.page.get_by_text('Some questions remain unresolved', exact=True)).to_be_visible()
        self.page.get_by_role('tab', name='Open questions', exact=True).click()
        expect(self.page.get_by_text('Audit evidence gap.', exact=True)).to_be_visible()
        self.page.goto(BASE + '/tasks')
        expect(self.page.get_by_role('link', name='Fixture question', exact=True)).to_be_visible()

    def test_native_comparison_citation_returns_to_same_evidence(self):
        self.open_task()
        self.page.get_by_role('tab', name='Comparison', exact=True).click()
        self.page.locator('.research-markdown table .citation-trigger').click()
        expect(self.page.locator('.evidence-quote')).to_have_text('Verbatim evidence 2.')
        self.page.get_by_role('button', name='Open PDF page', exact=True).click()
        expect(self.page).to_have_url(re.compile(r'pdf_page=2'))
        self.page.locator('.reader-task-return').click()
        expect(self.page.locator('.evidence-quote')).to_have_text('Verbatim evidence 2.')
        self.assertEqual(len(self.context.pages), 1)

    def test_interface_language_does_not_rewrite_question(self):
        for question in ('这篇论文提出了什么方法？', 'What method does this paper propose?', '请比较 English benchmark 中的方法。'):
            with self.subTest(question=question):
                self.page.goto(BASE + '/tasks/new?paper_id=' + PAPER_ID)
                expect(self.page.locator('textarea')).to_be_enabled()
                self.page.locator('textarea').fill(question)
                self.page.locator('.research-submit-panel button[type=submit]').click()
                expect(self.page.get_by_role('heading', name='Audit answer', exact=True)).to_be_visible()
                body, headers = self.posts[-1]
                self.assertEqual(body, dict(question=question, paper_ids=[PAPER_ID], allow_search=True))
                self.assertEqual(headers['x-csrf-token'], 'audit-csrf')
                self.assertRegex(headers['idempotency-key'], r'^[0-9a-f-]{36}$')

    def test_queued_running_and_failed_states(self):
        for status in ('queued', 'running', 'failed'):
            with self.subTest(status=status):
                self.record.update(status=status, result=None, error=dict(code='AGENT_EXECUTION_FAILED', message='Fixture failure'))
                self.page.goto(BASE + '/tasks/' + TASK_ID)
                if status == 'failed':
                    expect(self.page.get_by_text('Fixture failure', exact=True)).to_be_visible()
                    expect(self.page.get_by_role('progressbar')).to_have_count(0)
                else:
                    expect(self.page.get_by_role('progressbar')).to_be_visible()
                    expect(self.page.locator('.research-markdown')).to_have_count(0)

    def test_completed_result_without_optional_tabs(self):
        self.record['result'].update(stop_reason='completed', unresolved=[], comparison_table='')
        self.open_task()
        expect(self.page.get_by_role('tab', name='Comparison', exact=True)).to_have_count(0)
        expect(self.page.get_by_role('tab', name='Open questions', exact=True)).to_have_count(0)
        expect(self.page.get_by_text('Some questions remain unresolved', exact=True)).to_have_count(0)

    def test_public_http_login_and_submission(self):
        self.signed_in = False

        def proxy(route):
            parsed = urlparse(route.request.url)
            response = route.fetch(url=BASE + parsed.path + ('?' + parsed.query if parsed.query else ''))
            route.fulfill(response=response)

        self.context.route('http://acs-audit.invalid/**', proxy)
        self.context.route('**/api/v1/**', self.api)
        self.page.goto('http://acs-audit.invalid/login?next=' + '/tasks/new?paper_id=' + PAPER_ID)
        self.page.locator('#auth-username').fill('audit_user')
        self.page.locator('#auth-password').fill('123456')
        self.page.locator('.auth-form button[type=submit]').click()
        expect(self.page.locator('textarea')).to_be_enabled()
        self.assertFalse(self.page.evaluate('window.isSecureContext'))
        self.page.locator('textarea').fill('What method is supported?')
        self.page.locator('.research-submit-panel button[type=submit]').click()
        expect(self.page.get_by_role('heading', name='Audit answer', exact=True)).to_be_visible()
        self.assertEqual(len(self.posts), 1)
        self.assertRegex(self.posts[0][1]['idempotency-key'], r'^[0-9a-f-]{36}$')


if __name__ == '__main__':
    unittest.main(verbosity=2)
