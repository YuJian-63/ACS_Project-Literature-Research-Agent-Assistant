// Offline workspace integration check. All API responses are mocked.
const {launchBrowser}=require('./browser.cjs');
const BASE = process.env.AGENT_WORKSPACE_URL || 'http://127.0.0.1:5175';
(async()=>{
const browser=await launchBrowser();
const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[],calls=[];page.on('pageerror',e=>errors.push(e.message));
await page.addInitScript(()=>localStorage.setItem('literature-v3-ui-locale','zh-CN'));
const id='11111111-1111-4111-8111-111111111111', taskid='22222222-2222-4222-8222-222222222222';
const paper={id,title:'测试论文 Attention',original_filename:'paper.pdf',status:'ready',page_count:12,created_at:new Date().toISOString(),updated_at:new Date().toISOString(),source:null};
const submitted=[];
await page.route('**/api/v1/**',route=>{const req=route.request(),path=new URL(req.url()).pathname;calls.push([req.method(),path]);
if(req.method()!=='GET' && path!=='/api/v1/agent-research')throw Error('Unexpected mutation '+path);
if(path==='/api/v1/agent-research' && req.method()==='POST') {
  const input=req.postDataJSON();submitted.push(input);if(input.question!=='研究方法是什么？'||input.allow_search!==true)throw Error('Incorrect request contract');
  return route.fulfill({json:{task_id:taskid}});
}
if(path==='/api/v1/agent-research/'+taskid)return route.fulfill({json:{task_id:taskid,status:'succeeded',question:'研究方法是什么？',paper_ids:[id],error:null,result:{task_id:taskid,question:'研究方法是什么？',answer:'## 测试返回正文\n\n依据论文方法部分进行分析 [chunk-1]',comparison_table:'',citations:[{chunk_id:'chunk-1',source_id:'source-1',paper_id:id,title:paper.title,page:3,source_text:'这是一条用于验证接口的完整测试句子。',url:''}],sources:[{paper_id:id,source_id:'source-1',title:paper.title,url:''}],unresolved:[],stop_reason:'completed',usage:{},trace:[],errors:[],configuration:{}}}});
if(path.endsWith('/auth/me'))return route.fulfill({json:{user:{id:'a',username:'alice',email:'a@b.com'},csrf_token:'fixture'}});
if(path==='/api/v1/models')return route.fulfill({json:{bailian_config:'missing',bailian_name:null,enabled:true,state:'ready',owner:false,generation:null,job_id:null,base_url:'http://10.0.3.11:8000/v1',shared_url:null,detail:null,requested_at:null,checked_at:null}});
if(path==='/api/v1/papers/'+id)return route.fulfill({json:paper});
if(path.startsWith('/api/v1/tasks'))throw Error('Research detail API must remain disconnected: '+path);
return route.fulfill({json:{items:path==='/api/v1/papers'?[paper]:[],total:path==='/api/v1/papers'?1:0,limit:20,offset:0}});
});
await page.goto(BASE+'/tasks/new');
await page.getByRole('heading',{name:'参考论文（可选）',exact:true}).waitFor();
for(const label of ['01 · 明确问题','02 · 选择资料'])if(await page.getByText(label,{exact:true}).count())throw Error('Numbered step remains');
await page.getByRole('button',{name:'开始研究',exact:true}).click();
await page.getByText('请先写下你的研究问题。',{exact:true}).waitFor();
if(submitted.length)throw Error('Blank question was submitted');
await page.locator('textarea').fill('研究方法是什么？');
await page.getByRole('button',{name:'开始研究',exact:true}).click();
await page.waitForURL('**/tasks/'+taskid);
if(submitted[0].paper_ids.length!==0||!submitted[0].allow_search)throw Error('Question-only request contract invalid');
await page.goto(BASE+'/tasks/new?paper_id='+id);
await page.locator('.research-submit-panel li').filter({hasText:paper.title}).waitFor();
if (!(await page.getByRole('radio', {name:'Baseline', exact:true}).isChecked())) throw Error('Expected default Baseline');
await page.getByText('Extension', {exact:true}).click();
if (submitted[0].research.context_policy !== 'compact' || submitted[0].research.planner || submitted[0].research.reflection) throw Error('Incorrect Baseline defaults');
for (const name of ['Planner', 'Reflection']) {
  if (!(await page.getByRole('checkbox', {name, exact:true}).isChecked())) throw Error(name + ' should default to enabled');
}
await page.getByText('Planner', {exact:true}).click();
await page.getByText('Baseline', {exact:true}).click();
await page.getByText('Extension', {exact:true}).click();
await page.locator('textarea').fill('研究方法是什么？');
await page.getByRole('button',{name:'开始研究',exact:true}).click();await page.waitForURL('**/tasks/'+taskid);
if(submitted[1].paper_ids[0]!==id||!submitted[1].allow_search)throw Error('Reference paper request invalid');
if(submitted[1].research.workflow!=='extension'||submitted[1].research.context_policy!=='compact'||submitted[1].research.planner||!submitted[1].research.reflection)throw Error('Extension options missing');
await page.goto(BASE+'/tasks/new');await page.getByRole('button',{name:'English',exact:true}).click();
await page.getByRole('heading',{name:'Reference papers (optional)',exact:true}).waitFor();
await page.getByText('No reference papers selected. Relevant material will be found for your research question.',{exact:true}).waitFor();
await page.setViewportSize({width:390,height:844});await page.waitForFunction(()=>document.documentElement.scrollWidth<=innerWidth);
if(errors.length)throw Error(errors.join('\n'));
console.log('PASS: question required, optional references, no step numbering, both payloads allow search, bilingual labels and mobile layout');
await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
