/* Native, read-only presentation of source-backed account and research data. */
let activeTab = "account";
let chartInstance = null;
let allocationChartInstance = null;
let assetHistoryChartInstance = null;
let assetHistoryRequestVersion = 0;
let performanceChartInstance = null;
let performanceRequestVersion = 0;
let performanceData = null;
let researchRuns = [];
let researchSourceBenchmark = new Map();
let researchComparisonVersion = 0;
let currentLineDetail = null;
let currentLineId = null;
let detailRequestVersion = 0;
let positionRequestVersion = 0;
let paperLines = new Map();
let chartStart = 0;
let chartEnd = 0;
let chartRowCount = 0;
let liveObservedAt = null;
let liveReadAt = null;
let liveAttemptAt = null;
let liveIntervalMs = 300000;
let liveFetchPending = false;
let refreshPending = false;
let accountSafety = null;
let liveReadOnly = null;
let researchFilter = "all";
let researchQuery = "";
let researchCategory = "all";
const API_BASE = "";
const $ = (id) => document.getElementById(id);
const setText = (id, text) => {
  const node = $(id);
  if (!node || node.textContent === String(text)) return;
  const previous = node.textContent;
  node.textContent = text;
  if (previous && previous !== "--" && node.classList.contains("kpi-value") &&
      !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
    node.animate?.([{ opacity: 0.45 }, { opacity: 1 }], { duration: 280 });
  }
};
const escapeHtml = (value) =>
  String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
const researchName = (line) => QountResearch.profile(line).name;
const reduceMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
const fmt = (value, digits = 2) =>
  QountMetrics.number(value) == null
    ? "--"
    : Number(value).toLocaleString("zh-CN", {
        maximumFractionDigits: digits,
        minimumFractionDigits: digits,
      });
const pct = (value) =>
  QountMetrics.number(value) == null
    ? "--"
    : `${Number(value) > 0 ? "+" : ""}${fmt(Number(value) === 0 ? 0 : value)}%`;
function assetAmount(value) {
  const amount = QountMetrics.number(value);
  if (amount == null) return "--";
  const size = Math.abs(amount);
  if (size > 0 && size < 1e-8) return `${amount < 0 ? "−" : ""}<0.00000001`;
  return fmt(amount, size > 0 && size < 0.01 ? Math.min(8, -Math.floor(Math.log10(size)) + 2) : 2);
}
function walletName(name) {
  return ({ Spot: "现货钱包", Funding: "资金钱包", "Cross Margin": "全仓杠杆", "Isolated Margin": "逐仓杠杆",
    "USDⓈ-M Futures": "U 本位合约", "COIN-M Futures": "币本位合约", Earn: "理财钱包", Options: "期权钱包",
    "Trading Bots": "交易机器人", "Copy Trading": "跟单钱包" })[name] || name;
}
const signClass = (value) =>
  value == null ? "" : value > 0 ? "positive" : value < 0 ? "negative" : "";
const formatDate = (value) => {
  const text = String(value || "");
  return /^\d{8}$/.test(text)
    ? `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6)}`
    : /^\d{4}-\d{2}-\d{2}/.test(text) ? text.slice(0, 10) : "--";
};
function formatTime(value) {
  const timestamp = QountMetrics.timestamp(value);
  return Number.isFinite(timestamp)
    ? `${new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Singapore", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" }).format(timestamp).replaceAll("/", "-")} UTC+8`
    : "--";
}
function ledgerDate(value) {
  const text = String(value || "");
  return text.includes("T") && !/T00:00:00(?:\.0+)?(?:Z|\+00:00)?$/.test(text)
    ? formatTime(value)
    : formatDate(value);
}
async function readJSON(url) {
  const response = await fetch(`${API_BASE}${url}`, {
    cache: "no-store",
    signal: AbortSignal.timeout(20000),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}
function tableMessage(id, columns, message) {
  if ($(id))
    $(id).innerHTML =
      `<tr><td colspan="${columns}" class="table-empty">${escapeHtml(message)}</td></tr>`;
}
function showError(id, message) {
  setText(id, message);
  $(id)?.classList.toggle("hidden", !message);
}
function statusText(value) {
  return (
    {
      BUY: "买入",
      SELL: "卖出",
      OPEN: "建仓",
      CLOSE: "平仓",
      ADJUST: "调整",
      HOLD: "持有",
      SPLIT: "份额拆分",
      DIVIDEND_ACCRUAL: "分红应收",
      DIVIDEND_PAYMENT: "分红转现金",
      long: "多头",
      short: "空头",
      unknown: "未知",
      simulated_not_realized: "模拟记录",
      ACTIVE_PAPER: "研究模拟",
      ARCHIVED: "封存",
      STOPPED: "停止",
      FRESH: "来源已更新",
      STALE: "数据待更新",
      MISSING: "数据缺失",
    }[value] ||
    value ||
    "--"
  );
}
function historicalOnly(line) {
  return (
    !!line.error ||
    line.data_status === "MISSING" ||
    line.data_status === "ERROR" ||
    ["ARCHIVED", "STOPPED"].includes(line.status)
  );
}
function identity(line) {
  if (line.status === "ARCHIVED") return "研究封存";
  if (line.status === "STOPPED") return "停止／失败";
  return QountResearch.profile(line).sample;
}
function nextQuestion(line) {
  if (["ARCHIVED", "STOPPED"].includes(line.status))
    return "保留失败结论与资料；不根据旧指标推定策略已获准恢复。";
  if (["personal_assistant", "personal_assistant_forward"].includes(line.line_id))
    return "待验证：MA120＋1.5% 带宽相对同标的买持，在净收益、回撤与暴露上提供多少增量？已有历史回放；前向来源未接入时不显示为正在积累。";
  if (line.line_id === "universal_regime")
    return "待验证：v1.3 冻结参数（旧 Calmar 字段已更正）在未见数据上的前向表现能否复现回测指标？短样本期间不报告年化。";
  if (["cta_r", "cta_r_forward"].includes(line.line_id))
    return "待验证：前向记录是否连续、持仓与成本是否一致？短样本暂不报告年化与 Sharpe。";
  return "待验证：信号与模拟执行差异能否由来源中的费用、交易单位和执行约束解释？";
}
function costsText(line) {
  const assumptions = line.cost_assumptions || {};
  const parts = [];
  if (assumptions.commission_bps != null)
    parts.push(`佣金 ${fmt(assumptions.commission_bps)} bps`);
  if (assumptions.slippage_bps != null)
    parts.push(`滑点 ${fmt(assumptions.slippage_bps)} bps`);
  if (assumptions.cash_apr_pct != null)
    parts.push(`现金年利率 ${fmt(assumptions.cash_apr_pct)}%`);
  if (assumptions.combined_cost_per_side_bps != null)
    parts.push(
      `单边综合成本近似 ${fmt(assumptions.combined_cost_per_side_bps)} bps（未拆分项目）`,
    );
  return parts.length
    ? `来源明确：${parts.join("；")}。其他成本项目、整手与最低佣金等限制须逐项核对下方来源说明。`
    : "费率及完整成本覆盖：来源未提供。累计成本有值仅说明存在成本记录，不能据此认定已覆盖价差、冲击、税费或融资成本。";
}
function renderPermissions() {
  const live = liveReadOnly === true ? "账户只读采集" : "账户采集状态待核";
  setText("permission-status", `${live} · 页面不提交订单；后台策略运行状态见实盘`);
  setText("footer-permission", `${live} · 页面不提交订单`);
  setText("topbar-permission", `${liveReadOnly === true ? "页面只读" : "采集状态待核"}`);
  setText("account-mode-badge", "真实账户");
  setText("live-mode-badge", liveReadOnly === true ? "只读" : "权限待核");
}

document.addEventListener("DOMContentLoaded", () => {
  setupMotion();
  document.querySelectorAll(".nav-item").forEach(button => {
    button.tabIndex = button.classList.contains("active") ? 0 : -1;
  });
  $("research-category")?.addEventListener("change", (event) => {
    researchCategory = event.target.value;
    renderPaperLines([...paperLines.values()]);
  });
  $("research-search")?.addEventListener("input", (event) => {
    researchQuery = event.target.value;
    renderPaperLines([...paperLines.values()]);
  });
  $("research-filters")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-research-filter]");
    if (!button) return;
    researchFilter = button.dataset.researchFilter;
    renderPaperLines([...paperLines.values()]);
  });
  document.querySelector(".sidebar-nav")?.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const tabs = [...document.querySelectorAll(".nav-item")];
    const current = tabs.indexOf(document.activeElement);
    const index = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 :
      (current + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
    tabs[index].focus();
    switchTab(tabs[index].id.replace("tab-", ""));
  });
  $("asset-history-days")?.addEventListener("change", fetchAssetHistory);
  $("performance-days")?.addEventListener("change", fetchLivePerformance);
  $("performance-measure")?.addEventListener("change", renderLivePerformance);
  $("research-run-select")?.addEventListener("change", () => showLineDetail(currentLineId, false, false, $("research-run-select").value));
  $("research-compare-select")?.addEventListener("change", compareResearchRun);
  $("mascot-btn")?.addEventListener("click", () => {
    mascotReact("is-excited");
    mascotSay(MASCOT_TIPS[Math.floor(Math.random() * MASCOT_TIPS.length)]);
  });
  initApp();
  setInterval(() => { if (activeTab === "account") updateObservationAge(); }, 5000);
  setInterval(() => {
    if (
      !document.hidden &&
      !liveFetchPending &&
      (!liveAttemptAt || Date.now() - liveAttemptAt >= liveIntervalMs)
    ) {
      fetchLiveAccountData();
      fetchDailyReport();
    }
  }, 15000);
});
window.addEventListener("resize", () => {
  chartInstance?.resize();
  allocationChartInstance?.resize();
  assetHistoryChartInstance?.resize();
  performanceChartInstance?.resize();
  fitAssetValues();
});
document.addEventListener("visibilitychange", () => {
  document.documentElement.classList.toggle("page-hidden", document.hidden);
  if (!document.hidden) {
    updateObservationAge();
    if (!liveAttemptAt || Date.now() - liveAttemptAt >= liveIntervalMs) {
      fetchLiveAccountData();
      fetchDailyReport();
    }
  }
});
function setupMotion() {
  const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
  if (preference.matches || !("IntersectionObserver" in window)) return;
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      entry.target.classList.remove("reveal-pending");
      observer.unobserve(entry.target);
    });
  }, { threshold: 0.06 });
  document.querySelectorAll(".asset-dashboard .card-section").forEach((node) => {
    node.classList.add("reveal-pending");
    observer.observe(node);
  });
}
function showLoadingBar() {
  document.body.classList.add("is-loading");
  ["btn-refresh", "btn-refresh-mobile"].forEach(id => $(id)?.setAttribute("aria-busy", "true"));
  const bar = $("loading-bar");
  if (bar) bar.classList.add("active");
}
function hideLoadingBar() {
  document.body.classList.remove("is-loading");
  ["btn-refresh", "btn-refresh-mobile"].forEach(id => $(id)?.setAttribute("aria-busy", "false"));
  const bar = $("loading-bar");
  if (bar) bar.classList.remove("active");
}
async function initApp(manageLoading = true) {
  if (manageLoading) showLoadingBar();
  await Promise.allSettled([
    fetchLiveAccountData(),
    fetchPaperLines(),
    fetchDailyReport(),
  ]);
  if (manageLoading) hideLoadingBar();
  setText(
    "header-as-of",
    `读取 ${new Date().toLocaleTimeString("zh-CN", { timeZone: "Asia/Singapore", hour12: false })} UTC+8`,
  );
}
const TAB_TITLES = {
  account: "资产分析",
  live: "实盘",
  paper: "策略研究",
  positions: "模拟流水",
  records: "账户记录",
};
function switchTab(name) {
  activeTab = name;
  document
    .querySelectorAll(".nav-item")
    .forEach((button) => {
      const isActive = button.id === `tab-${name === "positions" ? "paper" : name}`;
      button.classList.toggle("active", isActive);
      if (button.hasAttribute("aria-selected"))
        button.setAttribute("aria-selected", String(isActive));
      button.tabIndex = isActive ? 0 : -1;
    });
  document
    .querySelectorAll(".screen-view")
    .forEach((view) =>
      view.classList.toggle("active", view.id === `screen-${name}`),
    );
  const topbarTitle = document.getElementById("topbar-title");
  if (topbarTitle && TAB_TITLES[name]) topbarTitle.textContent = TAB_TITLES[name];
  if (name === "paper") requestAnimationFrame(() => chartInstance?.resize());
  if (name === "live") requestAnimationFrame(() => performanceChartInstance?.resize());
  if (name === "account") requestAnimationFrame(() => { allocationChartInstance?.resize(); assetHistoryChartInstance?.resize(); fitAssetValues(); });

}
const MASCOT_TIPS = [
  "各线样本不同，不能直接按收益排名。",
  "回测漂亮不等于实盘盈利，前向验证才是证据。",
  "封存线的旧高收益已撤销，别信它。",
  "数据缺源时我只会说不知道，不会编数字。",
  "这里可以看账户与研究；页面不会提交订单。",
];
let mascotTimer = null;
function mascotSay(text, holdMs = 4200) {
  const bubble = $("mascot-bubble");
  if (!bubble) return;
  const stage = document.querySelector(".mascot-stage");
  const r = stage ? stage.getBoundingClientRect() : null;
  // The mascot lives inside .asset-hero (isolation:isolate), a stacking context that
  // caps the bubble's z-index below the sticky topbar. Show it from <body> instead so
  // its fixed z-index resolves in the root context, and skip it when the mascot is
  // not laid out (e.g. the account tab is hidden), which would misplace the bubble.
  if (!r || (r.width === 0 && r.height === 0)) {
    bubble.classList.add("hidden");
    return;
  }
  if (bubble.parentElement !== document.body) document.body.appendChild(bubble);
  bubble.textContent = text;
  bubble.classList.remove("hidden");
  {
    const bw = bubble.offsetWidth;
    const bh = bubble.offsetHeight;
    let left = r.left + r.width / 2 - bw / 2;
    left = Math.max(10, Math.min(left, window.innerWidth - bw - 10));
    let top = r.top - bh - 14;
    if (top < 10) {
      top = Math.max(10, Math.min(r.bottom + 14, window.innerHeight - bh - 10));
      bubble.classList.add("below");
    } else {
      bubble.classList.remove("below");
    }
    bubble.style.left = `${Math.round(left)}px`;
    bubble.style.top = `${Math.round(top)}px`;
  }
  clearTimeout(mascotTimer);
  if (holdMs) mascotTimer = setTimeout(() => bubble.classList.add("hidden"), holdMs);
}
function mascotReact(state) {
  const stage = document.querySelector(".mascot-stage");
  if (!stage) return;
  stage.classList.remove("is-excited", "is-worried", "is-thinking");
  if (!state) return;
  void stage.offsetWidth;
  stage.classList.add(state);
  if (state === "is-excited" || state === "is-worried")
    setTimeout(() => stage.classList.remove(state), 760);
}
async function refreshData() {
  if (refreshPending) return;
  refreshPending = true;
  $("btn-refresh").disabled = true;
  $("btn-refresh-mobile").disabled = true;
  $("btn-refresh").innerHTML = '<span class="refresh-icon" aria-hidden="true">↻</span> 读取中…';
  showLoadingBar();
  mascotReact("is-thinking");
  mascotSay("正在读取最新快照，稍等…", 0);
  try {
    await initApp(false);
    if (currentLineId) await showLineDetail(currentLineId, false, true);
  } finally {
    refreshPending = false;
    $("btn-refresh").disabled = false;
    $("btn-refresh-mobile").disabled = false;
    hideLoadingBar();
    $("btn-refresh").innerHTML = '<span class="refresh-icon" aria-hidden="true">↻</span> 刷新数据';
    mascotReact("is-excited");
    mascotSay("刷新完成，数字已更新。");
  }
}
async function fetchLiveAccountData() {
  if (liveFetchPending) return;
  liveFetchPending = true;
  liveAttemptAt = Date.now();
  const historyRequest = fetchAssetHistory();
  const recordsRequest = fetchLiveTradeRecords();
  const strategyRequest = fetchOneAtrStatus();
  const performanceRequest = fetchLivePerformance();
  try {
    const data = await readJSON("/account/assets");
    window.QountLive?.render(data);
    liveReadAt = Date.now();
    setText("live-read-at", `页面读取 ${formatTime(new Date(liveReadAt).toISOString())}`);
    liveReadOnly = data.read_only;
    accountSafety = data.safety;
    renderPermissions();
    if (!["AVAILABLE", "PARTIAL"].includes(data.status) || data.reported_total_usdt == null)
      throw new Error(data.error || "钱包汇总尚未采集");
    setText("asset-connection-badge", "Binance · 快照可读");
    liveObservedAt = data.observed_at;
    setText("live-as-of", `采集时间 ${formatTime(data.observed_at)}`);
    setText("live-source-path", (data.source_endpoints || []).join(" · ") || "币安只读账户快照");
    setText("live-nav", fmt(data.reported_total_usdt));
    setText("live-cash", fmt(data.usdm_available_balance_usdt));
    setText("live-equity", fmt(data.futures_equity_usdt));
    setText("live-pnl", fmt(data.futures_unrealized_pnl_usdt));
    $("live-pnl").className = `kpi-value ${signClass(data.futures_unrealized_pnl_usdt)}`;
    setText("live-currency", data.currency || "USDT");
    const available = QountMetrics.number(data.usdm_available_balance_usdt);
    const equity = QountMetrics.number(data.usdm_margin_balance_usdt);
    setText("live-unavailable", available == null || equity == null ? "--" : fmt(Math.max(0, equity - available)));
    const positions = data.futures_positions || [];
    const complete = data.futures_positions_complete === true;
    const notionals = positions.map((pos) => QountMetrics.number(pos.notional_usdt));
    setText("live-exposure", complete && notionals.every((v) => v != null) ? fmt(notionals.reduce((sum, v) => sum + Math.abs(v), 0)) : "--");
    setText("live-position-count", `${complete ? "" : "已读取 "}${positions.length} 项持仓`);
    setText("live-positions-note", complete ? "Binance USDⓈ-M · USDT" : "合约覆盖尚不完整");
    setText("wallet-count", `${data.wallets.length} 个钱包`);
    const unvalued = data.unvalued_collateral_assets || [];
    setText("asset-coverage", `${data.wallets.length} 个钱包 · USDT合约浮盈亏${complete ? "已读取" : "尚有缺项"}。${unvalued.length ? `非USDT保证金未估值：${unvalued.join("、")}。` : ""}不含现货成本法、COIN-M 与期权浮盈亏。`);
    const errors = Object.entries(data.errors || {}).map(([key, value]) => `${key}: ${value}`).join("；");
    setText("asset-source-errors", errors ? `来源缺项：${errors}` : "钱包余额按 Binance 全钱包汇总，合约权益按 USDⓈ-M USDT 口径；各接口存在采集时间差。");
    showError("live-error", data.status === "PARTIAL" ? "部分账户数据未取得，缺项显示为 --；钱包余额不与合约权益重复相加。" : "");
    $("wallets-body").innerHTML = data.wallets.map((wallet) => `<tr><td>${escapeHtml(walletName(wallet.name))}<small class="wallet-original">${escapeHtml(wallet.name)}</small></td><td><span class="wallet-state">${wallet.active ? "已启用" : "未启用"}</span></td><td class="numeric">${assetAmount(wallet.balance_usdt)}</td><td class="numeric ${signClass(wallet.unrealized_pnl_usdt)}">${wallet.market ? assetAmount(wallet.unrealized_pnl_usdt) : "不适用"}</td><td class="numeric">${wallet.market ? assetAmount(wallet.equity_usdt) : "不适用"}</td></tr>`).join("");
    renderWalletAllocation(data.wallets);
    if (!positions.length) tableMessage("live-positions-body", 5, complete ? "该次观测确认 USDⓈ-M 已采集范围无持仓" : "持仓来源不完整，尚不能确认空仓");
    else $("live-positions-body").innerHTML = positions.map((pos) => `<tr><td><small class="header-note">USDⓈ-M</small><br>${escapeHtml(pos.signal_symbol && pos.signal_symbol !== pos.symbol ? `${pos.signal_symbol} · ${pos.symbol}` : pos.symbol)}</td><td>${escapeHtml(statusText(pos.side))}</td><td class="numeric">${fmt(pos.quantity, 4)}</td><td class="numeric">${fmt(pos.notional_usdt)}</td><td class="numeric ${signClass(pos.unrealized_pnl_usdt)}">${fmt(pos.unrealized_pnl_usdt)}</td></tr>`).join("");
    updateObservationAge();
    fitAssetValues();
  } catch (error) {
    window.QountLive?.render(null);
    ["live-nav", "live-cash", "live-unavailable", "live-exposure", "live-equity", "live-pnl"].forEach((id) => setText(id, "--"));
    setText("live-position-count", "持仓待确认");
    setText("live-positions-note", "合约覆盖待确认");
    setText("wallet-count", "尚未接入");
    setText("asset-connection-badge", "Binance · 数据待接入");
    setText("asset-coverage", "完整钱包汇总尚未取得，不能据此确认总资产或空仓。");
    setText("live-source-path", "本次读取不可用");
    setText("asset-source-errors", "");
    tableMessage("wallets-body", 5, "完整钱包数据尚未取得");
    tableMessage("live-positions-body", 5, "账户来源不可用，无法确认当前持仓");
    renderWalletAllocation([]);
    showError("live-error", `资产读数不可用：${error.message || "读取失败"}。需由持有只读凭据的采集主机生成新版快照。`);
    updateObservationAge();
  } finally {
    await Promise.allSettled([historyRequest, recordsRequest, strategyRequest, performanceRequest]);
    liveFetchPending = false;
  }
}
async function fetchOneAtrStatus() {
  try { window.QountLive?.renderOneAtr(await readJSON('/account/one-atr')); }
  catch (_) { window.QountLive?.renderOneAtr(null); }
}
async function fetchLiveTradeRecords() {
  try { window.QountLive?.renderRecords(await readJSON('/account/trades?limit=100')); }
  catch (_) { window.QountLive?.renderRecords(null); }
}
function fitAssetValues() {
  document.querySelectorAll(".asset-kpi-grid .kpi-value").forEach((node) => {
    node.style.fontSize = "";
    node.title = node.textContent;
    if (!node.clientWidth) return;
    let size = parseFloat(getComputedStyle(node).fontSize);
    while (node.scrollWidth > node.clientWidth && size > 12) node.style.fontSize = `${--size}px`;
  });
}
const WALLET_COLORS = ["#ffd93d", "#4d96ff", "#6bcb77", "#ff9f43", "#00b8bd", "#ff6b6b", "#8c9b4a", "#2d2d2d"];
function renderWalletAllocation(wallets) {
  const funded = wallets.filter((w) => w.balance_usdt > 0);
  const total = funded.reduce((sum, w) => sum + w.balance_usdt, 0);
  const empty = $("asset-chart-empty");
  empty.classList.toggle("hidden", total > 0 && !!window.echarts);
  setText("asset-chart-empty", wallets.length ? total > 0 ? "图表暂不可用" : "暂无正余额钱包" : "钱包数据待确认");
  $("wallet-chart-legend").innerHTML = funded.map((w, i) => `<span><i class="legend-dot" style="background:${WALLET_COLORS[i % WALLET_COLORS.length]}"></i>${escapeHtml(walletName(w.name))} <b>${fmt(w.balance_usdt / total * 100, 1)}%</b></span>`).join("");
  if (!total || !window.echarts) { allocationChartInstance?.clear(); return; }
  if (!allocationChartInstance) allocationChartInstance = echarts.init($("asset-allocation-chart"));
  allocationChartInstance.setOption({
    animation: !window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    color: WALLET_COLORS,
    tooltip: { trigger: "item", formatter: (item) => `${escapeHtml(walletName(item.name))}：${assetAmount(item.value)} USDT (${fmt(item.percent, 1)}%)` },
    title: { text: `${funded.length}`, subtext: "有余额的钱包", left: "center", top: "35%", textStyle: { color: "#1a1a1a", fontSize: 28, fontWeight: 800 }, subtextStyle: { color: "#666666", fontSize: 12 } },
    series: [{ type: "pie", radius: ["67%", "84%"], center: ["50%", "48%"], label: { show: false }, itemStyle: { borderColor: "#fff", borderWidth: 4, borderRadius: 7 }, data: funded.map((w) => ({ name: w.name, value: w.balance_usdt })) }],
  }, true);
}
async function fetchAssetHistory() {
  const version = ++assetHistoryRequestVersion;
  const days = $("asset-history-days")?.value || "30";
  try {
    const data = await readJSON(`/account/history?days=${encodeURIComponent(days)}`);
    if (version !== assetHistoryRequestVersion) return;
    if (data.status === "ERROR") throw new Error("历史记录不可读");
    const points = data.points || [];
    const valued = points.filter((p) => p.reported_total_usdt != null);
    const ready = valued.length > 0 && !!window.echarts;
    $("asset-history-empty").classList.toggle("hidden", ready);
    setText("asset-history-empty", points.length ? "该区间暂无有效资产读数" : "真实资产历史待积累");
    setText("asset-history-note", points.length ? `${points.length} 次真实观测 · ${formatTime(points[0].observed_at)} 至 ${formatTime(points[points.length - 1].observed_at)}。余额变化包含充值、提现与估值变化，不作为收益率。钱包覆盖变化处断线。` : "尚无历史记录；采集主机启用新版只读采集后开始积累，不回填模拟值。");
    if (!ready) { assetHistoryChartInstance?.clear(); return; }
    if (!assetHistoryChartInstance) assetHistoryChartInstance = echarts.init($("asset-history-chart"));
    const seriesData = (key) => {
      let previousScope = null;
      const rows = [];
      for (const point of points) {
        const stamp = QountMetrics.timestamp(point.observed_at);
        const scope = JSON.stringify(point.wallet_scope || []);
        if (previousScope != null && scope !== previousScope) rows.push([stamp - 1, null]);
        rows.push([stamp, point[key] ?? null]); previousScope = scope;
      }
      return rows;
    };
    assetHistoryChartInstance.setOption({
      animation: false, color: ["#e0a800", "#4d96ff", "#6bcb77"],
      tooltip: { trigger: "axis", valueFormatter: (v) => v == null ? "未提供" : `${fmt(v)} USDT` },
      legend: { bottom: 0, textStyle: { color: "#555555", fontSize: 11 } },
      grid: { left: 65, right: 18, top: 20, bottom: 65 },
      xAxis: { type: "time", axisLine: { lineStyle: { color: "#2d2d2d" } }, axisLabel: { color: "#666666", hideOverlap: true } },
      yAxis: { type: "value", scale: true, axisLabel: { color: "#666666", fontSize: 10 }, splitLine: { lineStyle: { color: "#eeeeee", type: "dashed" } } },
      dataZoom: [{ type: "inside" }],
      series: [["钱包折合总额", "reported_total_usdt"], ["合约保证金权益", "futures_equity_usdt"], ["合约未实现盈亏", "futures_unrealized_pnl_usdt"]].map(([name, key]) => ({ name, type: "line", showSymbol: valued.length < 3, symbolSize: 7, connectNulls: false, data: seriesData(key), lineStyle: { width: 2 } })),
    }, true);
  } catch (error) {
    if (version !== assetHistoryRequestVersion) return;
    assetHistoryChartInstance?.clear();
    $("asset-history-empty")?.classList.remove("hidden");
    setText("asset-history-empty", "资产历史读取失败");
    setText("asset-history-note", "历史数据暂不可用，请刷新重试。");
  }
}
function updateObservationAge() {
  const age = QountMetrics.age(liveObservedAt);
  setText(
    "live-age",
    `${liveObservedAt ? "数据采集于 " : ""}${age.text}${age.stale && liveObservedAt ? " · 等待更新" : ""}`,
  );
  $("live-age")?.classList.toggle("fresh-stale", age.stale);
}
async function fetchDailyReport() {
  try {
    const data = await readJSON("/assistant/daily");
    if (!data.report) {
      setText("daily-status", data.reason || "最新日报未接入");
      setText("daily-date", "当前可查看历史回放末态");
      return;
    }
    const report = data.report;
    const input = report.input_status;
    const labels = {
      QUALIFIED: "该日合格研究日报",
      HISTORICAL: "最后合格历史日报 · 非今日状态",
      DISQUALIFIED: "日报资格不足 · 仅显示原因",
    };
    setText(
      "daily-date",
      `数据截止 ${formatDate(input.as_of_date)} · 生成 ${formatTime(report.generated_at)}`,
    );
    const qualifications = input.assets_qualification || {};
    const assets = Object.entries(report.rule_status.assets || {})
      .map(([key, asset]) => {
        const qualification = qualifications[key] || {};
        return `<div class="daily-asset"><strong>${escapeHtml(asset.name || asset.symbol)}</strong><p>规则状态：${escapeHtml(asset.regime)} · 数据资格 ${escapeHtml(qualification.data_qualification_status || "未提供")}</p><p>研究规则权重：${asset.target_weight == null ? "未提供" : pct(asset.target_weight * 100)} · 实际账户可执行资格待核</p><p>${escapeHtml(asset.reason || qualification.reason || "来源未提供原因")}</p></div>`;
      })
      .join("");
    const unknowns = report.risk_and_evidence.known_open_unknowns || [];
    $("daily-status").innerHTML =
      `<strong>${escapeHtml(labels[data.status] || "日报状态待核")}</strong><p class="header-note">来源新鲜度：${escapeHtml(statusText(input.freshness_status))}；预期数据日 ${formatDate(input.expected_as_of_date)}</p><div class="daily-assets">${assets}</div><p>待核事项：${escapeHtml(unknowns.join("；") || "来源未提供")}</p><details class="provenance-card"><summary>日报来源与资格</summary><p>完成包与清单哈希已匹配；这项校验不授予实盘交易资格。</p><code>${escapeHtml(data.source?.path)}</code><p><code>${escapeHtml(data.source?.sha256)}</code></p><p>证据状态 ${escapeHtml(report.tool_status.evidence_qualification_status)} · 输入哈希 ${escapeHtml(input.source_data_hash)}</p></details>`;
  } catch (error) {
    setText("daily-status", "最新日报读取失败");
    setText("daily-date", "今日状态无法确认");
  }
}

async function fetchPaperLines() {
  try {
    const lines = await readJSON("/research/lines");
    lines.sort(
      (a, b) => researchName(a).localeCompare(researchName(b), "zh-CN") || a.line_id.localeCompare(b.line_id),
    );
    paperLines = new Map(lines.map((line) => [line.line_id, line]));
    $("research-category").replaceChildren(...["all", ...new Set(lines.map(line => QountResearch.profile(line).category))].map(category => {
      const option = document.createElement("option");
      option.value = category;
      option.textContent = category === "all" ? "全部市场" : category;
      return option;
    }));
    if ([...$("research-category").options].some(option => option.value === researchCategory))
      $("research-category").value = researchCategory;
    else researchCategory = "all";
    renderPaperLines(lines);

    await populatePositionLineSelect(lines);
  } catch (error) {
    setText("paper-lines-body", "研究线列表读取失败，请刷新重试");
    setText("paper-lines-count", "列表读取失败");
  }
}
function sourceReturn(metrics, line) {
  if (line && QountResearch.forward(line)) return [line.sample_kind === "mixed" ? "连续模拟累计收益" : "前向起算收益", metrics?.total_return_pct ??
    (metrics?.executable_nav == null ? null : (metrics.executable_nav - 1) * 100)];
  if (metrics?.cagr_pct != null) return ["来源年化收益", metrics.cagr_pct];
  if (metrics?.ytd_return_pct != null)
    return ["年初至今收益", metrics.ytd_return_pct];
  if (metrics?.total_return_pct != null)
    return ["来源累计收益", metrics.total_return_pct];
  if (metrics?.executable_nav != null)
    return ["相对初始资金收益", (metrics.executable_nav - 1) * 100];
  return ["收益", null];
}
function paperRefreshText(line) {
  if (!QountResearch.forward(line)) return "";
  return [line.source?.produced_at ? `来源生成 ${formatTime(line.source.produced_at)}` : "",
    line.last_attempt_at ? `查询刷新 ${formatTime(line.last_attempt_at)}` : ""].filter(Boolean).join(" · ");
}
function renderPaperLines(lines) {
  const counts = QountResearch.summary(lines);
  const selected = QountResearch.select(lines, researchFilter, researchQuery, researchCategory);
  const groups = Object.fromEntries(["available", "waiting", "archived"].map(key =>
    [key, selected.filter(line => QountResearch.group(line) === key)]));
  groups.forward = groups.available.filter(QountResearch.forward);
  groups.historical = groups.available.filter(line => !QountResearch.forward(line));
  setText("paper-lines-count", `${counts.all} 条已接入`);
  $("research-summary").innerHTML = [
    ["启用模拟", counts.forward, "数据状态逐线显示", "available"],
    ["历史研究", counts.historical, "保留原样本与结论", "waiting"],
    ["封存与停止", counts.archived, "保留结论供复核", "archived"],
  ].map(([label, count, note, key]) => `<div class="research-stat ${key}"><span>${label}</span><strong>${count}<small> 条</small></strong><p>${note}</p></div>`).join("");
  document.querySelectorAll("[data-research-filter]").forEach(button => {
    const key = button.dataset.researchFilter;
    const labels = { all: "全部", forward: "持续模拟", available: "可查看结果", waiting: "等待数据", archived: "封存与停止" };
    button.textContent = `${labels[key]} ${counts[key]}`;
    button.classList.toggle("active", researchFilter === key);
    button.setAttribute("aria-pressed", String(researchFilter === key));
  });
  setText("research-match-count", researchQuery.trim() || researchFilter !== "all" || researchCategory !== "all"
    ? `找到 ${selected.length} 条研究线`
    : `${counts.stale} 条更新异常或待更新 · ${counts.missing} 条缺源（含封存线）`);
  function card(line, index) {
    const m = line.metrics || {};
    const profile = QountResearch.profile(line);
    const source = QountResearch.dataState(line);
    const unavailable = historicalOnly(line);
    const [returnLabel, returnValue] = sourceReturn(m, line);
    const forward = QountResearch.forward(line);
    const period = !QountResearch.available(line) && !m.start_date ? [] : [m.start_date, line.as_of].filter(date => date && date !== "unknown").map(formatDate);
    const facts = unavailable
      ? `<div class="research-unavailable"><span aria-hidden="true">${QountResearch.archived(line) ? "▤" : "◷"}</span><p>${QountResearch.archived(line) ? "历史工件与最终结论在详情中保留。" : "来源尚未接入，暂不展示收益与持仓。"}</p></div>`
      : `<dl class="research-facts"><div><dt>${returnLabel}</dt><dd class="${signClass(returnValue)}">${pct(returnValue)}</dd></div><div><dt>${line.sample_kind === "mixed" ? "全样本最大回撤" : forward ? "前向最大回撤" : "历史最大回撤"}</dt><dd class="negative">${pct(m.max_drawdown_pct == null ? null : -Math.abs(m.max_drawdown_pct))}</dd></div><div><dt>${m.benchmark_cagr_pct == null ? "当前回撤" : "同标的买持年化"}</dt><dd>${m.benchmark_cagr_pct == null ? pct(m.current_drawdown_pct == null ? null : -Math.abs(m.current_drawdown_pct)) : pct(m.benchmark_cagr_pct)}</dd></div></dl>`;
    const lifecycle = QountResearch.lifecycle(line);
    const footnote = m.cagr_basis === "252 trading days" ? "年化按 252 交易日计算" : profile.sample;
    const periodText = forward
      ? `${m.start_date ? "观测起于 " + formatDate(m.start_date) + " · " : ""}行情截至 ${formatDate(line.as_of)}`
      : period.length > 1 ? "样本 " + period.join(" — ") : period.length ? "数据截至 " + period[0] : "数据日期尚未确认";
    return `<article class="research-card" data-line-id="${escapeHtml(line.line_id)}" style="--enter-index:${index % 6}">
      <div class="research-card-top"><span class="research-category">${escapeHtml(profile.category)} <span>／ ${escapeHtml(profile.family)}</span></span><span class="research-lifecycle">${lifecycle}</span></div>
      <h3>${escapeHtml(profile.name)}</h3><p class="research-method">${escapeHtml(profile.method)}</p>
      <div class="research-source-row"><span class="source-chip ${source.tone}"><i aria-hidden="true"></i>${escapeHtml(source.label)}</span><span class="sample-chip">${escapeHtml(profile.sample)}</span></div>
      ${facts}<p class="research-card-period">${escapeHtml(periodText)}${unavailable ? "" : " · " + escapeHtml(footnote)}</p>
      ${paperRefreshText(line) ? `<p class="research-card-period">${escapeHtml(paperRefreshText(line))}</p>` : ""}
      <p class="research-takeaway"><strong>研究判断</strong>${escapeHtml(profile.note)}</p>
      <div class="research-card-bottom"><span class="research-id">${escapeHtml(line.line_id)}</span><button class="btn-action" data-open-line="${escapeHtml(line.line_id)}">${QountResearch.archived(line) ? "复核历史" : "查看详情"}<span aria-hidden="true"> ↗</span></button></div>
    </article>`;
  }
  let offset = 0;
  $("paper-lines-body").innerHTML = [
    ["forward", "已启用的模拟策略", "日线仅使用已收盘行情，休市期间沿用最近收盘日；行情截止日与来源生成、查询刷新时间分别展示。加密资产按 UTC 日线收盘及每日任务周期更新。"],
    ["historical", "历史研究结果", "保留原样本与结论，不与前向记录拼接收益。"],
    ["waiting", "等待数据的研究线", "保留研究方向与当前判断，接入来源后再展示结果。"],
  ].filter(([key]) => groups[key].length).map(([key, title, note]) => {
    const cards = groups[key].map(line => card(line, offset++)).join("");
    return `<section class="research-group"><div class="research-group-heading"><h3>${title}<span>${groups[key].length}</span></h3><p>${note}</p></div><div class="research-list">${cards}</div></section>`;
  }).join("");
  if (!selected.length) $("paper-lines-body").innerHTML = '<div class="research-empty"><span aria-hidden="true">⌕</span><h3>没有找到匹配的研究线</h3><p>试试市场、名称或 G20、ETF 等编号。</p><button class="btn-action" onclick="resetResearchFilters()">清除筛选</button></div>';
  $("archived-lines").classList.toggle("hidden", !groups.archived.length);
  if (researchFilter === "archived" || researchQuery.trim() || researchCategory !== "all") $("archived-lines").open = true;
  setText("archived-count", `封存与停止 · ${groups.archived.length} 条`);
  $("archived-lines-body").innerHTML = groups.archived.map((line, index) => card(line, index)).join("");
  document.querySelectorAll("[data-open-line]").forEach(button =>
    button.addEventListener("click", () => showLineDetail(button.dataset.openLine)));
}
function resetResearchFilters() {
  researchFilter = "all";
  researchQuery = "";
  researchCategory = "all";
  $("research-category").value = "all";
  $("research-search").value = "";
  renderPaperLines([...paperLines.values()]);
}
function populatePositionLineSelect(lines) {
  const select = $("positions-line-select");
  const previous = select.value;
  select.replaceChildren(
    ...lines.map((line) => {
      const option = document.createElement("option");
      option.value = line.line_id;
      option.textContent = QountResearch.profile(line).name;
      return option;
    }),
  );
  if (lines.some((line) => line.line_id === previous)) select.value = previous;
  if (select.value) return loadPaperPositions();
}
async function showLineDetail(lineId, scroll = true, preserveRange = false, runId = null) {
  ++researchComparisonVersion;
  $("research-run-controls")?.classList.add("hidden");
  setText("research-run-note", "");
  const previousRange = preserveRange ? $("chart-time-range").value : "all";
  const previousWindow =
    preserveRange && currentLineDetail ? selectedStats().selected : [];
  const requestVersion = ++detailRequestVersion;
  currentLineId = lineId;
  currentLineDetail = null;
  const panel = $("line-detail-panel");
  panel.classList.remove("hidden");
  panel.dataset.lineId = lineId;
  $("line-daily-panel")?.classList.toggle("hidden", lineId !== "personal_assistant");
  setText(
    "detail-title",
    `${paperLines.has(lineId) ? researchName(paperLines.get(lineId)) : lineId} · 读取中…`,
  );
  [
    "detail-adjudication",
    "detail-identity",
    "detail-position-as-of",
    "chart-range",
    "detail-next-question",
    "detail-window-note",
    "detail-execution-gap",
    "detail-source-path",
    "detail-source-sha256",
    "detail-cost-coverage",
    "retained-verification",
  ].forEach((id) => setText(id, ""));
  [
    "detail-metrics-grid",
    "detail-full-metrics",
    "retained-history-metrics",
    "detail-constraints",
  ].forEach((id) => $(id).replaceChildren());
  tableMessage("detail-current-positions", 6, `${lineId} 持仓读取中…`);
  $("detail-retained-history").classList.add("hidden");
  $("detail-current-content").classList.remove("hidden");
  $("detail-ledger-link").disabled = true;
  showError("detail-source-error", "");
  chartInstance?.dispose();
  chartInstance = null;
  setText("echarts-container", "研究曲线读取中…");
  const rangeSelect = $("chart-time-range");
  const customOption = rangeSelect.querySelector("[value=custom]");
  if (customOption) customOption.remove();
  rangeSelect.value = previousRange === "custom" ? "all" : previousRange;
  if (scroll) {
    $("detail-title").focus({ preventScroll: true });
    panel.scrollIntoView({ behavior: reduceMotion() ? "instant" : "smooth", block: "start" });
  }
  try {
    const data = await readJSON(`/research/lines/${encodeURIComponent(lineId)}${runId ? `?run_id=${encodeURIComponent(runId)}` : ""}`);
    if (requestVersion !== detailRequestVersion || currentLineId !== lineId)
      return;
    currentLineDetail = data;
    researchSourceBenchmark = new Map(data.nav_series.map(row => [row.date, row.benchmark_nav]));
    renderLineDetail(data);
    if (QountResearch.experimentRunId(data)) loadResearchRuns(data, requestVersion);
    if (
      previousRange === "custom" &&
      previousWindow.length &&
      data.nav_series.length
    ) {
      const lower = QountMetrics.timestamp(previousWindow[0].date);
      const upper = QountMetrics.timestamp(previousWindow.at(-1).date);
      const start = data.nav_series.findIndex(
        (row) => QountMetrics.timestamp(row.date) >= lower,
      );
      chartStart = start < 0 ? data.nav_series.length - 1 : start;
      chartEnd = chartStart;
      data.nav_series.forEach((row, index) => {
        if (QountMetrics.timestamp(row.date) <= upper)
          chartEnd = Math.max(chartStart, index);
      });
      $("chart-time-range").value = "custom";
      renderNavChart();
      updateWindowMetrics();
    }
    await loadLineCurrentPositions(data, requestVersion);
  } catch (error) {
    if (requestVersion !== detailRequestVersion || currentLineId !== lineId)
      return;
    setText(
      "detail-title",
      `${paperLines.has(lineId) ? researchName(paperLines.get(lineId)) : lineId} · 读取失败`,
    );
    showError("detail-source-error", "该研究线详情读取失败，请重新选择或刷新");
    setText("echarts-container", "曲线读取失败");
    tableMessage(
      "detail-current-positions",
      6,
      `${lineId} 持仓未读取，无法确认`,
    );
  }
}
function closeDetailPanel() {
  const opener = [...document.querySelectorAll("[data-open-line]")].find(button => button.dataset.openLine === currentLineId);
  $("line-detail-panel").classList.add("hidden");
  currentLineId = null;
  currentLineDetail = null;
  detailRequestVersion++;
  chartInstance?.dispose();
  chartInstance = null;
  opener?.focus({ preventScroll: true });
}
function fullMetricItems(line) {
  const m = line.metrics || {};
  const [returnTitle, value] = sourceReturn(m, line);
  return [
    [
      returnTitle +
        (m.cagr_basis === "252 trading days" ? "（252交易日）" : ""),
      pct(value),
    ],
    [
      "同标的基准年化" +
        (m.cagr_basis === "252 trading days" ? "（252交易日）" : ""),
      pct(m.benchmark_cagr_pct),
    ],
    [
      "来源最大回撤",
      pct(m.max_drawdown_pct == null ? null : -Math.abs(m.max_drawdown_pct)),
    ],
    ["来源 Sharpe", m.sharpe == null ? "未提供／样本不足" : fmt(m.sharpe)],
    ["来源 Calmar", fmt(m.calmar)],
    ["来源在市暴露", pct(m.exposure_pct)],
    ["买卖笔数", m.trade_count == null ? "来源未提供" : `${m.trade_count} 笔`],
    [
      "公司行动",
      m.corporate_action_count == null
        ? "来源未提供"
        : `${m.corporate_action_count} 次`,
    ],
    [
      "来源交易日数",
      m.trading_days == null ? "来源未明确" : `${m.trading_days} 个交易日`,
    ],
    ["完整样本观测点", `${(line.nav_series || []).length} 点`],
    [
      "初始模拟资金",
      m.initial_equity == null ? "来源未提供" : fmt(m.initial_equity),
    ],
    [
      "来源累计成本（全样本）",
      m.cumulative_cost == null
        ? "来源未提供"
        : `${fmt(m.cumulative_cost)}（源单位）`,
    ],
  ];
}
function pills(id, items) {
  $(id).innerHTML = items
    .map(
      ([title, value, color]) =>
        `<div class="metric-pill"><div class="metric-pill-title">${escapeHtml(title)}</div><div class="metric-pill-val ${color || ""}">${escapeHtml(value)}</div></div>`,
    )
    .join("");
}
function renderLineDetail(line) {
  const rows = line.nav_series || [];
  const unavailable = historicalOnly(line);
  setText("detail-title", QountResearch.profile(line).name);
  setText(
    "detail-identity",
    `${identity(line)} · ${QountResearch.dataState(line).label} · 行情截至 ${!QountResearch.available(line) && !rows.length ? "未知" : formatDate(line.as_of)}${paperRefreshText(line) ? " · " + paperRefreshText(line) : ""} · ${line.line_id}`,
  );
  setText("detail-adjudication", line.adjudication || "来源未提供裁决");
  setText("detail-next-question", nextQuestion(line));
  setText("detail-source-path", line.source?.path || "--");
  setText("detail-source-sha256", line.source?.sha256 || "未核验／来源未提供");
  setText("detail-cost-coverage", costsText(line));
  const kindLabel={historical:"原历史",reconstructed:"历史补算",forward:"前向观测",genesis:"初始观测"};
  setText("detail-sample-segments",(line.source?.segments || []).map(segment =>
    `${kindLabel[segment.kind] || segment.kind}：${formatDate(segment.start)} 至 ${formatDate(segment.end)}${segment.kind === "reconstructed" && segment.recorded_at ? "（实际记录 " + formatTime(segment.recorded_at) + "）" : ""}`).join("；"));
  $("line-daily-panel")?.classList.toggle("hidden",line.line_id !== "personal_assistant" || QountResearch.forward(line));
  $("detail-constraints").innerHTML =
    (line.execution_constraints || [])
      .map((text) => `<li>${escapeHtml(text)}</li>`)
      .join("") ||
    "<li>其他执行限制与成本缺项：来源未提供，不能推定实盘可获得同等收益。</li>";
  showError(
    "detail-source-error",
    unavailable
      ? `${line.data_status === "AVAILABLE" ? identity(line) : "当前数据不可用"}：以下保留历史仅供复核；当前裁决优先于历史数字。${line.error ? ` ${line.error.split(":")[0]}` : ""}`
      : "",
  );
  $("detail-current-content").classList.toggle("hidden", unavailable);
  $("detail-retained-history").classList.toggle("hidden", !unavailable);
  $("detail-retained-history").open = false;
  if (unavailable) {
    setText(
      "retained-history-label",
      `最后保留历史 · 截止 ${rows.length ? formatDate(rows.at(-1).date) : "无保留曲线"}`,
    );
    setText(
      "retained-verification",
      `当前来源${line.error ? "不可读取，旧数字未重新核验" : "可读取，保留工件不改变封存／停止裁决"}；来源哈希 ${line.source?.sha256 ? "已记录（不等于收益结论认证）" : "未提供"}。`,
    );
    pills("retained-history-metrics", fullMetricItems(line));
  } else pills("detail-full-metrics", fullMetricItems(line));
  $("detail-ledger-link").disabled = false;
  changeChartRange();
}
function selectedStats() {
  return QountMetrics.windowStats(
    currentLineDetail?.nav_series || [],
    chartStart,
    chartEnd,
    !["cta_r", "cta_r_forward"].includes(currentLineDetail?.line_id),
  );
}
function updateWindowMetrics() {
  if (!currentLineDetail) return;
  const line = currentLineDetail;
  const stats = selectedStats();
  const first = stats.selected[0]?.date;
  const last = stats.selected.at(-1)?.date;
  const range = first
    ? `${formatDate(first)} 至 ${formatDate(last)}`
    : "无净值观测";
  setText("detail-metrics-title", "所选窗口 · 收益与风险");
  pills("detail-metrics-grid", [
    [
      "策略窗口收益",
      pct(stats.strategy.total),
      signClass(stats.strategy.total),
    ],
    [
      "同窗基准收益",
      pct(stats.benchmark.total),
      signClass(stats.benchmark.total),
    ],
    [
      "相对基准差值",
      stats.excess == null ? "同窗基准不足" : `${fmt(stats.excess)} 个百分点`,
      signClass(stats.excess),
    ],
    [
      "窗口年化（自然年）",
      stats.strategy.cagr == null
        ? "样本不足，不年化"
        : pct(stats.strategy.cagr),
    ],
    [
      "同窗基准年化（自然年）",
      stats.benchmark.cagr == null
        ? "样本不足／基准缺失"
        : pct(stats.benchmark.cagr),
    ],
    ["完整历史峰值回撤 · 窗口最深", pct(stats.maxDrawdown), "negative"],
    ["完整历史峰值回撤 · 窗口末", pct(stats.currentDrawdown), "negative"],
    ["窗口内最大回撤（重置峰值）", pct(stats.windowDrawdown), "negative"],
    ["日期跨度（自然日）", `${fmt(stats.span, 0)} 天`],
    ["所选窗口观测点", `${stats.selected.length} 点`],
  ]);
  const sourceLabel = historicalOnly(line) ? " · 最后保留历史，非当前业绩" : "";
  const signalLabel =
    $("chart-show-signal").checked &&
    !stats.selected.some((row) => row.signal_nav != null)
      ? " · 信号净值不可用"
      : "";
  const benchmarkLabel = !stats.selected.some(
    (row) => row.benchmark_nav != null,
  )
    ? " · 基准不可用"
    : "";
  const containsReconstruction=(line.source?.segments || []).some(s => s.kind === "reconstructed" &&
    stats.selected.some(row => QountMetrics.timestamp(row.date)>=QountMetrics.timestamp(s.start) && QountMetrics.timestamp(row.date)<=QountMetrics.timestamp(s.end)));
  setText(
    "chart-range",
    `${range} · ${stats.selected.length} 个观测点${sourceLabel}${signalLabel}${benchmarkLabel}`,
  );
  setText(
    "detail-window-note",
    `${stats.selected.length === 1 ? (QountResearch.forward(line) && line.nav_series.length === 1 ? "仅有初始化观测，尚无可计算的收益区间。" : "窗口仅一个观测点，无法计算区间收益。") : ""}${containsReconstruction ? "所选窗口含历史补算，不能当作独立前向业绩。" : ""}窗口 ${range}。收益为首末观测比值；不足一年或不足 20 个观测点不年化，CTA-R 代理记录不年化。交易日数仅在全样本来源明确提供时展示。`,
  );
  const full =
    chartStart === 0 && chartEnd === (line.nav_series || []).length - 1;
  const gap =
    full &&
    line.metrics?.signal_nav != null &&
    line.metrics?.executable_nav != null
      ? (line.metrics.signal_nav - line.metrics.executable_nav) * 100
      : stats.executionGap;
  setText(
    "detail-execution-gap",
    `信号与模拟执行${full ? "相对初始资金" : "窗口"}收益差：${gap == null ? "来源不足，无法计算" : `${fmt(gap)} 个百分点（信号减执行）`}。${line.metrics?.cumulative_cost == null ? "累计成本来源未提供。" : `全样本累计成本 ${fmt(line.metrics.cumulative_cost)}（源单位，币种须核对来源）。`}差值仅作描述，未根据净值差直接归因。`,
  );
}
function changeChartRange() {
  if (!currentLineDetail) return;
  const rows = currentLineDetail.nav_series || [];
  chartStart = QountMetrics.rangeStart(rows, $("chart-time-range").value);
  chartEnd = rows.length - 1;
  renderNavChart();
  updateWindowMetrics();
}
function rerenderCurrentChart() {
  if (currentLineDetail) {
    renderNavChart();
    updateWindowMetrics();
  }
}
function renderNavChart() {
  const line = currentLineDetail;
  const rows = line.nav_series || [];
  chartRowCount = rows.length;
  const dom = $("echarts-container");
  if (!rows.length) {
    chartInstance?.dispose();
    chartInstance = null;
    dom.replaceChildren();
    dom.textContent = "无可复核净值观测";
    return;
  }
  if (!chartInstance) {
    dom.replaceChildren();
    chartInstance = echarts.init(dom, null, { renderer: "canvas" });
  }
  const checked = (id) => $(id).checked;
  const makeSeries = (name, key, color, fill) => ({
    name,
    type: "line",
    data: rows.map((row) => row[key]),
    smooth: 0.3,
    showSymbol: rows.length === 1,
    connectNulls: false,
    markArea: fill ? {silent:true,itemStyle:{color:"rgba(255,217,61,.22)"},label:{show:true,formatter:"历史补算",color:"#796000"},
      data:(line.source?.segments || []).filter(s=>s.kind==="reconstructed").map(s=>[{xAxis:s.start},{xAxis:s.end}])} : undefined,
    lineStyle: { width: 2.5, color },
    itemStyle: { color },
    symbolSize: 6,
    emphasis: { focus: "series" },
    areaStyle: fill
      ? {
          color: {
            type: "linear",
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: "rgba(107,203,119,0.22)" },
              { offset: 1, color: "rgba(107,203,119,0)" },
            ],
          },
        }
      : undefined,
    markLine: fill
      ? {
          silent: true,
          symbol: "none",
          data: [{ yAxis: 1 }],
          lineStyle: { color: "#bbbbbb", type: "dashed", width: 1 },
          label: { formatter: "初始 1.0", color: "#999999", fontWeight: 700 },
        }
      : undefined,
  });
  const series = [];
  if (checked("chart-show-executable"))
    series.push(makeSeries("模拟执行净值", "nav", "#6bcb77", true));
  if (
    checked("chart-show-signal") &&
    rows.some((row) => row.signal_nav != null)
  )
    series.push(makeSeries("信号净值", "signal_nav", "#4d96ff"));
  if (
    checked("chart-show-benchmark") &&
    rows.some((row) => row.benchmark_nav != null)
  )
    series.push(makeSeries("基准净值", "benchmark_nav", "#666666"));
  if (checked("chart-show-drawdown"))
    series.push({
      name: "回撤（完整历史峰值，%）",
      type: "line",
      data: QountMetrics.drawdowns(rows),
      yAxisIndex: 1,
      smooth: 0.3,
      showSymbol: false,
      emphasis: { focus: "series" },
      lineStyle: { color: "#ff6b6b", width: 1.8 },
      markPoint: {
        symbol: "pin",
        symbolSize: 36,
        itemStyle: { color: "#ff6b6b", borderColor: "#2d2d2d", borderWidth: 1.5 },
        label: {
          color: "#ffffff",
          fontWeight: 800,
          fontSize: 10,
          formatter: (p) => `${Math.round(Number(p.value))}%`,
        },
        data: [{ type: "min", name: "最大回撤" }],
      },
    });
  chartInstance.setOption({
    backgroundColor: "#ffffff",
    animation: !reduceMotion(),
    animationDuration: 600,
    animationDurationUpdate: 320,
    animationEasingUpdate: "cubicOut",
    tooltip: {
      trigger: "axis",
      confine: true,
      backgroundColor: "rgba(255,255,255,0.96)",
      borderColor: "#2d2d2d",
      borderWidth: 2,
      textStyle: { color: "#1a1a1a", fontSize: 13, fontWeight: 600 },
      axisPointer: {
        type: "cross",
        snap: true,
        lineStyle: { color: "#9b59b6", width: 1.5, type: "dashed" },
        crossStyle: { color: "#9b59b6", width: 1, type: "dashed" },
        label: { backgroundColor: "#2d2d2d", fontWeight: 700 },
      },
      formatter: (params) => {
        if (!params || !params.length) return "";
        const head = `<b>${formatDate(params[0].axisValue)}</b>`;
        const body = params
          .map(
            (p) =>
              `<div style="display:flex;align-items:center;gap:6px;margin-top:4px">${p.marker}<span>${p.seriesName}</span><b style="margin-left:auto;font-family:var(--font-mono)">${p.value == null ? "未提供" : fmt(p.value, 4)}</b></div>`,
          )
          .join("");
        return `<div style="min-width:190px">${head}${body}</div>`;
      },
    },
    legend: { top: 0, type: "scroll", selectedMode: false, textStyle: { color: "#666666", fontWeight: 700 } },
    grid: { left: 8, right: 8, top: 45, bottom: 60, containLabel: true },
    xAxis: {
      type: "category",
      data: rows.map((row) => row.date),
      axisLabel: {
        color: "#666666",
        fontWeight: 600,
        hideOverlap: true,
        formatter: (value) => formatDate(value),
      },
      axisLine: { lineStyle: { color: "#2d2d2d", width: 2 } },
    },
    yAxis: [
      {
        type: "value",
        scale: true,
        axisLabel: { color: "#666666", fontWeight: 600 },
        splitLine: { lineStyle: { color: "#eee", type: "dashed" } },
      },
      {
        type: "value",
        show: checked("chart-show-drawdown"),
        axisLabel: { formatter: "{value}%", color: "#ff6b6b", fontWeight: 600 },
        splitLine: { show: false },
      },
    ],
    dataZoom: [
      {
        type: "inside",
        startValue: chartStart,
        endValue: chartEnd,
        filterMode: "none",
      },
      {
        type: "slider",
        bottom: 8,
        height: 22,
        startValue: chartStart,
        endValue: chartEnd,
        filterMode: "none",
        borderColor: "#2d2d2d",
        borderWidth: 2,
        backgroundColor: "#f8f8f8",
        fillerColor: "rgba(77,150,255,0.15)",
        handleStyle: { color: "#4d96ff", borderColor: "#2d2d2d", borderWidth: 2 },
        textStyle: { color: "#666666", fontWeight: 600 },
      },
    ],
    series,
  }, true);
  if (chartInstance._zoomBound) return;
  chartInstance._zoomBound = true;
  chartInstance.on("datazoom", (event) => {
    const zoom = (event.batch || [event])[0];
    chartStart =
      zoom.startValue == null
        ? Math.round(((zoom.start || 0) / 100) * (chartRowCount - 1))
        : Number(zoom.startValue);
    chartEnd =
      zoom.endValue == null
        ? Math.round(((zoom.end ?? 100) / 100) * (chartRowCount - 1))
        : Number(zoom.endValue);
    chartStart = Math.max(0, Math.min(chartRowCount - 1, chartStart));
    chartEnd = Math.max(chartStart, Math.min(chartRowCount - 1, chartEnd));
    if (!$("chart-time-range").querySelector("[value=custom]")) {
      const option = document.createElement("option");
      option.value = "custom";
      option.textContent = "图表自选";
      $("chart-time-range").appendChild(option);
    }
    $("chart-time-range").value = "custom";
    updateWindowMetrics();
  });
}
async function loadLineCurrentPositions(line, version) {
  const lineId = line.line_id;
  tableMessage("detail-current-positions", 6, `${researchName(line)} 持仓读取中…`);
  setText(
    "detail-position-as-of",
    `${researchName(line)} · 来源截止 ${formatDate(line.as_of)}`,
  );
  if (line.position_status !== "KNOWN" || historicalOnly(line)) {
    tableMessage(
      "detail-current-positions",
      6,
      line.position_status === "NOT_APPLICABLE" ||
        ["ARCHIVED", "STOPPED"].includes(line.status)
        ? "该封存／停止线不适用当前持仓"
        : "持仓来源缺失或未知，不能确认当前仓位",
    );
    return;
  }
  try {
    const snapshot = QountResearch.positionSnapshot(
      await readJSON(
        `/research/positions/current?line_id=${encodeURIComponent(lineId)}`,
      ),
    );
    if (version !== detailRequestVersion || currentLineId !== lineId) return;
    setText(
      "detail-position-as-of",
      `${researchName(line)} · ${line.sample_kind === "historical" ? "历史快照" : "最新快照"} ${ledgerDate(snapshot.as_of || snapshot.positions[0]?.date)}`,
    );
    renderHoldingRows("detail-current-positions", snapshot, line);
  } catch (error) {
    if (version !== detailRequestVersion || currentLineId !== lineId) return;
    tableMessage("detail-current-positions", 6, `${researchName(line)} 持仓读取失败`);
    setText("detail-position-as-of", `${researchName(line)} · 快照读取失败`);
  }
}
function renderHoldingRows(id, snapshot, line) {
  const rows = snapshot.positions;
  const current = rows.filter(
    (row) =>
      row.action !== "CLOSE" &&
      (row.quantity == null || Number(row.quantity) > 1e-12),
  );
  if (!current.length) {
    tableMessage(
      id,
      6,
      snapshot.confirmed ? "来源快照确认空仓" : "尚无可复核持仓快照",
    );
    return;
  }
  $(id).innerHTML = current
    .map(
      (row) =>
        `<tr><td>${escapeHtml(row.symbol)}</td><td class="numeric" title="原值 ${escapeHtml(row.quantity)}">${fmt(row.quantity, 4)}${line.line_id === "personal_assistant" ? "<small> 模型份额</small>" : ""}</td><td class="numeric">${row.weight == null ? "权重未知" : pct(row.weight * 100)}</td><td class="numeric" title="${escapeHtml(row.price)}">${fmt(row.price, 4)}</td><td class="numeric" title="${escapeHtml(row.market_value)}">${fmt(row.market_value)}</td><td title="${escapeHtml(row.action)}">${escapeHtml(statusText(row.action))}</td></tr>`,
    )
    .join("");
}

function openCurrentLedger() {
  if (!currentLineDetail) return;
  const stats = selectedStats();
  $("positions-line-select").value = currentLineDetail.line_id;
  $("ledger-start").value =
    formatDate(stats.selected[0]?.date) === "--"
      ? ""
      : formatDate(stats.selected[0].date);
  $("ledger-end").value =
    formatDate(stats.selected.at(-1)?.date) === "--"
      ? ""
      : formatDate(stats.selected.at(-1).date);
  switchTab("positions");
  loadPaperPositions();
  window.scrollTo({ top: 0 });
}
function clearLedgerRange() {
  $("ledger-start").value = "";
  $("ledger-end").value = "";
  loadPaperPositions();
}
async function loadPaperPositions() {
  const id = $("positions-line-select").value;
  if (!id) return;
  const version = ++positionRequestVersion;
  const line = paperLines.get(id) || {
    line_id: id,
    position_status: "UNKNOWN",
  };
  const start = $("ledger-start").value;
  const end = $("ledger-end").value;
  const selectedRun = QountResearch.experimentRunId(currentLineDetail?.line_id === id ? currentLineDetail : line);
  [
    "paper-current-positions-body",
    "paper-trades-body",
    "paper-actions-body",
  ].forEach((body, i) =>
    tableMessage(body, [6, 7, 4][i], `${researchName(line) || id} 读取中…`),
  );
  setText("positions-as-of", `${researchName(line) || id} · 快照读取中…`);
  setText("trade-count", "读取中…");
  setText("action-count", "读取中…");
  setText(
    "ledger-context",
    `${researchName(line) || id}${selectedRun ? " · 实验 " + selectedRun.slice(0, 12) : ""} · ${start || "最早"} 至 ${end || "最新"}`,
  );
  if (start && end && start > end) {
    tableMessage("paper-trades-body", 7, "开始日期不能晚于结束日期");
    tableMessage("paper-actions-body", 4, "日期范围无效");
    tableMessage("paper-current-positions-body", 6, "请修正日期范围");
    return;
  }
  const query = new URLSearchParams({ line_id: id, limit: "1000" });
  if (start) query.set("start", start);
  if (end) query.set("end", end);
  if (selectedRun) query.set("run_id", selectedRun);
  const [positions, trades] = await Promise.allSettled([
    readJSON(`/research/positions/current?line_id=${encodeURIComponent(id)}`).then(
      QountResearch.positionSnapshot,
    ),
    readJSON(`/research/trades?${query}`),
  ]);
  if (
    version !== positionRequestVersion ||
    $("positions-line-select").value !== id
  )
    return;
  if (historicalOnly(line) || line.position_status !== "KNOWN") {
    tableMessage(
      "paper-current-positions-body",
      6,
      "当前持仓来源缺失／不适用，不能把历史快照视为当前仓位",
    );
    setText("positions-as-of", `${researchName(line) || id} · 当前快照不适用／未知`);
  } else if (positions.status === "rejected") {
    tableMessage("paper-current-positions-body", 6, "持仓快照读取失败");
    setText("positions-as-of", `${researchName(line) || id} · 快照读取失败`);
  } else {
    renderHoldingRows("paper-current-positions-body", positions.value, line);
    setText(
      "positions-as-of",
      `${researchName(line) || id} · ${line.sample_kind === "historical" ? "历史快照" : "最新快照"} ${ledgerDate(positions.value.as_of || positions.value.positions[0]?.date)}`,
    );
  }
  if (trades.status === "rejected") {
    tableMessage("paper-trades-body", 7, "流水读取失败");
    tableMessage("paper-actions-body", 4, "公司行动读取失败");
    setText("trade-count", "读取失败");
    setText("action-count", "读取失败");
    return;
  }
  const actions = trades.value.filter((row) => ["SPLIT","DIVIDEND_ACCRUAL","DIVIDEND_PAYMENT"].includes(row.side));
  const fills = trades.value.filter((row) => ["BUY","SELL"].includes(row.side));
  setText(
    "trade-count",
    `${fills.length} 笔买卖／调仓${trades.value.length >= 1000 ? " · 已达 1000 条上限" : ""}`,
  );
  setText("action-count", `${actions.length} 次公司行动`);
  if (!fills.length)
    tableMessage("paper-trades-body", 7, "该窗口暂无可复核买卖／调仓记录");
  else
    $("paper-trades-body").innerHTML = fills
      .map(
        (row) =>
          `<tr><td class="date">${escapeHtml(ledgerDate(row.date))}</td><td>${escapeHtml(row.symbol)}</td><td title="${escapeHtml(row.side)}">${escapeHtml(statusText(row.side))}</td><td class="numeric">${fmt(row.quantity, 4)}${id === "personal_assistant" ? "<small> 模型份额</small>" : ""}</td><td class="numeric">${fmt(row.price, 4)}</td><td class="numeric">${row.cost == null ? "来源未提供" : fmt(row.cost)}</td><td><details><summary>调仓原因</summary><p>${escapeHtml(sourceReason(row.note))}</p></details></td></tr>`,
      )
      .join("");
  if (!actions.length)
    tableMessage("paper-actions-body", 4, "该窗口暂无公司行动记录");
  else
    $("paper-actions-body").innerHTML = actions
      .map((row) => {
        if (row.side !== "SPLIT") {
          const amount = row.quantity != null && row.price != null ? fmt(row.quantity * row.price, 6) : "来源未提供";
          return `<tr><td class="date">${escapeHtml(ledgerDate(row.date))}</td><td>${escapeHtml(row.symbol)}</td><td>${escapeHtml(statusText(row.side))}</td><td>${amount} USD_EQ<details><summary>来源说明</summary><p>${escapeHtml(row.note || "来源未提供")}</p></details></td></tr>`;
        }
        const ratio =
          String(row.note || "").match(/split_ratio=([\d.]+)/)?.[1] ||
          String(row.note || "").match(/1\s*[:：]\s*([\d.]+)\s*拆分/)?.[1];
        return `<tr><td class="date">${escapeHtml(ledgerDate(row.date))}</td><td>${escapeHtml(row.symbol)}</td><td>份额拆分</td><td>${ratio ? `1 : ${escapeHtml(ratio)}` : "比例来源未提供"}<details><summary>来源说明</summary><p>${escapeHtml(row.note || "来源未提供")}</p></details></td></tr>`;
      })
      .join("");
}
function sourceReason(note) {
  const text = String(note || "");
  if (
    !text ||
    /^(simulated_not_realized|source paper rebalance event|split_ratio=)/.test(
      text,
    )
  )
    return "来源未提供";
  return text;
}

async function fetchLivePerformance() {
  const version=++performanceRequestVersion;
  const days=$("performance-days")?.value || "30";
  try {
    const data=await readJSON(`/account/performance?days=${encodeURIComponent(days)}`);
    if(version!==performanceRequestVersion)return;
    performanceData=data;
  } catch(_) {
    if(version!==performanceRequestVersion)return;
    performanceData=null;
  }
  renderLivePerformance();
}
function renderLivePerformance() {
  const data=window.QountLive?.performanceView(performanceData);
  const summary=data?.summary;
  setText("performance-return",pct(summary?.return_pct));
  setText("performance-pnl",fmt(summary?.net_pnl_usdt,4));
  setText("performance-flow",fmt(summary?.net_external_flow_usdt,4));
  setText("performance-drawdown",summary?.max_drawdown_pct == null ? "--" : `${fmt(summary.max_drawdown_pct)}%`);
  setText("performance-status",!data ? "收益待核算" : data.stale ? "历史观测已过期" : data.status==="PARTIAL" ? "部分区间可核算" : "资金流已核对");
  setText("performance-window",summary ? `${formatTime(summary.start)} 至 ${formatTime(summary.end)}` : "从可核对的真实观测开始");
  setText("performance-note",data ? `${data.observation_count}次观测，${data.segment_count}个连续区间。各段从零独立起算，卡片显示最近连续区间。${summary?.includes_latest_observation===false ? "最新观测尚未核对，以上为较早区间。" : ""}${data.stale ? "采集已过期。" : ""}` : "权益观测或资金流水尚不足以核算收益；不使用余额涨幅或回测替代。");
  const reasons={income_coverage_missing:"资金流水覆盖不足",wallet_income_mismatch:"钱包变化与流水未对齐",
    observation_gap:"观测间隔过长",income_during_observation:"采集期间发生资金变动",unsupported_income_type:"存在未支持的流水类型",
    return_capital_unavailable:"收益本金口径不可用",usdm_observation_unavailable:"合约权益观测不可用"};
  const counts={};
  for(const gap of performanceData?.gaps || [])counts[gap.reason]=(counts[gap.reason]||0)+1;
  setText("performance-gaps",Object.entries(counts).map(([reason,count])=>`${reasons[reason] || "待核对"}：${count}个区间`).join("；") || (data ? "所示区间未发现资金流水缺口。" : "等待完整观测与流水覆盖。"));
  const ready=!!data && !!window.echarts;
  $("performance-empty")?.classList.toggle("hidden",ready);
  setText("performance-empty",data ? "图表暂不可用" : "真实收益历史待核算");
  if(!ready){performanceChartInstance?.clear();return;}
  const measure=$("performance-measure")?.value || "return_pct";
  const suffix=measure==="return_pct" ? "%" : " USDT";
  const rows=[];
  let segment=null;
  for(const point of data.points) {
    const time=Date.parse(point.observed_at);
    if(segment!=null && segment!==point.segment_id)rows.push([time-1,null]);
    rows.push([time,point[measure]]);segment=point.segment_id;
  }
  if(!performanceChartInstance)performanceChartInstance=echarts.init($("performance-chart"));
  performanceChartInstance.setOption({
    animation:!reduceMotion(),
    tooltip:{trigger:"axis",confine:true,valueFormatter:value=>value==null?"缺口":`${fmt(value,4)}${suffix}`},
    grid:{left:12,right:20,top:20,bottom:55,containLabel:true},
    xAxis:{type:"time",axisLabel:{hideOverlap:true}},
    yAxis:{type:"value",scale:true,axisLabel:{formatter:value=>`${value}${suffix}`},splitLine:{lineStyle:{type:"dashed",color:"#ddd"}}},
    dataZoom:[{type:"inside"},{type:"slider",height:20,bottom:8}],
    series:[{name:measure==="return_pct"?"资金流调整收益":"资金流调整净损益",type:"line",smooth:false,
      connectNulls:false,showSymbol:false,lineStyle:{color:"#237b62",width:3},data:rows}]
  },true);
}
async function loadResearchRuns(line, version) {
  try {
    const data=await readJSON(`/research/lines/${encodeURIComponent(line.line_id)}/runs`);
    if(version!==detailRequestVersion || currentLineId!==line.line_id)return;
    researchRuns=data.runs || [];
    const options=researchRuns.map(run=>{
      const id=run.run_id, label=`${run.parameters?.scenario || "实验"} · ${id.slice(0,8)} · ${pct(run.total_return_pct)}`;
      return `<option value="${escapeHtml(id)}">${escapeHtml(label)}</option>`;
    }).join("");
    $("research-run-select").innerHTML=options;
    $("research-run-select").value=line.run_id;
    $("research-compare-select").innerHTML='<option value="">不添加</option>'+options;
    $("research-run-controls").classList.toggle("hidden",!options);
    setText("research-run-note",`正在查看实验 ${line.run_id.slice(0,12)}；更换实验不改变默认配置或实盘规则。`);
  } catch(_) {
    if(version===detailRequestVersion)$("research-run-controls")?.classList.add("hidden");
  }
}
async function compareResearchRun() {
  const reference=$("research-compare-select").value;
  const line=currentLineDetail;
  if(!line)return;
  const version=++researchComparisonVersion;
  if(!reference) {
    line.nav_series=line.nav_series.map(row=>({...row,benchmark_nav:researchSourceBenchmark.get(row.date) ?? null}));
    setText("research-run-note",`正在查看实验 ${line.run_id.slice(0,12)}；已恢复来源基准。`);
    rerenderCurrentChart();return;
  }
  try {
    const data=await readJSON(`/research/lines/${encodeURIComponent(line.line_id)}?run_id=${encodeURIComponent(reference)}`);
    if(version!==researchComparisonVersion || currentLineDetail!==line)return;
    const lookup=new Map(data.nav_series.map(row=>[row.date,row.nav]));
    line.nav_series=line.nav_series.map(row=>({...row,benchmark_nav:lookup.get(row.date) ?? null}));
    $("chart-show-benchmark").checked=true;
    setText("research-run-note",`实验 ${line.run_id.slice(0,12)} 对照 ${reference.slice(0,12)}；基准曲线为所选实验，只比较重合观测窗口。`);
    rerenderCurrentChart();
  } catch(_) {
    if(version===researchComparisonVersion)setText("research-run-note","对照实验读取失败，当前曲线保持原结果。");
  }
}
