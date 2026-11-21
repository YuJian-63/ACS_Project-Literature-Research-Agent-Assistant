import assert from 'node:assert/strict';
import { createServer } from 'vite';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const server = await createServer({ root, server: { middlewareMode: true, watch: null, hmr: false, ws: false }, appType: 'custom' });
try {
  const { resolveResearchSource, importedPaperProblem } = await server.ssrLoadModule('/src/features/agentResearch/lib/researchSource.ts');
  const paperId = '11111111-1111-4111-8111-111111111111';
  const local = { source_id: `local:${paperId}@${'a'.repeat(64)}`, paper_id: paperId, title: 'Local', url: '' };
  assert.deepEqual(resolveResearchSource(local), { kind: 'local', paperId });
  assert.deepEqual(resolveResearchSource({ ...local, paper_id: local.source_id }), { kind: 'local', paperId });
  const source = { source_id: 'arxiv:1706.03762v7', paper_id: 'arxiv:1706.03762', title: 'External', url: 'https://arxiv.org/abs/1706.03762v7' };
  assert.deepEqual(resolveResearchSource(source), { kind: 'arxiv', externalId: '1706.03762v7' });
  assert.equal(resolveResearchSource({ ...source, source_id: 'arxiv:hep-th/9901001v2', paper_id: 'arxiv:hep-th/9901001' }).externalId, 'hep-th/9901001v2');
  assert.equal(resolveResearchSource({ ...source, source_id: 'arxiv:1706.03762@012345abcdef', version: null }).reason, 'missing-version');
  assert.equal(resolveResearchSource({ ...source, source_id: 'arxiv:1706.03762' }).reason, 'missing-version');
  const hashed = resolveResearchSource({ ...source, source_id: 'arxiv:1706.03762@012345abcdef', version: 'v7' });
  assert.equal(hashed.sha256Prefix, '012345abcdef');
  assert.equal(resolveResearchSource({ ...source, version: 7 }).externalId, '1706.03762v7');
  for (const invalid of [
    { ...source, paper_id: 'arxiv:1810.04805' }, { ...source, version: 'v2' },
    { ...source, source_id: 'https://evil.test/paper.pdf' },
    { ...source, source_id: 'arxiv:1713.03762v7' },
    { ...local, paper_id: '22222222-2222-4222-8222-222222222222' },
  ]) assert.equal(resolveResearchSource(invalid).kind, 'unavailable');
  const paper = { id: paperId, status: 'ready', page_count: 12, sha256: '012345abcdef' + 'a'.repeat(52), source: { provider: 'arxiv', external_id: '1706.03762v7' } };
  assert.equal(importedPaperProblem(resolveResearchSource(source), paper, 3), null);
  assert.equal(importedPaperProblem(hashed, paper, 3), null);
  assert.equal(importedPaperProblem(hashed, { ...paper, sha256: 'b'.repeat(64) }, 3), 'content-mismatch');
  assert.equal(importedPaperProblem(resolveResearchSource(source), paper, 13), 'page-out-of-range');
  assert.equal(importedPaperProblem(resolveResearchSource(source), { ...paper, source: { ...paper.source, external_id: '1706.03762v8' } }), 'version-mismatch');
  console.log('PASS: local IDs, exact arXiv versions, legacy IDs, missing versions, hash binding and imported PDF page guards');
} finally {
  await server.close();
}
