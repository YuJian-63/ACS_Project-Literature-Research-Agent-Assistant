import assert from 'node:assert/strict';
import {createServer} from 'vite';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {fileURLToPath} from 'node:url';
const server=await createServer({root:fileURLToPath(new URL('../',import.meta.url)),server:{middlewareMode:true,watch:null,ws:false},appType:'custom'});
try {
 const module=await server.ssrLoadModule('/src/features/agentResearch/EvaluationPanel.tsx');
 assert.equal(typeof module.EvaluationReportView,'function','report layout must expose a testable view');
 const dimension={score:0,reason:'zero-reason'};
 const metrics={schema_version:'task-metrics-v1',evaluation:{status:'succeeded',assessment:'scored',overall_score:0,overall_score_max:80,score_max:4,weights:{grounded_correctness:23},dimensions:Object.fromEntries(['grounded_correctness','citation_support','task_completion','analysis_quality','clarity'].map(k=>[k,dimension]))},agent:{available:true,agent_steps:3,model_calls:5,tool_calls:2,input_tokens:null,output_tokens:0,total_tokens:null,token_usage_complete:false},model_server:{status:'partial',ttft_ms:{mean:0,samples:2,source:'native-ttft'},tpot_ms:{mean:null,samples:0,source:null},mean_itl_ms:{mean:12,samples:1,source:'native-itl'},tokens_per_second:{mean:10,samples:1,source:'native-speed'},gpus:[{uuid:'GPU-long-id',utilization_percent:0,call_index:1,sampled_at:'sample-time'}],requests:[{call_index:1,request_id:'req-one',ttft_ms:0,cache_hit_tokens:0,gpus:[],sources:{ttft_ms:'per-request-source'}}],cache_hit_tokens:0,cache_query_tokens:100,cache_hit_ratio:0,cache_measured_model_calls:1,cache_usage_complete:false,model_calls_total:5,observed_model_calls:4,measured_model_calls:2,aggregation:'same-source',gpu_scope:'response-completion'}};
 const version={id:'version-one',status:'succeeded',attempts:1,max_attempts:3,report:{summary:'summary-fixture',issues:[{severity:'major',message:'issue-fixture',citation_keys:['C1'],answer_excerpt:'<script>unsafe</script>'}],suggestions:['suggestion-fixture'],limitations:['limitation-fixture'],evaluation_scope:'original_pages',evidence_checks:[{citation_key:'C1',status:'matched'}],reference_checks:{unused_citations:['E1']},extra_field:'preserve-future-field'},usage:{prompt_tokens:15,total_tokens:null},input_sha256:'digest-fixture'};
 const html=renderToStaticMarkup(createElement(module.EvaluationReportView,{metrics,version}));
 for(const text of ['80','23%','zero-reason','summary-fixture','issue-fixture','suggestion-fixture','limitation-fixture','GPU-long-id','sample-time','native-ttft','same-source','response-completion']) assert.ok(html.includes(text),text);
 for(const text of ['REQUEST DETAILS','AUDIT &amp; METADATA','per-request-source','req-one','digest-fixture','preserve-future-field']) assert.ok(!html.includes(text),`removed sections must stay hidden: ${text}`);
 assert.ok(!html.includes('<script>unsafe</script>'),'report text is escaped');
 assert.ok(html.includes('&lt;script&gt;unsafe&lt;/script&gt;'));
 assert.match(html,/aria-valuemax="4"/);
 metrics.evaluation.assessment='insufficient_evidence';
 const missing=renderToStaticMarkup(createElement(module.EvaluationReportView,{metrics,version}));
 assert.ok(!missing.includes('aria-valuenow="0"'),'insufficient evidence has no numerical dimension meters');
 console.log('PASS: report, summary telemetry, removed detail sections, dynamic scale/weights and escaped report text');
}finally{await server.close()}
