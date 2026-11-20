const { launchBrowser } = require('./browser.cjs');
const assert = require('node:assert/strict');
(async () => {
 const browser = await launchBrowser();
 const page = await browser.newPage();
 let mode = 'error';
 const imported = new Map();
 const papers = [1,2,3,4].map(n => ({ external_id: '2601.0000' + n + 'v1', title: 'Paper ' + n, authors: ['Author'], abstract: 'Abstract', categories: ['cs.AI'], published_at: '2026-01-01', source_updated_at: '2026-01-01' }));
 const item = (identity, status) => ({ id: identity, external_id: identity, attempt: 1, status, paper_status: status === 'succeeded' ? 'uploaded' : null, paper_id: status === 'succeeded' ? identity : null, updated_at: new Date().toISOString(), error: status === 'failed' ? { code: 'ARXIV_UNAVAILABLE', message: '后台下载失败', details: {} } : null });
 const errors=[]; page.on('pageerror', e=>errors.push(e.message));
 await page.route('**/api/v1/**', async route => {
  if (new URL(route.request().url()).pathname.endsWith('/auth/me')) return route.fulfill({json:{user:{id:'fixture',username:'Researcher',email:'r@example.org'},csrf_token:'fixture'}});
  if (mode === 'imports') {
   const path = new URL(route.request().url()).pathname;
   if (path.endsWith('/paper-search')) return route.fulfill({json:{items: papers, total: 4, limit:10, offset:0}});
   if (route.request().method() === 'POST') { const identity = route.request().postDataJSON().external_id; imported.set(identity, imported.size); return route.fulfill({json:item(identity,'queued')}); }
   const identity = path.split('/').pop();
   return route.fulfill({json:item(identity, imported.get(identity) % 2 === 0 ? 'failed' : 'succeeded')});
  }
  return route.fulfill({status:503,headers:{'x-request-id':'fixture-request'},json:{error:{code:'ARXIV_UNAVAILABLE',message:'测试搜索失败',details:{}}}});
 });
 await page.goto((process.env.SEARCH_PREVIEW_URL || 'http://127.0.0.1:5198') + '/papers/search');
 await page.locator('#arxiv-keywords').fill('attention');
 await page.locator('button[type=submit]').click();
 await page.waitForTimeout(1200);
 const notices=page.locator('.ant-notification-notice');
 assert.equal(await notices.count(),1,'Error notification must remain visible after state renders');
 assert.match(await notices.innerText(),/测试搜索失败/);
 assert.deepEqual(errors,[]);
 const geometry = await notices.first().evaluate(el => {
   const card = el.getBoundingClientRect();
   const close = el.querySelector('.ant-notification-notice-close');
   const r = close.getBoundingClientRect();
   const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
   return { card: {left: card.left, right: card.right}, closeVisible: close.contains(hit), width: innerWidth };
 });
 assert.ok(geometry.closeVisible, 'Close control must be visible and not clipped by its container');
 assert.ok(geometry.card.left >= 16 && geometry.card.right <= geometry.width - 16, 'Card must fit viewport with margins');
 for (const width of [1440, 390, 320]) {
  await page.setViewportSize({width, height:1000});
  const layout = await notices.first().evaluate(el => {
   const card = el.getBoundingClientRect();
   const content = el.querySelector('.search-notification-content').getBoundingClientRect();
   const close = el.querySelector('.ant-notification-notice-close');
   const r = close.getBoundingClientRect();
   return { left:card.left, right:card.right, width:innerWidth,
    leftPadding:content.left-card.left, rightPadding:card.right-content.right,
    closeVisible:close.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)) };
  });
  assert.ok(layout.closeVisible, 'Close must be visible at width ' + width);
  assert.ok(layout.left >= 16 && layout.right <= layout.width - 16, 'Viewport margins at width ' + width);
  assert.ok(layout.leftPadding >= 20 && layout.rightPadding >= 20, 'Content padding at width ' + width);
 }
 await page.setViewportSize({width:1440, height:1000});
 console.log('PASS: visible close and content margins at 1440px, 390px and 320px');
 await page.waitForTimeout(4500);
 assert.equal(await notices.count(),0,'Notification closes automatically after five seconds');
 mode = 'imports';
 // A failed search now resets its input; start the next search explicitly.
 await page.locator('#arxiv-keywords').fill('attention');
 await page.locator('button[type=submit]').click();
 await page.locator('.search-paper').last().waitFor();
 for (let i=0;i<4;i++) await page.locator('.search-paper').nth(i).getByRole('button',{name:'导入 PDF',exact:true}).click();
 await page.waitForTimeout(1000);
 assert.equal(await notices.count(),3,'At most three notifications are visible');
 const text = (await notices.allInnerTexts()).join(' ');
 assert.match(text,/导入成功/);
 assert.match(text,/后台下载失败/);
 const padding = await notices.first().evaluate(el=>getComputedStyle(el).paddingLeft);
 assert.equal(padding,'28px');
 await notices.first().locator('.ant-notification-notice-close').click();
 await page.waitForTimeout(400);
 assert.equal(await notices.count(),2,'Manual dismissal works');
 await page.waitForTimeout(5200);
 assert.equal(await notices.count(),0,'Import feedback closes automatically');
 assert.deepEqual(errors,[]);
 console.log('PASS: background import success/failure, three-notice limit, padding, manual close and five-second auto close');
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
