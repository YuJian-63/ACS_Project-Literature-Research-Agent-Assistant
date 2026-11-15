"""Offline evidence-to-reader navigation with local three-page PDF fixtures."""
import os
import re
import runpy
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(ROOT / 'runtime/pw-browsers')
BASE = os.environ.get('EVIDENCE_PREVIEW_URL', 'http://127.0.0.1:5196')
FIXTURES = runpy.run_path(str(ROOT / 'frontend/checks/workspace-browser.py'))
PDF = runpy.run_path(str(ROOT / 'frontend/checks/library-reader-browser.py'))['pdf_fixture'](3)
PAPERS = FIXTURES['PAPERS']


def main():
    state = {'kind': 'summary'}
    errors, external = [], []
    with sync_playwright() as driver:
        options = {'channel': os.environ['PDF_BROWSER_CHANNEL']} if os.environ.get('PDF_BROWSER_CHANNEL') else {}
        browser = driver.chromium.launch(headless=True, **options)
        context = browser.new_context(reduced_motion='reduce')

        def api(route):
            path = urlparse(route.request.url).path
            if path == '/api/v1/auth/me':
                data = {'user': {'id': 'fixture', 'username': 'Researcher', 'email': 'r@example.org'}, 'csrf_token': 'fixture'}
            elif path == '/api/v1/papers':
                data = {'items': PAPERS, 'total': len(PAPERS), 'limit': 20, 'offset': 0}
            elif path.endswith('/file'):
                return route.fulfill(content_type='application/pdf', body=PDF)
            elif path.startswith('/api/v1/papers/'):
                data = next(paper for paper in PAPERS if path.endswith(paper['id']))
            elif path.endswith('/artifacts'):
                data = {'items': [{**FIXTURES['ARTIFACT'], 'task_type': state['kind'], 'comparison_table': FIXTURES['ARTIFACT']['comparison_table'] if state['kind'] == 'review' else None}]}
            elif path.endswith('/events'):
                data = {'items': [], 'next_after_seq': 0, 'has_more': False}
            elif path == '/api/v1/tasks/' + FIXTURES['TASK']['id']:
                data = {**FIXTURES['TASK'], 'task_type': state['kind']}
            else:
                raise AssertionError(path)
            route.fulfill(json=data)

        def network(route):
            if urlparse(route.request.url).netloc != urlparse(BASE).netloc:
                external.append(route.request.url)
                return route.abort()
            return route.continue_()

        context.route('**/*', network)
        context.route('**/api/v1/**', api)
        page = context.new_page()
        page.set_default_timeout(7000)
        page.on('pageerror', lambda error: errors.append(str(error)))
        reader = page.locator('.paper-reader')
        task_url = BASE + '/tasks/' + FIXTURES['TASK']['id']
        for locale in ['zh-CN', 'en-US']:
            page.goto(BASE + '/papers')
            page.evaluate('(locale) => localStorage.setItem("literature-ui-locale", locale)', locale)
            for kind in ['summary', 'qa', 'review']:
                state['kind'] = kind
                for width in [1440, 390]:
                    page.set_viewport_size({'width': width, 'height': 1050})
                    page.goto(task_url)
                    page.locator('.markdown .citation-trigger').last.click()
                    link = page.locator('.evidence-pdf-link')
                    destination = '/papers?paper_id=' + PAPERS[1]['id'] + '&pdf_page=3'
                    expect(link).to_have_attribute('href', re.compile('^' + re.escape(destination)))
                    assert link.get_attribute('target') is None
                    link.click()
                    expect(reader.get_by_role('heading', name=PAPERS[1]['title'], exact=True)).to_be_visible()
                    expect(reader.locator('iframe')).to_have_attribute('src', re.compile(r'#page=3&view=Fit$'))
                    expect(reader.locator('a[target="_blank"]')).to_have_attribute('href', re.compile(r'#page=3$'))
                    assert len(context.pages) == 1
                    page.reload()
                    expect(reader.locator('iframe')).to_have_attribute('src', re.compile(r'#page=3&view=Fit$'))
                    reader.get_by_role('button', name='返回任务' if locale == 'zh-CN' else 'Back to task', exact=True).click()
                    expect(page.locator('.markdown')).to_be_visible()
                    expect(page.locator('.evidence-quote:visible')).to_contain_text('paper 2')
                    expect(page.locator('.citation-chip:visible')).to_have_text('[C2]')
                    page.locator('.evidence-panel [role=tab], .evidence-drawer [role=tab]').nth(1).click()
                    input_link = page.locator('.evidence-papers a').first
                    expect(input_link).to_have_attribute('href', re.compile('^' + re.escape('/papers?paper_id=' + PAPERS[0]['id']) + '&'))
                    assert input_link.get_attribute('target') is None
                    input_link.click()
                    expect(reader.get_by_role('heading', name=PAPERS[0]['title'], exact=True)).to_be_visible()
                    expect(reader.locator('iframe')).to_have_attribute('src', re.compile(r'#page=1&view=Fit$'))
                    assert len(context.pages) == 1
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    reader.get_by_role('combobox').select_option(PAPERS[1]['id']) if width < 1001 else page.locator('.paper-reading-item > button').nth(1).click()
                    expect(reader.get_by_role('heading', name=PAPERS[1]['title'], exact=True)).to_be_visible()
                    page.reload()
                    reader.get_by_role('button', name='返回任务' if locale == 'zh-CN' else 'Back to task', exact=True).click()
                    expect(page.locator('.evidence-quote:visible')).to_contain_text('paper 2')
                    expect(page.locator('.citation-chip:visible')).to_have_text('[C2]')
                    page.goto(task_url)
                    if width < 1001:
                        page.locator('.mobile-evidence-button').click()
                    expect(page.locator('.citation-chip:visible')).to_have_text('[C1]')
                    print('PASS', locale, kind, width, 'citation page + input paper', flush=True)
        for width in [1440, 390]:
            page.set_viewport_size({'width': width, 'height': 1050})
            page.goto(task_url)
            page.get_by_role('tab', name='Comparison', exact=True).click()
            if width < 1001:
                page.locator('#comparison-paper').select_option(PAPERS[1]['id'])
                page.locator('.mobile-comparison .comparison-cell-trigger').first.click()
            else:
                page.locator('.comparison-scroll tbody tr').nth(1).locator('.comparison-cell-trigger').first.click()
            page.locator('.evidence-pdf-link:visible').click()
            expect(reader.locator('iframe')).to_have_attribute('src', re.compile(r'#page=3&view=Fit$'))
            reader.get_by_role('button', name='Back to task', exact=True).click()
            expect(page.get_by_role('tab', name='Comparison', exact=True)).to_have_attribute('aria-selected', 'true')
            expect(page.locator('.citation-chip:visible')).to_have_text('[C2]')
            print('PASS review comparison return', width, flush=True)
        page.set_viewport_size({'width': 1440, 'height': 1050})
        artifact_id = FIXTURES['ARTIFACT']['id']
        for artifact, citation in [(artifact_id, 'C999'), ('another-artifact', 'C2')]:
            page.goto(task_url + '?artifact_id=' + artifact + '&citation=' + citation + '&show_evidence=1')
            expect(page.locator('.citation-chip:visible')).to_have_text('[C1]')
        for invalid_task in ['', 'https%3A%2F%2Fexample.org', '..%2Ftasks']:
            page.goto(BASE + '/papers?paper_id=' + PAPERS[0]['id'] + '&return_task=' + invalid_task + '&return_artifact=' + artifact_id)
            expect(reader.locator('iframe')).to_be_visible()
            expect(reader.get_by_role('button', name='Back to task', exact=True)).to_have_count(0)
        for raw, expected in [('0', 1), ('-1', 1), ('abc', 1), ('1.5', 1), ('9007199254740992', 1), ('99', 3)]:
            page.goto(BASE + '/papers?paper_id=' + PAPERS[0]['id'] + '&pdf_page=' + raw)
            expect(reader.locator('iframe')).to_have_attribute('src', re.compile('#page=' + str(expected) + '&view=Fit$'))
            expect(reader.get_by_role('button', name='Back to task', exact=True)).to_have_count(0)
        page.set_viewport_size({'width': 390, 'height': 1050})
        page.goto(BASE + '/papers?paper_id=' + PAPERS[0]['id'] + '&pdf_page=3&selected_paper_id=' + PAPERS[0]['id'])
        expect(reader.locator('iframe')).to_have_attribute('src', re.compile(r'#page=3&view=Fit$'))
        reader.get_by_role('combobox').select_option(PAPERS[1]['id'])
        expect(reader.locator('iframe')).to_have_attribute('src', re.compile(r'#page=1&view=Fit$'))
        query = parse_qs(urlparse(page.url).query)
        assert 'pdf_page' not in query
        assert query['selected_paper_id'] == [PAPERS[0]['id']]
        reader.get_by_role('button', name='Close reader', exact=True).click()
        expect(reader).to_have_count(0)
        assert 'pdf_page' not in parse_qs(urlparse(page.url).query)
        assert not errors, errors
        assert not external, external
        browser.close()
    print('PASS: three task types, both languages, desktop/mobile, evidence and input links, return-to-task citation restoration, comparison view restoration, refresh and switching, invalid context fallback, PDF page anchors and selection preservation; mocked APIs only.')


if __name__ == '__main__':
    main()
