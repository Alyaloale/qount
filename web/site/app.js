"use strict";

const ROUTES = {
  live: ["权威读模型", "实时运行", "账户、组合与运行状态"],
  positions: ["组合事实", "仓位", "实际仓位、批准目标与决策追踪"],
  orders: ["执行事实", "订单", "订单状态、成交、费用与恢复"],
  strategies: ["治理注册表", "策略", "策略版本、治理状态与最新决定"],
  decisions: ["证据链", "决策追踪", "从市场快照到三方对账的完整链路"],
  risk: ["确定性控制", "风险", "风险决定、会计恒等式与对账"],
  readiness: ["运行门", "就绪检查", "运行门、策略资格与订单权限"],
  system: ["系统观测", "系统健康", "账本完整性与显式健康观测"],
  alerts: ["事件管理", "告警", "分级事件、状态与投递审计"],
  reports: ["确定性报告", "日报", "确定性日报与来源覆盖"],
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
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

function formatMoney(value, asset) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  const formatted = new Intl.NumberFormat("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(number);
  return asset ? `${formatted} ${asset}` : formatted;
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
    stale: "已过期",
    available: "可用",
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
    DELIVERED: "已投递",
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
    paper: "模拟运行",
    research_only: "仅研究",
    read_model_ready: "读模型就绪",
  })[value] || String(value || "-");
}

function tone(value) {
  if (["fresh", "available", "healthy", "clear", "pass", "passed", "FILLED", "RESOLVED", "DELIVERED", "INFO"].includes(value)) return "ok";
  if (["stale", "unavailable", "halt_required", "block", "blocked", "UNKNOWN", "REJECTED", "DEAD_LETTER", "CRITICAL", "HALT"].includes(value)) return "bad";
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
  return ({ clock: "时钟", disk: "磁盘", service: "服务", backup: "备份" })[value] || String(value || "-");
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
    return await response.json();
  } finally {
    clearTimeout(timer);
  }
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
  const expected = Object.keys(MODEL_PATHS).sort();
  const actual = Object.keys(publication.read_models).sort();
  if (JSON.stringify(actual) !== JSON.stringify(expected)) throw new Error("read model 集合不完整");
}

function validateModel(model, type, publication) {
  assertObject(model, type);
  assertObject(model.payload, `${type}.payload`);
  assertObject(model.freshness, `${type}.freshness`);
  assertObject(model.source_hashes, `${type}.source_hashes`);
  if (model.schema_version !== 1 || model.read_model_type !== type) throw new Error(`${type} schema 不匹配`);
  const reference = publication.read_models[type];
  if (!reference || reference.read_model_id !== model.read_model_id || reference.read_model_hash !== model.read_model_hash) {
    throw new Error(`${type} 与 publication 不一致`);
  }
  if (!["system", "alerts", "reports"].includes(type) && JSON.stringify(model.source_hashes) !== JSON.stringify(publication.source_hashes)) {
    throw new Error(`${type} 权威来源不一致`);
  }
}

function unavailableBlock(title, detail) {
  return `<div class="unavailable-block"><span class="unavailable-mark" aria-hidden="true">!</span><div><strong>${escapeHtml(title)}</strong><p>${escapeHtml(detail)}</p></div></div>`;
}

function renderLive() {
  const model = state.models.overview;
  const payload = model.payload;
  const account = payload.account.status === "available" ? payload.account.values : null;
  const pnl = payload.pnl.status === "available" ? payload.pnl.values : null;
  const portfolio = payload.portfolio;
  const risk = payload.risk;
  const batch = payload.latest_batch;
  const actual = portfolio.actual_positions.status === "available" ? portfolio.actual_positions.values.positions : {};
  const symbols = [...new Set([...Object.keys(portfolio.approved_target), ...Object.keys(actual)])].sort();
  const accountMetrics = account ? `
    <div class="metrics metrics-six">
      ${metric("钱包余额", formatMoney(account.wallet_balance, account.quote_asset), `可用余额 ${formatMoney(account.available_balance)}`, "good")}
      ${metric("账户权益", formatMoney(pnl.equity, account.quote_asset), `本期变化 ${formatMoney(pnl.equity_change)}`, pnl.passed ? "good" : "bad")}
      ${metric("实际总敞口", formatPercent(account.actual_gross_fraction), formatMoney(account.actual_gross_notional, account.quote_asset), "accent")}
      ${metric("保证金占用", formatPercent(account.margin_fraction), formatMoney(account.margin_used, account.quote_asset), "")}
      ${metric("峰值回撤", formatPercent(account.peak_drawdown_fraction), `峰值权益 ${formatMoney(account.peak_equity)}`, account.peak_drawdown_fraction > 0.1 ? "bad" : "")}
      ${metric("当前回撤", formatPercent(account.current_drawdown_fraction), `峰值时点 ${formatTime(account.peak_drawdown_at)}`, account.current_drawdown_fraction > 0.1 ? "bad" : "")}
    </div>` : unavailableBlock("权威账户读数不可用", "当前发布没有可验证的 RuntimeLedger 账户观测。");
  $("view-live").innerHTML = `${accountMetrics}
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
        <header class="panel-head"><div><h2>目标与实际</h2><p>RiskDecision / RuntimeLedger</p></div>${traceLink(portfolio.portfolio_target_id)}</header>
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
  if (payload.summary.status !== "available") {
    $("view-positions").innerHTML = unavailableBlock("仓位读模型不可用", "当前发布没有权威 ledger position facts。");
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
    <div class="table-wrap"><table><thead><tr><th>策略</th><th>状态</th><th>风险预算</th><th>本批决定</th><th>目标</th><th>NAV</th></tr></thead><tbody>
      ${rows.map((row) => { const decision = row.latest_decision; const nav = row.nav.status === "available" ? row.nav.values : null; return `<tr><td><strong>${escapeHtml(row.strategy_id)}</strong><small>v${escapeHtml(row.strategy_version)} / ${escapeHtml(row.strategy_kind)}</small></td><td>${pill(row.promotion_status)}</td><td>${escapeHtml(formatPercent(row.maximum_gross))}<small>压力损失 ${escapeHtml(formatPercent(row.maximum_stress_loss_fraction))}</small></td><td>${decision ? traceLink(decision.decision_id) : "-"}${decision ? `<small>${escapeHtml(decision.reason_codes.join(" / "))}</small>` : ""}</td><td>${decision ? escapeHtml(formatPercent(decision.standalone_target_gross)) : "-"}</td><td>${nav ? escapeHtml(formatMoney(nav.standalone_executable_nav)) : "-"}<small>${nav ? `信号净值 ${escapeHtml(formatMoney(nav.signal_nav))}` : "账本不可用"}</small></td></tr>`; }).join("")}
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
      <section class="panel"><header class="panel-head"><div><h2>账目事实</h2><p>最新 NAV 标记</p></div><span class="mono">${escapeHtml(shortHash(accounting.mark_hash))}</span></header><dl class="fact-list"><div><dt>资金费</dt><dd>${escapeHtml(formatMoney(accounting.funding))}</dd></div><div><dt>手续费</dt><dd>${escapeHtml(formatMoney(accounting.fees))}</dd></div><div><dt>转账</dt><dd>${escapeHtml(formatMoney(accounting.transfers))}</dd></div><div><dt>未解释残差</dt><dd>${escapeHtml(formatMoney(accounting.residual))}</dd></div><div><dt>容差</dt><dd>${escapeHtml(formatMoney(accounting.residual_tolerance))}</dd></div><div><dt>结论</dt><dd>${pill(accounting.passed ? "pass" : "block")}</dd></div></dl></section></div>`;
}

function renderReadiness() {
  const payload = state.models.readiness.payload;
  $("view-readiness").innerHTML = `<div class="readiness-head"><div><span>读模型就绪状态</span><strong>${escapeHtml(statusText(payload.status))}</strong></div>${pill(payload.status)}</div>
    <div class="split-layout"><section class="panel"><header class="panel-head"><div><h2>运行检查项</h2><p>所有订单权限保持关闭</p></div></header><div class="gate-list">${payload.gates.map((gate) => `<div class="gate-row"><span class="gate-signal ${tone(gate.status)}"></span><div><strong>${escapeHtml(gate.gate)}</strong><small>${escapeHtml(gate.detail)}</small></div>${pill(gate.status)}</div>`).join("")}</div></section>
    <section class="panel"><header class="panel-head"><div><h2>策略就绪状态</h2><p>${payload.strategies.length} 个策略</p></div></header><div class="gate-list">${payload.strategies.map((row) => `<div class="gate-row"><span class="gate-signal ${row.current_batch_decision_present ? "ok" : "warn"}"></span><div><strong>${escapeHtml(row.strategy_id)} v${escapeHtml(row.strategy_version)}</strong><small>${escapeHtml(statusText(row.promotion_status))} / 所有者授权${row.owner_authorization_present ? "已存在" : "缺失"}</small></div>${pill(row.live_orders_allowed ? "pass" : "block")}</div>`).join("")}</div></section></div>`;
}

function healthMetric(row) {
  const metrics = row.metrics;
  if (row.component === "clock") return metrics.drift_seconds == null ? "时钟偏差观测不可用" : `时钟偏差 ${metrics.drift_seconds} 秒`;
  if (row.component === "disk") return metrics.free_bytes == null || metrics.total_bytes == null ? "磁盘容量观测不可用" : `可用 ${formatMoney(metrics.free_bytes / 1000000000)} GB / 总计 ${formatMoney(metrics.total_bytes / 1000000000)} GB`;
  if (row.component === "service") return `${metrics.service_name} / 状态 ${metrics.active_state}`;
  return metrics.last_success_at ? `最近成功 ${formatTime(metrics.last_success_at)} / 距今 ${metrics.age_seconds} 秒` : "没有成功备份记录";
}

function renderSystem() {
  const payload = state.models.system.payload;
  const ledger = payload.ledger.status === "available" ? payload.ledger.values : null;
  const health = payload.health.status === "available" ? payload.health.values : null;
  $("view-system").innerHTML = `
    <div class="metrics metrics-four">
      ${metric("系统状态", statusText(payload.summary.status), `${payload.summary.reason_codes.length} 个原因码`, tone(payload.summary.status) === "ok" ? "good" : tone(payload.summary.status) === "bad" ? "bad" : "accent")}
      ${metric("内部账本", ledger ? "已验证" : "不可用", ledger ? `Schema v${ledger.schema_version}` : "没有快照", ledger ? "good" : "bad")}
      ${metric("审计行数", ledger ? String(ledger.audit_row_count) : "-", ledger ? shortHash(ledger.audit_last_hash) : "", "")}
      ${metric("健康观测", health ? String(health.observations.length) : "0", health ? statusText(health.status) : "缺失", health ? (health.status === "healthy" ? "good" : "bad") : "bad")}
    </div>
    ${health ? `<section class="health-band">${health.observations.map((row) => `<article><header><strong>${escapeHtml(componentText(row.component))}</strong>${pill(row.status)}</header><p>${escapeHtml(healthMetric(row))}</p><small>${escapeHtml(formatTime(row.observed_at))} / ${escapeHtml(shortHash(row.observation_hash))}</small></article>`).join("")}</section>` : unavailableBlock("系统健康观测缺失", "时钟、磁盘、服务和备份尚未由生产发布器提供。")}
    <div class="split-layout"><section class="panel"><header class="panel-head"><div><h2>账本完整性</h2><p>SQLite 快照 / JSONL 审计链</p></div><span class="mono">${escapeHtml(shortHash(ledger && ledger.snapshot_hash))}</span></header>${ledger ? `<dl class="fact-list"><div><dt>快照完整性</dt><dd>${pill(ledger.integrity_status === "verified" ? "pass" : "block")}</dd></div><div><dt>审计链</dt><dd>${pill(ledger.audit_chain_status === "verified" ? "pass" : "block")}</dd></div><div><dt>三方对账</dt><dd>${pill(ledger.reconciliation_passed ? "pass" : "block")}</dd></div><div><dt>可恢复订单</dt><dd>${ledger.recoverable_order_count}</dd></div><div><dt>恢复报告</dt><dd>${ledger.recovery_report_count}</dd></div><div><dt>来源更新时间</dt><dd>${escapeHtml(formatTime(ledger.source_updated_at))}</dd></div></dl>` : unavailableBlock("账本不可用", "没有可验证账本快照。")}</section>
      <section class="panel"><header class="panel-head"><div><h2>原因码</h2><p>显式运行结论</p></div>${pill(payload.summary.status)}</header><div class="code-list">${payload.summary.reason_codes.map((reason) => `<code>${escapeHtml(reason)}</code>`).join("") || `<span class="empty-cell">无异常理由</span>`}${payload.summary.unavailable_fields.map((field) => `<code class="muted-code">缺失:${escapeHtml(field)}</code>`).join("")}</div></section></div>`;
}

function renderAlerts() {
  const payload = state.models.alerts.payload;
  if (payload.summary.status !== "available") {
    $("view-alerts").innerHTML = unavailableBlock("通知快照不可用", "当前发布没有 NotificationStore 权威快照。");
    return;
  }
  const summary = payload.summary;
  $("view-alerts").innerHTML = `<div class="metrics metrics-four">${metric("待处理事件", String(summary.open_alert_count), `审计行 ${summary.audit_row_count}`, summary.open_alert_count ? "bad" : "good")}${metric("严重事件", String(summary.severity_counts.CRITICAL), `停机事件 ${summary.severity_counts.HALT}`, summary.severity_counts.CRITICAL || summary.severity_counts.HALT ? "bad" : "good")}${metric("等待投递", String(summary.delivery_state_counts.PENDING + summary.delivery_state_counts.RETRY_WAIT), `等待重试 ${summary.delivery_state_counts.RETRY_WAIT}`, "")}${metric("投递失败", String(summary.delivery_state_counts.DEAD_LETTER), `已投递 ${summary.delivery_state_counts.DELIVERED}`, summary.delivery_state_counts.DEAD_LETTER ? "bad" : "good")}</div>
    <section class="panel full-panel"><header class="panel-head"><div><h2>事件列表</h2><p>事件状态与投递</p></div><span class="mono">${escapeHtml(shortHash(summary.audit_last_hash))}</span></header><div class="incident-list">${payload.alerts.map((row) => `<article><div class="incident-status">${pill(row.severity)}${pill(row.status)}</div><div><strong>${escapeHtml(row.title)}</strong><p>${escapeHtml(row.summary)}</p><small>${escapeHtml(formatTime(row.occurred_at))} / ${escapeHtml(row.category)} / ${traceLink(row.trace_id || row.source_id)}</small></div><div class="delivery-list">${row.deliveries.map((delivery) => `<span>${escapeHtml(delivery.channel)} ${pill(delivery.status)} <small>${delivery.attempt_count}/${delivery.max_attempts}</small></span>`).join("") || "未配置投递通道"}</div></article>`).join("") || `<div class="empty-cell">无告警</div>`}</div></section>`;
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
}

function renderOffline() {
  const detail = state.error || "Dashboard v1 权威发布不可用";
  const markup = `<div class="offline-state"><div class="offline-kicker">生产已停止 / PRODUCTION STOPPED</div><h2>权威运行来源不可用</h2><p>当前站点没有可验证的 Dashboard v1 生产发布。旧版数据源已停用，页面不会展示过期的账户和交易状态。</p><dl><div><dt>订单执行</dt><dd>已禁用</dd></div><div><dt>权威发布器</dt><dd>不可用</dd></div><div><dt>旧数据回退</dt><dd>已移除</dd></div><div><dt>读取错误</dt><dd>${escapeHtml(detail)}</dd></div></dl></div>`;
  Object.keys(ROUTES).forEach((route) => { $(`view-${route}`).innerHTML = markup; });
}

function renderStatus() {
  const { route } = routeInfo();
  const model = modelForRoute(route);
  const stale = state.status !== "ready" || isStale(model);
  const badge = $("freshness-badge");
  badge.textContent = state.status === "ready" ? (stale ? "已过期" : "数据有效") : "不可用";
  badge.className = `status-pill ${stale ? "bad" : "ok"}`;
  $("side-signal").className = `signal ${stale ? "bad" : "ok"}`;
  $("side-status").textContent = state.status === "ready" ? (stale ? "数据已过期" : "权威发布已验证") : "生产来源不可用";
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
  renderStatus();
}

async function load() {
  $("refresh-button").classList.add("spinning");
  $("error-banner").hidden = true;
  try {
    const publication = await fetchJSON("data/v1/publication.json");
    validatePublication(publication);
    const entries = await Promise.all(Object.entries(MODEL_PATHS).map(async ([type, path]) => [type, await fetchJSON(path)]));
    const models = Object.fromEntries(entries);
    Object.entries(models).forEach(([type, model]) => validateModel(model, type, publication));
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
window.addEventListener("hashchange", showRoute);
document.addEventListener("visibilitychange", () => { if (!document.hidden) load(); });

showRoute();
load();
setInterval(load, 30000);
setInterval(renderStatus, 1000);
