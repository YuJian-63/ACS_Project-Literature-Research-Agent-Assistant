const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.BROWSER_EXECUTABLE || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
 try{
 const page=await browser.newPage({reducedMotion:'reduce'});page.setDefaultTimeout(7000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const id='11111111-1111-4111-8111-111111111111', paperId='33333333-3333-4333-8333-333333333333';
 const paper={id:paperId,title:'Fixture paper',status:'ready',page_count:3,created_at:'2026-01-01',size_bytes:10};
 const task={id,task_type:'review',status:'succeeded',stage:'completed',question:'Compare methods',paper_ids:[paperId],created_at:'2026-01-01',budget:{max_steps:2,max_tokens:1000,timeout_seconds:60},stats:{},versions:{},last_event_seq:0};
 const raw='rd\nnetwork (FFN) [80] are stacked in sequence to extract features.\nWe design seven architectures V AN-\nB3 according to computational cost. The details are s';
 const artifact={id:'22222222-2222-4222-8222-222222222222',task_id:id,title:'论文综述',content_markdown:'Result',citations:['C1','C2'].map((key,n)=>({citation_key:key,paper_id:paperId,paper_title:paper.title,page_number:n+1,quote:n===0?raw:'Evidence C2.'})),comparison_table:{columns:[{key:'method',label:'方法'}],rows:[{paper_id:paperId,cells:{method:{value:'Plain method text',citation_keys:['C1','C2']}}}]}};
 await page.route('**/api/v1/**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/auth/me'))return route.fulfill({json:{user:{username:'Researcher',id:'fixture',email:'r@example.org'},csrf_token:'fixture'}});
  if(path.includes('/papers/'))return route.fulfill({json:paper});
  if(path.endsWith('/artifacts'))return route.fulfill({json:{items:[artifact]}});
  if(path.endsWith('/events'))return route.fulfill({json:{items:[],next_after_seq:0,has_more:false}});
  return route.fulfill({json:task});
 });
 for(const width of [1440,390]){
 await page.setViewportSize({width,height:1000});await page.goto((process.env.SEARCH_PREVIEW_URL || 'http://127.0.0.1:5198')+'/tasks/'+id+'?view=compare');
 const cell=page.locator(width>1000?'.comparison-scroll td .comparison-cell-content':'.mobile-comparison .comparison-cell-content');
 await cell.waitFor();const buttons=cell.locator('button');assert.deepEqual(await buttons.allTextContents(),['[C1] 查看证据','[C2] 查看证据']);
 const styles=await buttons.evaluateAll(nodes=>nodes.map(el=>{const s=getComputedStyle(el);return [s.fontFamily,s.fontSize,s.fontWeight,s.padding,s.width]}));assert.deepEqual(styles[0],styles[1]);
 await cell.getByText('Plain method text',{exact:true}).click();assert.equal(await buttons.first().getAttribute('aria-pressed'),'false');assert.equal(await buttons.last().getAttribute('aria-pressed'),'false');
 if(width<1001)assert.equal(await page.locator('.evidence-drawer').count(),0);
 await buttons.last().click();await page.locator('.evidence-quote:visible').getByText('Evidence C2.',{exact:true}).waitFor();assert.equal(await buttons.last().getAttribute('aria-pressed'),'true');
 if(width<1001){await page.keyboard.press('Escape');await page.locator('.evidence-drawer').waitFor({state:'hidden'});}
 await buttons.first().focus();await page.keyboard.press('Enter');await page.locator('.evidence-quote:visible').getByText('We design seven architectures V AN-B3 according to computational cost.',{exact:true}).waitFor();
 await page.locator('.evidence-original:visible summary').click();
 assert.equal(await page.locator('.evidence-raw-quote:visible').textContent(),raw);
 }
 assert.deepEqual(errors,[]);console.log('PASS: uniform multi-citation text links, plain text inert, correct evidence selection and keyboard activation at desktop/mobile widths');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
