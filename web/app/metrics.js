/* Pure display calculations shared by the browser and node regression tests. */
const QountMetrics = (() => {
  const number = (value) =>
    value != null && Number.isFinite(Number(value)) ? Number(value) : null;
  const timestamp = (value) => {
    let text = String(value || "").trim();
    if (/^\d{8}$/.test(text))
      text = `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6)}`;
    return Date.parse(text.length === 10 ? `${text}T00:00:00Z` : text);
  };
  const drawdowns = (rows, key = "nav") => {
    let peak = -Infinity;
    return rows.map((row) => {
      const value = number(row[key]);
      if (value == null || value <= 0) return null;
      peak = Math.max(peak, value);
      return (value / peak - 1) * 100;
    });
  };
  function windowStats(
    rows,
    start = 0,
    end = rows.length - 1,
    allowAnnual = true,
  ) {
    const selected = rows.slice(start, end + 1);
    const span = selected.length
      ? Math.max(
          0,
          (timestamp(selected.at(-1).date) - timestamp(selected[0].date)) /
            86400000,
        )
      : 0;
    function returns(key) {
      // A comparison requires both endpoints and every selected observation. Do not bridge
      // missing benchmark or signal data and call it a same-window comparison.
      if (
        selected.length < 2 ||
        selected.some(
          (row) => number(row[key]) == null || number(row[key]) <= 0,
        )
      )
        return { total: null, cagr: null };
      const ratio = number(selected.at(-1)[key]) / number(selected[0][key]);
      return {
        total: (ratio - 1) * 100,
        cagr:
          allowAnnual && span >= 365 && selected.length >= 20
            ? (ratio ** (365.2425 / span) - 1) * 100
            : null,
      };
    }
    const dd = drawdowns(rows).slice(start, end + 1);
    const validDD = dd.filter((value) => value != null);
    const windowDD = drawdowns(selected).filter((value) => value != null);
    const strategy = returns("nav");
    const benchmark = returns("benchmark_nav");
    const signal = returns("signal_nav");
    return {
      selected,
      span,
      strategy,
      benchmark,
      signal,
      drawdown: dd,
      maxDrawdown: validDD.length ? Math.min(...validDD) : null,
      currentDrawdown: dd.at(-1) ?? null,
      windowDrawdown: windowDD.length ? Math.min(...windowDD) : null,
      excess:
        strategy.total != null && benchmark.total != null
          ? strategy.total - benchmark.total
          : null,
      executionGap:
        signal.total != null && strategy.total != null
          ? signal.total - strategy.total
          : null,
    };
  }
  function rangeStart(rows, range) {
    if (!rows.length || range === "all") return 0;
    const end = new Date(timestamp(rows.at(-1).date));
    if (range === "ytd") end.setUTCMonth(0, 1);
    else if (range === "1y") end.setUTCFullYear(end.getUTCFullYear() - 1);
    else if (range === "3m") end.setUTCMonth(end.getUTCMonth() - 3);
    // Include the last observation at/before the boundary as the return's starting value.
    let start = 0;
    rows.forEach((row, i) => {
      if (timestamp(row.date) <= end.getTime()) start = i;
    });
    return start;
  }
  function age(value, now = Date.now()) {
    const parsed = timestamp(value);
    if (!Number.isFinite(parsed)) return { text: "观测时间未知", stale: true };
    const seconds = Math.floor((now - parsed) / 1000);
    if (seconds < -60)
      return { text: "观测时间晚于当前时钟，请核对", stale: true };
    const elapsed = Math.max(0, seconds);
    let text = `${elapsed} 秒前`;
    if (elapsed >= 86400)
      text = `${Math.floor(elapsed / 86400)} 天 ${Math.floor((elapsed % 86400) / 3600)} 小时前`;
    else if (elapsed >= 3600)
      text = `${Math.floor(elapsed / 3600)} 小时 ${Math.floor((elapsed % 3600) / 60)} 分钟前`;
    else if (elapsed >= 60)
      text = `${Math.floor(elapsed / 60)} 分钟 ${elapsed % 60} 秒前`;
    return { text, stale: elapsed > 600 };
  }
  return { number, timestamp, drawdowns, windowStats, rangeStart, age };
})();
if (typeof module !== "undefined") module.exports = QountMetrics;
