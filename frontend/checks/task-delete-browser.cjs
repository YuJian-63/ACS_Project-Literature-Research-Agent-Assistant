const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');const assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({executablePath:process.env.BROWSER_EXECUTABLE || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});try{
 const page=await browser.newPage({reducedMotion:'reduce'});page.setDefaultTimeout(7000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const ids=[1,2,3,4].map(n=>'0000000'+n+'-1111-4111-8111-111111111111');
 let tasks=ids.map((id,n)=>({id,task_type:'review',status:n===3?'running':'succeeded',paper_ids:[],question:'Research '+n,created_at:'2026-01-01',is_mock:false}));let posts=[];
 await page.route('**/api/v1/**',route=>{const path=new URL(route.request().url()).pathname;
 if(path.endsWith('/auth/me'))return route.fulfill({json:{user:{id:'fixture',username:'Researcher'},csrf_token:'fixture'}});
 if(route.request().method()==='DELETE'){const id=path.split('/').pop();assert.equal(route.request().headers()['x-csrf-token'],'fixture');posts.push(id);if(id===ids[2])return route.fulfill({status:409,json:{error:{code:'TASK_RUNNING',message:'研究正在执行，请等待完成后再删除'}}});tasks=tasks.filter(t=>t.id!==id);return route.fulfill({status:204})}
 return route.fulfill({json:{items:tasks,total:tasks.length,limit:20,offset:0}});
 });
 await page.goto((process.env.SEARCH_PREVIEW_URL || 'http://127.0.0.1:5198')+'/tasks');
 const remove=()=>page.getByRole('button',{name:'删除研究记录 00000001',exact:true});await remove().click();await page.getByRole('button',{name:/取\s*消/}).click();assert.equal(posts.length,0);
 await remove().click();await page.getByRole('button',{name:'确认删除',exact:true}).click();await remove().waitFor({state:'detached'});
 assert.equal(await page.getByRole('checkbox',{name:'选择研究记录 00000004',exact:true}).isDisabled(),true);
 assert.equal(await page.getByRole('button',{name:'删除研究记录 00000004',exact:true}).isDisabled(),true);
 for(const suffix of ['00000002','00000003'])await page.getByRole('checkbox',{name:'选择研究记录 '+suffix,exact:true}).click();
 await page.getByRole('button',{name:'删除已选研究',exact:true}).click();await page.getByRole('button',{name:'确认删除',exact:true}).click();
 const notice=page.locator('.ant-notification-notice');await notice.getByText('1 条研究记录未删除',{exact:true}).waitFor();assert.match(await notice.innerText(),/研究正在执行/);
 assert.deepEqual(posts,[ids[0],ids[1],ids[2]]);assert.equal(await page.getByRole('checkbox',{name:'选择研究记录 00000003',exact:true}).isChecked(),true);
 await page.setViewportSize({width:390,height:900});await page.waitForFunction(()=>document.documentElement.scrollWidth<=innerWidth);
 await notice.locator('.ant-notification-notice-close').click();await notice.waitFor({state:'detached'});assert.deepEqual(errors,[]);
 console.log('PASS: single confirm/cancel, bulk selection/deletion, running protection, partial failure popup/selection, CSRF and mobile layout');
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exit(1)});
