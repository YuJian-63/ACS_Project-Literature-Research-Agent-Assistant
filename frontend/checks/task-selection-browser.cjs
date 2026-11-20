const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');const assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({executablePath:process.env.BROWSER_EXECUTABLE || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});try{
 const page=await browser.newPage();page.setDefaultTimeout(7000);let posts=0;
 const ids=[1,2].map(n=>'11111111-1111-4111-8111-'+String(n).padStart(12,'0'));const papers=ids.map((id,n)=>({id,title:'Paper '+n,status:'ready',page_count:1,size_bytes:10,created_at:'2026-01-01'}));
 await page.route('**/api/v1/**',route=>{const path=new URL(route.request().url()).pathname;
 if(path.endsWith('/auth/me'))return route.fulfill({json:{user:{id:'fixture',username:'Researcher'},csrf_token:'fixture'}});
 if(route.request().method()==='POST'){posts++;assert.equal(route.request().postDataJSON().paper_ids.length,2);return route.fulfill({status:202,json:{id:'22222222-2222-4222-8222-222222222222'}})}
 if(path.includes('/papers/'))return route.fulfill({json:papers.find(p=>path.endsWith(p.id))});
 if(path.endsWith('/papers'))return route.fulfill({json:{items:papers,total:2,limit:20,offset:0}});
 return route.fulfill({json:{id:'22222222-2222-4222-8222-222222222222',task_type:'review',status:'queued',paper_ids:[],created_at:'2026-01-01'}});
 });
 const base=process.env.SEARCH_PREVIEW_URL || 'http://127.0.0.1:5198';await page.goto(base+'/tasks/new?paper_id='+ids[0]);
 await page.getByText('跨论文综述',{exact:true}).click();await page.getByRole('textbox',{name:'研究问题',exact:true}).fill('Compare methods');
 const submit=()=>page.getByRole('button',{name:'创建研究任务'}).click();await submit();
 const notice=page.locator('.ant-notification-notice');await notice.getByText('综述任务需要选择 2—20 篇论文。',{exact:true}).waitFor();assert.equal(posts,0);
 assert.equal(await page.locator('.form-section .ant-alert-error').count(),0);
 await notice.locator('.ant-notification-notice-close').click();await notice.waitFor({state:'detached'});
 await submit();await notice.waitFor();await page.mouse.move(0,0);await notice.waitFor({state:'detached',timeout:7000});assert.equal(posts,0);
 await page.goto(base+'/tasks/new?'+ids.map(id=>'paper_id='+id).join('&'));await page.getByRole('textbox',{name:'研究问题',exact:true}).fill('Compare methods');await submit();await page.waitForURL('**/tasks/22222222-2222-4222-8222-222222222222');assert.equal(posts,1);
 console.log('PASS: review count warning popup, manual/five-second close, invalid submission blocked and two-paper submission accepted');
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exit(1)});
