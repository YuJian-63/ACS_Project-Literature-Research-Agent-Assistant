import assert from 'node:assert/strict';
import { createServer } from 'vite';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const server = await createServer({ root, server: { middlewareMode: true, watch: null }, appType: 'custom' });
try {
  const { normalizeSubmission, submissionSignature } = await server.ssrLoadModule('/src/lib/submission.ts');
  const { eventText } = await server.ssrLoadModule('/src/i18n/diagnostics.ts');
  const { setLocale } = await server.ssrLoadModule('/src/i18n/store.ts');
  const first = normalizeSubmission('review', 'Compare', ['b', 'a']);
  const second = normalizeSubmission('review', 'Compare', ['a', 'b']);
  assert.equal(Object.hasOwn(first, 'budget'), false, 'Review request must omit manual budgets');
  assert.equal(submissionSignature(first), submissionSignature(second));
  for (const taskType of ['summary', 'qa', 'review']) {
    const input = normalizeSubmission(taskType, 'method', ['a']);
    assert.equal(Object.hasOwn(input, 'budget'), false, 'All task requests must omit manual budgets');
    assert.equal(submissionSignature(input), submissionSignature({ ...input, budget: { max_steps: 1, max_tokens: 1, timeout_seconds: 1 } }));
  }
  const event = { stage: 'analyzing', message: '正在分析论文', payload: { current: 4, total: 6 } };
  setLocale('en-US');
  assert.equal(eventText(event), 'Analyzing papers: 4 / 6');
  setLocale('zh-CN');
  assert.equal(eventText(event), '正在分析论文：4 / 6');
  const insufficient = { stage: 'retrieving', message: '已完成证据检查', payload: { evidence_status: 'insufficient_selected_evidence' } };
  assert.match(eventText(insufficient), /不代表论文全文/);
  setLocale('en-US');
  assert.match(eventText(insufficient), /retrieved passages/);
  assert.match(eventText({ stage: 'retrieving', message: '检索词扩展不可用，已使用原问题和论文结构继续检索', payload: {} }), /Query expansion is unavailable/);
  console.log('PASS: server-owned review budgets, stable submissions, automatic summary/QA budgets and bilingual progress');
} finally {
  await server.close();
}
