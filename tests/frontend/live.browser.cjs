/* Static candidate or deployed UI over an owner-authorized localhost SSH tunnel. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const base=process.env.QOUNT_TEST_BASE_URL || 'http://127.0.0.1:8878';
const api=process.env.QOUNT_TEST_API_URL || 'http://127.0.0.1:8877';
const output=process.env.QOUNT_TEST_SCREENSHOTS || '/tmp/qount-live-view-20261016/screenshots';
for(const url of [base,api]) assert.match(url,/^http:\/\/(127\.0\.0\.1|localhost):\d+$/);
fs.mkdirSync(output,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 try {
  const page=await browser.newPage({viewport:{width:1200,height:900}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',async route=>{
   const url=new URL(route.request().url());
   if(/^\/(health|account|paper|research|assistant)(\/|$)/.test(url.pathname)) {
    assert.equal(route.request().method(),'GET','UI must never mutate account');
    return route.fulfill({response:await route.fetch({url:api+url.pathname+url.search})});
   }
   return route.continue();
  });
  await page.goto(base);
  await page.waitForFunction(()=>document.querySelector('#strategy-equity').textContent!=='--');
  assert.equal(await page.locator('.nav-item').count(),4);
  await page.click('#tab-live');
  assert.equal(await page.locator('#topbar-title').textContent(),'实盘');
  assert.match(await page.locator('#screen-live').textContent(),/后端记录/);
  assert.equal(await page.locator('#strategy-risk').count(),0);
  const actual=await (await page.request.get(api+'/account/assets')).json();
  const records={status:'AVAILABLE',read_only:true,orders_authorized:false,observed_at:new Date().toISOString(),fill_count:1,income_count:1,completed_symbols:['SPYUSDT'],
   fills:[{time:Date.now(),symbol:'SPYUSDT',side:'BUY',position_side:'BOTH',price:100,quantity:.1,commission:.005,commission_asset:'USDT',realized_pnl:0,pnl_asset:'USDT'}],
   income:[{time:Date.now(),symbol:'',income_type:'TRANSFER',amount:20,asset:'USDT'}]};
  await page.route('**/account/trades?limit=100',r=>r.fulfill({json:records}));
  await page.evaluate(()=>fetchLiveTradeRecords());
  assert.match(await page.locator('#real-trades-body').textContent(),/SPYUSDT/);
  assert.match(await page.locator('#real-trades-body').textContent(),/未归属策略/);
  assert.match(await page.locator('#real-income-body').textContent(),/划转/);
  await page.unroute('**/account/trades?limit=100');
  await page.evaluate(()=>fetchLiveTradeRecords());
  assert.equal(await page.locator('#strategy-equity').textContent(),Number(actual.usdm_margin_balance_usdt).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:4}));
  for(const width of [1440,1200,768,500,375,320]) {
   await page.setViewportSize({width,height:900});
   for(const tab of ['account','live','paper','records']) {
    await page.evaluate(t=>switchTab(t),tab);await page.waitForTimeout(80);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),width,`${tab} ${width}px overflow`);
   }
   await page.evaluate(()=>switchTab('live'));
   await page.waitForTimeout(600);
   await page.screenshot({path:`${output}/live-${width}.png`,fullPage:true});
  }
  const updated=structuredClone(actual);
  updated.observed_at=new Date().toISOString();updated.usdm_margin_balance_usdt=80;updated.usdm_available_balance_usdt=60;
  await page.route('**/account/assets',r=>r.fulfill({json:updated}));
  await page.evaluate(()=>fetchLiveAccountData());
  assert.equal(await page.locator('#strategy-equity').textContent(),'80.00');
  assert.equal(await page.locator('#strategy-available').textContent(),'60.00');
  assert.equal(await page.locator('#strategy-risk').count(),0);
  await page.unroute('**/account/assets');
  await page.route('**/account/assets',r=>r.fulfill({status:503,body:'unavailable'}));
  await page.evaluate(()=>fetchLiveAccountData());
  assert.equal(await page.locator('#strategy-equity').textContent(),'--');
  await page.evaluate(snapshot=>{snapshot.observed_at=new Date(Date.now()-20*60000).toISOString();QountLive.render(snapshot);},actual);
  assert.match(await page.locator('#strategy-account-state').textContent(),/过期/);
  await page.unroute('**/account/assets');
  await page.evaluate(()=>fetchLiveAccountData());
  assert.deepEqual(errors,[]);
  console.log('PASS: four screens / six widths, actual readonly account, dynamic80/60, failed/stale snapshots and no order mutations.');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
