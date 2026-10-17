/* Run against a local API only. Dependency: playwright; Chrome can be supplied via env. */
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const base = process.env.QOUNT_TEST_BASE_URL || "http://127.0.0.1:8766";
assert.ok(
  /^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(base),
  "Only an isolated local API is allowed",
);
const output = process.env.QOUNT_TEST_SCREENSHOTS || "/tmp/qount-ui-tests";
fs.mkdirSync(output, { recursive: true });
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath:
      process.env.QOUNT_BROWSER_EXECUTABLE ||
      "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  });
  try {
    const context = await browser.newContext({
      viewport: { width: 1200, height: 900 },
    });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(base);
    await page.waitForFunction(
      () => document.querySelectorAll(".research-card").length === 10,
    );
    await page.waitForFunction(() =>
      document.querySelector("#live-nav").textContent !== "--",
    );
    for (const width of [1440, 1200, 500, 375]) {
      await page.setViewportSize({ width, height: 900 });
      for (const tab of ["account", "live", "paper", "records"]) {
        await page.evaluate((tab) => switchTab(tab), tab);
        await page.waitForTimeout(450);
        assert.equal(
          await page.evaluate(() => document.documentElement.scrollWidth),
          width,
          `${width}px ${tab} must not overflow`,
        );
        if (tab === "account") {
          const fits = await page.evaluate(() => {
            const nav = document
              .querySelector(".sidebar")
              .getBoundingClientRect();
            return [...document.querySelectorAll(".nav-item")].every(
              (button) => {
                const rect = button.getBoundingClientRect();
                return rect.bottom <= nav.bottom && rect.top >= nav.top;
              },
            );
          });
          assert.ok(fits, `${width}px tabs must fit header`);
        }
        await page.screenshot({
          path: `${output}/${tab}-${width}.png`,
          fullPage: true,
        });
      }
    }
    console.log("PASS layout: 1440 / 1200 / 500 / 375px, four screens");
    await page.evaluate(() => switchTab("paper"));
    await page.locator('[data-research-filter="waiting"]').click();
    assert.ok(await page.locator(".research-card").count() >= 1);
    assert.match(await page.locator("#paper-lines-body").textContent(), /通用状态/);
    await page.locator('[data-research-filter="all"]').click();
    await page.selectOption("#research-category", "美股");
    assert.equal(await page.locator(".research-card").count(), 2);
    await page.fill("#research-search", "G20");
    assert.equal(await page.locator(".research-card").count(), 1);
    await page.evaluate(() => refreshData());
    assert.equal(await page.locator("#research-search").inputValue(), "G20");
    assert.equal(await page.locator("#research-category").inputValue(), "美股");
    assert.equal(await page.locator(".research-card").count(), 1);
    await page.fill("#research-search", "不存在的研究");
    assert.equal(await page.locator(".research-empty").count(), 1);
    await page.getByRole("button", { name: "清除筛选" }).click();
    assert.equal(await page.locator(".research-card").count(), 10);
    await page.fill("#research-search", "麒麟");
    assert.equal(await page.locator("#archived-lines").getAttribute("open"), "");
    assert.equal(await page.locator(".research-card").count(), 1);
    assert.equal(await page.locator(".research-facts").count(), 0, "withdrawn returns stay out of research cards");
    await page.evaluate(() => resetResearchFilters());
    await page.emulateMedia({ reducedMotion: "reduce" });
    assert.equal(await page.locator(".navigator-art").evaluate(node => getComputedStyle(node).animationName), "none");
    assert.equal(await page.locator(".research-card").first().evaluate(node => getComputedStyle(node).animationName), "none");
    await page.emulateMedia({ reducedMotion: "no-preference" });
    console.log("PASS research filters, search, refresh preservation and reduced motion");
    await page.setViewportSize({ width: 1200, height: 900 });
    await page.evaluate(async () => {
      switchTab("paper");
      await showLineDetail("personal_assistant", false);
    });
    assert.match(
      await page.locator("#detail-full-metrics").textContent(),
      /21\.28/,
    );
    assert.match(
      await page.locator("#detail-full-metrics").textContent(),
      /37 笔/,
    );
    assert.match(
      await page.locator("#detail-full-metrics").textContent(),
      /1 次/,
    );
    const full = await page.locator("#detail-metrics-grid").textContent();
    await page.selectOption("#chart-time-range", "1y");
    assert.notEqual(
      await page.locator("#detail-metrics-grid").textContent(),
      full,
    );
    const curve = await page.evaluate(() => ({
      expected: QountMetrics.drawdowns(currentLineDetail.nav_series),
      actual: chartInstance
        .getOption()
        .series.find((series) => series.name.startsWith("回撤"))?.data,
    }));
    await page.check("#chart-show-drawdown");
    assert.deepEqual(
      await page.evaluate(
        () =>
          chartInstance
            .getOption()
            .series.find((series) => series.name.startsWith("回撤")).data,
      ),
      curve.expected,
    );
    await page.evaluate(() =>
      chartInstance.dispatchAction({ type: "dataZoom", start: 80, end: 95 }),
    );
    assert.equal(
      await page.locator("#chart-time-range").inputValue(),
      "custom",
    );
    assert.match(await page.locator("#chart-range").textContent(), /观测点/);
    await page.screenshot({
      path: `${output}/assistant-window-1200.png`,
      fullPage: true,
    });
    await page.click("#detail-ledger-link");
    assert.equal(
      await page.locator("#positions-line-select").inputValue(),
      "personal_assistant",
    );
    assert.ok(await page.locator("#ledger-start").inputValue());
    await page.evaluate(() => clearLedgerRange());
    await page.waitForFunction(() =>
      document.querySelector("#trade-count").textContent.includes("37"),
    );
    assert.match(await page.locator("#action-count").textContent(), /1 次/);
    assert.match(
      await page.locator("#paper-actions-body").textContent(),
      /1 : 5/,
    );
    assert.match(
      await page.locator("#paper-trades-body").textContent(),
      /买入|卖出/,
    );
    console.log(
      "PASS real replay: benchmark, split counts, window, full-peak drawdown, ledger link",
    );
    await page.setViewportSize({ width: 500, height: 900 });
    for (const lineId of await page.evaluate(() => [...paperLines.keys()])) {
      await page.evaluate(async (id) => {
        switchTab("paper");
        await showLineDetail(id, false);
      }, lineId);
      assert.equal(
        await page.evaluate(() => document.documentElement.scrollWidth),
        500,
        `${lineId} detail must fit 500px`,
      );
    }
    await page.evaluate(() => showLineDetail("personal_assistant", false));
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({
      path: `${output}/assistant-detail-500.png`,
      fullPage: true,
    });
    console.log("PASS all research detail panels at 500px");
    // Delayed B holdings must clear A immediately. C wins when B later returns.
    const synthetic = (id) => ({
      line_id: id,
      name: `TEST-${id}`,
      status: "ACTIVE_PAPER",
      data_status: "AVAILABLE",
      position_status: "KNOWN",
      as_of: "2026-10-09",
      freshness: "FRESH",
      adjudication: "test only",
      source: { path: "test fixture" },
      metrics: { ytd_return_pct: 15.26 },
      nav_series: [
        { date: "2026-10-08", nav: 1 },
        { date: "2026-10-09", nav: 1.1 },
      ],
    });
    await page.route("**/research/lines/RACE_*", (route) =>
      route.fulfill({
        json: synthetic(route.request().url().split("/").at(-1)),
      }),
    );
    await page.route("**/research/lines/cta_r", (route) =>
      route.fulfill({
        json: {
          ...synthetic("cta_r"),
          position_status: "UNKNOWN",
          metrics: { observation_count: 5, trading_days: 4 },
          nav_series: Array.from({ length: 5 }, (_, i) => ({
            date: `2026-10-0${i + 1}`,
            nav: 1 + i / 100,
          })),
        },
      }),
    );
    await page.evaluate(() => showLineDetail("cta_r", false));
    assert.match(
      await page.locator("#detail-full-metrics").textContent(),
      /5 点/,
    );
    assert.match(
      await page.locator("#detail-full-metrics").textContent(),
      /4 个交易日/,
    );
    assert.match(
      await page.locator("#detail-metrics-grid").textContent(),
      /样本不足，不年化/,
    );
    await page.route(
      "**/research/positions/current?line_id=RACE_*",
      async (route) => {
        const id = new URL(route.request().url()).searchParams.get("line_id");
        if (id === "RACE_B") await sleep(500);
        await route.fulfill({
          json: [
            {
              symbol: `POSITION_${id}`,
              quantity: 1,
              date: "2026-10-09",
              action: "HOLD",
            },
          ],
        });
      },
    );
    await page.evaluate(async () => {
      switchTab("paper");
      await showLineDetail("RACE_A", false);
    });
    assert.match(
      await page.locator("#detail-current-positions").textContent(),
      /POSITION_RACE_A/,
    );
    await page.evaluate(() => {
      void showLineDetail("RACE_B", false);
    });
    assert.doesNotMatch(
      await page.locator("#detail-current-positions").textContent(),
      /POSITION_RACE_A/,
    );
    await page.evaluate(() => showLineDetail("RACE_C", false));
    await sleep(600);
    assert.match(
      await page.locator("#detail-current-positions").textContent(),
      /POSITION_RACE_C/,
    );
    assert.match(
      await page.locator("#detail-full-metrics").textContent(),
      /年初至今收益/,
    );
    assert.doesNotMatch(
      await page.locator("#detail-full-metrics").textContent(),
      /自起年化/,
    );
    await page.route("**/research/lines/FAIL", (route) =>
      route.fulfill({ status: 500, json: { error: "test" } }),
    );
    await page.evaluate(() => showLineDetail("FAIL", false));
    assert.doesNotMatch(
      await page.locator("#detail-current-positions").textContent(),
      /POSITION_RACE/,
    );
    assert.equal(await page.locator("#detail-source-error").isVisible(), true);
    await page.route("**/research/lines/ARCHIVE", (route) =>
      route.fulfill({
        json: {
          ...synthetic("ARCHIVE"),
          status: "ARCHIVED",
          data_status: "MISSING",
          error: "SOURCE_MISSING",
          metrics: { cagr_pct: 999, sharpe: 9 },
          adjudication: "高收益结论撤销，研究封存",
        },
      }),
    );
    await page.evaluate(() => showLineDetail("ARCHIVE", false));
    assert.equal(
      await page.locator("#detail-current-content").isVisible(),
      false,
    );
    assert.equal(
      await page.locator("#retained-history-metrics").isVisible(),
      false,
    );
    assert.match(
      await page.locator("#retained-history-label").textContent(),
      /2026-10-09/,
    );
    assert.match(
      await page.locator("#detail-adjudication").textContent(),
      /高收益结论撤销/,
    );
    console.log(
      "PASS delayed, out-of-order, failure and archived history presentation",
    );
    // Exercise clock updates and visible-only polling using a controlled source and clock.
    await page.clock.install();
    await page.evaluate(() => switchTab("account"));
    let reads = 0;
    await page.route("**/account/assets", (route) => {
      reads++;
      return route.fulfill({
        json: {
          status: "AVAILABLE",
          observed_at: new Date().toISOString(),
          reported_total_usdt: 100,
          wallets: [],
          futures_positions: [],
          futures_positions_complete: true,
          currency: "USDT",
          positions: [],
          read_only: true,
          source: { path: "test fixture" },
          safety: { research_only: true, orders_authorized: false },
          observation_interval_seconds: 300,
        },
      });
    });
    await page.reload();
    await page.waitForFunction(() => !liveFetchPending && liveObservedAt != null);
    const initialAge = await page.locator("#live-age").textContent();
    await page.clock.fastForward(65000);
    assert.notEqual(await page.locator("#live-age").textContent(), initialAge);
    const before = reads;
    await page.evaluate(() =>
      Object.defineProperty(document, "hidden", {
        configurable: true,
        get: () => true,
      }),
    );
    await page.clock.fastForward(300000);
    assert.equal(reads, before);
    await page.evaluate(() => {
      Object.defineProperty(document, "hidden", {
        configurable: true,
        get: () => false,
      });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await page.waitForFunction(() => !liveFetchPending);
    assert.ok(reads > before);
    console.log("PASS observation age and visible-only read polling");
    assert.deepEqual(errors, []);
    console.log("PASS no browser JavaScript errors");
    await context.close();
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
