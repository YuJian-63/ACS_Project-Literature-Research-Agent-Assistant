const assert = require('node:assert/strict');
const { launchBrowser } = require('./browser.cjs');
(async()=>{
 const browser=await launchBrowser();
 try {
 const page=await browser.newPage({viewport:{width:1440,height:1100}});
 page.setDefaultTimeout(10000);
 const errors=[]; page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(()=>localStorage.setItem('literature-v3-ui-locale','zh-CN'));
 await page.clock.install();
 const taskId='22222222-2222-4222-8222-222222222222';
 let evaluationId='33333333-3333-4333-8333-333333333333';
 let status='not_requested', posts=0, details=0, failPost=false, failGet=false;
 let assessment='scored', attempts=1, expectRefresh=false;
 const keys=['grounded_correctness','citation_support','task_completion','analysis_quality','clarity'];
 const evaluation=()=>({enabled:true,configured:true,status,evaluation_id:status==='not_requested'?null:evaluationId,provider:'deepseek',model:'judge-model',rubric_version:'research-v1',prompt_version:'judge-v1',assessment:status==='succeeded'?assessment:null,overall_score:status==='succeeded'&&assessment==='scored'?82.4:null,overall_score_max:100,score_max:5,weights:Object.fromEntries(keys.map((k,i)=>[k,[30,30,20,15,5][i]])),dimensions:Object.fromEntries(keys.map((k,i)=>[k,{score:status==='succeeded'&&assessment==='scored'?[4.2,3.8,4.5,4,4.4][i]:null,reason:status==='succeeded'?'来自引用证据的评分说明。':null}]))});
 const aggregate={mean:null,samples:0,source:null,unavailable_reason:'NO_SAMPLES'};
 const metrics=()=>({schema_version:'task-metrics-v1',evaluation:evaluation(),agent:{available:true,agent_steps:8,model_calls:10,tool_calls:7,input_tokens:12000,output_tokens:2000,total_tokens:14000,token_usage_complete:false},model_server:{status:'partial',unavailable_reason:null,model_calls_total:10,observed_model_calls:10,measured_model_calls:9,cache_measured_model_calls:9,cache_usage_complete:false,cache_hit_tokens:740,cache_query_tokens:1000,cache_hit_ratio:0.74,cache_unavailable_reason:null,aggregation:'arithmetic_mean_same_source',ttft_ms:{mean:120,samples:9,source:'metrics.time_to_first_token_ms',unavailable_reason:null},tpot_ms:aggregate,mean_itl_ms:aggregate,tokens_per_second:aggregate,gpus:[{uuid:'GPU-12345678-1234-1234-1234-123456789012',utilization_percent:0,call_index:9,sampled_at:'2026-11-23T00:00:00Z'}],gpu_scope:'allocated_device_response_completion',requests:[{call_index:1,available:true,request_id:'request-fixture',ttft_ms:120,tpot_ms:null,mean_itl_ms:null,tokens_per_second:null,cache_hit_tokens:740,cache_query_tokens:1000,cache_hit_ratio:0.74,sources:{ttft_ms:'metrics.time_to_first_token_ms'},gpus:[],gpu_sampled_at:null,unavailable_reason:null}]}});
 await page.route('**/api/v1/**',async route=>{
  const req=route.request(),url=new URL(req.url()),path=url.pathname;
  if(path.endsWith('/auth/me'))return route.fulfill({json:{user:{id:'user-fixture',username:'alice',email:'test@example.com'},csrf_token:'fixture'}});
  if(path===`/api/v1/tasks/${taskId}/evaluation`){
   if(req.method()==='POST'){
    posts++; assert.equal(req.headers()['x-csrf-token'],'fixture');
    if(expectRefresh){assert.deepEqual(req.postDataJSON(),{refresh_evidence:true});evaluationId='44444444-4444-4444-8444-444444444444';attempts=0;}
    else assert.ok(!req.postData());
    if(failPost)return route.fulfill({status:429,json:{error:{code:'DAILY_EVALUATION_LIMIT',message:'Daily evaluation allowance reached'}}});
    status='pending';await new Promise(resolve=>setTimeout(resolve,250));return route.fulfill({status:202,json:{task_id:taskId,id:evaluationId,status,attempts:0,max_attempts:3}});
   }
   const requestedId=url.searchParams.get('evaluation_id');
   assert.ok([evaluationId,'33333333-3333-4333-8333-333333333333'].includes(requestedId));
   if(requestedId!==evaluationId)return route.fulfill({json:{task_id:taskId,id:requestedId,status:'succeeded',attempts:3,max_attempts:3,report:{assessment:'insufficient_evidence',summary:'旧版本保留，等待新证据。',limitations:['原文核验不可用']}}});
   return route.fulfill({json:{task_id:taskId,id:evaluationId,status,attempts,max_attempts:3,report:status==='succeeded'?{assessment,summary:'结论清晰，实验条件仍需补充。',evaluation_scope:'original_pages',issues:[{severity:'major',code:'invalid_comparison',message:'跨论文实验条件不完全可比。',citation_keys:['C2'],answer_excerpt:'条件不同仍直接比较。'}],suggestions:['补充模型规模、数据集和上下文长度。'],limitations:['仅检查引用页，未审阅完整论文。'],evidence_checks:[{citation_key:'C2',status:'matched'}],reference_checks:{unused_citations:['C1']},extra_field:'all-fields-visible'}:null,usage:{prompt_tokens:1200,completion_tokens:500,total_tokens:1700},created_at:'2026-11-23T00:00:00Z'}});
  }
  if(path===`/api/v1/agent-research/${taskId}`){details++; if(failGet)return route.fulfill({status:503,json:{error:{code:'TEMPORARY_ERROR',message:'Try again'}}});return route.fulfill({json:{task_id:taskId,status:'succeeded',question:'长上下文方法的性能与局限有哪些？',paper_ids:[],error:null,metrics:metrics(),result:{task_id:taskId,answer:'## 研究结论\n\n这是用于界面验收的研究正文。',comparison_table:'',citations:[],sources:[],unresolved:[],usage:{},trace:[],errors:[],configuration:{}}}});}
  return route.fulfill({json:{items:[],total:0}});
 });
 const base=process.env.AGENT_WORKSPACE_URL||'http://127.0.0.1:5173';
 await page.goto(base+'/tasks/'+taskId);
 await page.getByRole('tab',{name:'研究评估',exact:true}).click();
 await page.getByRole('heading',{name:'一份有依据的研究评估'}).waitFor();
 assert.equal(posts,0,'render does not submit a paid evaluation');
 failPost=true;
 await page.getByRole('button',{name:/申请评分/}).click();
 await page.getByText('评分申请未成功',{exact:true}).waitFor();
 assert.equal(posts,1);
 failPost=false;
 const refreshed=page.waitForResponse(r=>r.request().method()==='GET' && new URL(r.url()).pathname===`/api/v1/agent-research/${taskId}`);
 await page.getByRole('button',{name:/申请评分/}).click();
 await page.getByRole('tab',{name:'研究正文',exact:true}).click();
 await refreshed;
 await page.getByRole('tab',{name:'研究评估',exact:true}).click();
 await page.getByText('等待评分',{exact:true}).waitFor();
 assert.equal(posts,2);
 status='succeeded';
 await page.clock.fastForward(31000);
 await page.locator('.evaluation-summary').waitFor();
 assert.equal(posts,2);
 await page.evaluate(()=>window.scrollTo(0,0));
 await page.setViewportSize({width:390,height:844});
 await page.evaluate(()=>window.scrollTo(0,0));
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),'no document-level horizontal overflow');
 failGet=true;
 await page.getByRole('button',{name:/刷\s*新/}).click();
 await page.getByText('查询失败',{exact:true}).waitFor();
 await page.locator('.evaluation-summary').waitFor();
 assert.ok(details>=3);
 failGet=false; assessment='insufficient_evidence'; attempts=3;
 await page.reload();
 await page.getByRole('tab',{name:'研究评估',exact:true}).click();
 await page.getByText('证据不足，无法评分',{exact:true}).waitFor();
 await page.locator('.evaluation-total-unavailable').getByText('无法评分',{exact:true}).waitFor();
 assert.equal(await page.getByText('未评分',{exact:true}).count(),5);
 await page.locator('.evaluation-summary').waitFor();
 assert.ok(await page.getByRole('button',{name:/重新评分/}).isEnabled(),'exhausted old version does not block a fresh evaluation');
 if(process.env.EVALUATION_SCREENSHOT_PATH)await page.screenshot({path:process.env.EVALUATION_SCREENSHOT_PATH,fullPage:true});
 expectRefresh=true;
 const reassessed=page.waitForResponse(response=>response.request().method()==='GET' && new URL(response.url()).searchParams.get('evaluation_id')==='44444444-4444-4444-8444-444444444444');
 await page.getByRole('button',{name:/重新评分/}).click();
 await reassessed;
 await page.getByText('等待评分',{exact:true}).waitFor();
 assert.equal(posts,3,'one explicit new-version request');
 status='succeeded'; assessment='scored'; attempts=1;
 await page.clock.fastForward(31000);
 await page.locator('.evaluation-total-number').filter({hasText:'82.4'}).waitFor();
 assert.equal(posts,3,'polling never creates another paid evaluation');
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),'reassessment fits a narrow screen');
 assert.deepEqual(errors,[]);
 console.log('PASS: explicit POST + CSRF, 429/retry, pinned report GET, independent polling, retained content, insufficient evidence, fresh reassessment and mobile layout');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
