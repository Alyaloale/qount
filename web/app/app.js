/* Native, read-only presentation of source-backed account and research data. */
let activeTab = "account";
let chartInstance = null;
let currentLineDetail = null;
let currentLineId = null;
let detailRequestVersion = 0;
let positionRequestVersion = 0;
let paperLines = new Map();
let chartStart = 0;
let chartEnd = 0;
let liveObservedAt = null;
let liveReadAt = null;
let liveAttemptAt = null;
let liveIntervalMs = 300000;
let liveFetchPending = false;
let refreshPending = false;
let accountSafety = null;
let liveReadOnly = null;
const API_BASE = "";
const $ = (id) => document.getElementById(id);
const setText = (id, text) => {
  if ($(id)) $(id).textContent = text;
};
const escapeHtml = (value) =>
  String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
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
    : `${Number(value) > 0 ? "+" : ""}${fmt(value)}%`;
const signClass = (value) =>
  value == null ? "" : value > 0 ? "positive" : value < 0 ? "negative" : "";
const formatDate = (value) => {
  const text = String(value || "");
  return /^\d{8}$/.test(text)
    ? `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6)}`
    : text.slice(0, 10) || "--";
};
function formatTime(value) {
  const timestamp = QountMetrics.timestamp(value);
  return Number.isFinite(timestamp)
    ? `${new Date(timestamp).toISOString().replace("T", " ").slice(0, 19)} UTC`
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
      long: "多头",
      short: "空头",
      unknown: "未知",
      simulated_not_realized: "模拟记录",
      ACTIVE_PAPER: "研究模拟",
      ARCHIVED: "封存",
      STOPPED: "停止",
      FRESH: "来源时点正常",
      STALE: "来源待更新",
      MISSING: "来源缺失",
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
  if (line.line_id === "personal_assistant") return "历史回放·参数已冻结";
  if (line.line_id === "universal_regime") return "前向记录·参数已冻结";
  if (line.line_id === "cta_r") return "早期前向记录";
  if (line.line_id.startsWith("dual_")) return "历史回放＋前向模拟";
  return "研究模拟（样本属性待核）";
}
function nextQuestion(line) {
  if (["ARCHIVED", "STOPPED"].includes(line.status))
    return "保留失败结论与资料；不根据旧指标推定策略已获准恢复。";
  if (line.line_id === "personal_assistant")
    return "待验证：相对同标的买入持有，MA120 Band 1.5% 择时机制在净收益、回撤与暴露上提供了什么价值？参数已冻结，前向记录累积中。";
  if (line.line_id === "universal_regime")
    return "待验证：v1.3 冻结参数（Calmar 1.02 基准）在未见数据上的前向表现能否复现回测指标？短样本期间不报告年化。";
  if (line.line_id === "cta_r")
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
  const research =
    accountSafety?.research_only === true ? "研究模拟" : "研究权限待核";
  const orders =
    accountSafety?.orders_authorized === false ? "未授权下单" : "下单权限待核";
  const live = liveReadOnly === true ? "真实账户只读" : "真实账户权限待核";
  setText("permission-status", `${live} · ${research} · ${orders}`);
  setText("footer-permission", `${live} · ${research} · ${orders}`);
  setText("topbar-permission", `${live} · ${research} · ${orders}`);
  setText("account-mode-badge", "真实账户与回放分别展示");
  setText("live-mode-badge", liveReadOnly === true ? "只读" : "权限待核");
}

document.addEventListener("DOMContentLoaded", () => {
  initApp();
  setInterval(updateObservationAge, 1000);
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
window.addEventListener("resize", () => chartInstance?.resize());
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) {
    updateObservationAge();
    if (!liveAttemptAt || Date.now() - liveAttemptAt >= liveIntervalMs) {
      fetchLiveAccountData();
      fetchDailyReport();
    }
  }
});
async function initApp() {
  await Promise.allSettled([
    fetchAccountData(),
    fetchLiveAccountData(),
    fetchPaperLines(),
    fetchDailyReport(),
  ]);
  setText(
    "header-as-of",
    `读取 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`,
  );
}
const TAB_TITLES = {
  account: "今日助手与账户",
  paper: "研究对比",
  positions: "持仓流水",
};
function switchTab(name) {
  activeTab = name;
  document
    .querySelectorAll(".nav-item")
    .forEach((button) =>
      button.classList.toggle("active", button.id === `tab-${name}`),
    );
  document
    .querySelectorAll(".screen-view")
    .forEach((view) =>
      view.classList.toggle("active", view.id === `screen-${name}`),
    );
  const topbarTitle = document.getElementById("topbar-title");
  if (topbarTitle && TAB_TITLES[name]) topbarTitle.textContent = TAB_TITLES[name];
  if (name === "paper") requestAnimationFrame(() => chartInstance?.resize());
}
async function refreshData() {
  if (refreshPending) return;
  refreshPending = true;
  $("btn-refresh").disabled = true;
  setText("btn-refresh", "读取中…");
  try {
    await initApp();
    if (currentLineId) await showLineDetail(currentLineId, false, true);
  } finally {
    refreshPending = false;
    $("btn-refresh").disabled = false;
    setText("btn-refresh", "↻ 刷新读取");
  }
}
async function fetchAccountData() {
  try {
    renderAccount(await readJSON("/account"));
  } catch (error) {
    [
      "acc-nav",
      "acc-cash",
      "acc-position-count",
      "acc-as-of",
      "acc-initial",
    ].forEach((id) => setText(id, "--"));
    tableMessage("account-positions-body", 4, "历史回放读取失败");
    showError("acc-error", "历史回放读取失败，请刷新重试");
    accountSafety = null;
    renderPermissions();
  }
}
function renderAccount(data) {
  accountSafety = data.safety;
  renderPermissions();
  setText(
    "acc-nav",
    data.error ? "--" : `${data.currency === "CNY" ? "¥" : ""}${fmt(data.nav)}`,
  );
  setText(
    "acc-cash",
    data.error || data.cash == null ? "来源未提供" : fmt(data.cash),
  );
  setText("acc-currency", data.currency || "--");
  setText(
    "acc-initial",
    data.error || data.initial_equity == null
      ? "初始模拟资金：来源未提供"
      : `初始模拟资金 ${data.currency === "CNY" ? "¥" : ""}${fmt(data.initial_equity)}`,
  );
  setText("acc-as-of", data.error ? "--" : formatDate(data.as_of));
  setText(
    "acc-position-count",
    data.error || data.positions_status !== "KNOWN"
      ? "持仓未确认"
      : `${data.positions.length} 项`,
  );
  setText("acc-freshness-status", "历史回放截止日，不代表今日状态");
  showError(
    "acc-error",
    data.error ? `回放来源不可用：${data.error.split(":")[0]}` : "",
  );
  setText("acc-source-path", data.source?.path || "--");
  setText("acc-source-sha256", data.source?.sha256 || "来源未提供");
  setText("acc-source-produced", formatTime(data.source?.produced_at));
  if (data.error || data.positions_status !== "KNOWN") {
    tableMessage("account-positions-body", 4, "回放持仓来源不足，无法确认");
    return;
  }
  if (!data.positions.length) {
    tableMessage("account-positions-body", 4, "账本确认回放期末空仓");
    return;
  }
  $("account-positions-body").innerHTML = data.positions
    .map(
      (pos) =>
        `<tr><td>${escapeHtml(pos.symbol)}</td><td class="numeric" title="来源模型份额">${fmt(pos.quantity, 4)}</td><td class="numeric">${pos.weight == null ? "权重未知" : pct(pos.weight * 100)}</td><td class="date">${escapeHtml(formatDate(pos.entry_date))}</td></tr>`,
    )
    .join("");
}
async function fetchLiveAccountData() {
  if (liveFetchPending) return;
  liveFetchPending = true;
  liveAttemptAt = Date.now();
  try {
    const data = await readJSON("/account/live");
    liveReadAt = Date.now();
    setText(
      "live-read-at",
      `页面读取 ${formatTime(new Date(liveReadAt).toISOString())}`,
    );
    liveReadOnly = data.read_only;
    renderPermissions();
    liveIntervalMs = Math.max(
      60000,
      (data.observation_interval_seconds || 300) * 1000,
    );
    if (data.error) throw new Error(`读数不可用：${data.error.split(":")[0]}`);
    liveObservedAt = data.as_of;
    setText("live-as-of", `账户观测 ${formatTime(data.as_of)}`);
    setText("live-source-path", data.source?.path || "--");
    setText("live-nav", fmt(data.nav));
    setText("live-cash", fmt(data.cash));
    setText("live-currency", data.currency || "--");
    setText(
      "live-positions-note",
      `${data.positions.length} 项持仓 · ${data.currency}`,
    );
    showError("live-error", "");
    updateObservationAge();
    if (!data.positions.length)
      tableMessage("live-positions-body", 4, "该次观测确认无持仓");
    else
      $("live-positions-body").innerHTML = data.positions
        .map(
          (pos) =>
            `<tr><td>${escapeHtml(pos.symbol)}</td><td>${escapeHtml(statusText(pos.side))}</td><td class="numeric" title="${escapeHtml(pos.quantity)}">${fmt(pos.quantity, 4)}</td><td class="numeric">${fmt(pos.market_value)}</td></tr>`,
        )
        .join("");
  } catch (error) {
    setText("live-nav", "--");
    setText("live-cash", "--");
    setText("live-positions-note", "持仓未确认");
    tableMessage(
      "live-positions-body",
      4,
      "真实账户读数读取失败，无法确认当前持仓",
    );
    showError(
      "live-error",
      `真实账户读数获取失败：${error.message || "读取失败"}。页面读取成功不代表账户重新观测。`,
    );
    // Keep the last observation's clock running, never replace its time with this request's time.
    updateObservationAge();
  } finally {
    liveFetchPending = false;
  }
}
function updateObservationAge() {
  const age = QountMetrics.age(liveObservedAt);
  setText(
    "live-age",
    `${liveObservedAt ? "最近成功观测：" : ""}${age.text}${age.stale && liveObservedAt ? " · 超过两个采集周期，待更新" : ""}`,
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
    const lines = await readJSON("/paper/lines");
    const rank = (line) =>
      line.line_id === "personal_assistant"
        ? 0
        : line.line_id === "universal_regime"
          ? 1
          : line.line_id.startsWith("dual_")
            ? 2
            : line.line_id === "cta_r"
              ? 3
              : 4;
    lines.sort(
      (a, b) => rank(a) - rank(b) || a.line_id.localeCompare(b.line_id),
    );
    paperLines = new Map(lines.map((line) => [line.line_id, line]));
    renderPaperLines(lines);
    await populatePositionLineSelect(lines);
  } catch (error) {
    setText("paper-lines-body", "研究线列表读取失败，请刷新重试");
    setText("paper-lines-count", "列表读取失败");
  }
}
function sourceReturn(metrics) {
  if (metrics?.cagr_pct != null) return ["来源年化收益", metrics.cagr_pct];
  if (metrics?.ytd_return_pct != null)
    return ["年初至今收益", metrics.ytd_return_pct];
  if (metrics?.total_return_pct != null)
    return ["来源累计收益", metrics.total_return_pct];
  if (metrics?.executable_nav != null)
    return ["相对初始资金收益", (metrics.executable_nav - 1) * 100];
  return ["收益", null];
}
function renderPaperLines(lines) {
  const archived = lines.filter((line) =>
    ["ARCHIVED", "STOPPED"].includes(line.status),
  );
  const active = lines.filter((line) => !archived.includes(line));
  setText(
    "paper-lines-count",
    `共 ${lines.length} 条 · 持续研究 ${active.length} · 封存／停止 ${archived.length}`,
  );
  setText(
    "archived-count",
    `封存／停止线 ${archived.length} 条 · 保留结论与详情`,
  );
  function card(line) {
    const m = line.metrics || {};
    const unavailable = historicalOnly(line);
    const [returnLabel, returnValue] = sourceReturn(m);
    const next = nextQuestion(line);
    const facts = unavailable
      ? '<p class="fresh-stale">当前绩效不可确认；历史资料在详情中单独保留。</p>'
      : `<dl class="research-facts"><div><dt>${returnLabel}${m.cagr_basis ? `（${escapeHtml(m.cagr_basis === "252 trading days" ? "252交易日" : m.cagr_basis)}）` : ""}</dt><dd class="${signClass(returnValue)}">${pct(returnValue)}</dd></div><div><dt>来源最大回撤</dt><dd class="negative">${pct(m.max_drawdown_pct == null ? null : -Math.abs(m.max_drawdown_pct))}</dd></div><div><dt>当前回撤</dt><dd class="negative">${pct(m.current_drawdown_pct == null ? null : -Math.abs(m.current_drawdown_pct))}</dd></div>${m.benchmark_cagr_pct == null ? "" : `<div><dt>同标的基准年化（252交易日）</dt><dd>${pct(m.benchmark_cagr_pct)}</dd></div>`}</dl>`;
    return `<article class="research-card ${line.line_id === "personal_assistant" ? "primary-line" : ""}" data-line-id="${escapeHtml(line.line_id)}"><div class="card-header"><div><h3>${escapeHtml(line.name)}</h3><span class="research-id">${escapeHtml(line.line_id)}</span></div><span class="status-badge">${escapeHtml(identity(line))}</span></div><p class="header-note">完整样本 ${formatDate(m.start_date)} 至 ${formatDate(line.as_of)} · ${escapeHtml(statusText(line.freshness))}${line.data_status !== "AVAILABLE" ? " · 数据不可用" : ""}</p>${facts}<p>${escapeHtml(line.adjudication || "来源未提供裁决")}</p><p class="header-note">${escapeHtml(costsText(line))}</p><details><summary class="header-note">下一项问题与样本说明</summary><p class="header-note">${escapeHtml(next)} ${m.observation_count == null ? "" : `来源观测 ${m.observation_count} 点。`}</p></details><button class="btn-action" data-open-line="${escapeHtml(line.line_id)}">查看研究详情</button></article>`;
  }
  $("paper-lines-body").innerHTML =
    active.map(card).join("") || "<p>暂无持续研究线</p>";
  $("archived-lines-body").innerHTML =
    archived.map(card).join("") || "<p>暂无封存线</p>";
  document
    .querySelectorAll("[data-open-line]")
    .forEach((button) =>
      button.addEventListener("click", () =>
        showLineDetail(button.dataset.openLine),
      ),
    );
}
function populatePositionLineSelect(lines) {
  const select = $("positions-line-select");
  const previous = select.value;
  select.replaceChildren(
    ...lines.map((line) => {
      const option = document.createElement("option");
      option.value = line.line_id;
      option.textContent = line.name;
      return option;
    }),
  );
  if (lines.some((line) => line.line_id === previous)) select.value = previous;
  else if (paperLines.has("personal_assistant"))
    select.value = "personal_assistant";
  if (select.value) return loadPaperPositions();
}
async function showLineDetail(lineId, scroll = true, preserveRange = false) {
  const previousRange = preserveRange ? $("chart-time-range").value : "all";
  const previousWindow =
    preserveRange && currentLineDetail ? selectedStats().selected : [];
  const requestVersion = ++detailRequestVersion;
  currentLineId = lineId;
  currentLineDetail = null;
  const panel = $("line-detail-panel");
  panel.classList.remove("hidden");
  panel.dataset.lineId = lineId;
  setText(
    "detail-title",
    `${paperLines.get(lineId)?.name || lineId} · 读取中…`,
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
  $("chart-time-range").value =
    previousRange === "custom" ? "all" : previousRange;
  if (scroll) panel.scrollIntoView({ behavior: "smooth", block: "start" });
  try {
    const data = await readJSON(`/paper/lines/${encodeURIComponent(lineId)}`);
    if (requestVersion !== detailRequestVersion || currentLineId !== lineId)
      return;
    currentLineDetail = data;
    renderLineDetail(data);
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
      `${paperLines.get(lineId)?.name || lineId} · 读取失败`,
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
  $("line-detail-panel").classList.add("hidden");
  currentLineId = null;
  currentLineDetail = null;
  detailRequestVersion++;
  chartInstance?.dispose();
  chartInstance = null;
}
function fullMetricItems(line) {
  const m = line.metrics || {};
  const [returnTitle, value] = sourceReturn(m);
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
  setText("detail-title", `${line.name} (${line.line_id})`);
  setText(
    "detail-identity",
    `${identity(line)} · 来源截止 ${formatDate(line.as_of)}`,
  );
  setText("detail-adjudication", line.adjudication || "来源未提供裁决");
  setText("detail-next-question", nextQuestion(line));
  setText("detail-source-path", line.source?.path || "--");
  setText("detail-source-sha256", line.source?.sha256 || "未核验／来源未提供");
  setText("detail-cost-coverage", costsText(line));
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
    currentLineDetail?.line_id !== "cta_r",
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
  setText("detail-metrics-title", `${line.name} · 所选窗口收益与风险`);
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
  setText(
    "chart-range",
    `${range} · ${stats.selected.length} 个观测点${sourceLabel}${signalLabel}${benchmarkLabel}`,
  );
  setText(
    "detail-window-note",
    `窗口 ${range}。收益为首末观测比值；不足一年或不足 20 个观测点不年化，CTA-R 早期记录不年化。交易日数仅在全样本来源明确提供时展示。`,
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
  const dom = $("echarts-container");
  chartInstance?.dispose();
  chartInstance = null;
  dom.replaceChildren();
  if (!rows.length) {
    dom.textContent = "无可复核净值观测";
    return;
  }
  chartInstance = echarts.init(dom, null, { renderer: "canvas" });
  const checked = (id) => $(id).checked;
  const makeSeries = (name, key, color) => ({
    name,
    type: "line",
    data: rows.map((row) => row[key]),
    smooth: false,
    showSymbol: rows.length === 1,
    connectNulls: false,
    lineStyle: { width: 1.8, color },
    itemStyle: { color },
  });
  const series = [];
  if (checked("chart-show-executable"))
    series.push(makeSeries("模拟执行净值", "nav", "#16803d"));
  if (
    checked("chart-show-signal") &&
    rows.some((row) => row.signal_nav != null)
  )
    series.push(makeSeries("信号净值", "signal_nav", "#7c3aed"));
  if (
    checked("chart-show-benchmark") &&
    rows.some((row) => row.benchmark_nav != null)
  )
    series.push(makeSeries("基准净值", "benchmark_nav", "#6b7280"));
  if (checked("chart-show-drawdown"))
    series.push({
      name: "回撤（完整历史峰值，%）",
      type: "line",
      data: QountMetrics.drawdowns(rows),
      yAxisIndex: 1,
      showSymbol: false,
      lineStyle: { color: "#be3a3a", width: 1.4 },
    });
  chartInstance.setOption({
    backgroundColor: "#ffffff",
    animation: false,
    tooltip: {
      trigger: "axis",
      confine: true,
      backgroundColor: "rgba(255,255,255,0.96)",
      borderColor: "#e2e5ea",
      textStyle: { color: "#1a1d23", fontSize: 12 },
      valueFormatter: (value) => (value == null ? "未提供" : fmt(value, 4)),
    },
    legend: { top: 0, textStyle: { color: "#6b7280" }, type: "scroll" },
    grid: { left: 8, right: 8, top: 45, bottom: 60, containLabel: true },
    xAxis: {
      type: "category",
      data: rows.map((row) => row.date),
      axisLabel: {
        color: "#6b7280",
        hideOverlap: true,
        formatter: (value) => formatDate(value),
      },
      axisLine: { lineStyle: { color: "#e2e5ea" } },
    },
    yAxis: [
      {
        type: "value",
        scale: true,
        axisLabel: { color: "#6b7280" },
        splitLine: { lineStyle: { color: "#f0f2f5" } },
      },
      {
        type: "value",
        show: checked("chart-show-drawdown"),
        axisLabel: { formatter: "{value}%", color: "#be3a3a" },
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
        borderColor: "#e2e5ea",
        backgroundColor: "#f8f9fb",
        fillerColor: "rgba(37,99,235,0.1)",
        handleStyle: { color: "#2563eb" },
        textStyle: { color: "#6b7280" },
      },
    ],
    series,
  });
  chartInstance.on("datazoom", (event) => {
    const zoom = (event.batch || [event])[0];
    chartStart =
      zoom.startValue == null
        ? Math.round(((zoom.start || 0) / 100) * (rows.length - 1))
        : Number(zoom.startValue);
    chartEnd =
      zoom.endValue == null
        ? Math.round(((zoom.end ?? 100) / 100) * (rows.length - 1))
        : Number(zoom.endValue);
    chartStart = Math.max(0, Math.min(rows.length - 1, chartStart));
    chartEnd = Math.max(chartStart, Math.min(rows.length - 1, chartEnd));
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
  tableMessage("detail-current-positions", 6, `${line.name} 持仓读取中…`);
  setText(
    "detail-position-as-of",
    `${line.name} · 来源截止 ${formatDate(line.as_of)}`,
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
    const rows = currentPositionRows(
      await readJSON(
        `/paper/positions/current?line_id=${encodeURIComponent(lineId)}`,
      ),
    );
    if (version !== detailRequestVersion || currentLineId !== lineId) return;
    setText(
      "detail-position-as-of",
      `${line.name} · 最新快照 ${rows[0] ? ledgerDate(rows[0].date) : formatDate(line.as_of)}`,
    );
    renderHoldingRows("detail-current-positions", rows, line);
  } catch (error) {
    if (version !== detailRequestVersion || currentLineId !== lineId) return;
    tableMessage("detail-current-positions", 6, `${line.name} 持仓读取失败`);
    setText("detail-position-as-of", `${line.name} · 快照读取失败`);
  }
}
function renderHoldingRows(id, rows, line) {
  const current = rows.filter(
    (row) =>
      row.action !== "CLOSE" &&
      (row.quantity == null || Number(row.quantity) > 1e-12),
  );
  if (!current.length) {
    tableMessage(
      id,
      6,
      rows.length ? "来源快照确认空仓" : "尚无可复核持仓快照",
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

function currentPositionRows(payload) {
  // Older test/preview APIs return an array; deployed APIs also bind validity to the read.
  if (Array.isArray(payload)) return payload;
  if (!payload || payload.status !== "KNOWN")
    throw new Error("当前快照资格不足");
  return payload.positions;
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
  [
    "paper-current-positions-body",
    "paper-trades-body",
    "paper-actions-body",
  ].forEach((body, i) =>
    tableMessage(body, [6, 7, 4][i], `${line.name || id} 读取中…`),
  );
  setText("positions-as-of", `${line.name || id} · 快照读取中…`);
  setText("trade-count", "读取中…");
  setText("action-count", "读取中…");
  setText(
    "ledger-context",
    `${line.name || id} · ${start || "最早"} 至 ${end || "最新"}`,
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
  const [positions, trades] = await Promise.allSettled([
    readJSON(`/paper/positions/current?line_id=${encodeURIComponent(id)}`).then(
      currentPositionRows,
    ),
    readJSON(`/paper/trades?${query}`),
  ]);
  if (
    version !== positionRequestVersion ||
    $("positions-line-select").value !== id
  )
    return;
  if (historicalOnly(line) || line.position_status !== "KNOWN")
    tableMessage(
      "paper-current-positions-body",
      6,
      "当前持仓来源缺失／不适用，不能把历史快照视为当前仓位",
    );
  else if (positions.status === "rejected")
    tableMessage("paper-current-positions-body", 6, "持仓快照读取失败");
  else {
    renderHoldingRows("paper-current-positions-body", positions.value, line);
    setText(
      "positions-as-of",
      `${line.name || id} · ${ledgerDate(positions.value[0]?.date)}`,
    );
  }
  if (trades.status === "rejected") {
    tableMessage("paper-trades-body", 7, "流水读取失败");
    tableMessage("paper-actions-body", 4, "公司行动读取失败");
    setText("trade-count", "读取失败");
    setText("action-count", "读取失败");
    return;
  }
  const actions = trades.value.filter((row) => row.side === "SPLIT");
  const fills = trades.value.filter((row) => row.side !== "SPLIT");
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
          `<tr><td class="date">${escapeHtml(ledgerDate(row.date))}</td><td>${escapeHtml(row.symbol)}</td><td title="${escapeHtml(row.side)}">${escapeHtml(statusText(row.side))}</td><td class="numeric">${fmt(row.quantity, 4)}${id === "personal_assistant" ? "<small> 模型份额</small>" : ""}</td><td class="numeric">${fmt(row.price, 4)}</td><td class="numeric">${row.cost == null ? "来源未提供" : fmt(row.cost)}</td><td><details><summary>原因与原值</summary><p>调仓原因：${escapeHtml(sourceReason(row.note))}</p><p>原始说明：${escapeHtml(row.note || "来源未提供")}</p><code>${escapeHtml(JSON.stringify(row))}</code></details></td></tr>`,
      )
      .join("");
  if (!actions.length)
    tableMessage("paper-actions-body", 4, "该窗口暂无公司行动记录");
  else
    $("paper-actions-body").innerHTML = actions
      .map((row) => {
        const ratio =
          String(row.note || "").match(/split_ratio=([\d.]+)/)?.[1] ||
          String(row.note || "").match(/1\s*[:：]\s*([\d.]+)\s*拆分/)?.[1];
        return `<tr><td class="date">${escapeHtml(ledgerDate(row.date))}</td><td>${escapeHtml(row.symbol)}</td><td>份额拆分</td><td>${ratio ? `1 : ${escapeHtml(ratio)}` : "比例来源未提供"}<details><summary>来源说明与原值</summary><p>${escapeHtml(row.note || "来源未提供")}</p><code>${escapeHtml(JSON.stringify(row))}</code></details></td></tr>`;
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
