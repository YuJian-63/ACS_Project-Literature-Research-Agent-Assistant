const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');const assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({executablePath:process.env.BROWSER_EXECUTABLE || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});try{
 const page=await browser.newPage();page.setDefaultTimeout(8000);let status='queued',offline=false,events=0,queries=0;const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const id='11111111-1111-4111-8111-111111111111';
 await page.route('**/api/v1/**',route=>{const path=new URL(route.request().url()).pathname;
 if(path.endsWith('/auth/me'))return route.fulfill({json:{user:{id:'fixture',username:'Researcher'},csrf_token:'fixture'}});
 if(path.endsWith('/events')){events++;return route.fulfill({status:404,json:{}})}
 if(path.endsWith('/artifacts'))return route.fulfill({json:{items:[{id:'a',task_id:id,task_type:'review',title:'论文综述',content_markdown:'Research is complete.',citations:[],comparison_table:null}]}});
 queries++;if(offline)return route.fulfill({status:503,json:{error:{code:'SERVICE_NOT_READY',message:'暂时无法查询'}}});
 return route.fulfill({json:{id,task_type:'review',status,paper_ids:[],question:'Research question',created_at:'2026-01-01',is_mock:false}});
 });
 await page.goto((process.env.SEARCH_PREVIEW_URL || 'http://127.0.0.1:5198')+'/tasks/'+id);
 await page.getByRole('heading',{name:'任务正在等待处理',exact:true}).waitFor();
 assert.equal(await page.locator('[role=progressbar]').getAttribute('aria-valuenow'),null,'No fabricated percentage');
 status='running';await page.getByRole('heading',{name:'研究正在进行',exact:true}).waitFor();
 await page.getByText(/最近状态确认：/).waitFor();
 for(const text of ['执行记录','实际运行统计','研究输入'])assert.equal(await page.getByText(text,{exact:true}).count(),0);
 offline=true;await page.getByRole('heading',{name:'正在重新连接',exact:true}).waitFor();assert.equal(await page.locator('.task-progress-track > span').evaluate(el=>getComputedStyle(el).animationPlayState),'paused');
 offline=false;await page.getByRole('heading',{name:'研究正在进行',exact:true}).waitFor();
 await page.setViewportSize({width:390,height:900});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 status='succeeded';await page.getByText('Research is complete.',{exact:true}).waitFor();assert.equal(await page.locator('[role=progressbar]').count(),0);assert.equal(events,0);
 const count=queries;await page.waitForTimeout(2500);assert.equal(queries,count,'Terminal tasks stop polling');
 assert.deepEqual(errors,[]);console.log('PASS: queued/running, indeterminate progress, connection loss/recovery, hidden technical details, no events dependency, mobile and automatic completion');
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exit(1)});
