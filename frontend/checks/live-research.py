"""Real browser acceptance, invoked only by backend/checks/live_research_acceptance.py."""
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


def main():
    base = os.environ['LIVE_RESEARCH_URL']
    output = Path(os.environ['LIVE_RESEARCH_OUTPUT'])
    question = '仅根据所选 PDF 回答：这份验收文档写明，使用哪一种内容摘要算法校验文件来源？请用中文简短回答并引用对应原文，不要搜索互联网。材料是合成验收文档，只需说明文档写了什么，不需要额外验证系统是否已实现这些行为。'
    with sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport=dict(width=1440, height=1080), reduced_motion='reduce')
            context.add_init_script("localStorage.setItem('literature-v3-ui-locale','en-US')")
            page = context.new_page()
            page.set_default_timeout(15000)
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/login')
            page.locator('#auth-username').fill(os.environ['LIVE_RESEARCH_USER'])
            page.locator('#auth-password').fill(os.environ['LIVE_RESEARCH_PASSWORD'])
            page.locator('.auth-form button[type="submit"]').click()
            page.wait_for_url('**/papers')
            print('PASS real browser login and session', flush=True)
            with page.expect_response(lambda response: urlparse(response.url).path == '/api/v1/papers' and response.request.method == 'POST') as uploaded:
                page.locator('input[type="file"]').set_input_files(os.environ['LIVE_RESEARCH_PDF'])
            response = uploaded.value
            assert response.status == 201, 'PDF upload did not return 201'
            paper = response.json()
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                response = context.request.get(base + '/api/v1/papers/' + paper['id'])
                assert response.ok, 'Paper status could not be read'
                paper = response.json()
                if paper['status'] == 'ready':
                    break
                assert paper['status'] != 'failed', 'PDF parsing failed: ' + str(paper.get('error', {}).get('code'))
                page.wait_for_timeout(1000)
            assert paper['status'] == 'ready' and paper['page_count'] == 1, 'Parser did not produce one ready PDF page'
            pdf = context.request.get(base + '/api/v1/papers/' + paper['id'] + '/file')
            assert pdf.ok and pdf.body().startswith(b'%PDF-'), 'Persisted PDF download failed'
            print('PASS real PDF upload, independent parsing and persisted file download', flush=True)
            page.goto(base + '/tasks/new?paper_id=' + paper['id'])
            expect(page.locator('textarea')).to_be_enabled()
            page.locator('textarea').fill(question)
            page.locator('.paper-name').get_by_role('link', name=paper['title'], exact=True).click()
            expect(page.locator('.paper-reader iframe')).to_be_visible()
            page.go_back()
            expect(page.locator('textarea')).to_have_value(question)
            expect(page.get_by_role('checkbox', name='Select paper ' + paper['title'], exact=True)).to_be_checked()
            print('PASS real PDF round trip preserves research draft and selection', flush=True)
            submissions = []

            def submit(route):
                response = route.fetch()
                assert response.ok, 'Real research submission failed with HTTP ' + str(response.status)
                accepted = response.json()
                submissions.append(dict(task_id=accepted['task_id'], key=route.request.header_value('idempotency-key')))
                if len(submissions) == 1:
                    route.abort('failed')
                else:
                    route.fulfill(response=response)

            page.route('**/api/v1/agent-research', lambda route: submit(route) if route.request.method == 'POST' else route.continue_())
            button = page.locator('.research-submit-panel button[type="submit"]')
            button.click()
            expect(page.locator('.ant-notification-notice-error')).to_be_visible()
            expect(button).to_be_enabled()
            assert len(submissions) == 1 and submissions[0]['key'], 'Initial submission omitted idempotency key'
            button.click()
            page.wait_for_url('**/tasks/' + submissions[0]['task_id'])
            assert len(submissions) == 2 and submissions[0] == submissions[1], 'Lost-response retry created a different task'
            assert page.evaluate("Object.keys(sessionStorage).every(key => !key.startsWith('literature-v3-research-draft:'))"), 'Successful submission retained draft'
            print('PASS lost real response and retry return the same persisted task', flush=True)
            deadline = time.monotonic() + 420
            previous = None
            while time.monotonic() < deadline:
                response = context.request.get(base + '/api/v1/agent-research/' + submissions[0]['task_id'])
                assert response.ok, 'Research status could not be read'
                record = response.json()
                if record['status'] != previous:
                    print('Real task status: ' + record['status'], flush=True)
                    previous = record['status']
                if record['status'] in ('succeeded', 'failed'):
                    break
                page.wait_for_timeout(1000)
            report = dict(task_id=submissions[0]['task_id'], paper_id=paper['id'], task_status=record['status'],
                stop_reason=(record.get('result') or {}).get('stop_reason'), error_code=(record.get('error') or {}).get('code'),
                citations=len((record.get('result') or {}).get('citations', [])),
                unresolved=(record.get('result') or {}).get('unresolved', []),
                model_errors=(record.get('result') or {}).get('errors', []))
            output.write_text(json.dumps(report, indent=2), encoding='utf-8')
            assert record['status'] == 'succeeded', 'Real Agent failed: ' + str(report)
            result = record['result']
            assert result['stop_reason'] == 'completed', 'Real Agent returned only a partial result'
            assert result['citations'] and re.search(r'[\u3400-\u9fff]', result['answer']), 'Expected Chinese answer with evidence'
            assert result['usage']['model_calls'] > 0, 'Real model execution was not recorded'
            identities = {paper['id'], 'local:' + paper['id'] + '@' + paper['sha256']}
            assert all(citation['paper_id'] in identities and citation['page'] == 1 for citation in result['citations']), 'Citations do not refer to the uploaded PDF page'
            listed = context.request.get(base + '/api/v1/agent-research').json()
            assert listed['total'] == 1, 'Idempotent retry left multiple research tasks'
            expect(page.locator('.research-markdown')).to_be_visible(timeout=15000)
            page.locator('.research-markdown .citation-trigger').first.click()
            quote = page.locator('.evidence-quote').inner_text()
            page.get_by_role('button', name='Open PDF page', exact=True).click()
            expect(page.locator('.paper-reader iframe')).to_have_attribute('src', re.compile(r'#page=1&'))
            page.locator('.reader-task-return').click()
            expect(page.locator('.evidence-quote')).to_have_text(quote)
            assert len(context.pages) == 1 and not errors, 'Browser error or unexpected tab'
            report.update(model_calls=result['usage']['model_calls'], citations=len(result['citations']),
                verified=['login', 'upload', 'parse', 'download', 'draft_return', 'lost_response_idempotency',
                    'local_worker', 'real_model', 'chinese_answer', 'citation_reader_return'])
            output.write_text(json.dumps(report, indent=2), encoding='utf-8')
            page.screenshot(path=str(output.with_suffix('.png')), full_page=True)
            print('LIVE RESEARCH ACCEPTANCE PASSED: ' + json.dumps(report), flush=True)
        finally:
            browser.close()


if __name__ == '__main__':
    main()
