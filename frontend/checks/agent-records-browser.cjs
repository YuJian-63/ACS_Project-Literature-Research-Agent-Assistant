// Offline workspace integration check. All API responses are mocked.
const {launchBrowser}=require('./browser.cjs');
const BASE = process.env.AGENT_WORKSPACE_URL || 'http://127.0.0.1:5174';
(async()=>{
const browser=await launchBrowser();
const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[],calls=[];page.on('pageerror',e=>errors.push(e.message));
await page.addInitScript(()=>{
  if (!localStorage.getItem('literature-v3-ui-locale')) localStorage.setItem('literature-v3-ui-locale','zh-CN');
});
const id='11111111-1111-4111-8111-111111111111', taskid='22222222-2222-4222-8222-222222222222';
const paper={id,title:'测试论文 Attention',original_filename:'paper.pdf',status:'ready',page_count:12,created_at:new Date().toISOString(),updated_at:new Date().toISOString(),source:null};
const external = {id:null, title:'External paper', source_id:'arxiv:1706.03762v7',
  paper_id:'arxiv:1706.03762', version:'v7', url:'https://arxiv.org/abs/1706.03762v7'};
const importedId = '33333333-3333-4333-8333-333333333333';
const importedPaper = {...paper, id:importedId, title:external.title, sha256:'a'.repeat(64),
  source:{provider:'arxiv', external_id:'1706.03762v7'}};
let showRecord = false, imported = false;
let concurrency = 2;
await page.route('**/api/v1/**',route=>{const req=route.request(),path=new URL(req.url()).pathname;calls.push([req.method(),path]);
if (path === '/api/v1/agent-research/queue/concurrency') {
  if (req.method() === 'PUT') {
    const value = req.postDataJSON().concurrency;
    if (![1, 2, 3, 4].includes(value)) throw Error('Invalid concurrency');
    concurrency = value;
  }
  return route.fulfill({json: {concurrency}});
}
if (path === '/api/v1/agent-research' && req.method() === 'GET' && showRecord) {
  const papers = [{id,title:paper.title}, imported ? {id:importedId,title:external.title} : external];
  return route.fulfill({json:{items:[{id:taskid,question:'Compare',paper_ids:[id],papers,
    status:'succeeded',created_at:paper.created_at}],total:1,limit:20,offset:0}});
}
if (path === '/api/v1/paper-imports' && req.method() === 'POST') {
  const input = req.postDataJSON();
  if (input.external_id !== '1706.03762v7' || input.provider !== 'arxiv') throw Error('Wrong import');
  imported = true;
  return route.fulfill({json:{id:importedId,provider:'arxiv',external_id:input.external_id,status:'succeeded',paper_id:importedId}});
}
if (path === '/api/v1/papers/'+importedId) return route.fulfill({json:importedPaper});
if (path.endsWith('/file')) return route.fulfill({contentType:'application/pdf',body:'%PDF-1.4\n%%EOF'});
if(req.method()!=='GET' && path!=='/api/v1/agent-research')throw Error('Unexpected mutation '+path);
if(path==='/api/v1/agent-research' && req.method()==='POST') {
  const input=req.postDataJSON();if(input.question!=='研究方法是什么？'||input.paper_ids[0]!==id)throw Error('Incorrect request contract');
  return route.fulfill({json:{task_id:taskid}});
}
if(path==='/api/v1/agent-research/'+taskid)return route.fulfill({json:{task_id:taskid,status:'succeeded',question:'研究方法是什么？',paper_ids:[id],error:null,result:{task_id:taskid,question:'研究方法是什么？',answer:'## 测试返回正文\n\n依据论文方法部分进行分析 [chunk-1]',comparison_table:'',citations:[{chunk_id:'chunk-1',source_id:'source-1',paper_id:id,title:paper.title,page:3,source_text:'这是一条用于验证接口的完整测试句子。',url:''}],sources:[{paper_id:id,source_id:'source-1',title:paper.title,url:''}],unresolved:[],stop_reason:'completed',usage:{},trace:[],errors:[],configuration:{}}}});
if(path.endsWith('/auth/me'))return route.fulfill({json:{user:{id:'a',username:'alice',email:'a@b.com'},csrf_token:'fixture'}});
if(path==='/api/v1/papers/'+id)return route.fulfill({json:paper});
if(path.startsWith('/api/v1/tasks'))throw Error('Research detail API must remain disconnected: '+path);
return route.fulfill({json:{items:path==='/api/v1/papers'?[paper]:[],total:path==='/api/v1/papers'?1:0,limit:20,offset:0}});
});
await page.goto(BASE+'/tasks');
await page.getByText('还没有研究任务',{exact:true}).waitFor();
const choices = page.getByRole('radiogroup', {name:'全站研究并发数'});
for (const limit of [4, 1, 3, 2]) {
  const saved = page.waitForResponse(res => res.request().method() === 'PUT' &&
    new URL(res.url()).pathname === '/api/v1/agent-research/queue/concurrency');
  await choices.getByText(String(limit), {exact:true}).click();
  await saved;
  await choices.getByRole('radio', {name:String(limit), checked:true}).waitFor({state:'attached'});
}
for(const label of ['论文摘要','论文问答','跨论文综述','全部类型'])if(await page.getByText(label,{exact:true}).count())throw Error('Legacy category remains: '+label);
if(await page.locator('[aria-label="筛选任务类型"]').count())throw Error('Type selector remains');
await page.getByRole('button',{name:'English',exact:true}).click();
await page.getByRole('heading',{name:'Research history',exact:true}).waitFor();
showRecord = true;
await page.reload();
const row = page.getByRole('row').filter({hasText:'Compare'});
await row.getByText('2 papers',{exact:true}).waitFor();
await row.getByRole('link',{name:paper.title}).waitFor();
if (await row.getByRole('link',{name:external.title}).count()) throw Error('Unimported paper links to reader');
await row.getByRole('button',{name:'Import and read “External paper”'}).click();
if (imported) throw Error('Import started before confirmation');
const openedPdf = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/papers/'+importedId+'/file');
await page.getByRole('dialog').getByRole('button',{name:'Import and read',exact:true}).click();
await page.waitForURL(url => url.searchParams.get('paper_id') === importedId);
await openedPdf;
await page.goBack();
await row.getByText('2 papers',{exact:true}).waitFor();
await row.getByRole('link',{name:external.title}).click();
await page.waitForURL(url => url.searchParams.get('paper_id') === importedId);
if (calls.filter(([method,path]) => method === 'POST' && path === '/api/v1/paper-imports').length !== 1)
  throw Error('Opening a downloaded title submitted another import');
if(calls.some(([method,path])=>path.startsWith('/api/v1/tasks')||method==='DELETE'))throw Error('Shared v2 records were accessed');
if(errors.length)throw Error(errors.join('\n'));
console.log('PASS: empty and mixed research records, total paper count, import confirmation and direct PDF links');
await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
