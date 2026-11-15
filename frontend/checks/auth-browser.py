"""Offline browser auth checks; no backend, email, or model access."""
import os
import runpy
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(ROOT / 'runtime/pw-browsers')
BASE = os.environ.get('AUTH_PREVIEW_URL', 'http://127.0.0.1:5193')
PASSWORD = 'ab_123'
USER = {'id': 'account-a', 'username': 'researcher_a', 'email': 'a@example.org'}
OTHER = {'id': 'account-b', 'username': 'researcher_b', 'email': 'b@example.org'}
FIXTURES = runpy.run_path(str(ROOT / 'frontend/checks/review-browser.py'))
PAPERS = FIXTURES['PAPERS']
TASK = {**FIXTURES['TASK'], 'status': 'running', 'stage': 'running'}


def main():
    with sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 390, 'height': 844})
        context.add_init_script("localStorage.setItem('literature-ui-locale', 'en-US')")
        state = {'user': None, 'csrf': 'csrf-a', 'user_papers': 1, 'expire': False, 'hold': False, 'hold_logout': False, 'hold_me': True}
        calls, errors, held, canceled, external, logouts, sessions = [], [], [], [], [], [], []

        def api(route):
            request = route.request
            path = urlparse(request.url).path
            data = request.post_data_json if request.method == 'POST' else None
            calls.append((path, data, request.headers))
            if path == '/api/v1/auth/me':
                if state['hold_me']:
                    sessions.append(route)
                    return
                return route.fulfill(status=200 if state['user'] else 401, json={'user': state['user'], 'csrf_token': state['csrf']})
            if path == '/api/v1/auth/login':
                if data['password'] == 'invalid password':
                    return route.fulfill(status=401, json={'error': {'code': 'INVALID_CREDENTIALS'}})
                state['user'] = USER
                return route.fulfill(json={'user': USER, 'csrf_token': state['csrf']}, headers={'Set-Cookie': 'session=a; HttpOnly; SameSite=Lax; Path=/'})
            if path in ['/api/v1/auth/logout', '/api/v1/auth/change-password']:
                assert request.headers.get('x-csrf-token') == state['csrf']
                assert 'session=a' in request.headers.get('cookie', '')
                if path.endswith('/logout') and state['hold_logout']:
                    logouts.append(route)
                    return
                state['user'] = None
                return route.fulfill(status=204)
            if path.startswith('/api/v1/auth/'):
                assert request.headers.get('content-type', '').startswith('application/json')
                assert request.headers.get('origin') == BASE
                assert request.headers.get('accept-language') == 'en-US'
                assert 'user_id' not in data
                if path.endswith('/reset-password') and data['token'] == 'expired-secret':
                    return route.fulfill(status=401, json={'error': {'code': 'INVALID_TOKEN'}})
                status = 202 if path.endswith(('register', 'forgot-password', 'resend-verification')) else 200
                return route.fulfill(status=status, json={})
            assert state['user'], 'Private API requested while logged out'
            if state['expire']:
                state['user'] = None
                return route.fulfill(status=401, json={})
            if path == '/api/v1/papers':
                if state['hold']:
                    held.append(route)
                    return
                papers = PAPERS[:state['user_papers']] if state['user'] == USER else []
                return route.fulfill(json={'items': papers, 'total': len(papers), 'limit': 20, 'offset': 0})
            if path == '/api/v1/paper-imports':
                return route.fulfill(json={'items': [], 'total': 0, 'limit': 20, 'offset': 0})
            if path.startswith('/api/v1/papers/'):
                return route.fulfill(json=next(paper for paper in PAPERS if path.endswith(paper['id'])))
            if path == '/api/v1/tasks' and request.method == 'POST':
                assert request.headers.get('x-csrf-token') == state['csrf']
                assert 'user_id' not in data
                assert 'budget' not in data
                return route.fulfill(status=503, json={})
            if path.startswith('/api/v1/tasks/'):
                if state['user'] != USER:
                    return route.fulfill(status=404, json={})
                if path.endswith('/events'):
                    return route.fulfill(json={'items': [], 'next_after_seq': 0, 'has_more': False})
                return route.fulfill(json=TASK)
            raise AssertionError('Unexpected API request: ' + path)

        def network(route):
            if urlparse(route.request.url).netloc != urlparse(BASE).netloc:
                external.append(route.request.url)
                return route.abort()
            return route.continue_()

        context.route('**/*', network)
        context.route('**/api/v1/**', api)
        page = context.new_page()
        page.set_default_timeout(6000)
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('requestfailed', lambda request: canceled.append(request.url))
        page.goto(BASE + '/tasks/new?draft=private')
        expect(page.get_by_role('status')).to_contain_text('Checking your sign-in status')
        assert not [call for call in calls if '/auth/' not in call[0]]
        state['hold_me'] = False
        for route in sessions:
            route.fulfill(status=401, json={})
        expect(page).to_have_url(BASE + '/login?next=%2Ftasks%2Fnew%3Fdraft%3Dprivate')
        assert not [call for call in calls if '/auth/' not in call[0]]
        page.get_by_role('link', name='Create account', exact=True).click()
        page.get_by_label('Username', exact=True).fill('bad-name')
        page.get_by_label('Email', exact=True).fill('invalid-email')
        page.get_by_label('Password', exact=True).fill('short')
        page.get_by_label('Confirm password', exact=True).fill('different')
        page.get_by_role('button', name='Create account', exact=True).click()
        expect(page.get_by_role('alert').first).to_be_visible()
        expect(page.get_by_text('Passwords do not match.', exact=True)).to_be_visible()
        expect(page.get_by_text('Enter a valid email address.', exact=True)).to_be_visible()
        assert not any(call[0].endswith('/register') for call in calls)
        page.get_by_label('Username', exact=True).fill(USER['username'])
        page.get_by_label('Email', exact=True).fill('a@example.org')
        page.get_by_label('Password', exact=True).fill(PASSWORD)
        page.get_by_label('Confirm password', exact=True).fill(PASSWORD)
        page.get_by_role('button', name='Create account', exact=True).click()
        expect(page.get_by_text('Check your email', exact=True)).to_be_visible()
        assert next(call[1] for call in calls if call[0].endswith('/register'))['password'] == PASSWORD
        expect(page.get_by_role('button', name='Resend verification', exact=True)).to_be_visible()
        page.get_by_role('button', name='Resend verification', exact=True).click()
        expect(page.get_by_role('status')).to_contain_text('If this address is eligible')
        page.goto(BASE + '/verify-email#token=verification-secret')
        expect(page).to_have_url(BASE + '/verify-email')
        assert not any(call[0].endswith('/verify-email') for call in calls)
        page.get_by_label('Original password', exact=True).fill(PASSWORD)
        page.get_by_role('button', name='Verify email', exact=True).click()
        expect(page.get_by_role('status')).to_contain_text('Email verified')
        assert next(call[1] for call in calls if call[0].endswith('/verify-email')) == {'token': 'verification-secret', 'password': PASSWORD}
        page.goto(BASE + '/login?next=https%3A%2F%2Fevil.invalid')
        page.get_by_label('Username', exact=True).fill(USER['username'])
        page.get_by_label('Password', exact=True).fill('invalid password')
        page.get_by_role('button', name='Log in', exact=True).click()
        expect(page.get_by_role('alert')).to_contain_text('Username or password is incorrect')
        expect(page).to_have_url(BASE + '/login?next=https%3A%2F%2Fevil.invalid')
        page.get_by_label('Password', exact=True).fill(PASSWORD)
        page.get_by_role('button', name='Log in', exact=True).click()
        expect(page).to_have_url(BASE + '/papers')
        expect(page.get_by_role('button', name=USER['username'], exact=True)).to_be_visible()
        get_paper_rows = page.locator('.ant-table-tbody tr[data-row-key]')
        expect(get_paper_rows).to_have_count(1)
        for task_type, label, count in (("summary", "Paper summary", 1), ("qa", "Paper Q&A", 1), ("review", "Literature review", 2)):
            page.goto(BASE + '/tasks/new?' + '&'.join('paper_id=' + paper['id'] for paper in PAPERS[:count]))
            page.get_by_text(label, exact=True).click()
            expect(page.get_by_role('heading', name='Automatic execution', exact=True)).to_be_visible()
            expect(page.get_by_role('spinbutton')).to_have_count(0)
            page.locator('textarea').first.fill('Compare methods')
            page.get_by_role('button', name='Create research task').click()
            expect(page.get_by_role('alert')).to_be_visible()
            submitted = [call[1] for call in calls if call[0] == '/api/v1/tasks'][-1]
            assert submitted['task_type'] == task_type and 'budget' not in submitted
        page.goto(BASE + '/tasks/new')
        page.locator('textarea').first.fill('A private unsaved draft')
        state['hold_logout'] = True
        page.get_by_role('button', name=USER['username'], exact=True).click()
        page.get_by_role('menuitem', name='Log out', exact=True).click()
        expect(page.locator('textarea')).to_have_count(0)
        assert logouts
        state.update(user=None, hold_logout=False)
        logouts.pop().fulfill(status=204)
        expect(page.get_by_role('heading', name='Log in', exact=True)).to_be_visible()
        page.get_by_label('Username', exact=True).fill(USER['username'])
        page.get_by_label('Password', exact=True).fill(PASSWORD)
        page.get_by_role('button', name='Log in', exact=True).click()
        expect(page.locator('textarea').first).to_have_value('')
        expect(page.get_by_role('button', name=USER['username'], exact=True)).to_be_visible()
        other_tab = context.new_page()
        other_tab.goto(BASE + '/forgot-password')
        expect(other_tab.get_by_role('heading', name='Forgot password', exact=True)).to_be_visible()
        page.locator('textarea').first.fill('Must clear on account change')
        state['hold'] = True
        page.get_by_role('searchbox').fill('pending old request')
        page.get_by_role('searchbox').press('Enter')
        page.wait_for_timeout(100)
        assert held, 'Expected an in-flight private request'
        state.update(user=OTHER, csrf='csrf-b')
        state['hold'] = False
        other_tab.evaluate("new BroadcastChannel('literature-auth').postMessage(crypto.randomUUID())")
        expect(page.get_by_role('button', name=OTHER['username'], exact=True)).to_be_visible()
        expect(page.locator('textarea').first).to_have_value('')
        assert any('/api/v1/papers?' in url for url in canceled), 'Old private request must be canceled'
        for route in held:
            route.fulfill(json={'items': PAPERS[:1], 'total': 1, 'limit': 20, 'offset': 0})
        page.goto(BASE + '/papers')
        expect(page.locator('.ant-table-tbody tr[data-row-key]')).to_have_count(0)
        state.update(user=USER, csrf='csrf-storage')
        other_tab.evaluate("localStorage.setItem('literature-auth', crypto.randomUUID())")
        expect(page.get_by_role('button', name=USER['username'], exact=True)).to_be_visible()
        expect(page.locator('.ant-table-tbody tr[data-row-key]')).to_have_count(1)
        other_tab.close()
        state.update(user=OTHER, expire=True)
        page.goto(BASE + '/papers')
        expect(page.get_by_role('heading', name='Log in', exact=True)).to_be_visible()
        state.update(user=None, expire=False)
        page.goto(BASE + '/reset-password#token=expired-secret')
        page.get_by_label('New password', exact=True).fill(PASSWORD)
        page.get_by_label('Confirm password', exact=True).fill(PASSWORD)
        page.get_by_role('button', name='Reset password', exact=True).click()
        expect(page.get_by_role('alert')).to_contain_text('The link is invalid or expired')
        expect(page).to_have_url(BASE + '/reset-password')
        for path in ['/forgot-password', '/reset-password#token=reset-secret']:
            page.goto(BASE + path)
            if path.startswith('/forgot'):
                page.get_by_label('Email', exact=True).fill('unknown@example.org')
                page.get_by_role('button', name='Send reset link', exact=True).click()
                expect(page.get_by_role('status')).to_contain_text('If this address is eligible')
            else:
                expect(page).to_have_url(BASE + '/reset-password')
                page.get_by_label('New password', exact=True).fill(PASSWORD)
                page.get_by_label('Confirm password', exact=True).fill(PASSWORD)
                page.get_by_role('button', name='Reset password', exact=True).click()
                expect(page.get_by_role('status')).to_contain_text('Password updated')
                assert [call[1] for call in calls if call[0].endswith('/reset-password')][-1] == {'token': 'reset-secret', 'password': PASSWORD}
        page.goto(BASE + '/login')
        page.get_by_label('Username', exact=True).fill(USER['username'])
        page.get_by_label('Password', exact=True).fill(PASSWORD)
        page.get_by_role('button', name='Log in', exact=True).click()
        page.goto(BASE + '/account/password')
        page.get_by_label('Current password', exact=True).fill(PASSWORD)
        page.get_by_label('New password', exact=True).fill('654321')
        page.get_by_label('Confirm password', exact=True).fill('654321')
        page.get_by_role('button', name='Change password', exact=True).click()
        expect(page.get_by_role('heading', name='Log in', exact=True)).to_be_visible()
        change = next(call for call in calls if call[0].endswith('/change-password'))
        assert change[1]['current_password'] == PASSWORD and change[1]['password'] == '654321'
        assert change[2].get('x-csrf-token')
        page.get_by_label('Username', exact=True).fill(USER['username'])
        page.get_by_label('Password', exact=True).fill(PASSWORD)
        page.get_by_role('button', name='Log in', exact=True).click()
        expect(page.get_by_role('button', name=USER['username'], exact=True)).to_be_visible()
        task_call_offset = len(calls)
        state['user_papers'] = 2
        task_inputs = '/tasks/new?' + '&'.join('paper_id=' + paper['id'] for paper in PAPERS[:2])
        page.goto(BASE + task_inputs)
        page.locator('textarea').first.fill('Compare these papers')
        create = page.locator('.submission-summary button')
        create.click()
        expect(page.locator('.submission-error')).to_be_visible()
        create.click()
        page.wait_for_timeout(100)
        old_keys = [call[2]['idempotency-key'] for call in calls[task_call_offset:] if call[0].endswith('/tasks')]
        assert len(old_keys) == 2 and old_keys[0] == old_keys[1]
        page.evaluate("new BroadcastChannel('literature-auth').postMessage(crypto.randomUUID())")
        expect(page.locator('textarea').first).to_have_value('')
        page.locator('textarea').first.fill('Compare these papers')
        create.click()
        expect(page.locator('.submission-error')).to_be_visible()
        new_keys = [call[2]['idempotency-key'] for call in calls[task_call_offset:] if call[0].endswith('/tasks')]
        assert len(new_keys) == 3 and new_keys[2] != old_keys[0]
        page.goto(BASE + '/tasks/' + TASK['id'])
        expect(page.locator('.task-overview .status-running')).to_be_visible()
        state.update(user=OTHER, csrf='csrf-other')
        page.evaluate("new BroadcastChannel('literature-auth').postMessage(crypto.randomUUID())")
        expect(page.get_by_role('button', name=OTHER['username'], exact=True)).to_be_visible()
        expect(page.locator('.task-overview .status-running')).to_have_count(0)
        page.wait_for_timeout(200)
        stopped_count = len([call for call in calls if call[0].startswith('/api/v1/tasks/')])
        page.wait_for_timeout(2200)
        assert stopped_count == len([call for call in calls if call[0].startswith('/api/v1/tasks/')]), 'Old task polling must stop'
        page.get_by_role('button', name=OTHER['username'], exact=True).click()
        page.get_by_role('menuitem', name='Log out', exact=True).click()
        expect(page.get_by_role('heading', name='Log in', exact=True)).to_be_visible()
        private_writes = [call for call in calls if call[0].endswith('/auth/logout')]
        assert private_writes and all(call[2].get('x-csrf-token') for call in private_writes)
        for path in ['/login', '/register', '/verify-email', '/forgot-password', '/reset-password']:
            page.goto(BASE + path)
            for width in [320, 390, 768, 1440]:
                page.set_viewport_size({'width': width, 'height': 900})
                page.wait_for_function('document.documentElement.scrollWidth <= innerWidth')
        page.get_by_role('combobox', name='界面语言 / Interface language').select_option('zh-CN')
        expect(page.get_by_role('heading', name='重置密码', exact=True)).to_be_visible()
        assert not errors, errors
        assert not external, external
        browser.close()
        print('PASS: private routes, bilingual registration, verify/reset fragments, login, CSRF logout/change, 401 expiry, cross-tab state clearing and 320–1440px layouts; mocked API only.')


if __name__ == '__main__':
    main()
