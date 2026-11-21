// prepare uploads the fixture. run submits both real jobs and verifies their citation links.
// node checks/live-tcloud.cjs prepare|run|retry FRONTEND_URL LOGIN_JSON PDF REPORT_JSON [discovered|selected]
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { launchBrowser } = require('./browser.cjs');

const [action, base, loginFile, pdfFile, reportFile, retryMode] = process.argv.slice(2);
const modes = ['discovered', 'selected'];
if (!['prepare', 'run', 'retry'].includes(action) || !reportFile || (action === 'retry' && !modes.includes(retryMode))) {
  throw Error('Expected prepare|run|retry FRONTEND_URL LOGIN_JSON PDF REPORT_JSON [discovered|selected]');
}
const title = 'Orchid Calibration Report';
const marker = 'LUMEN-472';
const question = 'Use only my library copy of "Orchid Calibration Report". What verification label was recorded in the final calibration run? Read page two and cite its exact evidence. Do not use the web or arXiv.';
const report = fs.existsSync(reportFile) ? JSON.parse(fs.readFileSync(reportFile, 'utf8')) : { jobs: {} };
function save() {
  fs.mkdirSync(path.dirname(reportFile), { recursive: true });
  fs.writeFileSync(reportFile + '.part', JSON.stringify(report, null, 2) + '\n');
  fs.renameSync(reportFile + '.part', reportFile);
}
const at = (response, method, pathname) => response.request().method() === method && new URL(response.url()).pathname === pathname;

async function login(page) {
  const account = JSON.parse(fs.readFileSync(loginFile, 'utf8'));
  await page.goto(new URL('/login', base).href);
  try {
    await page.getByLabel('用户名', { exact: true }).fill(account.username);
    await page.locator('input[autocomplete="current-password"]').fill(account.password);
    const loggedIn = page.waitForResponse(response => at(response, 'POST', '/api/v1/auth/login'));
    await page.getByRole('button', { name: '登录', exact: true }).click();
    assert.equal((await loggedIn).status(), 200);
    await page.waitForURL('**/papers');
  } catch {
    throw Error('Browser login did not complete');
  }
}

async function prepare(page) {
  const response = page.waitForResponse(response => at(response, 'POST', '/api/v1/papers'));
  await page.locator('input[type=file]').setInputFiles(pdfFile);
  const uploaded = await response;
  assert.equal(uploaded.status(), 201);
  const paper = await uploaded.json();
  assert.equal(paper.sha256, createHash('sha256').update(fs.readFileSync(pdfFile)).digest('hex'));
  await page.locator('[data-paper-id="' + paper.id + '"]').waitFor();
  report.paper = { id: paper.id, sha256: paper.sha256, title: paper.title };
  save();
  console.log('Uploaded', paper.id);
}

async function submit(page, kind) {
  await page.goto(new URL('/tasks/new', base).href);
  const selected = kind === 'selected' ? [report.paper.id] : [];
  if (selected.length) {
    await page.locator('tr[data-row-key="' + selected[0] + '"] input[type=checkbox]').check({ timeout: 120000 });
    await page.locator('.research-submit-panel li').filter({ hasText: title }).waitFor();
  } else {
    await page.locator('.research-auto-sources').waitFor();
  }
  await page.locator('textarea').fill(question);
  const accepted = page.waitForResponse(response => at(response, 'POST', '/api/v1/agent-research'));
  await page.getByRole('button', { name: '开始研究', exact: true }).click();
  const response = await accepted;
  assert.equal(response.status(), 202);
  const input = response.request().postDataJSON();
  const { task_id } = await response.json();
  if (report.jobs[kind]) {
    report.attempts ??= [];
    report.attempts.push({ kind, ...report.jobs[kind] });
  }
  report.jobs[kind] = { task_id, paper_ids: input.paper_ids, allow_search: input.allow_search };
  save();
  console.log('Submitted', kind, task_id);
  assert.deepEqual(input, { question, paper_ids: selected, allow_search: true });
  await page.waitForURL('**/tasks/' + task_id);
}

async function verify(page, kind) {
  const job = report.jobs[kind];
  const detail = '/api/v1/agent-research/' + job.task_id;
  const terminal = page.waitForResponse(async response => {
    if (!at(response, 'GET', detail)) return false;
    if (!response.ok()) return true;
    const { status } = await response.json();
    return status === 'succeeded' || status === 'failed';
  }, { timeout: 40 * 60 * 1000 });
  await page.goto(new URL('/tasks/' + job.task_id, base).href);
  const response = await terminal;
  assert.equal(response.status(), 200, 'Result page could not load the task');
  const record = await response.json();
  job.status = record.status;
  job.stop_reason = record.result?.stop_reason ?? null;
  job.error_code = record.error?.code ?? null;
  save();
  assert.equal(record.status, 'succeeded', job.error_code || 'Expected a successful job');
  assert.deepEqual(record.paper_ids, job.paper_ids);
  const result = record.result;
  job.tools = result.trace.filter(entry => entry.kind === 'tool').map(entry => entry.name);
  job.model_calls = result.usage.model_calls;
  save();
  if (kind === 'discovered') assert(job.tools.includes('search_library'), 'The empty-selection job did not search the library');
  const source = 'local:' + report.paper.id + '@' + report.paper.sha256;
  assert(result.sources.some(item => item.source_id === source && item.paper_id === report.paper.id));
  assert(result.answer.includes(marker));
  const citation = result.citations.find(item => item.source_id === source && item.page === 2 && item.source_text.includes(marker));
  assert(citation, 'Missing page-two evidence for the uploaded file');
  const body = page.locator('.research-markdown').filter({ hasText: marker });
  await body.waitFor();
  const index = result.citations.indexOf(citation) + 1;
  await body.getByRole('button', { name: '[C' + index + ']', exact: true }).first().click();
  const drawer = page.getByRole('dialog');
  await drawer.locator('blockquote').filter({ hasText: marker }).waitFor();
  const file = page.waitForResponse(response => at(response, 'GET', '/api/v1/papers/' + report.paper.id + '/file'));
  await drawer.getByRole('button', { name: '查看 PDF 对应页' }).click();
  const opened = await file;
  assert.equal(opened.status(), 200);
  assert.equal(createHash('sha256').update(await opened.body()).digest('hex'), report.paper.sha256);
  const reader = new URL(page.url()).searchParams;
  assert.equal(reader.get('paper_id'), report.paper.id);
  assert.equal(reader.get('pdf_page'), '2');
  assert.equal(reader.get('return_citation'), citation.chunk_id);
  await page.locator('.paper-reader iframe[src*="#page=2&"]').waitFor();
  Object.assign(job, { answer_marker: marker, source_id: source, citation: citation.chunk_id, pdf_page: 2, verified_at: new Date().toISOString() });
  save();
  console.log('Verified', kind, job.task_id);
}

(async () => {
  const browser = await launchBrowser();
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    await context.addInitScript(() => localStorage.setItem('literature-v3-ui-locale', 'zh-CN'));
    const page = await context.newPage();
    await login(page);
    if (action === 'prepare') {
      if (!report.paper) await prepare(page);
      return;
    }
    assert(report.paper, 'Run prepare with this report before submitting jobs');
    const kinds = action === 'retry' ? [retryMode] : modes;
    if (action === 'retry') assert.equal(report.jobs[retryMode]?.status, 'failed', 'The previous attempt must be terminal before retry');
    for (const kind of kinds) {
      if (!report.jobs[kind] || action === 'retry') await submit(page, kind);
    }
    const pending = kinds.filter(kind => !report.jobs[kind].verified_at);
    const outcomes = await Promise.allSettled(pending.map(async kind => {
      const view = await page.context().newPage();
      try {
        await verify(view, kind);
      } catch (error) {
        console.error('Verification failed', kind, report.jobs[kind].task_id, error.message);
        throw error;
      } finally {
        await view.close();
      }
    }));
    const failed = outcomes.find(result => result.status === 'rejected');
    if (failed) throw failed.reason;
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
