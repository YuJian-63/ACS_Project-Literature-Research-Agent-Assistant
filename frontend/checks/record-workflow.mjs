import assert from 'node:assert/strict';
import { createServer } from 'vite';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { fileURLToPath } from 'node:url';
const server = await createServer({ root: fileURLToPath(new URL('../', import.meta.url)), server: { middlewareMode: true, watch: null, ws: false }, appType: 'custom' });
try {
  const { WorkflowLabel } = await server.ssrLoadModule('/src/features/agentResearch/RecordWorkflow.tsx');
  const render = workflow => renderToStaticMarkup(createElement(WorkflowLabel, { workflow }));
  assert.match(render('baseline'), />Baseline</);
  assert.match(render('extended'), />Extension</);
  assert.doesNotMatch(render(undefined), /Baseline|Extension/);
  assert.doesNotMatch(render('unexpected'), /Baseline|Extension/);
  console.log('PASS: workflow labels distinguish submitted Baseline/Extension and never guess unavailable values');
} finally { await server.close(); }
