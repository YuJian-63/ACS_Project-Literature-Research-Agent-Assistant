import assert from 'node:assert/strict';
import { createServer } from 'vite';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const server = await createServer({ root, server: { middlewareMode: true, watch: null }, appType: 'custom' });
const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'sessionStorage');
const values = new Map();
const storage = {
  get length() { return values.size; },
  key(index) { return [...values.keys()][index] ?? null; },
  getItem(key) { return values.get(key) ?? null; },
  setItem(key, value) { values.set(key, value); },
  removeItem(key) { values.delete(key); },
};
try {
  Object.defineProperty(globalThis, 'sessionStorage', { configurable: true, value: storage });
  const { readResearchDraft, saveResearchDraft, clearResearchDraft, clearResearchDrafts, researchSubmission } = await server.ssrLoadModule('/src/shared/lib/researchDraft.ts');
  const input = { question: '  Research question  ', paper_ids: ['11111111-1111-4111-8111-111111111111'], allow_search: true };
  const first = researchSubmission(input);
  assert.match(first.key, /^[0-9a-f-]{36}$/);
  assert.equal(researchSubmission({ ...input, question: 'Research question' }, first).key, first.key);
  assert.notEqual(researchSubmission({ ...input, allow_search: false }, first).key, first.key);
  const research = { workflow: 'extension', planner: true, reflection: true, context_policy: 'compact' };
  assert.notEqual(researchSubmission({ ...input, research }, first).key, first.key);
  assert.notEqual(researchSubmission({ ...input, research: { ...research, model_provider: 'tacc' } }).fingerprint, researchSubmission({...input, research}).fingerprint);
  saveResearchDraft('alice', { question: input.question, paperIds: input.paper_ids, research, allowSearch: false });
  assert.deepEqual(readResearchDraft('alice').research, research);
  assert.equal(readResearchDraft('alice').allowSearch, false);
  saveResearchDraft('alice', { question: input.question, paperIds: input.paper_ids, submission: first });
  assert.deepEqual(readResearchDraft('alice'), { question: input.question, paperIds: input.paper_ids, submission: first });
  assert.equal(readResearchDraft('bob'), undefined);
  storage.setItem('literature-v3-research-draft:bob', '{broken');
  assert.equal(readResearchDraft('bob'), undefined);
  for (const data of [null, {}, { version: 1, question: '', paperIds: ['invalid-id'] }, { version: 1, question: 'a'.repeat(8001), paperIds: [] }]) {
    storage.setItem('literature-v3-research-draft:bob', JSON.stringify(data));
    assert.equal(readResearchDraft('bob'), undefined);
  }
  storage.setItem('unrelated-preference', 'keep');
  clearResearchDraft('alice');
  assert.equal(readResearchDraft('alice'), undefined);
  clearResearchDrafts();
  assert.deepEqual([...values.entries()], [['unrelated-preference', 'keep']]);
  Object.defineProperty(globalThis, 'sessionStorage', { configurable: true, get() { throw new Error('Storage blocked'); } });
  assert.equal(readResearchDraft('alice'), undefined);
  assert.doesNotThrow(() => saveResearchDraft('alice', { question: 'Question', paperIds: [] }));
  assert.doesNotThrow(() => clearResearchDrafts());
  console.log('PASS: request identity, account isolation, malformed drafts, scoped cleanup and blocked storage');
} finally {
  if (descriptor) Object.defineProperty(globalThis, 'sessionStorage', descriptor);
  else delete globalThis.sessionStorage;
  await server.close();
}
