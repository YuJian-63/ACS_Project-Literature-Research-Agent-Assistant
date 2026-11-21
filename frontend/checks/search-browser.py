"""Offline search interactions; all API responses are mocked."""
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(ROOT / 'runtime/pw-browsers'))
BASE = os.environ.get('SEARCH_PREVIEW_URL', 'http://127.0.0.1:5194')
SCREENSHOTS = ROOT / 'runtime/search-preview'
ABSTRACT = 'We study repository-level issue resolution with language-model agents. ' * 24


def main():
    with sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
        context.add_init_script("localStorage.setItem('literature-v3-ui-locale', 'en-US')")
        requests, errors, external = [], [], []
        state = {'fail': False, 'empty': False, 'total': 1500}

        def api(route):
            parsed = urlparse(route.request.url)
            if parsed.path == '/api/v1/auth/me':
                return route.fulfill(json={'user': {'id': 'researcher', 'username': 'researcher', 'email': 'fixture@example.org'}, 'csrf_token': 'fixture'})
            if parsed.path == '/api/v1/paper-imports':
                return route.fulfill(json={'items': [], 'total': 0, 'limit': 20, 'offset': 0})
            assert parsed.path == '/api/v1/paper-search', parsed.path
            params = parse_qs(parsed.query)
            requests.append(params)
            if state['fail']:
                return route.fulfill(status=502, json={'error': {'code': 'ARXIV_UNAVAILABLE', 'message': 'Source unavailable', 'details': {}}})
            offset = int(params['offset'][0])
            limit = int(params['limit'][0])
            items = [{
                'provider': 'arxiv', 'external_id': f'2601.{offset + index + 1:05d}v1',
                'title': f'Repository-Level Research Paper {offset + index + 1}: Evidence-Grounded Software Engineering Agents',
                'authors': ['Research Author', 'Second Author'], 'abstract': ABSTRACT if index else 'A short abstract.',
                'categories': ['cs.SE', 'cs.AI'], 'published_at': '2026-01-01T00:00:00Z',
                'source_updated_at': '2026-02-03T00:00:00Z', 'doi': None,
                'abstract_url': 'https://arxiv.org/abs/2601.00001v1', 'pdf_url': 'https://arxiv.org/pdf/2601.00001v1',
                'import_id': None, 'import_status': None, 'paper_id': None, 'paper_status': None,
            } for index in range(limit)]
            return route.fulfill(json={'items': [] if state['empty'] else items, 'total': state['total'], 'limit': limit, 'offset': offset})

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
        page.goto(BASE + '/papers/search')
        page.get_by_label('arXiv keywords', exact=True).fill('rust agents')
        page.locator('.arxiv-search-form button[type="submit"]').click()
        papers = page.locator('.search-paper')
        expect(papers).to_have_count(10)
        long_paper = papers.nth(1)
        toggle = long_paper.get_by_role('button', name='Expand abstract', exact=True)
        expect(toggle).to_have_attribute('aria-expanded', 'false')
        assert long_paper.locator('.paper-abstract').evaluate('(element) => element.scrollHeight > element.clientHeight')
        expect(papers.first.get_by_role('button', name='Expand abstract', exact=True)).to_have_count(0)
        toggle.click()
        expect(long_paper.get_by_role('button', name='Collapse abstract', exact=True)).to_have_attribute('aria-expanded', 'true')
        long_paper.get_by_role('button', name='Collapse abstract', exact=True).click()
        expect(toggle).to_have_attribute('aria-expanded', 'false')
        assert len(requests) == 1
        SCREENSHOTS.mkdir(parents=True, exist_ok=True)
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(SCREENSHOTS / 'search-desktop.png'))

        def assert_top():
            expect(page.locator('#search-results-heading')).to_be_focused()
            page.wait_for_function("document.querySelector('#search-results-heading').getBoundingClientRect().top >= 0 && document.querySelector('#search-results-heading').getBoundingClientRect().top < 180")

        pagination = page.locator('.search-pagination')
        expect(pagination).to_have_attribute('aria-label', 'Search result pages')
        pagination.locator('.ant-pagination-next').click()
        expect(papers.first).to_contain_text('Research Paper 11:')
        assert_top()
        jump = pagination.locator('.ant-pagination-options-quick-jumper input')
        jump.fill('5')
        jump.press('Enter')
        expect(papers.first).to_contain_text('Research Paper 41:')
        assert requests[-1]['offset'] == ['40']
        assert_top()
        jump.fill('999')
        jump.press('Enter')
        expect(papers.first).to_contain_text('Research Paper 1001:')
        assert requests[-1]['offset'] == ['1000']
        assert_top()
        pagination.locator('.ant-pagination-prev').click()
        expect(papers.first).to_contain_text('Research Paper 991:')
        assert_top()

        sort = page.get_by_label('Sort results', exact=True)
        for value, field, direction in [('published-desc', 'submittedDate', 'descending'), ('published-asc', 'submittedDate', 'ascending'), ('updated-desc', 'lastUpdatedDate', 'descending'), ('updated-asc', 'lastUpdatedDate', 'ascending'), ('relevance', 'relevance', 'descending')]:
            sort.select_option(value)
            expect(papers.first).to_contain_text('Research Paper 1:')
            page.wait_for_function("!document.querySelector('#search-sort').disabled")
            assert requests[-1]['sort_by'] == [field]
            assert requests[-1]['sort_order'] == [direction]
            assert requests[-1]['offset'] == ['0']
        state['fail'] = True
        pagination.locator('.ant-pagination-next').click()
        expect(page.get_by_role('alert')).to_be_visible()
        expect(papers).to_have_count(0)
        expect(page.get_by_label('arXiv keywords', exact=True)).to_have_value('')
        state['fail'] = False
        page.get_by_label('arXiv keywords', exact=True).fill('rust agents')
        page.locator('.arxiv-search-form button[type="submit"]').click()
        expect(papers.first).to_contain_text('Research Paper 1:')
        pagination.locator('.ant-pagination-next').click()
        expect(papers.first).to_contain_text('Research Paper 11:')
        assert requests[-1]['offset'] == ['10']
        assert_top()
        size_control = page.get_by_label('Results per page', exact=True)
        expect(size_control).to_have_value('10')
        expect(size_control.locator('option')).to_have_text(['10 papers', '25 papers', '50 papers'])
        for size in [25, 50, 10]:
            size_control.select_option(str(size))
            expect(papers).to_have_count(size)
            expect(papers.first).to_contain_text('Research Paper 1:')
            assert requests[-1]['limit'] == [str(size)]
            assert requests[-1]['offset'] == ['0']
            assert requests[-1]['q'] == ['rust agents']
            assert_top()
            pagination.locator('.ant-pagination-next').click()
            expect(papers.first).to_contain_text(f'Research Paper {size + 1}:')
            assert requests[-1]['offset'] == [str(size)]
            assert_top()
            jump = pagination.locator('.ant-pagination-options-quick-jumper input')
            jump.fill('999')
            jump.press('Enter')
            expect(papers.first).to_contain_text('Research Paper 1001:')
            assert requests[-1]['offset'] == ['1000']
            expect(pagination.locator('p')).to_contain_text(f'{size} papers per page · {1000 // size + 1} pages available')
            assert_top()
        size_control.select_option('25')
        expect(papers).to_have_count(25)
        sort.select_option('published-desc')
        page.wait_for_function("!document.querySelector('#search-sort').disabled")
        assert requests[-1]['limit'] == ['25']
        assert requests[-1]['sort_by'] == ['submittedDate']
        assert requests[-1]['offset'] == ['0']
        state['fail'] = True
        size_control.select_option('50')
        expect(page.get_by_role('alert')).to_be_visible()
        expect(papers).to_have_count(0)
        expect(size_control).to_have_value('10')
        state['fail'] = False
        page.get_by_label('arXiv keywords', exact=True).fill('rust agents')
        size_control.select_option('50')
        page.locator('.arxiv-search-form button[type="submit"]').click()
        expect(papers).to_have_count(50)
        assert requests[-1]['limit'] == ['50']
        size_control.select_option('10')
        expect(papers).to_have_count(10)
        for locale in ['zh-CN', 'en-US']:
            page.get_by_role('button', name='中文' if locale == 'zh-CN' else 'English', exact=True).click()
            for width in [320, 390, 768, 1190, 1440]:
                page.set_viewport_size({'width': width, 'height': 1000})
                page.wait_for_function('document.documentElement.scrollWidth <= innerWidth')
                paper_width = papers.first.bounding_box()['width']
                layout_width = page.locator('.search-layout').bounding_box()['width']
                assert paper_width >= layout_width * (0.75 if width > 1280 else 0.99), (width, paper_width, layout_width)
                expect(jump).to_be_visible()
            page.set_viewport_size({'width': 390, 'height': 844})
            page.evaluate('window.scrollTo(0, 0)')
            page.screenshot(path=str(SCREENSHOTS / f'search-mobile-{locale}.png'))
        jump.fill('5')
        jump.press('Enter')
        expect(papers.first).to_contain_text('Research Paper 41:')
        assert_top()
        page.set_viewport_size({'width': 1440, 'height': 1000})
        state['empty'] = True
        page.locator('.arxiv-search-form button[type="submit"]').click()
        expect(papers).to_have_count(0)
        expect(pagination).to_be_visible()
        state['total'] = 0
        page.locator('.arxiv-search-form button[type="submit"]').click()
        expect(pagination).to_have_count(0)
        assert not errors, errors
        assert not external, external
        browser.close()
        print('PASS: 10/25/50 page sizes, size/sort preservation and retry, collapsed abstracts, page jumps and caps, result focus/scroll, empty-page navigation and bilingual 320–1440px layouts; mocked APIs only.')


if __name__ == '__main__':
    main()
