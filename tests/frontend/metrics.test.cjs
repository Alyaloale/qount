const test = require("node:test");
const assert = require("node:assert/strict");
const M = require("../../web/app/metrics.js");
const rows = [
  { date: "2024-01-01", nav: 1, benchmark_nav: 1, signal_nav: 1 },
  { date: "2024-06-01", nav: 2, benchmark_nav: 1.4, signal_nav: 2.1 },
  { date: "2025-01-01", nav: 1, benchmark_nav: 1.5, signal_nav: 1.2 },
  { date: "2025-06-01", nav: 1.2, benchmark_nav: 1.6, signal_nav: 1.4 },
];
test("a cropped drawdown keeps the peak outside the selected window", () => {
  const result = M.windowStats(rows, 2, 3);
  assert.deepEqual(result.drawdown, [-50, -40]);
  assert.equal(result.maxDrawdown, -50);
  assert.equal(result.windowDrawdown, 0);
  assert.ok(Math.abs(result.strategy.total - 20) < 1e-8);
  assert.ok(Math.abs(result.benchmark.total - 6.6666666667) < 1e-8);
});
test("window return and full-sample return are separate", () => {
  assert.notEqual(
    M.windowStats(rows, 1, 3).strategy.total,
    M.windowStats(rows).strategy.total,
  );
  assert.equal(M.windowStats(rows, 2, 3).strategy.cagr, null);
});
test("short and sparse series are not annualized; CTA can explicitly suppress it", () => {
  assert.equal(M.windowStats(rows).strategy.cagr, null);
  const dense = Array.from({ length: 30 }, (_, i) => ({
    date: new Date(Date.UTC(2024, 0, 1) + i * 20 * 86400000).toISOString(),
    nav: 1 + i / 100,
  }));
  assert.ok(M.windowStats(dense).strategy.cagr > 0);
  assert.equal(M.windowStats(dense, 0, 29, false).strategy.cagr, null);
});
test("gaps and missing benchmark endpoints do not become same-window comparisons", () => {
  const incomplete = rows.map((row, i) => ({
    ...row,
    benchmark_nav: i === 1 ? null : row.benchmark_nav,
  }));
  assert.equal(M.windowStats(incomplete).benchmark.total, null);
  assert.equal(M.windowStats(incomplete).excess, null);
});
test("calendar span and observations are distinct, not a count mislabeled as days", () => {
  assert.equal(M.windowStats(rows).selected.length, 4);
  assert.equal(M.windowStats(rows).span, 517);
  assert.equal(M.rangeStart(rows, "1y"), 1);
});
test("observation age advances without a fetch and rejects bad/future times", () => {
  const time = Date.parse("2026-10-12T12:00:00Z");
  assert.equal(
    M.age("2026-10-12T12:00:00Z", time + 61000).text,
    "1 分钟 1 秒前",
  );
  assert.equal(M.age("2026-10-12T12:00:00Z", time + 601000).stale, true);
  assert.equal(M.age(null, time).text, "观测时间未知");
  assert.equal(M.age("2026-10-12T13:00:00Z", time).stale, true);
});
