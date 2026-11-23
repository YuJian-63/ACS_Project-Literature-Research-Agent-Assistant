// All requests are intercepted; this check never submits a real research or scoring task.
const assert = require('node:assert/strict');
const {launchBrowser}=require('./browser.cjs');
const base=process.env.AGENT_WORKSPACE_URL || 'http://127.0.0.1:5173';
(async()=>{
 const browser=await launchBrowser();
 try {
 const page=await browser.newPage({viewport:{width:1440,height:1000}, reducedMotion:'reduce'});
 const errors=[], requests=[];
 page.on('pageerror',error=>errors.push(error.message));
 await page.addInitScript(()=>localStorage.setItem('literature-v3-ui-locale','zh-CN'));
 const ids=['11111111-1111-4111-8111-111111111111','22222222-2222-4222-8222-222222222222'];
 const paper='33333333-3333-4333-8333-333333333333';
 const dimensionKeys=['grounded_correctness','citation_support','task_completion','analysis_quality','clarity'];
 const aggregate={mean:null,samples:0,source:null,unavailable_reason:'NO_SAMPLES'};
 function record(i){
  const result={task_id:ids[i],question:'相同研究问题',answer:`## 报告${i?'乙':'甲'}正文\n\n有证据支持的答案 [shared-chunk]`,comparison_table:'方法比较正文',unresolved:i?['乙的待解决项']:[],citations:[{source_id:'source-one',paper_id:paper,title:'原文论文',chunk_id:'shared-chunk',page:i+1,source_text:`${i?'乙':'甲'}的原文证据`,url:''}],sources:[{source_id:'source-one',paper_id:paper,title:'原文论文',url:''}],stop_reason:'completed',usage:{agent_steps:2,model_calls:3,tool_calls:2,input_tokens:40,output_tokens:60,total_tokens:100+i*20,token_usage_complete:true,elapsed_seconds:10+i*5},trace:[],errors:[],configuration:{workflow:i?'extension':'baseline',model:'same-model',context_policy:'CompactHistory',model_provider:'bailian',planner:Boolean(i),reflection:Boolean(i)}};
  const evaluation={status:'succeeded',assessment:'scored',enabled:true,configured:true,evaluation_id:null,overall_score:i?83:75,overall_score_max:100,score_max:5,weights:Object.fromEntries(dimensionKeys.map(k=>[k,20])),dimensions:Object.fromEntries(dimensionKeys.map(k=>[k,{score:i?4.2:3.8,reason:'核对结果'}])),provider:'deepseek',model:'judge',rubric_version:'v1',prompt_version:'p1'};
  const metrics={schema_version:'task-metrics-v1',evaluation,agent:{available:true,...result.usage},model_server:{status:'unavailable',requests:[],ttft_ms:aggregate,tpot_ms:aggregate,mean_itl_ms:aggregate,tokens_per_second:aggregate,gpus:[],cache_hit_tokens:null,cache_query_tokens:null,cache_hit_ratio:null,model_calls_total:3,observed_model_calls:0,measured_model_calls:0,cache_measured_model_calls:0,cache_usage_complete:false}};
  return {task_id:ids[i],question:result.question,status:'succeeded',paper_ids:[paper],result,error:null,metrics};
 }
 let missing=false,unrelated=false,insufficient=false;
 await page.route('**/api/v1/**',route=>{
  const req=route.request(),path=new URL(req.url()).pathname;requests.push([req.method(),path]);
  if(req.method()!=='GET')return route.fulfill({status:500,json:{error:{message:'Unexpected mutation'}}});
  if(path==='/api/v1/auth/me')return route.fulfill({json:{user:{id:'test-user',username:'test',email:'test@example.org'},csrf_token:'test-csrf'}});
  if(path==='/api/v1/agent-research')return route.fulfill({json:{items:ids.map((id,i)=>({id,question:'相同研究问题',paper_ids:[paper],papers:[{id:paper,title:'原文论文'}],status:'succeeded',created_at:'2026-11-23T12:00:00Z'})),total:2,limit:10,offset:0}});
  const i=ids.findIndex(id=>path.endsWith('/'+id));
  if(i!==-1&&path.startsWith('/api/v1/tasks/'))return route.fulfill({json:{workflow_type:unrelated?'baseline':i?'extended':'baseline'}});
  if(i!==-1&&path.startsWith('/api/v1/agent-research/')){
   if(i&&missing)return route.fulfill({status:404,json:{error:{code:'TASK_NOT_FOUND',message:'报告已不存在'}}});
   const r=record(i);if(i&&unrelated){r.question='另一个完全不同的问题';r.paper_ids=[];r.result.configuration.workflow='baseline';}
   if(i&&insufficient){r.metrics.evaluation.assessment='insufficient_evidence';r.metrics.evaluation.overall_score=null;}
   return route.fulfill({json:r});
  }
  return route.fulfill({status:404,json:{error:{code:'NOT_FOUND',message:path}}});
 });
 await page.goto(base+'/tasks');
 await page.getByRole('checkbox',{name:'选择研究记录 11111111'}).check();
 await page.getByRole('checkbox',{name:'选择研究记录 22222222'}).check();
 await page.getByRole('button',{name:'对比所选报告'}).click();
 await page.getByRole('heading',{name:'评测概览',exact:true}).waitFor();
 assert.match(await page.locator('.comparison-total-row').innerText(),/75.*83.*\+8/s);
 await page.getByRole('tab',{name:'论文比较',exact:true}).click();
 await page.getByText('方法比较正文',{exact:true}).first().waitFor();
 assert.equal(await page.getByText('方法比较正文',{exact:true}).count(),2);
 await page.getByRole('tab',{name:'待解决问题',exact:true}).click();
 await page.getByText('此报告未提供该部分内容',{exact:true}).waitFor();
 await page.getByText('乙的待解决项',{exact:true}).waitFor();
 await page.getByRole('tab',{name:'引用与来源',exact:true}).click();
 await page.locator('.research-citation-card').first().waitFor();
 const chipStyles = await page.locator('.research-citation-card .citation-chip').first().evaluate(el=>({whiteSpace:getComputedStyle(el).whiteSpace,shrink:getComputedStyle(el).flexShrink}));
 assert.equal(chipStyles.whiteSpace,'nowrap');assert.equal(chipStyles.shrink,'0');
 await page.getByRole('tab',{name:'研究正文',exact:true}).click();
 await page.locator('.comparison-reading-pane').first().locator('.citation-trigger').click();
 await page.getByText('甲的原文证据',{exact:true}).waitFor();
 await page.locator('.ant-drawer-open .ant-drawer-close').click();
 await page.locator('.comparison-reading-pane').nth(1).locator('.citation-trigger').click();
 await page.getByText('乙的原文证据',{exact:true}).waitFor();
 await page.locator('.ant-drawer-open .ant-drawer-close').click();
 await page.getByRole('tab',{name:'研究评估',exact:true}).click();
 await page.getByText('核对结果',{exact:true}).first().waitFor();
 await page.setViewportSize({width:390,height:844});
 await page.waitForTimeout(250);
 const overflow=await page.evaluate(()=>({width:innerWidth,document:document.documentElement.scrollWidth,elements:[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth+3&&e.getBoundingClientRect().width>0).slice(0,22).map(e=>({tag:e.tagName,cls:e.className,width:e.getBoundingClientRect().width,right:e.getBoundingClientRect().right}))}));
 if(overflow.document>overflow.width+2) console.log('OVERFLOW',JSON.stringify(overflow));
 assert.equal(overflow.document>overflow.width+2,false,'mobile page does not overflow horizontally');
 await page.setViewportSize({width:1440,height:1000});
 await page.getByRole('button',{name:'交换左右'}).click();
 await page.getByRole('heading',{name:'评测概览',exact:true}).waitFor();
 await page.waitForFunction(()=>/83.*75.*-8/s.test(document.querySelector('.comparison-total-row')?.innerText||''));
 assert.match(await page.locator('.comparison-total-row').innerText(),/83.*75.*-8/s);
 await page.getByRole('link',{name:'返回研究记录',exact:true}).click();
 assert.equal(await page.getByRole('checkbox',{name:'选择研究记录 11111111'}).isChecked(),true,'history selection retained');
 unrelated=true;
 await page.goto(base+`/tasks/compare?a=${ids[0]}&b=${ids[1]}`);
 await page.getByText('问题文本不同，仅供并排阅读',{exact:true}).waitFor();
 assert.equal(await page.locator('.comparison-report-card .record-workflow-baseline').count(),2,'same-method reports remain labelled correctly');
 assert.match(await page.locator('.comparison-total-row td').last().innerText(),/\+8/);
 unrelated=false;insufficient=true;await page.reload();
 await page.getByText('证据不足，无法评分',{exact:true}).first().waitFor();
 assert.match(await page.locator('.comparison-total-row td').last().innerText(),/—/);
 missing=true;await page.reload();await page.getByText('报告已不存在',{exact:true}).waitFor();
 assert.equal(await page.getByRole('heading',{name:'评测概览',exact:true}).count(),0);
 await page.goto(base+'/tasks/compare?a=invalid&b=invalid');
 await page.getByText('请选择两份不同的报告',{exact:true}).waitFor();
 assert.deepEqual(errors,[]);assert.ok(requests.every(([method])=>method==='GET'),'comparison makes no automatic POST');
 console.log('PASS: selection navigation, metrics, all content/citation states, swap, history return, mobile width, unrelated/insufficient/missing reports and invalid IDs; GET only');
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
