import assert from 'node:assert/strict';
import { createServer } from 'vite';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { fileURLToPath } from 'node:url';
const server = await createServer({ root: fileURLToPath(new URL('../', import.meta.url)), server: { middlewareMode: true, hmr: false, watch: null }, appType: 'custom' });
try {
  const { default: Panel } = await server.ssrLoadModule('/src/features/agentResearch/EvaluationPanel.tsx');
  const render = metrics => renderToStaticMarkup(createElement(Panel, { metrics }));
  assert.match(render(), /当前服务未提供指标|has not provided metrics/);
  const dimensions = Object.fromEntries(['grounded_correctness','citation_support','task_completion','analysis_quality','clarity'].map(key => [key, {score:0, reason:'verified-zero'}]));
  const empty = {mean:null,samples:0,source:null,unavailable_reason:'NO_SAMPLES'};
  const metrics = {
    evaluation:{status:'succeeded',assessment:'scored',overall_score:0,score_max:5,overall_score_max:100,weights:{},dimensions},
    agent:{agent_steps:0,model_calls:0,tool_calls:0,input_tokens:null,output_tokens:0,total_tokens:null,token_usage_complete:false},
    model_server:{status:'partial',requests:[],ttft_ms:empty,tpot_ms:empty,mean_itl_ms:empty,tokens_per_second:empty,cache_hit_tokens:740,cache_query_tokens:1000,cache_hit_ratio:0.74,cache_measured_model_calls:2,model_calls_total:5,cache_usage_complete:false,gpus:[{uuid:'GPU-fixture',utilization_percent:0,call_index:1,sampled_at:'2026-11-23T00:00:00Z'}]},
  };
  const html = render(metrics).replace(/<[^>]+>/g, '').replace(/\s+/g, ' ');
  for (const text of ['0 / 100','0 / 5','74%','740 / 1000','2 / 5','GPU-fixture: 0%','NO_SAMPLES','verified-zero']) assert.ok(html.includes(text), text);
  metrics.evaluation.assessment = 'insufficient_evidence';
  assert.ok(!/score\)?: 0 \/ 100|评分: 0 \/ 100/.test(render(metrics)), 'insufficient evidence must never become a zero score');
  console.log('PASS: real evaluation panel renders missing metrics, genuine zero scores, partial cache coverage and GPU snapshots');
} finally { await server.close(); }
