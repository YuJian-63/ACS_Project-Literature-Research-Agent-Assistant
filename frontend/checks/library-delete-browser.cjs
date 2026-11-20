const { launchBrowser } = require('./browser.cjs');
const assert = require('node:assert/strict');
(async () => {
 const browser = await launchBrowser();
 try {
 const context = await browser.newContext({reducedMotion:'reduce'});
 const page = await context.newPage(); page.setDefaultTimeout(5000); const errors=[]; page.on('pageerror', e=>errors.push(e.message));
 const base = process.env.SEARCH_PREVIEW_URL || 'http://127.0.0.1:5198';
 const id='11111111-1111-4111-8111-111111111111';
 const external_id='1706.03762v1';
 const source={provider:'arxiv',external_id,title:'Fixture paper',authors:['Author'],abstract:'Abstract',categories:['cs.AI'],published_at:'2026-01-01',source_updated_at:'2026-01-01'};
 const paper={id,title:source.title,original_filename:'fixture.pdf',status:'ready',size_bytes:20,page_count:2,parser_version:'fixture',source,created_at:'2026-01-01',updated_at:'2026-01-01',error:null};
 const second={...paper,id:'22222222-2222-4222-8222-222222222222',title:'Second paper'};
 let present=true, blocked=false, failed=false, detailUnavailable=false, retries=0, pendingSnapshot=false, secondPresent=false, delayDelete=false, releaseDelete;
 const record=()=>({id,external_id,attempt:retries+1,status:failed?'failed':'succeeded',paper_status:failed?null:'ready',paper_id:failed?null:id,error:failed?{code:'ARXIV_INVALID_RESPONSE',message:'下载失败',details:{retryable:false}}:null,updated_at:new Date().toISOString()});
 await context.route('**/api/v1/**', async route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/auth/me')) return route.fulfill({json:{user:{id:'fixture',username:'Researcher',email:'r@example.org'},csrf_token:'fixture'}});
  if(path.endsWith('/paper-search')) return route.fulfill({json:{items:[{...source,import_id:present?id:null,import_status:present?(pendingSnapshot?'running':failed?'failed':'succeeded'):null,paper_id:present&&!failed?id:null,paper_status:present&&!failed?'ready':null}],total:1,limit:10,offset:0}});
  if(path.endsWith('/retry')) { assert.equal(route.request().postDataJSON().expected_attempt,retries+1); retries++; failed=false; return route.fulfill({json:record()}); }
  if(path.includes('/paper-imports/')) {
   if(!present) return route.fulfill({status:404,json:{error:{code:'PAPER_IMPORT_NOT_FOUND',message:'导入记录不存在'}}});
   if(detailUnavailable) return route.fulfill({status:503,json:{error:{code:'SERVICE_NOT_READY',message:'状态读取失败'}}});
   return route.fulfill({json:record()});
  }
  if(route.request().method()==='DELETE') {
   if(delayDelete) await new Promise(resolve=>{releaseDelete=resolve});
   assert.equal(route.request().headers()['x-csrf-token'],'fixture');
   if(blocked) return route.fulfill({status:409,json:{error:{code:'PAPER_IN_USE',message:'论文已被研究任务引用，无法删除'}}});
   present=false; return route.fulfill({status:204});
  }
  if(path.endsWith('/file')) return route.fulfill({contentType:'application/pdf',body:'%PDF-fixture'});
  if(path==='/api/v1/papers') return route.fulfill({json:{items:[...(present?[paper]:[]),...(secondPresent?[second]:[])],total:Number(present)+Number(secondPresent),limit:20,offset:0}});
  if(path==='/api/v1/papers/'+second.id) return route.fulfill({json:second});
  if(path==='/api/v1/papers/'+id) return route.fulfill({json:paper});
  throw Error(path);
 });
 await page.goto(base+'/papers');
 await page.getByRole('checkbox',{name:'选择论文 Fixture paper',exact:true}).click();
 await page.waitForTimeout(300); assert.ok(page.url().includes('selected_paper_id'));
 const remove=()=>page.getByRole('button',{name:'删除论文 Fixture paper',exact:true});
 await remove().click(); await page.getByRole('button',{name:/取\s*消/}).click(); assert.equal(present,true);
 blocked=true; await remove().click(); await page.locator('.ant-popconfirm').getByRole('button',{name:/删\s*除/}).click();
 await page.getByText('论文已被研究任务引用，无法删除',{exact:true}).waitFor(); assert.equal(present,true);
 blocked=false; await remove().click(); await page.locator('.ant-popconfirm').getByRole('button',{name:/删\s*除/}).click();
 await page.getByText('论文已删除',{exact:true}).waitFor();
 assert.equal(present,false); assert.ok(!page.url().includes('selected_paper_id'));
 await page.locator('.primary-nav a[href="/papers/search"]').click();
 await page.locator('#arxiv-keywords').fill('attention'); await page.locator('button[type=submit]').click();
 await page.getByRole('button',{name:'导入 PDF',exact:true}).waitFor();
 // Refresh an open search after deletion in another tab: terminal state is rechecked on focus.
 present=true; await page.locator('button[type=submit]').click(); await page.getByText('已导入 · 可用于研究',{exact:true}).waitFor();
 present=false; await page.evaluate(()=>window.dispatchEvent(new Event('focus'))); await page.getByRole('button',{name:'导入 PDF',exact:true}).waitFor();
 // A historical failure marked non-retryable must still offer an explicit manual retry.
 present=true; failed=true; detailUnavailable=true; await page.locator('button[type=submit]').click();
 await page.getByRole('button',{name:'重新下载',exact:true}).waitFor();
 detailUnavailable=false; await page.getByRole('button',{name:'重新下载',exact:true}).click();
 await page.getByText('已导入 · 可用于研究',{exact:true}).waitFor(); assert.equal(retries,1);
 // Initial failed hydration of a running import must recover through polling.
 pendingSnapshot=true; detailUnavailable=true;
 await page.goto(base+'/papers/search');
 await page.locator('#arxiv-keywords').fill('attention'); await page.locator('button[type=submit]').click();
 await page.getByText('状态读取失败',{exact:true}).waitFor();
 detailUnavailable=false;
 await page.getByText('已导入 · 可用于研究',{exact:true}).waitFor(); pendingSnapshot=false;
 // A delayed delete must preserve a later selection and newly opened reader.
 secondPresent=true; delayDelete=true;
 await page.goto(base+'/papers?selected_paper_id='+id);
 await page.getByRole('button',{name:'删除论文 Fixture paper',exact:true}).click();
 await page.locator('.ant-popconfirm').getByRole('button',{name:/删\s*除/}).click();
 await page.getByRole('checkbox',{name:'选择论文 Second paper',exact:true}).click();
 await page.getByRole('button',{name:'Second paper',exact:true}).click();
 await page.locator('.paper-reader').waitFor();
 assert.ok(releaseDelete); releaseDelete(); delayDelete=false;
 await page.getByText('论文已删除',{exact:true}).waitFor();
 await page.waitForTimeout(200);
 const latest = new URL(page.url()).searchParams;
 assert.equal(latest.get('paper_id'),second.id);
 assert.deepEqual(latest.getAll('selected_paper_id'),[second.id]);
 present=true; secondPresent=false;
 await page.setViewportSize({width:390,height:1000});
 await page.goto(base+'/papers?paper_id='+id+'&selected_paper_id='+id);
 await page.locator('.paper-reader').waitFor();
 await page.getByRole('button',{name:'删除论文 Fixture paper',exact:true}).click();
 await page.locator('.ant-popconfirm').getByRole('button',{name:/删\s*除/}).focus();
 await page.keyboard.press('Enter');
 await page.getByText('论文已删除',{exact:true}).waitFor();
 await page.locator('.paper-reader').waitFor({state:'detached'});
 assert.equal(await page.locator('.paper-reader').count(),0);
 assert.ok(!page.url().includes('selected_paper_id') && !page.url().includes('paper_id='));
 assert.deepEqual(errors,[]);
 console.log('PASS: cancel/delete, referenced-paper protection, CSRF, selection cleanup, deleted result becomes importable, focus synchronization and failed-detail retry fallback');
 } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exit(1)});
