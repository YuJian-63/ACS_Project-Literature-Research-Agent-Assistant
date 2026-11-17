import assert from 'node:assert/strict';
import { normalizeAgentSubmission, agentCitationUrl } from '../src/features/research/lib/agentV1.ts';
{
  const body = normalizeAgentSubmission({ task_type: 'qa', question: ' Why? ', sources: ' 2401.12345v2\nhttps://arxiv.org/abs/2402.01234 ', allow_search: false, max_papers: 3 });
  assert.equal(body.question, 'Why?');
  assert.deepEqual(body.sources, ['2401.12345v2', 'https://arxiv.org/abs/2402.01234']);
  assert.equal(body.max_output_tokens, 4096);
  assert.equal(Object.hasOwn(body, 'paper_ids'), false);
  assert.equal(agentCitationUrl('javascript:alert(1)', 3), undefined);
  assert.equal(agentCitationUrl('/api/v1/papers/local/file', 3), undefined);
  assert.equal(agentCitationUrl('https://arxiv.org/pdf/2401.12345#old', 3), 'https://arxiv.org/pdf/2401.12345#page=3');
  console.log('PASS: Agent request and safe external citation contracts');
}
