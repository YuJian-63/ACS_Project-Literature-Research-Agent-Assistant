const assert=require('node:assert/strict');
const {launchBrowser}=require('./browser.cjs');
(async()=>{
 const browser=await launchBrowser();
 try {
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],calls=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(()=>localStorage.setItem('literature-v3-ui-locale','zh-CN'));
 let config='local',failed=false;
 await page.route('**/api/v1/**',route=>{
  const req=route.request(),path=new URL(req.url()).pathname;calls.push([req.method(),path]);
  if(path==='/api/v1/auth/me')return route.fulfill({json:{user:{id:'config-user',username:'tester',email:'test@example.org'},csrf_token:'test'}});
  if(path==='/api/v1/models')return failed?route.fulfill({status:500,json:{error:{code:'CHECK_FAILED',message:'配置读取失败'}}}):route.fulfill({json:{bailian_config:config,bailian_name:'test-model',enabled:false,state:'stopped',owner:false,shared_url:null,generation:null,job_id:null,base_url:null,detail:null,requested_at:null,checked_at:null}});
  if(path==='/api/v1/agent-research/queue/concurrency')return route.fulfill({json:{concurrency:2}});
  return route.fulfill({status:404,json:{}});
 });
 await page.goto((process.env.AGENT_WORKSPACE_URL||'http://127.0.0.1:5173')+'/models');
 const card=page.locator('.models-bailian');
 await card.getByText('配置已读取',{exact:true}).waitFor();
 assert.equal(await card.locator('.ant-tag-green').count(),0,'configuration existence must not claim service availability');
 assert.ok((await card.innerText()).includes('未验证'));
 config='missing';await card.getByRole('button',{name:'重新读取配置',exact:true}).click();
 await card.getByText('配置缺失或不完整',{exact:true}).waitFor();
 config='remote';await card.getByRole('button',{name:'重新读取配置',exact:true}).click();
 await card.getByText('远端配置未验证',{exact:true}).waitFor();
 failed=true;await card.getByRole('button',{name:'重新读取配置',exact:true}).click();
 await page.getByText('配置读取失败',{exact:true}).waitFor();
 assert.deepEqual(errors,[]);assert.ok(calls.every(([method])=>method==='GET'));
 console.log('PASS: local/missing/remote configuration labels, no false healthy state, explicit reload, reload failures, GET only');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
