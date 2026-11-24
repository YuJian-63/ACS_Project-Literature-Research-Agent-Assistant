import assert from 'node:assert/strict';
import { createServer } from 'vite';
import { createElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { renderToStaticMarkup } from 'react-dom/server';
import { fileURLToPath } from 'node:url';
const server = await createServer({ root: fileURLToPath(new URL('../', import.meta.url)), server: { middlewareMode: true, hmr: false, watch: null }, appType: 'custom' });
try {
  const { setLocale } = await server.ssrLoadModule('/src/i18n/store.ts');
  setLocale('zh-CN');
  const { RecordStatusView } = await server.ssrLoadModule('/src/features/agentResearch/RecordStatus.tsx');
  const render = (status, evaluation) => renderToStaticMarkup(createElement(RecordStatusView, { status, evaluation })).replace(/<[^>]+>/g, '').replace(/\s+/g, ' ');
  for (const status of ['failed', 'queued', 'running']) assert.doesNotMatch(render(status, { status: 'succeeded', assessment: 'scored', overall_score: 85, overall_score_max: 100 }), /评分|85/);
  for (const [status, label] of [['not_requested', '尚未评分'], ['pending', '等待评分'], ['running', '正在评分'], ['failed', '评分失败'], ['skipped', '已跳过评分']]) assert.ok(render('succeeded', { status }).includes(label));
  assert.match(render('succeeded', { status: 'succeeded', assessment: 'scored', overall_score: 0, overall_score_max: 100 }), /评分完成.*0 \/ 100/);
  const insufficient = render('succeeded', { status: 'succeeded', assessment: 'insufficient_evidence', overall_score: null });
  assert.match(insufficient, /证据不足，无法评分/);
  assert.doesNotMatch(insufficient, /0 \/|评分完成/);
  assert.match(render('succeeded'), /正在读取评分/);
  const markup = renderToStaticMarkup(createElement(MemoryRouter, {}, createElement(RecordStatusView, { status: 'succeeded', taskId: 'task-one', evaluation: { status: 'failed' } })));
  assert.match(markup, /class="status-badge status-failed"/, 'evaluation uses the shared badge appearance');
  assert.match(markup, /href="\/tasks\/task-one\?tab=evaluation"[^>]*>[^]*评分失败/, 'evaluation links to its report tab');
  assert.doesNotMatch(markup, /<a[^>]*>[^]*已完成[^]*<\/a>/, 'research completion is not linked');
  for (const [score, tone] of [[100, 'high'], [85, 'high'], [84.99, 'medium'], [70, 'medium'], [69.99, 'warning'], [60, 'warning'], [59.99, 'low'], [0, 'low']]) {
    const html = renderToStaticMarkup(createElement(MemoryRouter, {}, createElement(RecordStatusView, { status: 'succeeded', taskId: 'task-one', evaluation: { status: 'succeeded', assessment: 'scored', overall_score: score, overall_score_max: 100 } })));
    const scoreLink = html.match(/<a class="status-badge record-evaluation-score record-score-([^"]+)"[^>]*href="([^"]+)"[^>]*>([^]*?)<\/a>/);
    assert.ok(scoreLink, 'score has its own linked badge');
    assert.equal(scoreLink[1], tone, `score color at ${score}`);
    assert.equal(scoreLink[2], '/tasks/task-one?tab=evaluation');
    assert.ok(!scoreLink[3].includes('status-dot'), 'score badge has no dot');
  }
  const { default: ResultContent } = await server.ssrLoadModule('/src/features/agentResearch/ResultContent.tsx');
  const result = { task_id: 'task-one', answer: 'Answer', comparison_table: '', unresolved: [], citations: [], sources: [], trace: [] };
  const report = renderToStaticMarkup(createElement(MemoryRouter, { initialEntries: ['/tasks/task-one?tab=evaluation'] }, createElement(ResultContent, { result })));
  assert.match(report, /data-node-key="evaluation"[^]*?<div role="tab" aria-selected="true"/, 'deep link opens evaluation tab');
  console.log('PASS: research record evaluation states, badge links and evaluation deep links');
} finally { await server.close(); }
