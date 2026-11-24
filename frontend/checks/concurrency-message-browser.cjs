const assert=require('node:assert/strict');
const {launchBrowser}=require('./browser.cjs');
(async()=>{
 const browser=await launchBrowser();try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 await page.addInitScript(()=>localStorage.setItem('literature-v3-ui-locale','zh-CN'));
 let concurrency=2,updates=0;
 await page.route('**/api/v1/**',route=>{
  const r=route.request(),path=new URL(r.url()).pathname;
  if(path==='/api/v1/auth/me')return route.fulfill({json:{user:{id:'test',username:'test',email:'test@example.org'},csrf_token:'test'}});
  if(path==='/api/v1/models')return route.fulfill({json:{state:'stopped',enabled:false,bailian_config:'missing',bailian_name:null,owner:false}});
  if(path==='/api/v1/agent-research/queue/concurrency'){
   if(r.method()==='PUT'){concurrency=r.postDataJSON().concurrency;updates++;}
   return route.fulfill({json:{concurrency}});
  }
  return route.fulfill({status:404,json:{}});
 });
 await page.goto((process.env.AGENT_WORKSPACE_URL||'http://127.0.0.1:5173')+'/models');
 for(const limit of [1,2,3,4,1]){
  const updated=page.waitForResponse(r=>r.url().endsWith('/queue/concurrency')&&r.request().method()==='PUT');
  await page.locator('.models-concurrency .ant-radio-button-wrapper').filter({hasText:new RegExp('^'+limit+'$')}).click();
  await updated;
  await page.getByText('研究并发数已设置为 '+limit,{exact:true}).last().waitFor();
  await page.waitForFunction(n=>{const el=document.querySelector('.models-concurrency input[value="'+n+'"]');return el?.checked&&!el.disabled;},limit);
  await page.waitForFunction(()=>document.querySelectorAll('.ant-message-notice').length<=3,null,{timeout:1500});
  assert.ok(await page.locator('.ant-message-notice').count()<=3,'at most three concurrency messages after dismissal animation');
 }
 assert.equal(updates,5);assert.ok(await page.locator('.ant-message-notice').count()<=3);
 console.log('PASS: concurrency success wording and three-message maximum during repeated updates');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
