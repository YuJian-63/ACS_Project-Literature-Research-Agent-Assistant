const { launchBrowser } = require('./browser.cjs');
const assert = require('node:assert/strict');
(async()=>{
 const browser=await launchBrowser();
 try {
 const page=await browser.newPage({reducedMotion:'reduce'});page.setDefaultTimeout(7000);
 const ids=[1,2,21].map(n=>'11111111-1111-4111-8111-'+String(n).padStart(12,'0'));
 const make=(id,n)=>({id,title:'Paper '+n,original_filename:n+'.pdf',status:'ready',size_bytes:100,page_count:1,parser_version:'test',source:null,created_at:'2026-01-01',updated_at:'2026-01-01'});
 let papers=ids.map((id,n)=>make(id,n+1)); const deleted=[]; const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/api/v1/**',async route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/auth/me'))return route.fulfill({json:{user:{id:'user',username:'Researcher',email:'r@example.org'},csrf_token:'fixture'}});
  if(route.request().method()==='DELETE'){
   const id=path.split('/').pop();deleted.push(id);
   if(id===ids[1])return route.fulfill({status:409,json:{error:{code:'PAPER_IN_USE',message:'论文已被研究任务引用，无法删除'}}});
   papers=papers.filter(p=>p.id!==id);return route.fulfill({status:204});
  }
  // Third selected paper is on a different page and absent from visible rows.
  return route.fulfill({json:{items:papers.filter(p=>p.id!==ids[2]),total:papers.length,limit:20,offset:0}});
 });
 const base=process.env.SEARCH_PREVIEW_URL || 'http://127.0.0.1:5198';
 await page.goto(base+'/papers?'+ids.map(id=>'selected_paper_id='+id).join('&'));
 const notices=page.locator('.ant-notification-notice');
 await page.getByRole('button',{name:'删除论文 Paper 2',exact:true}).click();
 await page.locator('.ant-popconfirm').getByRole('button',{name:/删\s*除/}).click();
 await notices.getByText('删除失败',{exact:true}).waitFor();
 assert.match(await notices.innerText(),/论文已被研究任务引用/);
 await notices.locator('.ant-notification-notice-close').click();
 await notices.waitFor({state:'detached'});
 deleted.length=0;
 const trigger=page.getByRole('button',{name:'删除已选论文',exact:true});
 await trigger.click();await page.getByRole('button',{name:/取\s*消/}).click();assert.equal(deleted.length,0);
 await trigger.click();await page.getByRole('button',{name:'确认删除',exact:true}).click();
 await notices.getByText('1 篇论文未删除，已保留选择',{exact:true}).waitFor();
 assert.match(await notices.innerText(),/论文已被研究任务引用/);
 assert.equal(await page.locator('.library-panel .ant-alert-warning').count(),0);
 assert.deepEqual(deleted,ids,'Includes selected off-page paper');
 assert.deepEqual(new URL(page.url()).searchParams.getAll('selected_paper_id'),[ids[1]]);
 assert.equal(papers.length,1);
 await page.setViewportSize({width:390,height:900});
 await trigger.waitFor({state:'visible'});
 assert.ok(await trigger.isVisible());
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await page.mouse.move(0,0);
 await notices.waitFor({state:'detached',timeout:7000});
 assert.deepEqual(errors,[]);
 console.log('PASS: single/bulk deletion failure notifications, manual/automatic close, confirmation/cancel, off-page selected deletion, protected paper retained and mobile layout');
 } finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
