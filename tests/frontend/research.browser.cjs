/* Read-only UI regression over a local API or an owner-authorized localhost tunnel.
 * Dependency: playwright. Screenshots and dependencies stay outside the repository. */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const base = process.env.QOUNT_TEST_BASE_URL || 'http://127.0.0.1:8878';
const api = process.env.QOUNT_TEST_API_URL || 'http://127.0.0.1:8877';
const researchApi = process.env.QOUNT_TEST_RESEARCH_API_URL || api;
const output = process.env.QOUNT_TEST_SCREENSHOTS || '/tmp/qount-research-ui';
for (const url of [base, api, researchApi]) assert.match(url, /^http:\/\/(127\.0\.0\.1|localhost):\d+$/);
fs.mkdirSync(output, {recursive: true});
(async () => {
  const browser = await chromium.launch({headless: true, args: ['--no-proxy-server'], executablePath: process.env.QOUNT_BROWSER_EXECUTABLE ||
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  let page;
  try {
    page = await browser.newPage({viewport: {width: 1440, height: 1000}, reducedMotion: 'reduce'});
    const errors = [], failures = [], requests = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('response', response => { if (response.status() >= 400) failures.push(response.url()); });
    await page.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url());
      assert.equal(request.method(), 'GET', 'research UI must remain read-only');
      // The unrelated account chart is large; this regression exercises actual research inputs.
      if (url.pathname === '/account/history') return route.fulfill({json: []});
      if (/^\/(health|account|paper|research|assistant)(\/|$)/.test(url.pathname)) {
        requests.push(url);
        return route.fulfill({response: await route.fetch({url: (/^\/(research|paper|health)(\/|$)/.test(url.pathname) ? researchApi : api) + url.pathname + url.search, maxRetries: 2})});
      }
      return route.continue();
    });
    const lines = await (await page.request.get(researchApi + '/research/lines')).json();
    const forwards = lines.filter(line => line.paper_enabled && ['forward','mixed'].includes(line.sample_kind));
    assert.ok(forwards.length > 0);
    await page.goto(base);
    await page.waitForFunction(count => document.querySelectorAll('.research-card').length === count, lines.length);
    await page.click('#tab-paper');
    const original = page.locator('[data-line-id="dual_g20"]');
    assert.equal(await original.locator('.research-lifecycle').innerText(), '模拟已启用');
    assert.equal(await page.locator('[data-line-id="dual_g20_forward"]').count(), 0, 'one canonical G20 card');
    assert.doesNotMatch((await page.locator('.research-lifecycle').allTextContents()).join(' '), /暂停研究|研究中/);
    await page.click('[data-research-filter="forward"]');
    assert.equal(await page.locator('.research-card').count(), forwards.length);
    assert.ok((await page.locator('.research-lifecycle').allTextContents()).every(text => /^(模拟|前向)已启用$/.test(text)));
    assert.match(await page.locator('#paper-lines-body').innerText(), /连续模拟累计收益/);
    assert.doesNotMatch(await page.locator('#paper-lines-body').innerText(), /年初至今收益/);
    assert.doesNotMatch(await page.locator('#paper-lines-body').innerText(), /-0\.00%/);
    for (const width of [1440, 768, 375, 320]) {
      await page.setViewportSize({width, height: 1000});
      await page.waitForTimeout(100);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), width, `list ${width}px`);
      if ([1440, 375].includes(width)) await page.screenshot({path: `${output}/forward-${width}.png`, fullPage: width === 1440});
    }
    await page.fill('#research-search', 'G20');
    assert.equal(await page.locator('.research-card').count(), 1);
    await page.evaluate(() => fetchPaperLines());
    assert.equal(await page.locator('[data-research-filter="forward"]').getAttribute('aria-pressed'), 'true');
    assert.equal(await page.locator('.research-card').count(), 1);
    await page.evaluate(() => resetResearchFilters());
    for (const line of forwards) {
      await page.evaluate(id => {switchTab('paper'); return showLineDetail(id, true);}, line.line_id);
      assert.ok(await page.locator('#detail-title').evaluate(node => node.getBoundingClientRect().top >=
        document.querySelector('.sidebar').getBoundingClientRect().bottom), 'mobile detail heading clears fixed navigation');
      const snapshot = await (await page.request.get(researchApi + '/research/positions/current?line_id=' + line.line_id)).json();
      const held = snapshot.positions.filter(row => row.action !== 'CLOSE' && (row.quantity == null || Number(row.quantity) > 1e-12));
      if (!held.length) assert.match(await page.locator('#detail-current-positions').innerText(), /来源快照确认空仓/);
      else for (const row of held) assert.ok((await page.locator('#detail-current-positions').innerText()).includes(row.symbol));
      assert.doesNotMatch(await page.locator('#detail-position-as-of').innerText(), /--/);
      assert.equal(await page.locator('#research-run-controls').isVisible(), false);
      if (line.sample_kind === 'mixed') {
        assert.match(await page.locator('#detail-window-note').innerText(), /历史补算/);
        assert.match(await page.locator('#detail-sample-segments').innerText(), /历史补算.*实际记录/);
      } else if ((line.metrics?.observation_count || 0) <= 1) {
        assert.match(await page.locator('#detail-window-note').innerText(), /初始化观测/);
      } else {
        assert.match(await page.locator('#detail-window-note').innerText(), /不年化|不足一年/);
      }
      assert.ok(await page.locator('#echarts-container canvas').count() > 0);
      await page.evaluate(() => openCurrentLedger());
      await page.waitForFunction(() => !document.querySelector('#trade-count').textContent.includes('读取中'));
      assert.doesNotMatch(await page.locator('#paper-trades-body').innerText(), /读取失败|读取中/);
      if (!held.length) assert.match(await page.locator('#paper-current-positions-body').innerText(), /来源快照确认空仓/);
      else for (const row of held) assert.ok((await page.locator('#paper-current-positions-body').innerText()).includes(row.symbol));
      assert.doesNotMatch(await page.locator('#positions-as-of').innerText(), /--/);
      assert.equal(requests.some(url => url.pathname === `/research/lines/${line.line_id}/runs`), false);
      assert.equal(requests.some(url => url.pathname === '/research/trades' &&
        url.searchParams.get('line_id') === line.line_id && url.searchParams.has('run_id')), false);
    }
    // Historical experiments still select an explicit run and compare the same window.
    await page.evaluate(() => {switchTab('paper'); return showLineDetail('macro_1atr', false);});
    await page.waitForFunction(() => document.querySelector('#research-run-select').options.length >= 2);
    const runs = await (await page.request.get(researchApi + '/research/lines/macro_1atr/runs')).json();
    const baseRun = runs.runs.find(run => run.parameters.scenario === 'base').run_id;
    const doubleRun = runs.runs.find(run => run.parameters.scenario === 'double_cost').run_id;
    await page.selectOption('#research-run-select', doubleRun);
    await page.waitForFunction(id => currentLineDetail?.run_id === id &&
      !document.querySelector('#research-run-controls').classList.contains('hidden'), doubleRun);
    const sourceBenchmark = await page.evaluate(() => currentLineDetail.nav_series.map(row => row.benchmark_nav));
    await page.selectOption('#research-compare-select', baseRun);
    await page.waitForFunction(() => document.querySelector('#research-run-note').textContent.includes('对照'));
    const displayed = await page.locator('#detail-metrics-grid .metric-pill-val').allTextContents();
    const expected = await page.evaluate(() => pct(selectedStats().benchmark.total));
    assert.equal(displayed[1], expected, 'benchmark metrics refresh with comparison curve');
    await page.selectOption('#research-compare-select', '');
    assert.deepEqual(await page.evaluate(() => currentLineDetail.nav_series.map(row => row.benchmark_nav)), sourceBenchmark);
    assert.equal((await page.locator('#detail-metrics-grid .metric-pill-val').allTextContents())[1],
      await page.evaluate(() => pct(selectedStats().benchmark.total)));
    for (const width of [1440, 768, 375, 320]) {
      await page.setViewportSize({width, height: 1000});
      await page.waitForTimeout(100);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), width, `detail ${width}px`);
    }
    await page.evaluate(() => openCurrentLedger());
    await page.waitForFunction(() => !document.querySelector('#trade-count').textContent.includes('读取中'));
    assert.equal(await page.locator('#paper-trades-body tr').count(), 2);
    assert.match(await page.locator('#positions-as-of').innerText(), /不适用/);
    assert.deepEqual(failures, [], 'all real research requests should succeed');
    // A source with unknown positions must not be rendered as a confirmed flat account.
    const lineId = 'personal_assistant';
    await page.route(`**/research/positions/current?line_id=${lineId}`, route => route.fulfill({json:
      {line_id: lineId, status: 'UNKNOWN', as_of: null, positions: []}}));
    await page.evaluate(id => {switchTab('paper'); return showLineDetail(id, false);}, lineId);
    assert.match(await page.locator('#detail-current-positions').innerText(), /读取失败/);
    await page.evaluate(() => openCurrentLedger());
    await page.waitForFunction(() => !document.querySelector('#trade-count').textContent.includes('读取中'));
    assert.match(await page.locator('#paper-current-positions-body').innerText(), /读取失败/);
    assert.match(await page.locator('#positions-as-of').innerText(), /读取失败/);
    assert.deepEqual(errors, []);
    console.log(`PASS: ${forwards.length} enabled paper details/ledgers, filters, known/unknown snapshots, historical run comparison and four viewport widths; all GET.`);
  } finally {
    if (page) await page.unrouteAll({behavior: 'wait'});
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
