import assert from 'node:assert/strict';
import { createServer } from 'vite';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const server = await createServer({ root, server: { middlewareMode: true, watch: null }, appType: 'custom' });
try {
  const { readableEvidence } = await server.ssrLoadModule('/src/features/research/lib/evidenceText.ts');
  const broken = 'rd\nnetwork (FFN) [80] are stacked in sequence to extract features.\nWe design seven architectures V AN-B0, V AN-\nB3 according to the parameters and\ncomputational cost. The details of the whole network are s';
  assert.equal(readableEvidence(broken).text, 'We design seven architectures V AN-B0, V AN-B3 according to the parameters and computational cost.');
  assert.equal(readableEvidence(broken).trimmed, true);
  assert.equal(readableEvidence('Only a partial word frag').text, null);
  assert.equal(readableEvidence('We obtain 3.14 accuracy. Results are stable.').text, 'We obtain 3.14 accuracy. Results are stable.');
  assert.equal(readableEvidence('这是一个\n完整句子。尾部残句').text, '这是一个完整句子。');
  assert.equal(readableEvidence('The inter\u00ad\nface is stable.').text, 'The interface is stable.');
  assert.equal(readableEvidence('A long-\nterm study is reported.').text, 'A long-term study is reported.');
  console.log('PASS: readable evidence, sentence fragments, Chinese wrapping and conservative hyphen handling');
  const { importFeedback } = await server.ssrLoadModule('/src/features/search/lib/importFeedback.ts');
  const importing = { attempt: 1, status: 'running', paper_status: null };
  const failedImport = { ...importing, status: 'failed' };
  const downloaded = { ...importing, status: 'succeeded', paper_status: 'uploaded' };
  assert.equal(importFeedback(importing, failedImport), 'failed', 'Background download failures must notify');
  assert.equal(importFeedback(importing, downloaded), 'downloaded', 'Completed downloads must notify');
  assert.equal(importFeedback(failedImport, failedImport), null, 'Repeated polling must not repeat failures');
  assert.equal(importFeedback(downloaded, downloaded), null, 'Repeated polling must not repeat success');
  assert.equal(importFeedback(undefined, failedImport), null, 'Historical failures must not pop up on search');
  assert.equal(importFeedback(undefined, failedImport, true), 'failed', 'Immediate import failures must notify');
  assert.equal(importFeedback(undefined, downloaded, true), 'downloaded', 'Already completed imports must notify when requested');
  assert.equal(importFeedback(downloaded, { ...downloaded, paper_status: 'failed' }), 'parse-failed');
  assert.equal(importFeedback(failedImport, { ...failedImport, attempt: 2 }), 'failed', 'A failed retry is a new event');
  console.log('PASS: asynchronous import success/failure, parsing failure, retry attempts and notification deduplication');
  const { normalizeSubmission, submissionSignature } = await server.ssrLoadModule('/src/features/research/lib/submission.ts');
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
