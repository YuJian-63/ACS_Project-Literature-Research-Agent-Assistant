"""Offline retrieval diagnostics checks; all API responses are local fixtures."""
import os
import runpy
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(ROOT / 'runtime/pw-browsers')
BASE = os.environ.get('SEARCH_PREVIEW_URL', 'http://127.0.0.1:5194')
FIXTURES = runpy.run_path(str(ROOT / 'frontend/checks/review-browser.py'))
TASK = {**FIXTURES['TASK'], 'status': 'succeeded', 'stage': 'completed',
    'retrieval': {'status': 'partial', 'expansion_degraded': True, 'selected_chunks': 8, 'lexical_matches': 4, 'missing_aspects': ['Missing numerical results'], 'papers': [{'paper_id': FIXTURES['PAPERS'][0]['id'], 'paper_title': FIXTURES['PAPERS'][0]['title'], 'columns': ['局限性']}] }}
PAPERS = FIXTURES['PAPERS']


def main():
    with sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        for locale in ['zh-CN', 'en-US']:
            context = browser.new_context(viewport={'width': 1280, 'height': 900})
            context.add_init_script(f"localStorage.setItem('literature-ui-locale', '{locale}')")
            errors = []
            current_task = TASK
            def api(route):
                path = urlparse(route.request.url).path
                if path == '/api/v1/auth/me':
                    return route.fulfill(json={'user': {'id': 'fixture', 'username': 'researcher', 'email': 'fixture@example.org'}, 'csrf_token': 'fixture'})
                if path.startswith('/api/v1/papers/'):
                    return route.fulfill(json=next(paper for paper in PAPERS if path.endswith(paper['id'])))
                if path.endswith('/events'):
                    return route.fulfill(json={'items': [], 'next_after_seq': 0, 'has_more': False})
                if path.endswith('/artifacts'):
                    return route.fulfill(json={'items': [{'id': 'artifact', 'task_id': TASK['id'], 'task_type': 'review',
                        'schema_version': 1, 'is_mock': False, 'title': '论文综述', 'content_markdown': 'Supported result.',
                        'comparison_table': {'columns': [{'key': 'method', 'label': '方法'}],
                            'rows': [{'paper_id': paper['id'], 'cells': {'method': {'value': None, 'citation_keys': []}}} for paper in PAPERS]},
                        'citations': [], 'created_at': FIXTURES['STAMP']}]})
                if path == '/api/v1/tasks/' + TASK['id']:
                    return route.fulfill(json=current_task)
                raise AssertionError('Unexpected fixture request: ' + path)
            def network(route):
                if urlparse(route.request.url).netloc != urlparse(BASE).netloc:
                    raise AssertionError('Unexpected external request')
                return route.continue_()
            context.route('**/*', network)
            context.route('**/api/v1/**', api)
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(BASE + '/tasks/' + TASK['id'])
            page.wait_for_load_state('networkidle')
            expected = '部分问题或比较维度缺少支持证据，请结合引用阅读。' if locale == 'zh-CN' else 'Some questions or comparison dimensions lack supporting evidence. Read the result alongside its citations.'
            expect(page.get_by_text(expected, exact=True)).to_be_visible()
            notice = page.get_by_role('alert').filter(has_text=expected)
            expect(notice.get_by_text('Missing numerical results', exact=True)).to_be_visible()
            expect(notice.get_by_text(PAPERS[0]['title'], exact=True)).to_be_visible()
            expect(notice.get_by_text('：局限性' if locale == 'zh-CN' else '：Limitations', exact=True)).to_be_visible()
            page.get_by_role('tab', name='论文比较' if locale == 'zh-CN' else 'Comparison', exact=True).click()
            label = '当前证据未覆盖' if locale == 'zh-CN' else 'Not covered by retrieved evidence'
            expect(page.locator('.comparison-scroll').get_by_text(label, exact=True).first).to_be_visible()
            for task_type in ['summary', 'qa']:
                current_task = {**TASK, 'task_type': task_type, 'retrieval': {**TASK['retrieval'], 'papers': []}}
                page.reload()
                page.wait_for_load_state('networkidle')
                expect(page.get_by_role('alert').get_by_text('Missing numerical results', exact=True)).to_be_visible()
            current_task = {**TASK, 'retrieval': {'status': 'partial', 'missing_aspects': []}}
            page.reload()
            page.wait_for_load_state('networkidle')
            expect(page.get_by_text(expected, exact=True)).to_be_visible()
            expect(page.get_by_role('alert').locator('li')).to_have_count(0)
            current_task = {**TASK, 'retrieval': {**TASK['retrieval'], 'status': 'answered'}}
            page.reload()
            page.wait_for_load_state('networkidle')
            expect(page.get_by_role('alert')).to_have_count(0)
            assert not errors, errors
            context.close()
        browser.close()
        print('PASS: bilingual partial-evidence alerts and accurate comparison missing-evidence labels')


if __name__ == '__main__':
    main()
