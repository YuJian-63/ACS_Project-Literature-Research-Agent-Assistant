// Offline workspace integration check. All API responses are mocked.
const {launchBrowser}=require('./browser.cjs');
const BASE = process.env.AGENT_WORKSPACE_URL || 'http://127.0.0.1:5175';
(async()=>{
const browser=await launchBrowser();
const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[],calls=[];page.on('pageerror',e=>errors.push(e.message));
await page.addInitScript(()=>localStorage.setItem('literature-v3-ui-locale','zh-CN'));
const id='11111111-1111-4111-8111-111111111111', taskid='22222222-2222-4222-8222-222222222222';
const paper={id,title:'测试论文 Attention',original_filename:'paper.pdf',status:'ready',page_count:12,created_at:new Date().toISOString(),updated_at:new Date().toISOString(),source:null};
await page.route('**/api/v1/**',route=>{const req=route.request(),path=new URL(req.url()).pathname;calls.push([req.method(),path]);
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
await page.goto(BASE+'/tasks/new?paper_id='+id);
await page.getByRole('heading',{name:'你想了解什么？'}).waitFor();
await page.locator('.research-submit-panel li').filter({hasText:paper.title}).waitFor();
if(await page.getByText('查看结果示例',{exact:true}).count())throw Error('Sample entry remains');
await page.locator('textarea').fill('研究方法是什么？');
await page.getByRole('button',{name:'开始研究',exact:true}).click();
await page.waitForURL('**/tasks/'+taskid);
await page.getByRole('heading',{name:'测试返回正文',exact:true}).waitFor();
if(await page.locator('select[aria-label="切换结果示例"]').count())throw Error('Sample selector remains');
if(await page.getByRole('tab',{name:'论文比较',exact:true}).count())throw Error('Empty comparison tab remains');
await page.locator('.research-markdown .citation-trigger').first().click();
await page.getByRole('button',{name:'查看 PDF 对应页',exact:true}).click();
await page.waitForURL('**/papers?**');if(!page.url().includes('pdf_page=3'))throw Error('Wrong PDF page');
await page.goto(BASE+'/tasks/new');await page.getByRole('button',{name:'English',exact:true}).click();
await page.getByRole('button',{name:'Start research',exact:true}).waitFor();
await page.setViewportSize({width:390,height:844});await page.waitForFunction(()=>document.documentElement.scrollWidth<=innerWidth);
if(errors.length)throw Error(errors.join('\n'));
console.log('PASS: formal submission contract, result-by-ID, no sample entries, conditional content, evidence PDF navigation, bilingual and mobile. All research APIs mocked.');
await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
