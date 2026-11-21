"""Offline regressions for research submission recovery and account-scoped drafts."""
import os
import unittest
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(ROOT / 'runtime/pw-browsers'))
BASE = os.environ.get('AGENT_PREVIEW_URL', 'http://127.0.0.1:5199')
PAPER_ID = '11111111-1111-4111-8111-111111111111'
TASK_ID = '22222222-2222-4222-8222-222222222222'
PAPER = dict(id=PAPER_ID, title='Research draft fixture', original_filename='fixture.pdf',
    status='ready', page_count=3, size_bytes=100, source=None,
    created_at='2026-11-20T10:00:00Z', updated_at='2026-11-20T10:00:00Z')


class ResearchDraftTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.driver = sync_playwright().start()
        cls.browser = cls.driver.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.driver.stop()

    def setUp(self):
        self.context = self.browser.new_context(viewport=dict(width=1440, height=1000), reduced_motion='reduce')
        self.context.add_init_script("localStorage.setItem('literature-v3-ui-locale','en-US')")
        self.user = 'alice'
        self.fail_submission = True
        self.missing_paper = False
        self.calls = []
        self.errors = []
        self.context.route('**/api/v1/**', self.respond)
        self.page = self.context.new_page()
        self.page.set_default_timeout(7000)
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])

    def respond(self, route):
        request = route.request
        path = urlparse(request.url).path
        if path == '/api/v1/auth/me':
            return route.fulfill(json=dict(user=dict(id=self.user, username=self.user, email=self.user + '@example.org'), csrf_token='fixture'))
        if path == '/api/v1/auth/logout':
            return route.fulfill(status=204)
        if path == '/api/v1/papers':
            return route.fulfill(json=dict(items=[] if self.missing_paper else [PAPER], total=0 if self.missing_paper else 1, limit=20, offset=0))
        if path == '/api/v1/papers/' + PAPER_ID:
            if self.missing_paper:
                return route.fulfill(status=404, json=dict(error=dict(code='PAPER_NOT_FOUND', message='Fixture paper removed', details={})))
            return route.fulfill(json=PAPER)
        if path == '/api/v1/papers/' + PAPER_ID + '/file':
            return route.fulfill(content_type='application/pdf', body=b'%PDF-1.4\n%%EOF\n')
        if path == '/api/v1/agent-research' and request.method == 'POST':
            self.calls.append(dict(body=request.post_data_json, key=request.header_value('idempotency-key')))
            if self.fail_submission:
                return route.fulfill(status=503, json=dict(error=dict(code='SERVICE_NOT_READY', message='Fixture response lost', details={})))
            return route.fulfill(status=202, json=dict(task_id=TASK_ID, status='queued'))
        if path == '/api/v1/agent-research/' + TASK_ID:
            return route.fulfill(json=dict(task_id=TASK_ID, question='Fixture question', status='queued', paper_ids=[PAPER_ID], result=None, error=None))
        raise AssertionError('Unexpected API request: ' + request.method + ' ' + path)

    def open_draft(self):
        self.page.goto(BASE + '/tasks/new')
        expect(self.page.locator('textarea')).to_be_enabled()

    def select_paper(self):
        self.page.get_by_role('checkbox', name='Select paper ' + PAPER['title'], exact=True).check()

    def submit_failure(self):
        count = len(self.calls)
        self.page.locator('.research-submit-panel button[type="submit"]').click()
        expect(self.page.get_by_text('Fixture response lost', exact=True).first).to_be_visible()
        expect(self.page.locator('.research-submit-panel button[type="submit"]')).to_be_enabled()
        self.assertEqual(len(self.calls), count + 1)

    def assert_key(self, key):
        self.assertRegex(key or '', r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')

    def test_submission_retries_and_reload_reuse_key(self):
        self.open_draft()
        self.select_paper()
        self.page.locator('textarea').fill('Research question')
        self.submit_failure()
        self.submit_failure()
        self.assert_key(self.calls[0]['key'])
        self.assertEqual(self.calls[0], self.calls[1])
        self.page.reload()
        expect(self.page.locator('textarea')).to_have_value('Research question')
        expect(self.page.get_by_role('checkbox', name='Select paper ' + PAPER['title'], exact=True)).to_be_checked()
        self.submit_failure()
        self.assertEqual(self.calls[0], self.calls[2])

    def test_changed_question_or_selection_uses_new_key(self):
        self.open_draft()
        self.page.locator('textarea').fill('First question')
        self.submit_failure()
        self.page.locator('textarea').fill('Changed question')
        self.submit_failure()
        self.select_paper()
        self.submit_failure()
        keys = [call['key'] for call in self.calls]
        for key in keys:
            self.assert_key(key)
        self.assertEqual(len(set(keys)), 3)

    def test_pdf_round_trip_and_refresh_restore_draft(self):
        self.open_draft()
        self.select_paper()
        self.page.locator('textarea').fill('Keep this research question')
        self.page.locator('.paper-name').get_by_role('link', name=PAPER['title'], exact=True).click()
        expect(self.page.locator('.paper-reader')).to_be_visible()
        self.page.go_back()
        expect(self.page.locator('textarea')).to_have_value('Keep this research question')
        expect(self.page.get_by_role('checkbox', name='Select paper ' + PAPER['title'], exact=True)).to_be_checked()
        self.page.reload()
        expect(self.page.locator('textarea')).to_have_value('Keep this research question')
        expect(self.page.get_by_role('checkbox', name='Select paper ' + PAPER['title'], exact=True)).to_be_checked()

    def test_success_clears_draft_and_next_submission_has_new_key(self):
        self.open_draft()
        self.page.locator('textarea').fill('Research question')
        self.fail_submission = False
        self.page.locator('.research-submit-panel button[type="submit"]').click()
        self.page.wait_for_url('**/tasks/' + TASK_ID)
        self.open_draft()
        expect(self.page.locator('textarea')).to_have_value('')
        self.page.locator('textarea').fill('Research question')
        self.page.locator('.research-submit-panel button[type="submit"]').click()
        self.page.wait_for_url('**/tasks/' + TASK_ID)
        self.assertNotEqual(self.calls[0]['key'], self.calls[1]['key'])

    def test_drafts_are_account_scoped(self):
        self.open_draft()
        self.select_paper()
        self.page.locator('textarea').fill('Alice private question')
        self.user = 'bob'
        self.page.reload()
        expect(self.page.locator('textarea')).to_have_value('')
        expect(self.page.get_by_role('checkbox', name='Select paper ' + PAPER['title'], exact=True)).not_to_be_checked()

    def test_logout_clears_draft(self):
        self.open_draft()
        self.page.locator('textarea').fill('Discard on logout')
        self.page.evaluate('window.scrollTo(0, 0)')
        self.page.get_by_role('button', name='alice', exact=True).click()
        self.page.get_by_role('menuitem', name='Log out', exact=True).press('Enter')
        self.page.wait_for_url('**/login?**')
        self.open_draft()
        expect(self.page.locator('textarea')).to_have_value('')

    def test_deleted_paper_is_removed_from_restored_draft(self):
        self.open_draft()
        self.select_paper()
        self.page.locator('textarea').fill('Question without removed paper')
        self.missing_paper = True
        self.page.reload()
        expect(self.page.locator('textarea')).to_have_value('Question without removed paper')
        expect(self.page.locator('.research-submit-panel button[type="submit"]')).to_be_enabled()
        self.submit_failure()
        self.assertEqual(self.calls[0]['body']['paper_ids'], [])

    def test_unavailable_storage_does_not_break_submission_retry(self):
        self.context.add_init_script("Object.defineProperty(window, 'sessionStorage', {get() { throw new Error('Storage unavailable'); }});")
        self.open_draft()
        self.page.locator('textarea').fill('Storage unavailable')
        self.submit_failure()
        self.submit_failure()
        self.assert_key(self.calls[0]['key'])
        self.assertEqual(self.calls[0], self.calls[1])

    def test_preselected_url_does_not_override_edited_draft(self):
        self.page.goto(BASE + '/tasks/new?paper_id=' + PAPER_ID)
        checkbox = self.page.get_by_role('checkbox', name='Select paper ' + PAPER['title'], exact=True)
        expect(checkbox).to_be_checked()
        checkbox.uncheck()
        self.page.locator('textarea').fill('Keep the updated selection')
        self.page.locator('.paper-name').get_by_role('link', name=PAPER['title'], exact=True).click()
        expect(self.page.locator('.paper-reader')).to_be_visible()
        self.page.go_back()
        expect(self.page.locator('textarea')).to_have_value('Keep the updated selection')
        expect(checkbox).not_to_be_checked()

    def test_cross_tab_auth_event_discards_draft(self):
        self.open_draft()
        self.page.locator('textarea').fill('Discard on account event')
        self.page.evaluate("window.dispatchEvent(new StorageEvent('storage', {key:'literature-v3-auth',newValue:'fixture-auth-change'}))")
        expect(self.page.locator('textarea')).to_have_value('')


if __name__ == '__main__':
    unittest.main()
