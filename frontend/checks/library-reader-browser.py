"""Offline library reading checks. All APIs and PDF bytes are local fixtures."""
import os
import re
from pathlib import Path
from uuid import UUID
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Error, expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(ROOT / 'runtime/pw-browsers'))
BASE = os.environ.get('LIBRARY_PREVIEW_URL', 'http://127.0.0.1:5196')
SCREENSHOTS = ROOT / 'runtime/library-reader-preview'
PAPERS = [{
    'id': str(UUID(int=index, version=4)), 'title': title, 'original_filename': 'research-' + str(index) + '.pdf',
    'content_type': 'application/pdf', 'size_bytes': 1200, 'sha256': 'a' * 64,
    'status': 'ready', 'page_count': 1, 'parser_version': 'fixture-v1', 'error': None, 'source': None,
    'created_at': '2026-11-15T00:00:00Z', 'updated_at': '2026-11-15T00:00:00Z',
} for index, title in enumerate([
    'Evidence-Grounded Repository-Level Issue Resolution with Language Model Agents',
    'Understanding Research Evidence Across Software Engineering Papers',
], start=1)]


def pdf_fixture(page_count=1):
    font_id = 3 + page_count * 2
    children = ' '.join(str(3 + index * 2) + ' 0 R' for index in range(page_count))
    objects = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        f'<< /Type /Pages /Kids [{children}] /Count {page_count} >>'.encode(),
    ]
    for index in range(page_count):
        stream = f'BT /F1 20 Tf 60 730 Td (Research evidence - page {index + 1}) Tj ET'.encode()
        objects.extend([
            f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {4 + index * 2} 0 R >>'.encode(),
            b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream',
        ])
    objects.append(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')
    result = b'%PDF-1.4\n'
    offsets = [0]
    for index, content in enumerate(objects, start=1):
        offsets.append(len(result))
        result += str(index).encode() + b' 0 obj\n' + content + b'\nendobj\n'
    xref = len(result)
    result += f'xref\n0 {len(objects) + 1}\n0000000000 65535 f \n'.encode()
    result += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
    return result + f'trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n'.encode() + str(xref).encode() + b'\n%%EOF\n'


def main():
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as driver:
        options = {'channel': os.environ['PDF_BROWSER_CHANNEL']} if os.environ.get('PDF_BROWSER_CHANNEL') else {}
        browser = driver.chromium.launch(headless=True, **options)
        context = browser.new_context(viewport={'width': 1440, 'height': 1080}, reduced_motion='reduce')
        context.add_init_script("""
            localStorage.setItem('literature-v3-ui-locale', 'en-US');
            window.revokedDocuments = [];
            const originalRevoke = URL.revokeObjectURL.bind(URL);
            URL.revokeObjectURL = (url) => { window.revokedDocuments.push(url); originalRevoke(url); };
        """)
        state = {'failure': False, 'invalid': False, 'hold': False, 'expired': False, 'paged': False, 'details_failure': False}
        files, held, errors, external = [], [], [], []

        def api(route):
            parsed = urlparse(route.request.url)
            if parsed.path == '/api/v1/auth/me':
                return route.fulfill(status=401, json={}) if state['expired'] else route.fulfill(json={
                    'user': {'id': 'reader', 'username': 'Researcher', 'email': 'reader@example.org'}, 'csrf_token': 'fixture',
                })
            if parsed.path == '/api/v1/papers':
                parameters = parse_qs(parsed.query)
                query = parameters.get('q', [''])[0]
                offset = int(parameters.get('offset', ['0'])[0])
                dataset = PAPERS + ([{**PAPERS[0], 'id': str(UUID(int=100 + index, version=4)), 'title': 'Additional research paper ' + str(index)} for index in range(20)] if state['paged'] else [])
                papers = [paper for paper in dataset if query.lower() in paper['title'].lower()]
                return route.fulfill(json={'items': papers[offset:offset + 20], 'total': len(papers), 'limit': 20, 'offset': offset})
            if parsed.path.startswith('/api/v1/papers/') and not parsed.path.endswith('/file'):
                if state['details_failure']:
                    return route.fulfill(status=503, json={'error': {'code': 'PAPER_UNAVAILABLE', 'message': 'Paper details unavailable', 'details': {}}})
                known = PAPERS + [{**PAPERS[0], 'id': str(UUID(int=100 + index, version=4)), 'title': 'Additional research paper ' + str(index)} for index in range(20)]
                paper = next((paper for paper in known if parsed.path.endswith('/' + paper['id'])), None)
                if paper is None:
                    return route.fulfill(status=404, json={'error': {'code': 'PAPER_NOT_FOUND', 'message': 'Paper not found', 'details': {}}})
                return route.fulfill(json=paper)
            if parsed.path.endswith('/file'):
                files.append(parsed.path)
                if state['expired']:
                    return route.fulfill(status=401, json={})
                if state['failure']:
                    return route.fulfill(status=503, json={'error': {'code': 'FILE_UNAVAILABLE', 'message': 'File unavailable', 'details': {}}})
                if state['hold']:
                    held.append(route)
                    return
                return route.fulfill(content_type='application/pdf', body=b'not a PDF' if state['invalid'] else pdf_fixture())
            raise AssertionError('Unexpected API: ' + parsed.path)

        def network(route):
            if urlparse(route.request.url).netloc != urlparse(BASE).netloc:
                external.append(route.request.url)
                return route.abort()
            return route.continue_()

        context.route('**/*', network)
        context.route('**/api/v1/**', api)
        page = context.new_page()
        page.set_default_timeout(5000)
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(BASE + '/tasks/new')
        paper_link = page.get_by_role('link', name=PAPERS[0]['title'], exact=True)
        expect(paper_link).to_have_attribute('href', '/papers?paper_id=' + PAPERS[0]['id'])
        assert paper_link.get_attribute('target') is None
        paper_link.click()
        reader = page.locator('.paper-reader')
        expect(reader.locator('iframe')).to_have_attribute('src', re.compile('^blob:'))
        expect(reader.get_by_role('heading', name=PAPERS[0]['title'], exact=True)).to_be_visible()
        assert len(context.pages) == 1
        page.reload()
        expect(reader.locator('iframe')).to_be_visible()
        expect(reader.get_by_role('heading', name=PAPERS[0]['title'], exact=True)).to_be_visible()
        page.go_back()
        expect(page).to_have_url(BASE + '/tasks/new')
        expect(page.get_by_role('heading', name='Reference papers (optional)', exact=True)).to_be_visible()
        state['paged'] = True
        page.reload()
        page.get_by_role('checkbox', name='Select paper ' + PAPERS[0]['title'], exact=True).check()
        page.locator('.paper-picker .ant-pagination-item-2').click()
        page.get_by_role('checkbox', name='Select paper Additional research paper 19', exact=True).check()
        page.locator('.paper-picker .ant-pagination-item-1').click()
        page.get_by_role('link', name=PAPERS[1]['title'], exact=True).click()
        expect(reader.get_by_role('heading', name=PAPERS[1]['title'], exact=True)).to_be_visible()
        expect(page.get_by_role('checkbox', name='Select paper ' + PAPERS[0]['title'], exact=True)).to_be_checked()
        expect(page.get_by_role('checkbox', name='Select paper ' + PAPERS[1]['title'], exact=True)).not_to_be_checked()
        expect(page.locator('.selection-notice strong')).to_have_text('2')
        page.locator('.library-panel .ant-pagination-item-2').click()
        expect(page.get_by_role('checkbox', name='Select paper Additional research paper 19', exact=True)).to_be_checked()
        page.get_by_role('button', name='Read Additional research paper 19', exact=True).click()
        expect(reader.get_by_role('heading', name='Additional research paper 19', exact=True)).to_be_visible()
        page.reload()
        expect(reader.locator('iframe')).to_be_visible()
        expect(page.locator('.selection-notice strong')).to_have_text('2')
        expect(page.get_by_role('checkbox', name='Select paper ' + PAPERS[0]['title'], exact=True)).to_be_checked()
        page.get_by_role('checkbox', name='Select paper ' + PAPERS[0]['title'], exact=True).click()
        expect(page.get_by_role('checkbox', name='Select paper ' + PAPERS[0]['title'], exact=True)).not_to_be_checked()
        page.reload()
        expect(reader.locator('iframe')).to_be_visible()
        expect(page.locator('.selection-notice strong')).to_have_text('1')
        expect(page.get_by_role('checkbox', name='Select paper ' + PAPERS[0]['title'], exact=True)).not_to_be_checked()
        reader.get_by_role('button', name='Close reader', exact=True).click()
        expect(page.locator('.selection-notice strong')).to_have_text('1')
        page.locator('.page-actions a').click()
        expect(page.locator('.selected-papers')).to_contain_text('Additional research paper 19')
        page.locator('.paper-picker .ant-pagination-item-2').click()
        expect(page.get_by_role('checkbox', name='Select paper Additional research paper 19', exact=True)).to_be_checked()
        state['paged'] = False
        page.goto(BASE + '/papers?paper_id=' + str(UUID(int=119, version=4)))
        expect(reader.get_by_role('heading', name='Additional research paper 19', exact=True)).to_be_visible()
        expect(reader.locator('iframe')).to_be_visible()
        assert page.get_by_role('button', name='Read Additional research paper 19', exact=True).count() == 0
        reader.get_by_role('button', name='Close reader', exact=True).click()
        expect(page).to_have_url(BASE + '/papers')
        page.reload()
        expect(page.get_by_role('heading', name='My papers', exact=True)).to_be_visible()
        expect(reader).to_have_count(0)
        state['details_failure'] = True
        page.goto(BASE + '/papers?paper_id=' + PAPERS[0]['id'])
        expect(page.get_by_text('Paper details unavailable', exact=True)).to_be_visible()
        state['details_failure'] = False
        page.get_by_role('button', name='Try again', exact=True).click()
        expect(reader.locator('iframe')).to_be_visible()
        page.goto(BASE + '/papers?paper_id=' + str(UUID(int=999, version=4)))
        expect(page.get_by_text('Paper not found', exact=True)).to_be_visible()
        expect(reader).to_have_count(0)
        page.get_by_role('button', name='Back to library', exact=True).click()
        expect(page).to_have_url(BASE + '/papers')
        files.clear()
        page.goto(BASE + '/papers')
        expect(page.get_by_role('heading', name='My papers', exact=True)).to_be_visible()
        assert not files, 'Library browsing must not download PDFs'
        page.get_by_role('checkbox', name='Select paper ' + PAPERS[0]['title'], exact=True).click()
        expect(page.get_by_role('checkbox', name='Select paper ' + PAPERS[0]['title'], exact=True)).to_be_checked()
        page.get_by_role('button', name=PAPERS[0]['title'], exact=True).click()
        reader = page.locator('.paper-reader')
        expect(reader).to_be_visible()
        expect(reader.locator('iframe')).to_have_attribute('src', re.compile('^blob:'))
        assert len(context.pages) == 1, 'Reading must stay in the current browser tab'
        first_url = reader.locator('iframe').get_attribute('src').split('#')[0]
        page.get_by_role('button', name='Read ' + PAPERS[1]['title'], exact=True).click()
        expect(reader.get_by_role('heading', name=PAPERS[1]['title'], exact=True)).to_be_focused()
        expect(reader.locator('iframe')).to_have_attribute('src', re.compile('^blob:'))
        page.wait_for_function('url => window.revokedDocuments.includes(url)', arg=first_url)
        downloads = len(files)
        page.get_by_role('button', name='Focus on reading', exact=True).click()
        expect(page.locator('.library-panel')).to_be_hidden()
        page.get_by_role('button', name='Show paper list', exact=True).click()
        expect(page.locator('.library-panel')).to_be_visible()
        page.get_by_role('button', name='中文', exact=True).click()
        expect(reader.get_by_role('button', name='关闭阅读', exact=True)).to_be_visible()
        assert len(files) == downloads, 'Locale/layout changes must not reload the PDF'
        page.get_by_role('button', name='English', exact=True).click()
        reader.get_by_role('button', name='Close reader', exact=True).click()
        expect(page.get_by_role('button', name=PAPERS[1]['title'], exact=True)).to_be_focused()
        expect(page.get_by_role('checkbox', name='Select paper ' + PAPERS[0]['title'], exact=True)).to_be_checked()
        state['paged'] = True
        page.locator('.library-panel .panel-heading button').click()
        page.locator('.pagination-bar .ant-pagination-item-2').click()
        expect(page.locator('.paper-title-button').first).to_have_text('Additional research paper 18')
        page.locator('.paper-title-button').first.click()
        expect(reader.locator('iframe')).to_be_visible()
        page.locator('.library-panel .ant-pagination-item-1').click()
        expect(page.get_by_role('button', name='Read ' + PAPERS[0]['title'], exact=True)).to_be_visible()
        expect(reader.get_by_role('heading', name='Additional research paper 18', exact=True)).to_be_visible()
        page.locator('.library-panel .ant-pagination-item-2').click()
        reader.get_by_role('button', name='Close reader', exact=True).click()
        expect(page.locator('.ant-pagination-item-active')).to_have_attribute('title', '2')
        expect(page.locator('.paper-title-button').first).to_be_focused()
        page.locator('.pagination-bar .ant-pagination-item-1').click()
        state['paged'] = False
        page.locator('.library-panel .panel-heading button').click()
        expect(page.locator('.paper-title-button')).to_have_count(2)
        expect(page.get_by_role('checkbox', name='Select paper ' + PAPERS[0]['title'], exact=True)).to_be_checked()
        query = page.get_by_role('searchbox', name='Find papers', exact=True)
        query.fill('Evidence-Grounded')
        query.press('Enter')
        expect(page.locator('.paper-title-button')).to_have_count(1)
        page.locator('.paper-title-button').click()
        expect(reader.locator('iframe')).to_be_visible()
        reader.get_by_role('button', name='Close reader', exact=True).click()
        expect(query).to_have_value('Evidence-Grounded')
        query.fill('')
        query.press('Enter')
        expect(page.locator('.paper-title-button')).to_have_count(2)
        state['failure'] = True
        page.locator('.paper-title-button').first.click()
        expect(reader.get_by_text('Unable to load PDF', exact=True)).to_be_visible()
        state['failure'] = False
        reader.get_by_role('button', name='Try again', exact=True).click()
        expect(reader.locator('iframe')).to_be_visible()
        reader.get_by_role('button', name='Close reader', exact=True).click()
        state['invalid'] = True
        page.locator('.paper-title-button').first.click()
        expect(reader.get_by_text('Unable to load PDF', exact=True)).to_be_visible()
        state['invalid'] = False
        reader.get_by_role('button', name='Try again', exact=True).click()
        expect(reader.locator('iframe')).to_be_visible()
        reader.get_by_role('button', name='Close reader', exact=True).click()
        state['hold'] = True
        with page.expect_request(lambda request: request.url.endswith('/' + PAPERS[0]['id'] + '/file')):
            page.locator('.paper-title-button').first.click()
        expect(reader.get_by_text('Loading PDF…', exact=True)).to_be_visible()
        assert held, 'The first download must remain pending to exercise stale-response fencing'
        state['hold'] = False
        page.get_by_role('button', name='Read ' + PAPERS[1]['title'], exact=True).click()
        expect(reader.get_by_role('heading', name=PAPERS[1]['title'], exact=True)).to_be_visible()
        expect(reader.locator('iframe')).to_be_visible()
        current_url = reader.locator('iframe').get_attribute('src')
        for route in held:
            try:
                route.fulfill(content_type='application/pdf', body=pdf_fixture())
            except Error:
                pass
        expect(reader.locator('iframe')).to_have_attribute('src', current_url)
        for locale in ['zh-CN', 'en-US']:
            page.get_by_role('button', name='中文' if locale == 'zh-CN' else 'English', exact=True).click()
            for width in [320, 390, 768, 1190, 1440]:
                page.set_viewport_size({'width': width, 'height': 1080})
                page.wait_for_function('document.documentElement.scrollWidth <= innerWidth')
                expect(reader.locator('iframe')).to_be_visible()
                if width <= 1000:
                    reader.get_by_role('combobox').select_option(PAPERS[0]['id'])
                    expect(reader.get_by_role('heading', name=PAPERS[0]['title'], exact=True)).to_be_visible()
            page.screenshot(path=str(SCREENSHOTS / ('reader-desktop-' + locale + '.png')))
            page.set_viewport_size({'width': 390, 'height': 900})
            page.screenshot(path=str(SCREENSHOTS / ('reader-mobile-' + locale + '.png')))
        expect(reader.get_by_role('link', name='Open in new tab', exact=True)).to_have_attribute('target', '_blank')
        page.set_viewport_size({'width': 1440, 'height': 1080})
        reader.get_by_role('button', name='Close reader', exact=True).click()
        page.wait_for_function('url => window.revokedDocuments.includes(url)', arg=current_url.split('#')[0])
        state['expired'] = True
        page.locator('.paper-title-button').first.click()
        expect(page.get_by_role('heading', name='Log in', exact=True)).to_be_visible()
        expect(page.locator('iframe')).to_have_count(0)
        assert not errors, errors
        assert not external, external
        browser.close()
        print('PASS: new-task reader links, cross-route/cross-page selections, refresh and deselection, returning to research creation, refresh/history, off-page papers, metadata retry/missing papers, inline PDFs, switching, query/page/selection preservation, focus, URL cleanup, stale responses, retry, invalid files, session expiry and bilingual 320-1440px layouts; mocked APIs only.')


if __name__ == '__main__':
    main()
