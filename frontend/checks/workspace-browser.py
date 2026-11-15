import json
import os
import runpy
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(ROOT / 'runtime/pw-browsers')
BASE = os.environ.get('WORKSPACE_PREVIEW_URL', 'http://127.0.0.1:5191')
fixtures = runpy.run_path(str(ROOT / 'frontend/checks/review-browser.py'))
PAPERS = fixtures['PAPERS']
PAPERS[0]['title'] = 'Evaluating and Improving Automated Repository-Level Rust Issue Resolution with LLM-based Agents'
PAPERS[1]['title'] = 'SWE-Adept: An LLM-Based Agentic Framework for Deep Codebase Analysis and Structured Issue Resolution'
TASK = {**fixtures['TASK'], 'status': 'succeeded', 'stage': 'completed', 'finished_at': fixtures['STAMP']}
ARTIFACT = {'id': '22222222-2222-4222-8222-222222222222', 'task_id': TASK['id'], 'task_type': 'review', 'schema_version': 1,
    'is_mock': False, 'title': '论文综述', 'created_at': fixtures['STAMP'],
    'content_markdown': '## Research overview\n\nRepository context matters [C1].\n\n### Methods\n\nStructured analysis provides a second perspective [C2].\n\n### Citation syntax\n\nCode stays literal: \x60[C1]\x60. A linked citation also works: [[C2]](#citation-C2).',
    'citations': [{'id': 'citation-' + str(index), 'citation_key': 'C' + str(index), 'paper_id': PAPERS[index-1]['id'],
        'paper_title': PAPERS[index-1]['title'], 'chunk_id': 'chunk-' + str(index), 'page_number': index+1,
        'quote': 'Exact evidence fragment for paper ' + str(index)} for index in range(1, 3)],
    'comparison_table': {'columns': [{'key': key, 'label': label} for key, label in [('objective','研究目标'),('method','方法'),('evaluation','评估'),('limitations','局限')]],
        'rows': [{'paper_id': paper['id'], 'cells': {key: {'value': 'Evidence-supported ' + key if index<2 else None, 'citation_keys': ['C'+str(index+1)] if index<2 else []} for key in ['objective','method','evaluation','limitations']}} for index,paper in enumerate(PAPERS)]}}


def main():
    with sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1050}, reduced_motion='reduce')
        page = context.new_page()
        page.set_default_timeout(7000)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        status = {'value': 'succeeded'}

        def api(route):
            path = urlparse(route.request.url).path
            if path == '/api/v1/papers':
                return route.fulfill(json={'items': PAPERS, 'total': 6, 'limit': 20, 'offset': 0})
            if path.startswith('/api/v1/papers/'):
                return route.fulfill(json=next(paper for paper in PAPERS if path.endswith(paper['id'])))
            if path == '/api/v1/tasks':
                assert route.request.method == 'GET', 'No real task creation in this check'
                return route.fulfill(json={'items': [TASK], 'total': 1, 'limit': 20, 'offset': 0})
            if path.endswith('/events'):
                return route.fulfill(json={'items': [{'task_id': TASK['id'], 'seq': 1, 'event_type': 'status', 'status': status['value'], 'stage': 'completed', 'message': '研究任务完成', 'payload': {}, 'created_at': fixtures['STAMP']}], 'next_after_seq': 1, 'has_more': False})
            if path.endswith('/artifacts'):
                return route.fulfill(json={'items': [ARTIFACT], 'total': 1, 'limit': 20, 'offset': 0})
            if path == '/api/v1/tasks/' + TASK['id']:
                return route.fulfill(json={**TASK, 'status': status['value'], 'error': {'code':'AGENT_EXECUTION_FAILED','message':'研究任务执行失败','details':{}} if status['value']=='failed' else None})
            if path == '/api/v1/paper-imports':
                return route.fulfill(json={'items': [], 'total': 0, 'limit': 20, 'offset': 0})
            raise AssertionError('Unexpected API request ' + route.request.url)

        context.route('**/api/v1/**', api)
        page.goto(BASE + '/tasks/' + TASK['id'])
        trigger = page.locator('.markdown .citation-trigger').first
        expect(trigger).to_be_visible()
        trigger.click()
        expect(page.locator('.evidence-quote')).to_contain_text('Exact evidence fragment for paper 1')
        expect(page.locator('.markdown code')).to_have_text('[C1]')
        linked = page.locator('.markdown .citation-trigger').last
        linked.click()
        expect(page.locator('.evidence-quote')).to_contain_text('paper 2')
        page.locator('.evidence-panel [role=tab]').nth(1).click()
        expect(page.locator('.evidence-papers')).to_be_visible()
        linked.click()
        expect(page.locator('.evidence-quote')).to_be_visible()
        expect(page.locator('.evidence-quote')).to_contain_text('paper 2')
        assert '#page=3' in page.locator('.evidence-pdf-link').get_attribute('href')
        expect(page.locator('.result-outline a').first).to_be_visible()
        page.get_by_role('tab', name='论文比较', exact=True).click()
        expect(page.locator('.comparison-section table thead th')).to_have_count(5)
        expect(page.locator('.comparison-section table tbody tr')).to_have_count(6)
        expect(page.locator('.comparison-section table tbody tr').first).to_contain_text(PAPERS[0]['title'])
        page.locator('.comparison-cell-trigger').first.click()
        expect(page.locator('.evidence-quote')).to_contain_text('paper 1')
        page.get_by_role('tab', name='执行记录', exact=True).click()
        expect(page.locator('.trace-panel')).to_be_visible()
        page.get_by_role('button', name='English', exact=True).click()
        expect(page.get_by_role('tab', name='Execution events', exact=True)).to_be_visible()
        page.get_by_role('tab', name='Review', exact=True).click()
        expect(page.locator('.markdown')).to_contain_text('Repository context matters')
        page.reload()
        expect(page.get_by_role('tab', name='Review', exact=True)).to_be_visible()
        for route in ['/papers', '/papers/search', '/tasks/new', '/tasks', '/tasks/' + TASK['id']]:
            page.goto(BASE + route)
            expect(page.locator('main h1')).to_be_visible()
            for width in [390, 768, 1440]:
                page.set_viewport_size({'width': width, 'height': 1000})
                page.wait_for_function('document.documentElement.scrollWidth <= innerWidth', timeout=3000)
        page.set_viewport_size({'width':390,'height':844})
        page.locator('.markdown .citation-trigger').first.click()
        expect(page.get_by_role('dialog',name='Evidence & sources')).to_be_visible()
        page.keyboard.press('Escape')
        expect(page.get_by_role('dialog',name='Evidence & sources')).not_to_be_visible()
        expect(page.locator('.markdown .citation-trigger').first).to_be_focused()
        page.get_by_role('tab',name='Comparison',exact=True).click()
        expect(page.locator('.mobile-comparison')).to_be_visible()
        page.locator('.mobile-comparison select').select_option(PAPERS[1]['id'])
        page.locator('.mobile-comparison .comparison-cell-trigger').first.click()
        expect(page.locator('.ant-drawer .evidence-quote')).to_contain_text('paper 2')
        page.keyboard.press('Escape')
        for value in ['running','failed']:
            status['value']=value
            page.goto(BASE + '/tasks/' + TASK['id'])
            expect(page.locator('.task-overview .status-' + value)).to_be_visible()
            expect(page.locator('.waiting-result')).to_be_visible()
        status['value'] = 'succeeded'
        TASK['task_type'] = 'summary'
        ARTIFACT.update({'task_type': 'summary', 'title': '论文摘要', 'citations': [], 'comparison_table': None})
        page.set_viewport_size({'width': 1440, 'height': 1000})
        page.goto(BASE + '/tasks/' + TASK['id'])
        expect(page.get_by_role('heading', name='Paper summary', exact=True)).to_be_visible()
        expect(page.get_by_role('tab', name='Comparison', exact=True)).to_have_count(0)
        expect(page.locator('.evidence-panel .ant-empty')).to_be_visible()
        page.locator('.evidence-panel [role=tab]').nth(1).click()
        expect(page.locator('.evidence-papers li')).to_have_count(6)
        TASK['is_mock'] = True
        ARTIFACT['is_mock'] = True
        page.reload()
        expect(page.locator('.artifact-heading')).to_contain_text('Mock')
        assert not errors, errors
        browser.close()
        print('PASS: live React workspace routes, real citation markers, literal code, linked references, title-based matrix, evidence drawer, bilingual persistence, activity, running/failure states and responsive layout; mocked APIs only.')


if __name__ == '__main__':
    main()
