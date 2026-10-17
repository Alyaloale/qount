/* Run only against an isolated candidate API with real read-only observations. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const base=process.env.QOUNT_TEST_BASE_URL || 'http://127.0.0.1:8877';
assert.match(base,/^http:\/\/(127\.0\.0\.1|localhost):\d+$/);
const output=process.env.QOUNT_TEST_SCREENSHOTS || '/tmp/qount-personal-system-screenshots';
fs.mkdirSync(output,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 try {
  const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>assert.equal(r.method(),'GET','candidate UI is read-only'));
  await page.goto(base);await page.click('#tab-live');
  await page.waitForFunction(()=>document.querySelector('#performance-return').textContent!=='--');
  const actual=await (await page.request.get(base+'/account/performance')).json();
  assert.equal(actual.summary.includes_latest_observation,true,'latest real equity observation must be covered');
  assert.equal(await page.evaluate(()=>performanceData.summary.net_pnl_usdt),actual.summary.net_pnl_usdt);
  assert.equal(await page.evaluate(()=>performanceData.summary.includes_latest_observation),true);
  assert.ok(await page.locator('#performance-chart canvas').count()>0);
  assert.match(await page.locator('#performance-heading').textContent(),/实盘/);
  assert.ok(!(await page.locator('#permission-status').textContent()).includes('策略研究模式'));
  for(const width of [1440,768,375,320]) {
   await page.setViewportSize({width,height:1000});await page.waitForTimeout(100);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),width);
   if(width===1440 || width===375)await page.screenshot({path:`${output}/performance-${width}.png`,fullPage:true});
  }
  await page.setViewportSize({width:1440,height:1000});await page.click('#tab-paper');
  await page.evaluate(()=>showLineDetail('macro_1atr',false));
  await page.waitForFunction(()=>document.querySelector('#research-run-select').options.length>=2);
  const runs=await (await page.request.get(base+'/research/lines/macro_1atr/runs')).json();
  const baseRun=runs.runs.find(r=>r.parameters.scenario==='base').run_id;
  const doubleRun=runs.runs.find(r=>r.parameters.scenario==='double_cost').run_id;
  await page.selectOption('#research-run-select',doubleRun);
  await page.waitForFunction(id=>currentLineDetail?.run_id===id,doubleRun);
  assert.ok(await page.evaluate(()=>currentLineDetail.metrics.total_return_pct)<0);
  await page.waitForFunction(()=>!document.querySelector('#research-run-controls').classList.contains('hidden'));
  await page.selectOption('#research-compare-select',baseRun);
  await page.waitForFunction(()=>currentLineDetail.nav_series.some(r=>r.benchmark_nav!=null));
  assert.match(await page.locator('#research-run-note').textContent(),/对照/);
  await page.screenshot({path:`${output}/research-comparison.png`,fullPage:true});
  await page.evaluate(()=>openCurrentLedger());
  await page.waitForFunction(()=>!document.querySelector('#paper-trades-body').textContent.includes('读取中'));
  assert.equal(await page.locator('#paper-trades-body tr').count(),2,'one double-cost round trip only');
  await page.click('#tab-live');
  await page.route('**/account/performance?*',r=>r.fulfill({status:503,body:'unavailable'}));
  await page.evaluate(()=>fetchLivePerformance());
  assert.equal(await page.locator('#performance-return').textContent(),'--');
  assert.equal(await page.locator('#performance-chart canvas').count(),1,'chart is cleared, not replaced by invented data');
  await page.unroute('**/account/performance?*');
  await page.evaluate(()=>fetchLivePerformance());
  assert.notEqual(await page.locator('#performance-return').textContent(),'--');
  assert.deepEqual(errors,[]);
  console.log('PASS: real performance, responsive widths, isolated run selection/comparison/trades and missing-source handling.');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
