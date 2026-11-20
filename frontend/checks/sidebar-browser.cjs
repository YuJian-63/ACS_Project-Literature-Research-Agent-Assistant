const {launchBrowser}=require('./browser.cjs');const assert=require('node:assert/strict');
(async()=>{const browser=await launchBrowser();try{
 const page=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});page.setDefaultTimeout(7000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/api/v1/**',route=>new URL(route.request().url()).pathname.endsWith('/auth/me')?route.fulfill({json:{user:{id:'fixture',username:'Researcher'},csrf_token:'fixture'}}):route.fulfill({json:{items:[],total:0,limit:20,offset:0}}));
 const base=process.env.SEARCH_PREVIEW_URL || 'http://127.0.0.1:5198';await page.goto(base+'/papers');
 const before=await page.locator('.workspace-body').boundingBox();await page.getByRole('button',{name:'收起侧栏',exact:true}).click();
 await page.waitForFunction(()=>Math.round(document.querySelector('.sidebar').getBoundingClientRect().width)===72);
 const after=await page.locator('.workspace-body').boundingBox();assert.ok(after.width>before.width+100);
 assert.equal(await page.getByRole('button',{name:'展开侧栏',exact:true}).getAttribute('aria-expanded'),'false');
 const search=page.locator('.primary-nav a[href="/papers/search"]');assert.equal(await search.getAttribute('title'),'搜索论文');await search.click();await page.locator('#arxiv-keywords').waitFor();
 await page.reload();await page.getByRole('button',{name:'展开侧栏',exact:true}).waitFor();assert.equal(await page.locator('.sidebar').evaluate(el=>Math.round(el.getBoundingClientRect().width)),72);
 await page.getByRole('button',{name:'展开侧栏',exact:true}).focus();await page.keyboard.press('Enter');await page.getByRole('button',{name:'收起侧栏',exact:true}).waitFor();
 await page.setViewportSize({width:1000,height:900});await page.getByRole('button',{name:'收起侧栏',exact:true}).click();await page.waitForFunction(()=>Math.round(document.querySelector('.sidebar').getBoundingClientRect().width)===72);
 await page.setViewportSize({width:390,height:900});await page.waitForFunction(()=>getComputedStyle(document.querySelector('.sidebar')).display==='none');assert.equal(await page.locator('.sidebar-toggle').isVisible(),false);assert.equal(await page.locator('.mobile-nav').isVisible(),true);
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));assert.deepEqual(errors,[]);
 console.log('PASS: sidebar collapse expands content, icon navigation labels, persisted preference, keyboard expansion and mobile layout');
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exit(1)});
