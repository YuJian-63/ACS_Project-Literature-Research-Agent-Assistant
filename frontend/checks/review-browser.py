import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(ROOT / 'runtime/pw-browsers')
BASE = 'http://127.0.0.1:5182'
STAMP = '2026-11-14T00:00:00Z'
PAPERS = [{'id': f'00000000-0000-4000-8000-{index:012d}', 'title': f'Rust agents paper {index}',
    'original_filename': 'fixture.pdf', 'content_type': 'application/pdf', 'size_bytes': 100, 'sha256': 'a' * 64,
    'status': 'ready', 'page_count': 3, 'parser_version': 'fixture', 'error': None, 'source': None,
    'created_at': STAMP, 'updated_at': STAMP} for index in range(1, 7)]
TASK_ID = '11111111-1111-4111-8111-111111111111'
TASK = {'id': TASK_ID, 'task_type': 'review', 'workflow_type': 'baseline', 'is_mock': False,
    'status': 'running', 'stage': 'analyzing', 'created_at': STAMP, 'updated_at': STAMP, 'started_at': STAMP, 'finished_at': None,
    'question': '比较方法', 'paper_ids': [paper['id'] for paper in PAPERS], 'error': None, 'budget_mode': 'automatic',
    'budget': {'max_steps': 11, 'max_tokens': 42000, 'timeout_seconds': 1020},
    'versions': {'model_id': 'fixture', 'workflow_version': 'langgraph-review-v2', 'prompt_version': 'evidence-review-v3', 'dataset_version': None},
    'stats': {'queue_ms': 1, 'execution_ms': None, 'end_to_end_ms': None, 'input_tokens': 500, 'output_tokens': 200,
        'total_tokens': 700, 'model_calls': 4, 'tool_calls': 0, 'usage_estimated': True}, 'last_event_seq': 1}


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1280, 'height': 900})
        page = context.new_page()
        page.set_default_timeout(8000)
        errors, posts = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))

        def api(route):
            request = route.request
            path = urlparse(request.url).path
            if path == '/api/v1/papers':
                return route.fulfill(json={'items': PAPERS, 'total': 6, 'limit': 20, 'offset': 0})
            if path.startswith('/api/v1/papers/'):
                return route.fulfill(json=next(paper for paper in PAPERS if path.endswith(paper['id'])))
            if path == '/api/v1/tasks' and request.method == 'POST':
                posts.append(request.post_data_json)
                return route.fulfill(status=202, json=TASK)
            if path.endswith('/events'):
                return route.fulfill(json={'items': [{'task_id': TASK_ID, 'seq': 1, 'event_type': 'stage', 'status': 'running', 'stage': 'analyzing', 'message': '正在分析论文', 'payload': {'current': 4, 'total': 6}, 'created_at': STAMP}], 'next_after_seq': 1, 'has_more': False})
            if path == '/api/v1/tasks/' + TASK_ID:
                return route.fulfill(json=TASK)
            raise AssertionError('Unexpected request ' + request.url)

        context.route('**/api/v1/**', api)
        page.goto(BASE + '/tasks/new?' + '&'.join('paper_id=' + paper['id'] for paper in PAPERS))
        expect(page.get_by_role('heading', name='自动安排执行', exact=True)).to_be_visible()
        expect(page.get_by_text('执行预算', exact=True)).to_have_count(0)
        switch = page.get_by_role('group', name='界面语言 / Interface language')
        switch.get_by_role('button', name='English', exact=True).click()
        expect(page.get_by_role('heading', name='Automatic execution', exact=True)).to_be_visible()
        question = page.get_by_role('textbox', name='Research question', exact=True)
        question.fill('比较方法')
        page.get_by_role('button', name='Create research task').click()
        expect(page).to_have_url(BASE + '/tasks/' + TASK_ID)
        expect(page.get_by_role('heading', name='Research in progress', exact=True)).to_be_visible()
        expect(page.locator('[role=progressbar]')).to_be_visible()
        expect(page.locator('.stats-panel, .trace-panel, .input-panel')).to_have_count(0)
        assert len(posts) == 1 and 'budget' not in posts[0]
        switch.get_by_role('button', name='中文', exact=True).click()
        expect(page.get_by_role('heading', name='研究正在进行', exact=True)).to_be_visible()
        page.reload()
        expect(page.get_by_role('heading', name='研究正在进行', exact=True)).to_be_visible()
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        assert not errors, errors
        browser.close()
        print('PASS: six-paper review without budget controls, POST excludes budget, bilingual progress, read-only auto allocation, estimated usage and refresh/mobile')


if __name__ == '__main__':
    main()
