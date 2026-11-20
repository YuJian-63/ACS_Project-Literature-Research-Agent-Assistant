const {launchBrowser}=require('./browser.cjs');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await launchBrowser();
 try{
 const context=await browser.newContext({reducedMotion:'reduce'});const page=await context.newPage();page.setDefaultTimeout(7000);
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 let requests=0,delay=false,release,fail=false;
 await context.route('**/api/v1/**',async route=>{
  const url=new URL(route.request().url());
  if(url.pathname.endsWith('/auth/me'))return route.fulfill({json:{user:{id:'fixture',username:'Researcher',email:'r@example.org'},csrf_token:'fixture'}});
  if(url.pathname.endsWith('/paper-search')){
   requests++;if(fail)return route.fulfill({status:502,json:{error:{code:'ARXIV_INVALID_RESPONSE',message:'arXiv 返回了不合法的响应'}}});
   if(delay) await new Promise(resolve=>{release=resolve});
   return route.fulfill({json:{items:[{external_id:'1706.03762v1',title:'Retained paper',authors:['Author'],abstract:'Abstract',categories:['cs.AI'],published_at:'2026-01-01',source_updated_at:'2026-01-01'}],total:50,offset:Number(url.searchParams.get('offset')),limit:Number(url.searchParams.get('limit'))}}).catch(()=>{});
  }
  return route.fulfill({json:{items:[],total:0,limit:20,offset:0}});
 });
 const base=process.env.SEARCH_PREVIEW_URL || 'http://127.0.0.1:5198';
 const goSearch=()=>page.locator('.primary-nav a[href="/papers/search"]').click();
 const leave=()=>page.locator('.primary-nav a[href="/papers"]').click();
 await page.goto(base+'/papers/search');
 await page.locator('#arxiv-keywords').fill('attention');await page.locator('button[type=submit]').click();
 await page.getByRole('heading',{name:'Retained paper',exact:true}).waitFor();
 await page.locator('#search-page-size').selectOption('25');await page.getByText('共 50 篇 · 第 1 页',{exact:true}).waitFor();
 await leave();await page.getByRole('heading',{name:'论文库',exact:true}).waitFor();
 assert.equal(await page.getByRole('heading',{name:'Retained paper',exact:true}).count(),0);
 const count=requests;await goSearch();await page.getByRole('heading',{name:'Retained paper',exact:true}).waitFor();
 assert.equal(await page.locator('#arxiv-keywords').inputValue(),'attention');assert.equal(await page.locator('#search-page-size').inputValue(),'25');assert.equal(requests,count);
 delay=true;await page.locator('#search-sort').selectOption('published-desc');
 await page.waitForTimeout(100);await leave();assert.ok(release);release();delay=false;
 await page.waitForTimeout(150);assert.ok(page.url().endsWith('/papers'));await goSearch();
 await page.getByRole('heading',{name:'Retained paper',exact:true}).waitFor();assert.equal(await page.locator('#search-sort').inputValue(),'published-desc');
 fail=true;await page.locator('button[type=submit]').click();
 await page.locator('.ant-notification-notice').getByText('arXiv 返回了不合法的响应',{exact:true}).waitFor();
 assert.equal(await page.getByRole('heading',{name:'Retained paper',exact:true}).count(),0);
 assert.equal(await page.locator('#arxiv-keywords').inputValue(),'');
 assert.equal(await page.locator('#search-sort').inputValue(),'relevance');
 assert.ok(!(await page.locator('.ant-notification-notice').innerText()).includes('上次成功'));
 await leave();await goSearch();assert.equal(await page.getByRole('heading',{name:'Retained paper',exact:true}).count(),0);
 fail=false;await page.locator('#arxiv-keywords').fill('clear');await page.locator('button[type=submit]').click();
 await page.getByRole('heading',{name:'Retained paper',exact:true}).waitFor();
 await page.getByRole('button',{name:'清除搜索',exact:true}).click();
 assert.equal(await page.locator('#arxiv-keywords').inputValue(),'');assert.equal(await page.getByRole('heading',{name:'Retained paper',exact:true}).count(),0);
 // Clearing an in-flight search must also reject its late response.
 delay=true;await page.locator('#arxiv-keywords').fill('pending');await page.locator('button[type=submit]').click();await page.waitForTimeout(100);
 await page.getByRole('button',{name:'清除搜索',exact:true}).click();release();delay=false;await page.waitForTimeout(150);
 assert.equal(await page.getByRole('heading',{name:'Retained paper',exact:true}).count(),0);
 await page.locator('#arxiv-keywords').fill('refresh');await page.locator('button[type=submit]').click();await page.getByRole('heading',{name:'Retained paper',exact:true}).waitFor();
 await page.reload();await page.locator('#arxiv-keywords').waitFor();assert.equal(await page.locator('#arxiv-keywords').inputValue(),'');assert.equal(await page.getByRole('heading',{name:'Retained paper',exact:true}).count(),0);
 const other=await context.newPage();await other.goto(base+'/papers/search');await other.locator('#arxiv-keywords').waitFor();assert.equal(await other.locator('#arxiv-keywords').inputValue(),'');
 assert.deepEqual(errors,[]);console.log('PASS: route retention, options, background search, clear including pending request, refresh/new-page reset');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
