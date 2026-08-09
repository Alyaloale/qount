"use strict";

const ROUTES = {
  live: ["权威读模型", "实时运行", "账户、组合与运行状态"],
  paper: ["无订单模拟平台", "多策略模拟盘", "四种策略的信号净值与可执行净值"],
  positions: ["组合事实", "仓位", "实际仓位、批准目标与决策追踪"],
  orders: ["执行事实", "订单", "订单状态、成交、费用与恢复"],
  strategies: ["治理注册表", "策略", "策略版本、治理状态与最新决定"],
  decisions: ["证据链", "决策追踪", "从市场快照到三方对账的完整链路"],
  risk: ["确定性控制", "风险", "风险决定、会计恒等式与对账"],
  readiness: ["运行门", "就绪检查", "运行门、策略资格与订单权限"],
  system: ["系统观测", "系统健康", "账本完整性与显式健康观测"],
  alerts: ["事件管理", "告警", "分级事件、状态与投递审计"],
  reports: ["确定性报告", "日报", "确定性日报与来源覆盖"],
  intelligence: ["只读情报平面", "情报复盘", "行情、事件、交易历史与多智能体复核"],
};

const MODEL_PATHS = {
  overview: "data/v1/overview.json",
  positions: "data/v1/positions.json",
  orders: "data/v1/orders.json",
  strategies: "data/v1/strategies.json",
  decisions: "data/v1/decisions.json",
  risk: "data/v1/risk.json",
  readiness: "data/v1/readiness.json",
  system: "data/v1/system.json",
  alerts: "data/v1/alerts.json",
  reports: "data/v1/reports.json",
  intelligence: "data/v1/intelligence.json",
  paper: "data/v1/paper.json",
};

const ROUTE_MODELS = {
  live: "overview",
  positions: "positions",
  orders: "orders",
  strategies: "strategies",
  decisions: "decisions",
  risk: "risk",
  readiness: "readiness",
  system: "system",
  alerts: "alerts",
  reports: "reports",
  intelligence: "intelligence",
  paper: "paper",
};

const state = { status: "loading", publication: null, models: {}, error: null };
const $ = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value == null ? "" : value).replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "'": "&#39;",
    '"': "&quot;",
  })[character]);
}

function shortHash(value) {
  const text = String(value || "");
  return text.length === 64 ? `${text.slice(0, 9)}...${text.slice(-7)}` : (text || "-");
}

function formatTime(value) {
  if (value == null || value === "") return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  const parts = new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    hourCycle: "h23",
  }).formatToParts(date);
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}年${values.month}月${values.day}日 ${values.hour}:${values.minute}:${values.second}`;
}

function formatDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  const parts = new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}年${values.month}月${values.day}日`;
}

function formatShortDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  const parts = new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.month}月${values.day}日`;
}

function assetText(value) {
  return ({ USD_EQ: "美元等值", USD: "美元" })[value] || String(value || "");
}

function portfolioText(value) {
  return ({
    G20: "美股轮动（G20）",
    C60: "加密趋势（C60）",
    GC5: "固定组合（GC5）",
    D15: "动态组合（D15）",
  })[value] || String(value || "-");
}

function formatMoney(value, asset) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  const formatted = new Intl.NumberFormat("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(number);
  return asset ? `${formatted} ${assetText(asset)}` : formatted;
}

function formatPercent(value) {
  const number = Number(value);
  return Number.isFinite(number) ? `${(number * 100).toFixed(2)}%` : "-";
}

function formatQuantity(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 8 }).format(number);
}

function statusText(value) {
  return ({
    fresh: "数据有效",
    stale: "数据待更新",
    available: "可用",
    available_readonly: "交易所只读事实",
    healthy: "健康",
    degraded: "降级",
    unavailable: "不可用",
    attention_required: "需要关注",
    halt_required: "需要停机",
    clear: "清晰",
    pass: "通过",
    warn: "警告",
    block: "阻断",
    blocked: "阻断",
    passed: "通过",
    none: "无",
    OPEN: "待处理",
    RESOLVED: "已解决",
    INFO: "信息",
    WARNING: "警告",
    CRITICAL: "严重",
    HALT: "停机",
    PENDING: "待投递",
    RETRY_WAIT: "等待重试",
    DELIVERED: "通道已接受",
    DEAD_LETTER: "投递失败",
    PLANNED: "已计划",
    SUBMITTING: "提交中",
    ACKNOWLEDGED: "已确认",
    PARTIALLY_FILLED: "部分成交",
    FILLED: "已成交",
    REJECTED: "已拒绝",
    CANCELED: "已取消",
    EXPIRED: "已过期",
    UNKNOWN: "未知",
    BUY: "买入",
    SELL: "卖出",
    entry: "建仓",
    exit: "退出",
    protective: "保护",
    promoted: "已晋级",
    shadow: "影子运行",
    SCHEDULED: "等待事件",
    FREEZE_REQUIRED: "等待冻结",
    EVENT_FROZEN: "事件已冻结",
    BLACKOUT: "观察静默期",
    OBSERVE: "观察中",
    ARMED: "信号就绪",
    NO_TRADE: "禁止入场",
    HALTED: "已停机",
    long: "做多",
    short: "做空",
    paper: "模拟运行",
    owner_authorized_ytd_replay: "已授权年度回放",
    draft: "草稿登记",
    research: "研究登记",
    frozen_candidate: "冻结候选登记",
    minimal_live: "最小实盘登记",
    scaled_live: "扩展实盘登记",
    halted: "停机登记",
    research_only: "仅研究",
    read_model_ready: "读模型就绪",
    read_only_observation_ready: "账户只读观察就绪",
    complete: "完整",
    incomplete: "不完整",
    sufficient: "充足",
    limited: "有限",
    registry_authorized: "注册授权存在",
    disarmed: "未武装",
    armed: "已武装",
    metadata_only: "仅元数据",
    substantive: "实质正文",
    no_order_expected: "无需订单",
    orders_expected_but_missing: "预期订单缺失",
    fills_verified: "成交已核验",
    ledger_current: "当前账本有效",
    ledger_current_after_blocked_observation: "当前账本有效",
    ledger_stale: "账本已过期",
    ledger_stale_after_blocked_observation: "账本已过期",
    ledger_superseded_by_blocked_observation: "账本已被只读观察取代",
    ledger_unavailable: "当前账本不可用",
    ledger_unavailable_with_blocked_observation: "当前账本不可用",
    ledger_future_dated: "账本时钟异常",
    ledger_future_dated_after_blocked_observation: "账本时钟异常",
    ledger_freshness_unverified: "账本时效未验证",
    ledger_freshness_unverified_after_blocked_observation: "账本时效未验证",
    eligible_for_research_design: "可进入研究设计",
    blocked_source_capacity: "来源容量阻断",
    blocked_history_capacity: "历史容量阻断",
    blocked_source_and_history_capacity: "来源与历史容量阻断",
  })[value] || String(value || "-");
}

function tone(value) {
  if (["fresh", "available", "healthy", "clear", "pass", "passed", "complete", "sufficient", "fills_verified", "no_order_expected", "eligible_for_research_design", "FILLED", "RESOLVED", "DELIVERED", "INFO"].includes(value)) return "ok";
  if (["unavailable", "halt_required", "block", "blocked", "insufficient", "orders_expected_but_missing", "blocked_source_capacity", "blocked_history_capacity", "blocked_source_and_history_capacity", "UNKNOWN", "REJECTED", "DEAD_LETTER", "CRITICAL", "HALT"].includes(value)) return "bad";
  return "warn";
}

function pill(value) {
  return `<span class="status-pill ${tone(value)}">${escapeHtml(statusText(value))}</span>`;
}

function metric(label, value, detail, valueTone) {
  return `<article class="metric"><span>${escapeHtml(label)}</span><strong class="${escapeHtml(valueTone || "")}">${escapeHtml(value)}</strong><small>${escapeHtml(detail || "")}</small></article>`;
}

function traceLink(identifier, label) {
  if (!identifier) return "-";
  return `<a class="trace-link mono" href="#/decisions?trace=${escapeHtml(identifier)}">${escapeHtml(label || shortHash(identifier))}</a>`;
}

function componentText(value) {
  return ({ clock: "时钟", disk: "磁盘", service: "发布服务", backup: "备份", operations: "运行观察" })[value] || String(value || "-");
}

function sourceText(value) {
  return ({
    primary: "主要来源",
    decision_batch: "决策批次",
    decision_batch_manifest: "决策批次",
    event_strategy: "事件策略",
    strategy_registry: "策略注册表",
    runtime_ledger: "运行账本",
    blocked_runtime_observation: "账户只读观察",
    notification_store: "通知库",
    notification_monitor: "通知监测",
    daily_brief: "确定性日报",
    daily_intelligence: "每日情报",
    paper_program: "双引擎模拟盘",
    dual_engine_paper: "双引擎模拟盘",
    system_health: "系统观察",
    ops_observer: "运维观察器",
  })[value] || String(value || "-");
}

function alertCategoryText(value) {
  return ({
    fomc_event_cash_only: "FOMC 现金窗口",
    fomc_event_freeze: "FOMC 区间冻结",
    fomc_event_readiness: "FOMC 运行就绪",
    fomc_event_signal: "FOMC 交易信号",
  })[value] || String(value || "-");
}

function axisText(value) {
  return ({
    publication_integrity: "发布完整性",
    observation_state: "观测状态",
    operational_state: "运行状态",
    trading_authority: "交易权限",
    evidence_state: "证据状态",
  })[value] || String(value || "-");
}

function scopeText(value) {
  return ({ execution: "执行", observation: "观测", intelligence: "情报", delivery: "投递" })[value] || String(value || "-");
}

function operationCheckText(value) {
  return ({
    "service:fomc_shadow": "FOMC 公共行情影子服务",
    "service:fomc_live": "FOMC 受控执行定时器",
    "service:mini_trend_forward": "MiniTrend 前向定时器",
    "service:mini_trend_live": "MiniTrend 实盘定时器",
    "service:mini_trend_live_service": "MiniTrend 实盘服务",
    "trading:manual_arm": "手动执行授权",
    "trading:halt": "全局交易停机",
    "release:provenance": "发布来源证明",
  })[value] || String(value || "-");
}

function traceTypeText(value) {
  return ({
    decision_batch: "决策批次",
    market_snapshot: "市场快照",
    strategy_decision: "策略决定",
    portfolio_target: "组合目标",
    risk_decision: "风险决定",
    order_plan: "订单计划",
    runtime_ledger: "运行账本",
    reconciliation: "三方对账",
  })[value] || String(value || "-");
}

function traceLabel(node) {
  const labels = {
    "Verified decision batch": "已验证决策批次",
    "Market snapshot": "市场快照",
    "Portfolio target": "组合目标",
    "Risk decision": "风险决定",
    "Order plan": "订单计划",
    "Runtime ledger snapshot": "运行账本快照",
    "Three-way reconciliation": "三方对账",
  };
  return labels[node && node.label] || (node && node.label) || "完整批次";
}

function routeInfo() {
  const raw = (location.hash || "#/live").replace(/^#\/?/, "");
  const [path, query = ""] = raw.split("?", 2);
  const valid = Object.hasOwn(ROUTES, path);
  const route = valid ? path : "live";
  return { route, trace: new URLSearchParams(query).get("trace"), valid };
}

function canonicalRouteInfo() {
  const info = routeInfo();
  if (!location.hash || !info.valid) {
    history.replaceState(null, "", "#/live");
    return { route: "live", trace: null, valid: true };
  }
  return info;
}

function modelForRoute(route) {
  return state.models[ROUTE_MODELS[route]] || null;
}

function isStale(model) {
  if (!model || !model.freshness) return true;
  return model.freshness.status === "stale" || Date.now() >= new Date(model.freshness.stale_at).getTime();
}

async function fetchJSON(path) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 8000);
  try {
    const response = await fetch(`${path}?t=${Date.now()}`, {
      cache: "no-store",
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const raw = await response.text();
    return { value: JSON.parse(raw), fileSha256: await sha256Hex(raw) };
  } finally {
    clearTimeout(timer);
  }
}

async function sha256Hex(value) {
  if (!globalThis.crypto || !globalThis.crypto.subtle) {
    throw new Error("浏览器不支持读模型完整性校验");
  }
  const digest = await globalThis.crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(value),
  );
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function assertObject(value, name) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${name} 格式错误`);
  }
}

function validatePublication(publication) {
  assertObject(publication, "publication");
  assertObject(publication.read_models, "publication.read_models");
  if (publication.schema_version !== 1) throw new Error("publication schema 不匹配");
  if (!/^[a-f0-9]{64}$/.test(publication.publication_id || "")) {
    throw new Error("publication ID 不匹配");
  }
  const expected = Object.keys(MODEL_PATHS).sort();
  const actual = Object.keys(publication.read_models).sort();
  if (JSON.stringify(actual) !== JSON.stringify(expected)) throw new Error("read model 集合不完整");
}

function releaseModelPath(path, publicationId) {
  return path.replace("data/v1/", `data/releases/${publicationId}/`);
}

function validateModel(response, type, publication) {
  const { value: model, fileSha256 } = response;
  assertObject(model, type);
  assertObject(model.payload, `${type}.payload`);
  assertObject(model.freshness, `${type}.freshness`);
  assertObject(model.source_hashes, `${type}.source_hashes`);
  if (model.schema_version !== 1 || model.read_model_type !== type) throw new Error(`${type} schema 不匹配`);
  const reference = publication.read_models[type];
  if (!reference || reference.read_model_id !== model.read_model_id || reference.read_model_hash !== model.read_model_hash || reference.file_sha256 !== fileSha256) {
    throw new Error(`${type} 与 publication 不一致`);
  }
  if (!["system", "alerts", "reports", "intelligence", "paper"].includes(type)) {
    const sharedSources = Object.entries(model.source_hashes).filter(
      ([name]) => Object.hasOwn(publication.source_hashes, name),
    );
    const sourcesMatch = sharedSources.length > 0 && sharedSources.every(
      ([name, hash]) => publication.source_hashes[name] === hash,
    );
    if (!sourcesMatch) throw new Error(`${type} 权威来源不一致`);
  }
}

function unavailableBlock(title, detail) {
  return `<div class="unavailable-block"><span class="unavailable-mark" aria-hidden="true">!</span><div><strong>${escapeHtml(title)}</strong><p>${escapeHtml(detail)}</p></div></div>`;
}

function renderFreshnessDetail() {
  const { route } = routeInfo();
  const model = modelForRoute(route);
  const target = $("freshness-detail");
  if (!model || !model.freshness) {
    target.hidden = true;
    target.innerHTML = "";
    return;
  }
  const freshness = model.freshness;
  const sources = Object.entries(freshness.sources || {});
  target.innerHTML = `<div class="freshness-overview"><div><span>模块观测</span><strong>${escapeHtml(formatTime(freshness.observed_at))}</strong></div><div><span>内容变化</span><strong>${escapeHtml(formatTime(freshness.content_updated_at))}</strong></div><div><span>本轮评估</span><strong>${escapeHtml(formatTime(freshness.evaluated_at))}</strong></div></div><div class="freshness-sources">${sources.map(([name, row]) => `<article><div><strong>${escapeHtml(sourceText(name))}</strong>${pill(row.status)}</div><small>更新 ${escapeHtml(formatTime(row.updated_at))}</small><small>到期 ${escapeHtml(formatTime(row.stale_at))}</small></article>`).join("")}</div>`;
  target.hidden = false;
}

function renderLive() {
  const model = state.models.overview;
  const payload = model.payload;
  const readonlyAccount = payload.account.status === "available_readonly";
  const account = ["available", "available_readonly"].includes(payload.account.status) ? payload.account.values : null;
  const pnl = payload.pnl.status === "available" ? payload.pnl.values : null;
  const portfolio = payload.portfolio;
  const risk = payload.risk;
  const batch = payload.latest_batch;
  const actual = ["available", "available_readonly"].includes(portfolio.actual_positions.status) ? portfolio.actual_positions.values.positions : {};
  const symbols = [...new Set([...Object.keys(portfolio.approved_target), ...Object.keys(actual)])].sort();
  const accountMetrics = account && readonlyAccount ? `
    <div class="metrics metrics-four">
      ${metric("钱包余额", formatMoney(account.wallet_balance, account.quote_asset), "私有只读账户预检", "good")}
      ${metric("可用余额", formatMoney(account.available_balance, account.quote_asset), `普通挂单 ${account.open_order_count}`, "good")}
      ${metric("实际总敞口", formatPercent(account.actual_gross_fraction), formatMoney(account.actual_gross_notional, account.quote_asset), "accent")}
      ${metric("保证金占用", formatPercent(account.margin_fraction), formatMoney(account.margin_used, account.quote_asset), "")}
    </div>` : account ? `
    <div class="metrics metrics-six">
      ${metric("钱包余额", formatMoney(account.wallet_balance, account.quote_asset), `可用余额 ${formatMoney(account.available_balance)}`, "good")}
      ${metric("账户权益", formatMoney(pnl.equity, account.quote_asset), `本期变化 ${formatMoney(pnl.equity_change)}`, pnl.passed ? "good" : "bad")}
      ${metric("实际总敞口", formatPercent(account.actual_gross_fraction), formatMoney(account.actual_gross_notional, account.quote_asset), "accent")}
      ${metric("保证金占用", formatPercent(account.margin_fraction), formatMoney(account.margin_used, account.quote_asset), "")}
      ${metric("峰值回撤", formatPercent(account.peak_drawdown_fraction), `峰值权益 ${formatMoney(account.peak_equity)}`, account.peak_drawdown_fraction > 0.1 ? "bad" : "")}
      ${metric("当前回撤", formatPercent(account.current_drawdown_fraction), `峰值时点 ${formatTime(account.peak_drawdown_at)}`, account.current_drawdown_fraction > 0.1 ? "bad" : "")}
    </div>` : unavailableBlock("权威账户读数不可用", "当前发布没有可验证的运行账本账户观测。");
  $("view-live").innerHTML = `${accountMetrics}
    ${readonlyAccount ? `<div class="unavailable-block"><span class="unavailable-mark" aria-hidden="true">i</span><div><strong>只读账户观测</strong><p>该账户由私有只读预检提供；损益、回撤、账本对账和订单执行仍不可用。</p></div></div>` : ""}
    <div class="account-strip">
      <div><span>交易损益</span><strong>${pnl ? escapeHtml(formatMoney(pnl.trading_pnl)) : "-"}</strong></div>
      <div><span>资金费</span><strong>${pnl ? escapeHtml(formatMoney(pnl.funding)) : "-"}</strong></div>
      <div><span>手续费</span><strong>${pnl ? escapeHtml(formatMoney(pnl.fees)) : "-"}</strong></div>
      <div><span>转账</span><strong>${pnl ? escapeHtml(formatMoney(pnl.transfers)) : "-"}</strong></div>
      <div><span>未解释残差</span><strong>${pnl ? escapeHtml(formatMoney(pnl.residual)) : "-"}</strong></div>
      <div><span>账目核验</span>${pnl ? pill(pnl.passed ? "pass" : "block") : pill("unavailable")}</div>
    </div>
    <div class="split-layout">
      <section class="panel">
        <header class="panel-head"><div><h2>目标与实际</h2><p>风险决定 / 运行账本</p></div>${traceLink(portfolio.portfolio_target_id)}</header>
        <div class="table-wrap"><table><thead><tr><th>标的</th><th>批准权重</th><th>实际数量</th><th>追踪</th></tr></thead><tbody>
          ${symbols.length ? symbols.map((symbol) => `<tr><td><strong>${escapeHtml(symbol)}</strong></td><td>${escapeHtml(formatPercent(portfolio.approved_target[symbol]))}</td><td>${escapeHtml(formatQuantity(actual[symbol]))}</td><td>${traceLink(batch.batch_id, "查看")}</td></tr>`).join("") : `<tr><td colspan="4" class="empty-cell">全现金</td></tr>`}
        </tbody></table></div>
      </section>
      <section class="panel">
        <header class="panel-head"><div><h2>当前批次</h2><p>${batch.decision_count} 个策略决定</p></div>${pill(model.freshness.status)}</header>
        <dl class="fact-list">
          <div><dt>批次</dt><dd>${traceLink(batch.batch_id)}</dd></div>
          <div><dt>清单哈希</dt><dd class="mono">${escapeHtml(shortHash(batch.manifest_hash))}</dd></div>
          <div><dt>市场快照</dt><dd>${traceLink(batch.snapshot_id)}</dd></div>
          <div><dt>决策时间</dt><dd>${escapeHtml(formatTime(batch.decision_time))}</dd></div>
          <div><dt>风险结论</dt><dd>${pill(risk.approved ? "pass" : "block")}</dd></div>
          <div><dt>订单计划</dt><dd>${portfolio.planned_order_count} 笔 / 撤单 ${portfolio.planned_cancellation_count} 笔</dd></div>
        </dl>
      </section>
    </div>`;
}

function renderPositions() {
  const payload = state.models.positions.payload;
  if (payload.summary.status === "available_readonly") {
    const summary = payload.summary;
    $("view-positions").innerHTML = `
      <div class="metrics metrics-four">
        ${metric("交易所仓位", String(summary.position_count), "账户预检只读观察", "accent")}
        ${metric("非零仓位", String(summary.nonzero_position_count), "不属于 Qount ledger", "")}
        ${metric("Ledger 对账", statusText(summary.reconciliation_status), "没有权威 ledger reconciliation", "bad")}
        ${metric("事实范围", "只读", "非 ledger 账户仓位，Qount 未归因", "accent")}
      </div>
      <section class="panel full-panel">
        <header class="panel-head"><div><h2>交易所只读仓位事实</h2><p>仅展示账户观察，不补造策略账本事实</p></div><span class="mono">${escapeHtml(shortHash(state.models.positions.source_hashes.blocked_runtime_observation))}</span></header>
        <div class="table-wrap"><table><thead><tr><th>标的</th><th>方向</th><th>实际数量</th><th>名义价值</th><th>成本</th><th>已实现损益</th><th>对账</th><th>观测时间</th></tr></thead><tbody>
          ${payload.positions.map((row) => `<tr><td><strong>${escapeHtml(row.symbol)}</strong><small>Qount ledger 外仓位</small></td><td>${pill(row.side)}</td><td>${escapeHtml(formatQuantity(row.actual_quantity))}</td><td>${escapeHtml(formatMoney(row.notional))}</td><td>${escapeHtml(statusText("unavailable"))}<small>非 ledger 事实</small></td><td>${escapeHtml(statusText("unavailable"))}<small>非 ledger 事实</small></td><td>${pill(row.reconciliation_status)}</td><td>${escapeHtml(formatTime(row.observed_at))}<small class="mono">${escapeHtml(shortHash(row.observation_hash))}</small></td></tr>`).join("") || `<tr><td colspan="8" class="empty-cell">账户观察为空仓</td></tr>`}
        </tbody></table></div>
      </section>`;
    return;
  }
  if (payload.summary.status !== "available") {
    $("view-positions").innerHTML = unavailableBlock("仓位读模型不可用", "当前发布既没有权威 ledger position facts，也没有可验证的交易所账户观察。");
    return;
  }
  $("view-positions").innerHTML = `
    <div class="metrics metrics-four">
      ${metric("跟踪标的", String(payload.summary.position_count), "目标、预期与实际的并集", "accent")}
      ${metric("非零仓位", String(payload.summary.nonzero_position_count), "权威账本记录", "")}
      ${metric("对账状态", statusText(payload.summary.reconciled ? "pass" : "block"), shortHash(payload.summary.reconciliation_id), payload.summary.reconciled ? "good" : "bad")}
      ${metric("追踪覆盖", "完整", "批次到订单计划", "good")}
    </div>
    <section class="panel full-panel">
      <header class="panel-head"><div><h2>仓位事实</h2><p>实际值不在浏览器推导</p></div>${traceLink(payload.summary.reconciliation_id)}</header>
      <div class="table-wrap"><table><thead><tr><th>标的</th><th>实际</th><th>预期</th><th>差异</th><th>目标权重</th><th>成本</th><th>已实现</th><th>追踪</th></tr></thead><tbody>
        ${payload.positions.map((row) => `<tr><td><strong>${escapeHtml(row.symbol)}</strong><small>${row.updated_at ? escapeHtml(formatTime(row.updated_at)) : "账本无记录，按零仓位"}</small></td><td>${escapeHtml(formatQuantity(row.actual_quantity))}</td><td>${escapeHtml(formatQuantity(row.expected_quantity))}</td><td class="${Number(row.quantity_difference) === 0 ? "good" : "warn-text"}">${escapeHtml(formatQuantity(row.quantity_difference))}</td><td>${escapeHtml(formatPercent(row.approved_target_weight))}</td><td>${escapeHtml(formatMoney(row.average_cost))}</td><td>${escapeHtml(formatMoney(row.realized_trading_pnl))}</td><td><a class="trace-link" href="${escapeHtml(row.trace.href)}">查看链路</a><small class="mono">${escapeHtml(shortHash(row.position_hash))}</small></td></tr>`).join("")}
      </tbody></table></div>
    </section>`;
}

function renderOrders() {
  const payload = state.models.orders.payload;
  const summary = payload.summary;
  if (summary.status !== "available") {
    $("view-orders").innerHTML = unavailableBlock("订单读模型不可用", "当前发布没有权威 ledger order facts。");
    return;
  }
  $("view-orders").innerHTML = `
    <div class="metrics metrics-four">
      ${metric("订单总数", String(summary.total_order_count), `未完成 ${summary.open_order_count}`, summary.open_order_count ? "bad" : "good")}
      ${metric("成交记录", String(summary.fill_count), `成交名义 ${formatMoney(summary.fill_notional)}`, "accent")}
      ${metric("部分成交 / 拒绝", `${summary.partial_fill_count} / ${summary.rejected_count}`, `保护单 ${summary.protective_order_count}`, summary.partial_fill_count || summary.rejected_count ? "bad" : "")}
      ${metric("恢复状态", statusText(summary.latest_recovery_status), `未解决订单 ${summary.unresolved_order_count}`, summary.unresolved_order_count ? "bad" : "good")}
    </div>
    <section class="panel full-panel"><header class="panel-head"><div><h2>订单状态机</h2><p>逐单累计观察</p></div><span class="mono">${escapeHtml(shortHash(state.models.orders.source_hashes.runtime_ledger))}</span></header>
      <div class="table-wrap"><table><thead><tr><th>订单</th><th>标的</th><th>阶段</th><th>状态</th><th>计划</th><th>累计</th><th>成交名义</th><th>最后观察</th></tr></thead><tbody>
        ${payload.orders.map((row) => `<tr><td>${traceLink(row.batch_id, shortHash(row.client_order_id))}</td><td><strong>${escapeHtml(row.symbol)}</strong><small>${escapeHtml(statusText(row.side))} / ${escapeHtml(row.order_type)}</small></td><td>${pill(row.phase)}</td><td>${pill(row.status)}</td><td>${escapeHtml(formatQuantity(row.planned_quantity))}</td><td>${escapeHtml(formatQuantity(row.executed_quantity))}</td><td>${escapeHtml(formatMoney(row.fill_notional))}</td><td>${escapeHtml(formatTime(row.last_transition_at))}<small class="mono">${escapeHtml(shortHash(row.last_observation_hash))}</small></td></tr>`).join("") || `<tr><td colspan="8" class="empty-cell">无订单</td></tr>`}
      </tbody></table></div>
    </section>
    <section class="panel full-panel"><header class="panel-head"><div><h2>成交记录</h2><p>${payload.fills.length} 笔权威成交</p></div></header>
      <div class="table-wrap"><table><thead><tr><th>成交</th><th>订单</th><th>交易所成交 ID</th><th>数量</th><th>价格</th><th>费用</th><th>时间</th></tr></thead><tbody>
        ${payload.fills.map((fill) => `<tr><td class="mono">${escapeHtml(shortHash(fill.fill_id))}</td><td class="mono">${escapeHtml(shortHash(fill.client_order_id))}</td><td>${escapeHtml(fill.exchange_trade_id)}</td><td>${escapeHtml(formatQuantity(fill.quantity))}</td><td>${escapeHtml(formatMoney(fill.price))}</td><td>${escapeHtml(formatMoney(fill.fee, fill.fee_asset))}</td><td>${escapeHtml(formatTime(fill.occurred_at))}</td></tr>`).join("") || `<tr><td colspan="7" class="empty-cell">无成交</td></tr>`}
      </tbody></table></div>
    </section>`;
}

function renderStrategies() {
  const rows = state.models.strategies.payload.strategies;
  $("view-strategies").innerHTML = `<section class="panel full-panel"><header class="panel-head"><div><h2>策略注册表</h2><p>${rows.length} 个当前版本</p></div><span class="mono">${escapeHtml(shortHash(state.models.strategies.source_hashes.strategy_registry))}</span></header>
    <div class="table-wrap"><table><thead><tr><th>策略</th><th>注册状态</th><th>执行状态</th><th>订单权限</th><th>风险预算</th><th>本批决定</th><th>目标</th><th>净值</th></tr></thead><tbody>
      ${rows.map((row) => { const decision = row.latest_decision; const nav = row.nav.status === "available" ? row.nav.values : null; return `<tr><td><strong>${escapeHtml(row.strategy_id)}</strong><small>v${escapeHtml(row.strategy_version)} / ${escapeHtml(row.strategy_kind)}</small></td><td>${pill(row.registry_status)}<small>仅注册表阶段</small></td><td>${pill(row.execution_status)}<small>${row.execution_blockers.length ? escapeHtml(row.execution_blockers.join(" / ")) : "运行前置条件已观测"}</small></td><td>${pill(row.live_orders_allowed ? "pass" : "block")}<small>实盘订单权限：${row.live_orders_allowed ? "开启" : "关闭"}</small></td><td>${escapeHtml(formatPercent(row.maximum_gross))}<small>压力损失 ${escapeHtml(formatPercent(row.maximum_stress_loss_fraction))}</small></td><td>${decision ? traceLink(decision.decision_id) : "-"}${decision ? `<small>${escapeHtml(decision.reason_codes.join(" / "))}</small>` : ""}</td><td>${decision ? escapeHtml(formatPercent(decision.standalone_target_gross)) : "-"}</td><td>${nav ? escapeHtml(formatMoney(nav.standalone_executable_nav)) : "-"}<small>${nav ? `信号净值 ${escapeHtml(formatMoney(nav.signal_nav))}` : "账本不可用"}</small></td></tr>`; }).join("")}
    </tbody></table></div></section>`;
}

function renderDecisions() {
  const payload = state.models.decisions.payload;
  const selected = routeInfo().trace;
  const selectedNode = payload.trace.nodes.find((node) => node.id === selected) || null;
  $("view-decisions").innerHTML = `
    <div class="trace-summary">
      <div><span>已选链路</span><strong>${escapeHtml(traceLabel(selectedNode))}</strong><small class="mono">${escapeHtml(shortHash(selectedNode ? selectedNode.id : payload.batch.batch_id))}</small></div>
      <div>${pill(payload.risk.approved ? "pass" : "block")}<span>风险决定</span></div>
      <div>${pill(payload.order_plan.executable ? "pass" : "block")}<span>订单计划</span></div>
    </div>
    <section class="panel full-panel"><header class="panel-head"><div><h2>决策证据链</h2><p>${payload.trace.nodes.length} 个节点 / ${payload.trace.edges.length} 条连接</p></div>${traceLink(payload.batch.batch_id, "批次根节点")}</header>
      <div class="trace-flow">${payload.trace.nodes.map((node, index) => `<a href="${escapeHtml(node.href)}" class="trace-node ${node.id === selected ? "selected" : ""}"><span>${String(index + 1).padStart(2, "0")}</span><div><small>${escapeHtml(traceTypeText(node.type))}</small><strong>${escapeHtml(traceLabel(node))}</strong><code>${escapeHtml(shortHash(node.integrity_hash))}</code></div></a>`).join("")}</div>
    </section>
    <div class="split-layout">
      <section class="panel"><header class="panel-head"><div><h2>策略决定</h2><p>理由与独立目标</p></div></header><div class="decision-list">
        ${payload.strategies.map((row) => `<a href="${escapeHtml(row.href)}" class="decision-row ${row.decision_id === selected ? "selected" : ""}"><div><strong>${escapeHtml(row.strategy_id)}</strong><small>v${escapeHtml(row.strategy_version)} / ${escapeHtml(formatTime(row.decision_time))}</small></div><span>${escapeHtml(formatPercent(Object.values(row.target_weights)[0]))}</span><small>${escapeHtml(row.reason_codes.join(" / "))}</small></a>`).join("")}
      </div></section>
      <section class="panel"><header class="panel-head"><div><h2>证据标识</h2><p>已验证批次引用</p></div></header><dl class="fact-list">
        <div><dt>清单哈希</dt><dd class="mono">${escapeHtml(shortHash(payload.batch.manifest_hash))}</dd></div>
        <div><dt>组合目标</dt><dd>${traceLink(payload.portfolio.portfolio_target_id)}</dd></div>
        <div><dt>风险决定</dt><dd>${traceLink(payload.risk.risk_decision_id)}</dd></div>
        <div><dt>订单计划</dt><dd>${traceLink(payload.order_plan.order_plan_id)}</dd></div>
        <div><dt>订单数量</dt><dd>${payload.order_plan.order_ids.length}</dd></div>
        <div><dt>订单授权</dt><dd>${pill(payload.batch.orders_authorized ? "pass" : "block")}</dd></div>
      </dl></section>
    </div>`;
}

function renderRisk() {
  const payload = state.models.risk.payload;
  if (payload.runtime.status !== "available") {
    $("view-risk").innerHTML = unavailableBlock("运行风险事实不可用", "RiskDecision 存在，但没有权威 ledger reconciliation。");
    return;
  }
  const runtime = payload.runtime.values;
  const reconciliation = runtime.reconciliation;
  const accounting = runtime.accounting;
  $("view-risk").innerHTML = `
    <div class="metrics metrics-four">
      ${metric("决策门", statusText(payload.decision.increase_risk_allowed ? "pass" : "block"), `${payload.decision.violations.length} 项违规`, payload.decision.increase_risk_allowed ? "good" : "bad")}
      ${metric("运行门", statusText(runtime.gate_status), `${runtime.reason_codes.length} 个原因码`, runtime.gate_status === "pass" ? "good" : "bad")}
      ${metric("三方对账", statusText(reconciliation.passed ? "pass" : "block"), `${reconciliation.blockers.length} 个阻断项`, reconciliation.passed ? "good" : "bad")}
      ${metric("账目核验", statusText(accounting.passed ? "pass" : "block"), `未解释残差 ${formatMoney(accounting.residual)}`, accounting.passed ? "good" : "bad")}
    </div>
    <div class="split-layout"><section class="panel"><header class="panel-head"><div><h2>三方仓位差异</h2><p>批准目标 / 内部账本 / 交易所</p></div>${traceLink(reconciliation.reconciliation_id)}</header><div class="table-wrap"><table><thead><tr><th>标的</th><th>目标减账本</th><th>账本减交易所</th></tr></thead><tbody>${Object.entries(reconciliation.position_differences).map(([symbol, row]) => `<tr><td><strong>${escapeHtml(symbol)}</strong></td><td>${escapeHtml(formatQuantity(row.target_minus_ledger))}</td><td>${escapeHtml(formatQuantity(row.ledger_minus_exchange))}</td></tr>`).join("") || `<tr><td colspan="3" class="empty-cell">无差异</td></tr>`}</tbody></table></div></section>
      <section class="panel"><header class="panel-head"><div><h2>账目事实</h2><p>最新净值标记</p></div><span class="mono">${escapeHtml(shortHash(accounting.mark_hash))}</span></header><dl class="fact-list"><div><dt>资金费</dt><dd>${escapeHtml(formatMoney(accounting.funding))}</dd></div><div><dt>手续费</dt><dd>${escapeHtml(formatMoney(accounting.fees))}</dd></div><div><dt>转账</dt><dd>${escapeHtml(formatMoney(accounting.transfers))}</dd></div><div><dt>未解释残差</dt><dd>${escapeHtml(formatMoney(accounting.residual))}</dd></div><div><dt>容差</dt><dd>${escapeHtml(formatMoney(accounting.residual_tolerance))}</dd></div><div><dt>结论</dt><dd>${pill(accounting.passed ? "pass" : "block")}</dd></div></dl></section></div>`;
}

function renderReadiness() {
  const payload = state.models.readiness.payload;
  const axes = Object.entries(payload.axes);
  $("view-readiness").innerHTML = `<div class="readiness-head"><div><span>读模型就绪状态</span><strong>${escapeHtml(statusText(payload.status))}</strong></div>${pill(payload.status)}</div>
    <section class="axis-band">${axes.map(([name, axis]) => `<article><header><strong>${escapeHtml(axisText(name))}</strong>${pill(axis.status)}</header><p>${escapeHtml(axis.detail)}</p><small>${axis.impact_scopes.map(scopeText).map(escapeHtml).join(" / ")}</small></article>`).join("")}</section>
    <div class="split-layout"><section class="panel"><header class="panel-head"><div><h2>运行检查项</h2><p>所有订单权限保持关闭</p></div></header><div class="gate-list">${payload.gates.map((gate) => `<div class="gate-row"><span class="gate-signal ${tone(gate.status)}"></span><div><strong>${escapeHtml(gate.gate)}</strong><small>${escapeHtml(gate.detail)}</small></div>${pill(gate.status)}</div>`).join("")}</div></section>
    <section class="panel"><header class="panel-head"><div><h2>策略就绪状态</h2><p>${payload.strategies.length} 个策略</p></div></header><div class="gate-list">${payload.strategies.map((row) => `<div class="gate-row"><span class="gate-signal ${tone(row.execution_status)}"></span><div><strong>${escapeHtml(row.strategy_id)} v${escapeHtml(row.strategy_version)}</strong><small>注册状态：${escapeHtml(statusText(row.registry_status))} / 执行状态：${escapeHtml(statusText(row.execution_status))} / 实盘订单权限：关闭${row.execution_blockers.length ? ` / 阻断或未武装原因：${row.execution_blockers.map(escapeHtml).join("、")}` : ""}</small></div>${pill(row.live_orders_allowed ? "pass" : "block")}</div>`).join("")}</div></section></div>`;
}

function healthMetric(row) {
  const metrics = row.metrics;
  if (row.component === "clock") return metrics.drift_seconds == null ? "时钟偏差观测不可用" : `时钟偏差 ${metrics.drift_seconds} 秒`;
  if (row.component === "disk") return metrics.free_bytes == null || metrics.total_bytes == null ? "磁盘容量观测不可用" : `可用 ${formatMoney(metrics.free_bytes / 1000000000)} GB / 总计 ${formatMoney(metrics.total_bytes / 1000000000)} GB`;
  if (row.component === "service") return `${metrics.service_name} / 状态 ${metrics.active_state}`;
  if (row.component === "backup") return metrics.last_success_at ? `最近成功 ${formatTime(metrics.last_success_at)} / 距今 ${metrics.age_seconds} 秒` : "没有成功备份记录";
  return Object.entries(metrics.scope_status || {}).map(([scope, status]) => `${scopeText(scope)} ${statusText(status)}`).join(" / ");
}

function renderSystem() {
  const payload = state.models.system.payload;
  const ledger = payload.ledger.status === "available" ? payload.ledger.values : null;
  const health = payload.health.status === "available" ? payload.health.values : null;
  const baseHealth = health ? health.observations.filter((row) => row.component !== "operations") : [];
  const operations = health ? health.observations.find((row) => row.component === "operations") : null;
  $("view-system").innerHTML = `
    <div class="metrics metrics-four">
      ${metric("系统状态", statusText(payload.summary.status), `${payload.summary.reason_codes.length} 个原因码`, tone(payload.summary.status) === "ok" ? "good" : tone(payload.summary.status) === "bad" ? "bad" : "accent")}
      ${metric("内部账本", ledger ? "已验证" : "不可用", ledger ? `Schema v${ledger.schema_version}` : "没有快照", ledger ? "good" : "bad")}
      ${metric("审计行数", ledger ? String(ledger.audit_row_count) : "-", ledger ? shortHash(ledger.audit_last_hash) : "", "")}
      ${metric("健康观测", health ? String(health.observations.length) : "0", health ? statusText(health.status) : "缺失", health ? (health.status === "healthy" ? "good" : "bad") : "bad")}
    </div>
    ${health ? `<section class="health-band">${baseHealth.map((row) => `<article><header><strong>${escapeHtml(componentText(row.component))}</strong>${pill(row.status)}</header><p>${escapeHtml(healthMetric(row))}</p><small>${escapeHtml(formatTime(row.observed_at))} / ${escapeHtml(shortHash(row.observation_hash))}</small></article>`).join("")}</section>` : unavailableBlock("系统健康观测缺失", "时钟、磁盘、服务和备份尚未由生产发布器提供。")}
    ${operations ? `<section class="panel full-panel"><header class="panel-head"><div><h2>运维观察器</h2><p>${Object.entries(operations.metrics.scope_status).map(([scope, status]) => `${scopeText(scope)} ${statusText(status)}`).join(" / ")}</p></div>${pill(operations.status)}</header><div class="table-wrap"><table><thead><tr><th>检查项</th><th>状态</th><th>影响域</th><th>阻断执行</th><th>观测值</th><th>结论</th></tr></thead><tbody>${operations.metrics.checks.map((check) => `<tr><td><strong>${escapeHtml(operationCheckText(check.check_id))}</strong><small class="mono">${escapeHtml(check.check_id)}</small></td><td>${pill(check.status)}</td><td>${check.impact_scopes.map(scopeText).map(escapeHtml).join(" / ")}</td><td>${check.blocks_execution ? pill("block") : pill("pass")}</td><td class="mono">${escapeHtml(check.observed_value)}</td><td><small>${escapeHtml(check.detail)}</small></td></tr>`).join("")}</tbody></table></div></section>` : ""}
    <div class="split-layout"><section class="panel"><header class="panel-head"><div><h2>账本完整性</h2><p>数据库快照 / 追加式审计链</p></div><span class="mono">${escapeHtml(shortHash(ledger && ledger.snapshot_hash))}</span></header>${ledger ? `<dl class="fact-list"><div><dt>快照完整性</dt><dd>${pill(ledger.integrity_status === "verified" ? "pass" : "block")}</dd></div><div><dt>审计链</dt><dd>${pill(ledger.audit_chain_status === "verified" ? "pass" : "block")}</dd></div><div><dt>三方对账</dt><dd>${pill(ledger.reconciliation_passed ? "pass" : "block")}</dd></div><div><dt>可恢复订单</dt><dd>${ledger.recoverable_order_count}</dd></div><div><dt>恢复报告</dt><dd>${ledger.recovery_report_count}</dd></div><div><dt>来源更新时间</dt><dd>${escapeHtml(formatTime(ledger.source_updated_at))}</dd></div></dl>` : unavailableBlock("账本不可用", "没有可验证账本快照。")}</section>
      <section class="panel"><header class="panel-head"><div><h2>原因码</h2><p>显式运行结论</p></div>${pill(payload.summary.status)}</header><div class="code-list">${payload.summary.reason_codes.map((reason) => `<code>${escapeHtml(reason)}</code>`).join("") || `<span class="empty-cell">无异常理由</span>`}${payload.summary.unavailable_fields.map((field) => `<code class="muted-code">缺失:${escapeHtml(field)}</code>`).join("")}</div></section></div>`;
}

function renderAlerts() {
  const payload = state.models.alerts.payload;
  if (payload.summary.status !== "available") {
    $("view-alerts").innerHTML = unavailableBlock("通知快照不可用", "当前发布没有 NotificationStore 权威快照。");
    return;
  }
  const summary = payload.summary;
  const openAlerts = payload.alerts.filter((row) => row.status === "OPEN");
  const resolvedAlerts = payload.alerts.filter((row) => row.status === "RESOLVED");
  const incidentRows = (rows, empty) => rows.map((row) => {
    const eventClass = row.source_type === "event_strategy" ? " event-incident" : "";
    return `<article class="${eventClass.trim()}"><div class="incident-status">${pill(row.severity)}${pill(row.status)}${row.source_type === "event_strategy" ? `<span class="source-badge">${escapeHtml(sourceText(row.source_type))}</span>` : ""}</div><div><strong>${escapeHtml(row.title)}</strong><p>${escapeHtml(row.summary)}</p><small>${escapeHtml(formatTime(row.occurred_at))} / ${escapeHtml(alertCategoryText(row.category))} / ${traceLink(row.trace_id || row.source_id)}</small></div><div class="delivery-list">${row.deliveries.map((delivery) => `<span>${escapeHtml(delivery.channel)} ${pill(delivery.status)} <small>${delivery.attempt_count}/${delivery.max_attempts}</small></span>`).join("") || "未配置投递通道"}</div></article>`;
  }).join("") || `<div class="empty-cell">${escapeHtml(empty)}</div>`;
  const openEventAlertCount = openAlerts.filter((row) => row.source_type === "event_strategy").length;
  const deliveryRows = payload.alerts.flatMap((row) => row.deliveries.map((delivery) => ({ alert: row, delivery })));
  const deliveryResult = (delivery) => {
    if (delivery.last_error) return delivery.last_error;
    if (!delivery.delivered_at) return "等待";
    const label = delivery.channel === "openclaw_weixin"
      ? "微信接口已接受（无客户端展示回执）"
      : "通道已接受";
    return `${label} ${formatTime(delivery.delivered_at)}`;
  };
  $("view-alerts").innerHTML = `<div class="metrics metrics-four">${metric("当前待处理", String(summary.open_alert_count), `严重 ${summary.severity_counts.CRITICAL} / 停机 ${summary.severity_counts.HALT}`, summary.open_alert_count ? "bad" : "good")}${metric("已解决历史", String(summary.resolved_alert_count), `历史严重 ${summary.historical_severity_counts.CRITICAL} / 停机 ${summary.historical_severity_counts.HALT}`, "")}${metric("等待投递", String(summary.delivery_state_counts.PENDING + summary.delivery_state_counts.RETRY_WAIT), `等待重试 ${summary.delivery_state_counts.RETRY_WAIT}`, "")}${metric("投递失败", String(summary.delivery_state_counts.DEAD_LETTER), `通道已接受 ${summary.delivery_state_counts.DELIVERED}`, summary.delivery_state_counts.DEAD_LETTER ? "bad" : "good")}</div>
    <div class="split-layout"><section class="panel"><header class="panel-head"><div><h2>当前事件</h2><p>待处理 / FOMC ${openEventAlertCount}</p></div><span>${openAlerts.length}</span></header><div class="incident-list">${incidentRows(openAlerts, "当前无待处理事件")}</div></section><section class="panel"><header class="panel-head"><div><h2>已解决历史</h2><p>已解决事件</p></div><span>${resolvedAlerts.length}</span></header><div class="incident-list compact-incidents">${incidentRows(resolvedAlerts, "暂无已解决历史")}</div></section></div>
    <section class="panel full-panel"><header class="panel-head"><div><h2>投递审计</h2><p>投递队列 / ${escapeHtml(formatTime(summary.content_updated_at))}</p></div><span class="mono">${escapeHtml(shortHash(summary.audit_last_hash))}</span></header><div class="table-wrap"><table><thead><tr><th>事件</th><th>通道</th><th>状态</th><th>尝试</th><th>最近尝试</th><th>结果</th></tr></thead><tbody>${deliveryRows.map(({ alert, delivery }) => `<tr><td><strong>${escapeHtml(alert.title)}</strong><small>${escapeHtml(shortHash(alert.alert_id))}</small></td><td>${escapeHtml(delivery.channel)}</td><td>${pill(delivery.status)}</td><td>${delivery.attempt_count}/${delivery.max_attempts}</td><td>${escapeHtml(formatTime(delivery.last_attempt_at))}</td><td><small>${escapeHtml(deliveryResult(delivery))}</small></td></tr>`).join("") || `<tr><td colspan="6" class="empty-cell">无投递任务</td></tr>`}</tbody></table></div></section>`;
}

function renderReports() {
  const payload = state.models.reports.payload;
  if (payload.summary.status !== "available") {
    $("view-reports").innerHTML = unavailableBlock("确定性日报不可用", "当前发布没有已验证 DailyBrief。");
    return;
  }
  const brief = payload.brief;
  const account = brief.account;
  const pnl = brief.pnl;
  $("view-reports").innerHTML = `<div class="metrics metrics-four">${metric("日报状态", statusText(brief.status), brief.report_date, tone(brief.status) === "ok" ? "good" : "bad")}${metric("钱包余额", formatMoney(account.wallet_balance, account.quote_asset), `可用余额 ${formatMoney(account.available_balance)}`, "good")}${metric("实际总敞口", formatPercent(account.actual_gross_fraction), formatMoney(account.actual_gross_notional), "accent")}${metric("峰值回撤", formatPercent(pnl.peak_drawdown_fraction), `当前 ${formatPercent(pnl.current_drawdown_fraction)}`, pnl.peak_drawdown_fraction > 0.1 ? "bad" : "")}</div>
    <div class="split-layout"><section class="panel"><header class="panel-head"><div><h2>日报仓位</h2><p>策略意图追踪链</p></div><span class="mono">${escapeHtml(shortHash(brief.source_hashes.runtime_ledger))}</span></header><div class="table-wrap"><table><thead><tr><th>标的</th><th>实际</th><th>预期</th><th>目标</th><th>策略</th></tr></thead><tbody>${brief.positions.map((row) => `<tr><td><strong>${escapeHtml(row.symbol)}</strong></td><td>${escapeHtml(formatQuantity(row.actual_quantity))}</td><td>${escapeHtml(formatQuantity(row.expected_quantity))}</td><td>${escapeHtml(formatPercent(row.approved_target_weight))}</td><td>${row.strategy_links.map((link) => traceLink(link.decision_id, link.strategy_id)).join(" ") || "-"}</td></tr>`).join("")}</tbody></table></div></section>
      <section class="panel"><header class="panel-head"><div><h2>所有者待办</h2><p>${brief.owner_actions.length} 项</p></div>${pill(brief.status)}</header><div class="code-list">${brief.owner_actions.map((action) => `<code>${escapeHtml(action)}</code>`).join("") || `<span class="empty-cell">无待办</span>`}</div></section></div>`;
}

function renderIntelligence() {
  const payload = state.models.intelligence.payload;
  if (payload.summary.status !== "available") {
    $("view-intelligence").innerHTML = unavailableBlock("情报复盘不可用", "当前发布没有已验证的 DailyIntelligenceReport。");
    return;
  }
  const report = payload.report;
  const history = report.trading_history;
  const historyAuthority = report.runtime_history_authority;
  const currentHistoryAuthoritative = historyAuthority?.current_history_authoritative === true;
  const symbols = report.market_pulse.symbols;
  const evidence = report.evidence_summary;
  $("view-intelligence").innerHTML = `<div class="metrics metrics-four">
      ${metric("处理链状态", statusText(report.pipeline_status), report.report_date, tone(report.pipeline_status) === "ok" ? "good" : "bad")}
      ${metric("证据状态", statusText(report.evidence_status), `${evidence.substantive_source_count}/${evidence.verified_source_count} 份实质正文`, tone(report.evidence_status) === "ok" ? "good" : "bad")}
      ${metric("研究建议", String(report.research_proposals.length), "G0 容量先行", "accent")}
      ${metric("执行证据", currentHistoryAuthoritative ? statusText(history.execution_evidence_status || "unavailable") : "当前不可用", currentHistoryAuthoritative ? `${history.order_count} 订单 / ${history.fill_count} 成交` : historyAuthority ? `${statusText(historyAuthority.status)} / 历史账本仅截至 ${formatTime(history.source_updated_at)}` : "旧报告缺少当前权威边界", currentHistoryAuthoritative && history.execution_evidence_sufficient ? "good" : "bad")}
    </div>
    <section class="market-strip">${symbols.map((row) => `<article><span>${escapeHtml(row.symbol)}</span><strong>${escapeHtml(formatMoney(row.last_price))}</strong><small class="${Number(row.change_24h_pct) >= 0 ? "positive" : "negative"}">${escapeHtml(formatPercent(Number(row.change_24h_pct) / 100))} / 资金费率 ${escapeHtml(formatPercent(row.funding_rate))}</small></article>`).join("")}</section>
    <section class="panel full-panel"><header class="panel-head"><div><h2>综合结论</h2><p>${escapeHtml(report.llm.model)} / ${escapeHtml(formatTime(report.created_at))}</p></div><span class="mono">${escapeHtml(shortHash(report.report_hash))}</span></header><div class="intelligence-summary"><p>${escapeHtml(report.executive_summary)}</p><div class="conclusion-grid"><div><h3>已观测事实</h3><div class="code-list">${report.observed_impacts.map((item) => `<code>${escapeHtml(item)}</code>`).join("") || `<span class="empty-cell">无已验证事实</span>`}</div></div><div><h3>证据缺口</h3><div class="code-list">${evidence.gaps.map((item) => `<code class="muted-code">${escapeHtml(item)}</code>`).join("") || `<span class="empty-cell">无合同缺口</span>`}</div></div><div><h3>假设边界</h3><div class="code-list">${report.risk_notes.map((item) => `<code>${escapeHtml(item)}</code>`).join("") || `<span class="empty-cell">无新增假设</span>`}</div></div><div><h3>研究建议</h3><div class="proposal-list">${report.research_proposals.map((item) => `<article><div><strong>${escapeHtml(item.hypothesis)}</strong>${pill(item.g0_status)}</div><small>来源 ${escapeHtml(statusText(item.source_capacity))} / 历史 ${escapeHtml(statusText(item.history_capacity))} / ${escapeHtml(item.holdout_role)}</small></article>`).join("") || `<span class="empty-cell">无新研究建议</span>`}</div></div></div></div></section>
    <div class="split-layout"><section class="panel"><header class="panel-head"><div><h2>智能体复核链</h2><p>固定角色与状态</p></div><span>${report.agent_reports.length}</span></header><div class="agent-list">${report.agent_reports.map((row) => `<article><div>${pill(row.status)}<strong>${escapeHtml(row.role_id)}</strong></div><p>${escapeHtml(row.summary)}</p></article>`).join("")}</div></section><section class="panel"><header class="panel-head"><div><h2>来源证据</h2><p>正文质量与三类时间</p></div><span>${report.sources.length}</span></header><div class="source-list">${report.sources.map((row) => `<article><div class="source-title"><strong>${escapeHtml(row.title || row.final_url)}</strong>${pill(row.content_quality)}</div><small>发布 ${escapeHtml(formatTime(row.published_at))} / 修改 ${escapeHtml(formatTime(row.modified_at))} / 观测 ${escapeHtml(formatTime(row.observed_at))}</small><small>${escapeHtml(row.parser_version)} / ${escapeHtml(row.extractor)} / ${escapeHtml(shortHash(row.body_hash))}</small><p>${escapeHtml(row.final_url)}</p></article>`).join("") || `<div class="empty-cell">无可验证来源</div>`}</div></section></div>`;
}

function navSparkline(points) {
  const rows = Array.isArray(points) ? points.filter((row) => Number.isFinite(Number(row.signal)) && Number.isFinite(Number(row.executable))) : [];
  if (rows.length < 2) return `<div class="paper-chart-empty">等待第二个净值点</div>`;
  const values = rows.flatMap((row) => [Number(row.signal), Number(row.executable)]);
  const low = Math.min(...values);
  const high = Math.max(...values);
  const range = Math.max(high - low, 0.0001);
  const coordinates = (key) => rows.map((row, index) => {
    const x = rows.length === 1 ? 0 : (index / (rows.length - 1)) * 100;
    const y = 36 - ((Number(row[key]) - low) / range) * 32;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(" ");
  const baselineY = 36 - ((1 - low) / range) * 32;
  const baseline = baselineY >= 4 && baselineY <= 36 ? `<line class="paper-chart-baseline" x1="0" y1="${baselineY.toFixed(2)}" x2="100" y2="${baselineY.toFixed(2)}"></line>` : "";
  return `<svg class="paper-chart" viewBox="0 0 100 40" preserveAspectRatio="none" role="img" aria-label="信号净值与可执行净值走势"><title>信号净值与可执行净值走势</title>${baseline}<polyline class="paper-signal-line" points="${coordinates("signal")}"></polyline><polyline class="paper-executable-line" points="${coordinates("executable")}"></polyline></svg><div class="paper-chart-legend"><span class="signal-key">信号净值</span><span class="executable-key">可执行净值</span><small>${rows.length} 个观测点</small></div>`;
}

function paperRebalanceEvents(portfolio) {
  const events = portfolio?.rebalances?.events;
  return Array.isArray(events) ? events.filter((event) => Array.isArray(event?.fills) && event.fills.length) : [];
}

function paperRebalanceScopeText(value) {
  return {
    initial: "初始建仓",
    g20_cross_sleeve: "G20 月度调仓",
    c60_sleeve: "C60 日度调仓",
  }[value] || "模拟调仓";
}

function marketPrice(value, symbol = "") {
  const price = Number(value);
  if (!Number.isFinite(price)) return "-";
  const isCrypto = String(symbol).endsWith("USDT");
  const digits = isCrypto ? (price >= 1000 ? 2 : price >= 1 ? 4 : 6) : (price >= 1 ? 2 : 4);
  return price.toLocaleString("zh-CN", { maximumFractionDigits: digits });
}

const paperCurveState = {
  range: "all",
  mode: "return",
  showBenchmark: true,
  hiddenSeries: new Set(),
  zoom: 1,
  pan: 0,
  drag: null,
};
let paperCurveModel = null;

const PAPER_CURVE_SERIES = {
  G20: { id: "g20", label: "美股轮动（G20）" },
  C60: { id: "c60", label: "加密趋势（C60）" },
  GC5: { id: "gc5", label: "固定组合（GC5）" },
  D15: { id: "d15", label: "动态组合（D15）" },
  benchmark: { id: "benchmark", label: "标普 500（SPY）" },
};

function clamp(value, minimum, maximum) {
  return Math.min(Math.max(value, minimum), maximum);
}

function formatSignedMoney(value, asset) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return `${number > 0 ? "+" : number < 0 ? "−" : ""}${formatMoney(Math.abs(number), asset)}`;
}

function paperPerformanceText(value) {
  const number = Number(value);
  return Number.isFinite(number) ? formatPercent(number) : "—";
}

function paperPerformanceTone(value) {
  const number = Number(value);
  return number > 0 ? "good-text" : number < 0 ? "bad-text" : "";
}

function paperPeriodDetail(performance, returnKey, pnlKey, asset) {
  return `${paperPerformanceText(performance?.[returnKey])} · ${formatSignedMoney(performance?.[pnlKey], asset)}`;
}

function paperCurveSeries(snapshot) {
  const portfolios = Array.isArray(snapshot.portfolios) ? snapshot.portfolios : [];
  const strategies = portfolios.map((portfolio) => {
    const spec = PAPER_CURVE_SERIES[portfolio.label];
    const points = (portfolio.nav?.points || []).map((point) => ({
      marked_at: point.marked_at,
      time: Date.parse(point.marked_at),
      nav: Number(point.executable),
      equity: Number(point.executable_equity),
    })).filter((point) => Number.isFinite(point.time) && Number.isFinite(point.nav));
    return spec ? { ...spec, kind: "strategy", portfolio, points } : null;
  }).filter((row) => row && row.points.length >= 2);
  const benchmark = (snapshot.benchmarks || []).find((row) => row.status === "available" && Array.isArray(row.nav?.points));
  if (benchmark) {
    const points = benchmark.nav.points.map((point) => ({
      marked_at: point.marked_at,
      time: Date.parse(point.marked_at),
      nav: Number(point.nav),
      equity: Number(point.equity),
    })).filter((point) => Number.isFinite(point.time) && Number.isFinite(point.nav));
    if (points.length >= 2) strategies.push({ ...PAPER_CURVE_SERIES.benchmark, label: benchmark.label, kind: "benchmark", benchmark, points });
  }
  return strategies;
}

function paperCurveValue(point, mode) {
  return mode === "equity" ? Number(point.equity) : Number(point.nav);
}

function paperCurveAxisValue(value, mode, asset) {
  return mode === "equity" ? formatMoney(value, asset) : formatPercent(value - 1);
}

function paperCurveDomain(series) {
  const allTimes = series.flatMap((row) => row.points.map((point) => point.time));
  const first = Math.min(...allTimes);
  const last = Math.max(...allTimes);
  const day = 24 * 60 * 60 * 1000;
  const requested = { "30": 30 * day, "90": 90 * day, "180": 180 * day }[paperCurveState.range];
  const baseStart = requested ? Math.max(first, last - requested) : first;
  const baseRange = Math.max(last - baseStart, 1);
  const visibleRange = Math.max(baseRange / paperCurveState.zoom, 1);
  const start = baseStart + (baseRange - visibleRange) * paperCurveState.pan;
  return { start, end: start + visibleRange, fullStart: first, fullEnd: last };
}

function paperCurveNearestPoint(points, time) {
  return points.reduce((nearest, point) => (
    Math.abs(point.time - time) < Math.abs(nearest.time - time) ? point : nearest
  ));
}

function paperPerformanceChart(snapshot) {
  const series = paperCurveSeries(snapshot);
  const strategySeries = series.filter((row) => row.kind === "strategy");
  if (strategySeries.length < 2) return `<section class="panel full-panel"><div class="paper-chart-empty">等待四账户的第二个净值点</div></section>`;
  const hasBenchmark = series.some((row) => row.kind === "benchmark");
  const hasEquity = strategySeries.every((row) => row.points.every((point) => Number.isFinite(point.equity)));
  if (paperCurveState.mode === "equity" && !hasEquity) paperCurveState.mode = "return";
  const visible = series.filter((row) => {
    if (row.kind === "benchmark") return hasBenchmark && paperCurveState.showBenchmark;
    return !paperCurveState.hiddenSeries.has(row.id);
  });
  const displayed = visible.length ? visible : strategySeries;
  const domain = paperCurveDomain(series);
  const chartSeries = displayed.map((row) => ({
    ...row,
    visiblePoints: row.points.filter((point) => point.time >= domain.start && point.time <= domain.end),
  })).filter((row) => row.visiblePoints.length >= 2);
  if (!chartSeries.length) return `<section class="panel full-panel"><div class="paper-chart-empty">当前缩放区间没有足够的净值点</div></section>`;
  const values = chartSeries.flatMap((row) => row.visiblePoints.map((point) => paperCurveValue(point, paperCurveState.mode))).filter(Number.isFinite);
  const baseline = paperCurveState.mode === "equity" ? 10000 : 1;
  const observedLow = Math.min(baseline, ...values);
  const observedHigh = Math.max(baseline, ...values);
  const padding = Math.max((observedHigh - observedLow) * 0.09, paperCurveState.mode === "equity" ? 10 : 0.002);
  const low = observedLow - padding;
  const high = observedHigh + padding;
  const width = 1120;
  const height = 390;
  const left = paperCurveState.mode === "equity" ? 108 : 66;
  const right = 22;
  const top = 18;
  const bottom = 42;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const x = (time) => left + ((time - domain.start) / Math.max(domain.end - domain.start, 1)) * plotWidth;
  const y = (value) => top + ((high - value) / Math.max(high - low, 0.000001)) * plotHeight;
  const ticks = Array.from({ length: 5 }, (_, index) => high - ((high - low) * index) / 4);
  const grid = ticks.map((value) => `<line x1="${left}" y1="${y(value).toFixed(2)}" x2="${width - right}" y2="${y(value).toFixed(2)}"></line>`).join("");
  const xTicks = Array.from({ length: 5 }, (_, index) => domain.start + ((domain.end - domain.start) * index) / 4);
  const verticalGrid = xTicks.map((value) => `<line x1="${x(value).toFixed(2)}" y1="${top}" x2="${x(value).toFixed(2)}" y2="${height - bottom}"></line>`).join("");
  const lines = chartSeries.map((row) => `<polyline class="paper-curve-line paper-curve-${row.id}" points="${row.visiblePoints.map((point) => `${x(point.time).toFixed(2)},${y(paperCurveValue(point, paperCurveState.mode)).toFixed(2)}`).join(" ")}"></polyline>`).join("");
  const yLabels = ticks.map((value) => `<span style="top:${((y(value) / height) * 100).toFixed(2)}%">${escapeHtml(paperCurveAxisValue(value, paperCurveState.mode, snapshot.reporting_asset))}</span>`).join("");
  const xLabels = xTicks.map((value, index) => `<span class="paper-x-label-${index}" style="left:${((x(value) / width) * 100).toFixed(2)}%">${escapeHtml(formatShortDate(new Date(value).toISOString()))}</span>`).join("");
  const rangeText = { all: "年初至今", "180": "近 180 天", "90": "近 90 天", "30": "近 30 天" }[paperCurveState.range];
  const modeText = paperCurveState.mode === "equity" ? "账户金额" : "累计收益率";
  paperCurveModel = { series: chartSeries, domain, left, right, top, bottom, width, height, mode: paperCurveState.mode, asset: snapshot.reporting_asset };
  const lineToggles = strategySeries.map((row) => `<button class="paper-series-toggle ${paperCurveState.hiddenSeries.has(row.id) ? "is-hidden" : ""}" type="button" data-paper-curve-action="series" data-series="${row.id}" aria-pressed="${!paperCurveState.hiddenSeries.has(row.id)}"><i></i><span>${escapeHtml(row.label)}</span><small>${escapeHtml(paperPerformanceText(row.portfolio.nav?.performance?.total_return_fraction))}</small></button>`).join("");
  const benchmarkToggle = `<button class="paper-series-toggle paper-series-benchmark ${!hasBenchmark || !paperCurveState.showBenchmark ? "is-hidden" : ""}" type="button" data-paper-curve-action="benchmark" ${hasBenchmark ? "" : "disabled"} aria-pressed="${hasBenchmark && paperCurveState.showBenchmark}"><i></i><span>${hasBenchmark ? escapeHtml(series.find((row) => row.kind === "benchmark").label) : "大盘基准待补齐"}</span><small>${hasBenchmark ? escapeHtml(paperPerformanceText(series.find((row) => row.kind === "benchmark").benchmark.nav.performance?.total_return_fraction)) : "需要完整公开回放"}</small></button>`;
  return `<section class="panel full-panel paper-performance-panel"><header class="panel-head"><div><h2>策略收益曲线</h2><p>${escapeHtml(formatDate(new Date(domain.start).toISOString()))} 至 ${escapeHtml(formatDate(new Date(domain.end).toISOString()))} / ${modeText} / 四条策略线为独立模拟账户</p></div><span>${escapeHtml(rangeText)} · ${paperCurveState.zoom.toFixed(1)}×</span></header><div class="paper-performance-toolbar"><div class="paper-range-buttons">${[["all", "YTD"], ["180", "180D"], ["90", "90D"], ["30", "30D"]].map(([value, label]) => `<button type="button" class="${paperCurveState.range === value ? "active" : ""}" data-paper-curve-action="range" data-value="${value}">${label}</button>`).join("")}</div><div class="paper-mode-buttons"><button type="button" class="${paperCurveState.mode === "return" ? "active" : ""}" data-paper-curve-action="mode" data-value="return">收益率</button><button type="button" class="${paperCurveState.mode === "equity" ? "active" : ""}" data-paper-curve-action="mode" data-value="equity" ${hasEquity ? "" : "disabled"}>金额</button></div><button type="button" class="paper-reset-button" data-paper-curve-action="reset">复位视图</button><span class="paper-gesture-hint">滚轮缩放 · 拖动平移 · 悬停查看</span></div><div class="paper-series-toggles">${lineToggles}${benchmarkToggle}</div><div class="paper-performance-plot"><svg class="paper-performance-chart" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="四账户模拟收益曲线与可选标普 500 对比"><title>四账户模拟收益曲线与可选标普 500 对比</title><g class="paper-ytd-grid">${grid}${verticalGrid}</g><line class="paper-curve-baseline" x1="${left}" y1="${y(baseline).toFixed(2)}" x2="${width - right}" y2="${y(baseline).toFixed(2)}"></line>${lines}<line class="paper-curve-crosshair" x1="0" y1="${top}" x2="0" y2="${height - bottom}" hidden></line><rect class="paper-curve-hit-area" x="${left}" y="${top}" width="${plotWidth}" height="${plotHeight}"></rect></svg><div class="paper-curve-y-scale" aria-hidden="true">${yLabels}</div><div class="paper-curve-x-scale" aria-hidden="true">${xLabels}</div><div class="paper-curve-tooltip" hidden></div></div><div class="paper-performance-caption"><p>四条策略线均为可执行净值；可选灰色虚线为同起点的标普 500 ETF（SPY）未复权价格收益，不含股息再投资。曲线用于模拟盘比较，不代表真实账户收益。</p><span>调仓细节请在下方 K 线与调仓表中查看。</span></div></section>`;
}

function wirePaperPerformanceChart() {
  const plot = document.querySelector("#view-paper .paper-performance-plot");
  if (!plot || !paperCurveModel) return;
  const svg = plot.querySelector("svg");
  const tooltip = plot.querySelector(".paper-curve-tooltip");
  const crosshair = plot.querySelector(".paper-curve-crosshair");
  const hideTooltip = () => {
    tooltip.hidden = true;
    crosshair.hidden = true;
  };
  const showTooltip = (event) => {
    if (paperCurveState.drag) return;
    const rect = svg.getBoundingClientRect();
    const ratio = clamp((event.clientX - rect.left) / Math.max(rect.width, 1), 0, 1);
    const time = paperCurveModel.domain.start + ratio * (paperCurveModel.domain.end - paperCurveModel.domain.start);
    const chartX = paperCurveModel.left + ratio * (paperCurveModel.width - paperCurveModel.left - paperCurveModel.right);
    const rows = paperCurveModel.series.map((series) => ({ series, point: paperCurveNearestPoint(series.visiblePoints, time) }));
    const titlePoint = rows[0]?.point;
    crosshair.setAttribute("x1", chartX.toFixed(2));
    crosshair.setAttribute("x2", chartX.toFixed(2));
    crosshair.hidden = false;
    tooltip.innerHTML = `<strong>${escapeHtml(formatDate(titlePoint?.marked_at))}</strong>${rows.map(({ series, point }) => `<div class="paper-tooltip-row paper-tooltip-${series.id}"><span><i></i>${escapeHtml(series.label)}</span><b>净值 ${escapeHtml(point.nav.toFixed(4))}</b><small>${Number.isFinite(point.equity) ? escapeHtml(formatMoney(point.equity, paperCurveModel.asset)) : "金额待下一次快照"}</small></div>`).join("")}`;
    tooltip.style.left = `${clamp(event.clientX - rect.left + 14, 8, Math.max(rect.width - 246, 8))}px`;
    tooltip.style.top = `${clamp(event.clientY - rect.top + 14, 8, Math.max(rect.height - 176, 8))}px`;
    tooltip.hidden = false;
  };
  plot.addEventListener("pointermove", showTooltip);
  plot.addEventListener("pointerleave", hideTooltip);
  plot.addEventListener("wheel", (event) => {
    event.preventDefault();
    paperCurveState.zoom = clamp(paperCurveState.zoom * (event.deltaY < 0 ? 1.35 : 1 / 1.35), 1, 12);
    if (paperCurveState.zoom === 1) paperCurveState.pan = 0;
    renderPaper();
  }, { passive: false });
  plot.addEventListener("pointerdown", (event) => {
    paperCurveState.drag = { startX: event.clientX, startPan: paperCurveState.pan, width: Math.max(svg.getBoundingClientRect().width, 1) };
    plot.classList.add("is-dragging");
    hideTooltip();
  });
}

const paperExplorer = { portfolioId: null, symbol: null, window: "90" };

function paperTradeRows(portfolio) {
  return paperRebalanceEvents(portfolio).flatMap((event) => event.fills.map((fill) => ({ ...fill, observed_at: event.observed_at, scope: event.scope }))).reverse();
}

function paperMarketExplorer(snapshot) {
  const portfolios = Array.isArray(snapshot.portfolios) ? snapshot.portfolios : [];
  const portfolio = portfolios.find((row) => row.portfolio_id === paperExplorer.portfolioId) || portfolios[0];
  const barsBySymbol = snapshot.market_charts?.bars_by_symbol;
  if (!portfolio || !barsBySymbol || typeof barsBySymbol !== "object") {
    return `<section class="panel full-panel"><header class="panel-head"><div><h2>调仓与 K 线</h2><p>仅显示已验证的公开 OHLC；旧快照不补造历史蜡烛。</p></div></header><div class="paper-chart-empty">当前发布尚未包含可视化市场历史。完成已授权的 YTD 回放后将显示 K 线与全部模拟调仓。</div></section>`;
  }
  paperExplorer.portfolioId = portfolio.portfolio_id;
  const symbols = Object.keys(barsBySymbol).filter((symbol) => Array.isArray(barsBySymbol[symbol]) && barsBySymbol[symbol].length);
  const eventSymbols = new Set(paperTradeRows(portfolio).map((row) => row.symbol));
  const firstSymbol = symbols.find((symbol) => eventSymbols.has(symbol) && symbol !== "BIL") || symbols.find((symbol) => symbol !== "BIL") || symbols[0];
  const symbol = symbols.includes(paperExplorer.symbol) ? paperExplorer.symbol : firstSymbol;
  paperExplorer.symbol = symbol;
  const bars = barsBySymbol[symbol]
    .filter((row) => ["open", "high", "low", "close"].every((key) => Number.isFinite(Number(row[key]))))
    .sort((left, right) => Date.parse(left.marked_at) - Date.parse(right.marked_at));
  const trades = paperTradeRows(portfolio).filter((row) => row.symbol === symbol);
  if (!bars.length) return `<section class="panel full-panel"><div class="paper-chart-empty">${escapeHtml(symbol || "当前标的")} 暂无完整 OHLC。</div></section>`;
  const windowSize = Number.parseInt(paperExplorer.window, 10);
  const visibleBars = Number.isInteger(windowSize) && windowSize > 0 ? bars.slice(-windowSize) : bars;
  const visibleStart = Date.parse(visibleBars[0].marked_at);
  const visibleTrades = trades.filter((row) => Date.parse(row.observed_at) >= visibleStart);
  const values = visibleBars.flatMap((row) => [Number(row.high), Number(row.low)]).concat(visibleTrades.map((row) => Number(row.reference_price))).filter(Number.isFinite);
  const observedLow = Math.min(...values);
  const observedHigh = Math.max(...values);
  const padding = Math.max((observedHigh - observedLow) * 0.08, observedHigh * 0.003, 0.000001);
  const low = observedLow - padding;
  const high = observedHigh + padding;
  const width = 1000;
  const height = 360;
  const left = 62;
  const right = 18;
  const top = 18;
  const bottom = 42;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const step = plotWidth / Math.max(visibleBars.length, 1);
  const candleWidth = Math.max(1.1, Math.min(7, step * 0.62));
  const x = (index) => left + step * index + step / 2;
  const y = (value) => top + ((high - Number(value)) / (high - low)) * plotHeight;
  const candles = visibleBars.map((bar, index) => {
    const open = Number(bar.open);
    const close = Number(bar.close);
    const up = close >= open;
    const topY = Math.min(y(open), y(close));
    const bodyHeight = Math.max(Math.abs(y(open) - y(close)), 1.2);
    const summary = `${formatDate(bar.marked_at)} 开 ${marketPrice(open, symbol)} 高 ${marketPrice(bar.high, symbol)} 低 ${marketPrice(bar.low, symbol)} 收 ${marketPrice(close, symbol)}`;
    return `<g class="paper-candle ${up ? "paper-candle-up" : "paper-candle-down"}"><title>${escapeHtml(summary)}</title><line x1="${x(index).toFixed(2)}" y1="${y(bar.high).toFixed(2)}" x2="${x(index).toFixed(2)}" y2="${y(bar.low).toFixed(2)}"></line><rect x="${(x(index) - candleWidth / 2).toFixed(2)}" y="${topY.toFixed(2)}" width="${candleWidth.toFixed(2)}" height="${bodyHeight.toFixed(2)}"></rect></g>`;
  }).join("");
  const tradeMarkers = visibleTrades.map((trade) => {
    const tradeTime = Date.parse(trade.observed_at);
    const barIndex = visibleBars.reduce((closest, bar, candidate) => Math.abs(Date.parse(bar.marked_at) - tradeTime) < Math.abs(Date.parse(visibleBars[closest].marked_at) - tradeTime) ? candidate : closest, 0);
    const markerX = x(barIndex);
    const markerY = y(trade.reference_price);
    const buy = trade.side === "buy";
    const path = buy ? `M ${markerX.toFixed(2)} ${(markerY - 7).toFixed(2)} l -5 8 h 10 z` : `M ${markerX.toFixed(2)} ${(markerY + 7).toFixed(2)} l -5 -8 h 10 z`;
    const detail = `${formatTime(trade.observed_at)} ${buy ? "买入" : "卖出"} ${trade.symbol} / ${formatQuantity(trade.quantity)} / ${marketPrice(trade.reference_price, symbol)}`;
    return `<path class="paper-trade-marker ${buy ? "paper-trade-buy" : "paper-trade-sell"}" d="${path}"><title>${escapeHtml(detail)}</title></path>`;
  }).join("");
  const ticks = Array.from({ length: 5 }, (_, index) => high - ((high - low) * index) / 4);
  const grid = ticks.map((value) => `<line x1="${left}" y1="${y(value).toFixed(2)}" x2="${width - right}" y2="${y(value).toFixed(2)}"></line>`).join("");
  const yLabels = ticks.map((value) => `<span style="top:${((y(value) / height) * 100).toFixed(2)}%">${escapeHtml(marketPrice(value, symbol))}</span>`).join("");
  const tickIndices = [...new Set([0, Math.round((visibleBars.length - 1) / 3), Math.round(((visibleBars.length - 1) * 2) / 3), visibleBars.length - 1])];
  const xLabels = tickIndices.map((index, labelIndex) => `<span class="paper-x-label-${labelIndex}" style="left:${((x(index) / width) * 100).toFixed(2)}%">${escapeHtml(formatShortDate(visibleBars[index].marked_at))}</span>`).join("");
  const allTrades = paperTradeRows(portfolio);
  const windowLabel = windowSize > 0 ? `近 ${windowSize} 个交易日` : "YTD 全程";
  const priceBasisNote = symbol === "BIL" ? "BIL 为派息型短债 ETF；此处显示未复权价格，月初除息跳空正常，调仓标记采用同一价格口径。" : "显示原始未复权 OHLC；调仓三角为无订单模拟成交，采用同一价格口径。";
  return `<section class="panel full-panel paper-market-panel"><header class="panel-head"><div><h2>调仓与 K 线</h2><p>公开日线 OHLC / ${escapeHtml(portfolioText(portfolio.label))} 可执行层模拟成交标记</p></div><span>${visibleBars.length}/${bars.length} 根 K 线</span></header><div class="paper-chart-controls"><label>组合<select id="paper-portfolio-select">${portfolios.map((row) => `<option value="${escapeHtml(row.portfolio_id)}"${row.portfolio_id === portfolio.portfolio_id ? " selected" : ""}>${escapeHtml(portfolioText(row.label))}</option>`).join("")}</select></label><label>行情标的<select id="paper-symbol-select">${symbols.map((item) => `<option value="${escapeHtml(item)}"${item === symbol ? " selected" : ""}>${escapeHtml(item)}${eventSymbols.has(item) ? " · 有调仓" : ""}</option>`).join("")}</select></label><label>展示区间<select id="paper-window-select"><option value="45"${paperExplorer.window === "45" ? " selected" : ""}>近 45 个交易日</option><option value="90"${paperExplorer.window === "90" ? " selected" : ""}>近 90 个交易日</option><option value="all"${paperExplorer.window === "all" ? " selected" : ""}>YTD 全程</option></select></label><div><span>当前标记</span><strong>${visibleTrades.length} 笔 / 标的总计 ${trades.length} 笔</strong></div></div><div class="paper-candle-plot"><svg class="paper-candle-chart" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="${escapeHtml(`${symbol} ${windowLabel}日 K 线及模拟调仓标记`)}"><title>${escapeHtml(`${symbol} ${windowLabel}日 K 线及模拟调仓标记`)}</title><g class="paper-ytd-grid">${grid}</g>${candles}${tradeMarkers}</svg><div class="paper-candle-y-scale" aria-hidden="true">${yLabels}</div><div class="paper-candle-x-scale" aria-hidden="true">${xLabels}</div></div><div class="paper-candle-legend"><span class="paper-candle-up-key">收涨</span><span class="paper-candle-down-key">收跌</span><span class="paper-buy-key">模拟买入</span><span class="paper-sell-key">模拟卖出</span><small>${escapeHtml(priceBasisNote)}</small></div><div class="table-wrap"><table><thead><tr><th>调仓时间</th><th>类型</th><th>方向 / 标的</th><th>数量</th><th>参考价</th><th>名义金额</th><th>模拟成本</th></tr></thead><tbody>${allTrades.map((trade) => `<tr><td>${escapeHtml(formatTime(trade.observed_at))}<small>${escapeHtml(paperRebalanceScopeText(trade.scope))}</small></td><td>${pill(trade.scope === "c60_sleeve" ? "paper" : "pass")}</td><td><strong>${escapeHtml(trade.side === "buy" ? "买入" : "卖出")} ${escapeHtml(trade.symbol)}</strong><small>${escapeHtml(trade.sleeve_id.toUpperCase())} 袖套</small></td><td>${escapeHtml(formatQuantity(trade.quantity))}</td><td>${escapeHtml(marketPrice(trade.reference_price, trade.symbol))}</td><td>${escapeHtml(formatMoney(trade.notional, snapshot.reporting_asset))}</td><td>${escapeHtml(formatMoney(trade.cost, snapshot.reporting_asset))}</td></tr>`).join("") || `<tr><td colspan="7" class="empty-cell">该组合尚无实际模拟调仓</td></tr>`}</tbody></table></div></section>`;
}

function renderPaper() {
  const payload = state.models.paper.payload;
  if (!payload.snapshot) {
    $("view-paper").innerHTML = unavailableBlock("模拟盘曲线正在准备", "控制台已保留独立入口；2026 年初至最近完整交易日的公开行情模拟完成后显示四账户曲线。");
    return;
  }
  const snapshot = payload.snapshot;
  const decision = snapshot.latest_decision || {};
  const g20 = decision.g20 || {};
  const c60 = decision.c60 || {};
  const portfolioCards = snapshot.portfolios.map((portfolio) => {
    const nav = portfolio.nav;
    const performance = nav.performance || {};
    const allocation = portfolio.allocation;
    const holdings = portfolio.holdings || [];
    const divergence = Number(nav.executable) - Number(nav.signal);
    return `<article class="paper-card">
      <header class="paper-card-head"><div><span>${escapeHtml(portfolio.portfolio_id)}</span><h2>${escapeHtml(portfolioText(portfolio.label))}</h2></div>${pill(portfolio.status)}</header>
      <div class="paper-nav-grid paper-performance-grid"><div><span>当前模拟资产</span><strong>${escapeHtml(formatMoney(performance.current_equity, snapshot.reporting_asset))}</strong><small>可执行净值 ${escapeHtml(Number(nav.executable).toFixed(6))}</small></div><div><span>日收益</span><strong class="${paperPerformanceTone(performance.day_return_fraction)}">${escapeHtml(paperPerformanceText(performance.day_return_fraction))}</strong><small>${escapeHtml(formatSignedMoney(performance.day_pnl, snapshot.reporting_asset))}</small></div><div><span>本月收益</span><strong class="${paperPerformanceTone(performance.month_return_fraction)}">${escapeHtml(paperPerformanceText(performance.month_return_fraction))}</strong><small>${escapeHtml(formatSignedMoney(performance.month_pnl, snapshot.reporting_asset))}</small></div><div><span>年初至今</span><strong class="${paperPerformanceTone(performance.total_return_fraction)}">${escapeHtml(paperPerformanceText(performance.total_return_fraction ?? nav.since_start_return_fraction))}</strong><small>${escapeHtml(formatSignedMoney(performance.total_pnl, snapshot.reporting_asset))}</small></div></div>
      ${navSparkline(nav.points)}
      <dl class="fact-list paper-facts"><div><dt>信号 / 可执行净值</dt><dd>${escapeHtml(Number(nav.signal).toFixed(6))} / ${escapeHtml(Number(nav.executable).toFixed(6))}</dd></div><div><dt>执行偏差</dt><dd class="${divergence < -0.0001 ? "bad-text" : ""}">${escapeHtml(formatPercent(divergence))}</dd></div><div><dt>日收益（最近观测）</dt><dd class="${paperPerformanceTone(performance.day_return_fraction)}">${escapeHtml(paperPeriodDetail(performance, "day_return_fraction", "day_pnl", snapshot.reporting_asset))}</dd></div><div><dt>本月收益</dt><dd class="${paperPerformanceTone(performance.month_return_fraction)}">${escapeHtml(paperPeriodDetail(performance, "month_return_fraction", "month_pnl", snapshot.reporting_asset))}</dd></div><div><dt>当前 / 最大回撤</dt><dd>${escapeHtml(formatPercent(nav.current_drawdown_fraction))} / ${escapeHtml(formatPercent(nav.max_drawdown_fraction))}</dd></div><div><dt>累计基础 / 压力成本</dt><dd>${escapeHtml(formatMoney(nav.cumulative_cost, snapshot.reporting_asset))} / ${escapeHtml(formatMoney(nav.cumulative_stress_cost, snapshot.reporting_asset))}</dd></div><div><dt>G20 / C60 预算</dt><dd>${escapeHtml(formatPercent(allocation.g20_budget))} / ${escapeHtml(formatPercent(allocation.c60_budget))}</dd></div><div><dt>现金权重 / 本轮模拟成交</dt><dd>${escapeHtml(formatPercent(allocation.cash_weight))} / ${portfolio.latest_execution.count}</dd></div></dl>
      <div class="table-wrap"><table><thead><tr><th>持仓</th><th>数量</th><th>权重</th><th>市值</th></tr></thead><tbody>${holdings.map((row) => `<tr><td><strong>${escapeHtml(row.symbol)}</strong></td><td>${escapeHtml(formatQuantity(row.quantity))}</td><td>${escapeHtml(formatPercent(row.actual_weight))}</td><td>${escapeHtml(formatMoney(row.market_value, snapshot.reporting_asset))}</td></tr>`).join("") || `<tr><td colspan="4" class="empty-cell">全现金</td></tr>`}</tbody></table></div>
    </article>`;
  }).join("");
  $("view-paper").innerHTML = `<div class="paper-guard"><div><strong>模拟盘 / 不具备订单权限</strong><p>四个账户各以 10,000 美元等值起始。“信号净值”按理想分数份额且不计成本；“可执行净值”应用数量步长、最小名义金额和模拟成本。2026 年初至今曲线来自经所有者授权的公开历史行情模拟，不代表真实账户收益；美元与 USDT 仅按 1:1 等值假设展示。</p></div><div>${pill(snapshot.status)}<span class="mono">${escapeHtml(shortHash(snapshot.snapshot_hash))}</span></div></div>
    <div class="metrics metrics-four">${metric("策略组合", String(snapshot.portfolios.length), "美股轮动 / 加密趋势 / 固定组合 / 动态组合", "accent")}${metric("年初模拟起点", formatTime(snapshot.forward_start_at), "2026 年初至今公开行情模拟", "")}${metric("美股轮动当前标的", g20.selected_symbol || "-", "63 日代理资产动量第一名 / 风险预算 20%", "good")}${metric("动态组合加密预算", formatPercent(decision.d15_c60_budget), `合格加密资产 ${c60.eligible_count ?? "-"} 个`, "")}</div>
    ${paperPerformanceChart(snapshot)}
    ${paperMarketExplorer(snapshot)}
    <section class="panel full-panel"><header class="panel-head"><div><h2>最新策略决定</h2><p>决定时间 ${escapeHtml(formatTime(decision.decision_time))} / 数据截止 ${escapeHtml(formatTime(decision.data_cutoff))}</p></div>${pill(c60.btc_system_gate ? "pass" : "block")}</header><div class="paper-decision-band"><div><span>美股轮动配置目标</span><strong>${escapeHtml(Object.entries(g20.target_weights || {}).map(([symbol, weight]) => `${symbol} ${formatPercent(weight)}`).join(" · ") || "-")}</strong></div><div><span>加密动量前两名</span><strong>${escapeHtml((c60.candidates || []).join(" / ") || "无正动量候选")}</strong></div><div><span>比特币系统风控</span><strong>${escapeHtml(c60.btc_system_gate ? "通过" : "未通过")}</strong></div><div><span>波动率缩放比例</span><strong>${escapeHtml(formatPercent(c60.volatility_scalar))}</strong></div></div></section>
    <div class="paper-grid">${portfolioCards}</div>
    <section class="panel full-panel"><header class="panel-head"><div><h2>证据边界</h2><p>年初至今模拟与真实成交严格分离</p></div><span>${snapshot.audit_row_count} 行审计记录</span></header><dl class="fact-list"><div><dt>历史曲线</dt><dd>${escapeHtml(statusText(snapshot.history_reference.status || "unavailable"))}</dd></div><div><dt>大盘基准</dt><dd>${snapshot.benchmarks?.length ? "SPY 公开价格基准（未复权）" : "待完整公开回放补齐；未使用替代数据"}</dd></div><div><dt>真实组合净值</dt><dd>不可用：没有真实成交</dd></div><div><dt>订单与私有接口</dt><dd>全部禁用</dd></div><div><dt>审计链</dt><dd class="mono">${escapeHtml(shortHash(snapshot.audit_last_hash))}</dd></div></dl></section>`;
  wirePaperPerformanceChart();
}

function renderAll() {
  renderLive();
  renderPositions();
  renderOrders();
  renderStrategies();
  renderDecisions();
  renderRisk();
  renderReadiness();
  renderSystem();
  renderAlerts();
  renderReports();
  renderIntelligence();
  renderPaper();
}

function renderOffline() {
  const detail = state.error || "权威生产发布不可用";
  const markup = `<div class="offline-state"><div class="offline-kicker">生产数据不可用</div><h2>权威运行来源不可用</h2><p>当前站点没有可验证的生产发布。旧版数据源已停用，页面不会展示过期的账户和交易状态。</p><dl><div><dt>订单执行</dt><dd>已禁用</dd></div><div><dt>权威发布器</dt><dd>不可用</dd></div><div><dt>旧数据回退</dt><dd>已移除</dd></div><div><dt>读取错误</dt><dd>${escapeHtml(detail)}</dd></div></dl></div>`;
  Object.keys(ROUTES).forEach((route) => { $(`view-${route}`).innerHTML = markup; });
}

function renderStatus() {
  const { route } = routeInfo();
  const model = modelForRoute(route);
  const unavailable = state.status !== "ready";
  const stale = !unavailable && isStale(model);
  const badge = $("freshness-badge");
  badge.textContent = unavailable ? "不可用" : (stale ? "数据待更新" : "数据有效");
  badge.className = `status-pill ${unavailable ? "bad" : (stale ? "warn" : "ok")}`;
  $("side-signal").className = `signal ${unavailable ? "bad" : (stale ? "warn" : "ok")}`;
  $("side-status").textContent = unavailable ? "生产来源不可用" : (stale ? "等待下一次数据更新" : "权威发布已验证");
  $("as-of").textContent = model ? `截至 ${formatTime(model.freshness.source_updated_at)}` : "未加载";
}

function showRoute() {
  const { route } = canonicalRouteInfo();
  document.querySelectorAll("[data-view]").forEach((view) => { view.hidden = view.dataset.view !== route; });
  document.querySelectorAll("[data-route]").forEach((link) => {
    const active = link.dataset.route === route;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  $("page-eyebrow").textContent = ROUTES[route][0];
  $("page-title").textContent = ROUTES[route][1];
  $("page-subtitle").textContent = ROUTES[route][2];
  document.body.classList.remove("nav-open");
  if (route === "decisions" && state.status === "ready") renderDecisions();
  renderFreshnessDetail();
  renderStatus();
}

async function load() {
  $("refresh-button").classList.add("spinning");
  $("error-banner").hidden = true;
  try {
    const publicationResponse = await fetchJSON("data/v1/publication.json");
    const publication = publicationResponse.value;
    validatePublication(publication);
    const entries = await Promise.all(Object.entries(MODEL_PATHS).map(async ([type, path]) => [
      type,
      await fetchJSON(releaseModelPath(path, publication.publication_id)),
    ]));
    const responses = Object.fromEntries(entries);
    Object.entries(responses).forEach(([type, response]) => validateModel(response, type, publication));
    const models = Object.fromEntries(Object.entries(responses).map(([type, response]) => [type, response.value]));
    state.status = "ready";
    state.publication = publication;
    state.models = models;
    state.error = null;
    renderAll();
  } catch (error) {
    state.status = "offline";
    state.publication = null;
    state.models = {};
    state.error = error && error.name === "AbortError" ? "请求超时" : String(error && error.message ? error.message : error);
    renderOffline();
    const banner = $("error-banner");
    banner.textContent = "生产读模型不可用；实时订单执行保持禁用。";
    banner.hidden = false;
  } finally {
    $("refresh-button").classList.remove("spinning");
    showRoute();
  }
}

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  try { localStorage.setItem("qount-theme", theme); } catch (error) {}
}

$("theme-button").addEventListener("click", () => {
  applyTheme(document.documentElement.getAttribute("data-theme") === "light" ? "dark" : "light");
});
$("refresh-button").addEventListener("click", load);
$("menu-button").addEventListener("click", () => document.body.classList.toggle("nav-open"));
$("scrim").addEventListener("click", () => document.body.classList.remove("nav-open"));
document.addEventListener("change", (event) => {
  if (event.target.id === "paper-portfolio-select") {
    paperExplorer.portfolioId = event.target.value;
    paperExplorer.symbol = null;
    renderPaper();
  }
  if (event.target.id === "paper-symbol-select") {
    paperExplorer.symbol = event.target.value;
    renderPaper();
  }
  if (event.target.id === "paper-window-select") {
    paperExplorer.window = event.target.value;
    renderPaper();
  }
});
document.addEventListener("click", (event) => {
  const control = event.target.closest("[data-paper-curve-action]");
  if (!control || control.disabled) return;
  const action = control.dataset.paperCurveAction;
  if (action === "range") {
    paperCurveState.range = control.dataset.value;
    paperCurveState.zoom = 1;
    paperCurveState.pan = 0;
  }
  if (action === "mode") paperCurveState.mode = control.dataset.value;
  if (action === "series") {
    const id = control.dataset.series;
    if (paperCurveState.hiddenSeries.has(id)) paperCurveState.hiddenSeries.delete(id);
    else if (paperCurveState.hiddenSeries.size < 3) paperCurveState.hiddenSeries.add(id);
  }
  if (action === "benchmark") paperCurveState.showBenchmark = !paperCurveState.showBenchmark;
  if (action === "reset") {
    paperCurveState.range = "all";
    paperCurveState.mode = "return";
    paperCurveState.showBenchmark = true;
    paperCurveState.hiddenSeries.clear();
    paperCurveState.zoom = 1;
    paperCurveState.pan = 0;
  }
  renderPaper();
});
document.addEventListener("pointermove", (event) => {
  if (!paperCurveState.drag) return;
  const drag = paperCurveState.drag;
  const movement = (drag.startX - event.clientX) / drag.width;
  paperCurveState.pan = clamp(drag.startPan + movement, 0, 1);
});
document.addEventListener("pointerup", () => {
  if (!paperCurveState.drag) return;
  paperCurveState.drag = null;
  renderPaper();
});
window.addEventListener("hashchange", showRoute);
document.addEventListener("visibilitychange", () => { if (!document.hidden) load(); });

showRoute();
load();
setInterval(load, 30000);
setInterval(renderStatus, 1000);
