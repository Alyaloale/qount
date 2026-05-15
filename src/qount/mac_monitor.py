from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse


HTML_PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>qount 交易看板</title>
  <style>
    :root {
      --bg: #f2ebdf;
      --panel: rgba(255, 249, 239, 0.92);
      --panel-strong: rgba(255, 251, 245, 0.98);
      --ink: #18202d;
      --muted: #5e6675;
      --line: #d6c9b5;
      --good: #236847;
      --warn: #9c5e17;
      --bad: #a2332e;
      --accent: #0d5d7c;
      --accent-soft: #dcecf4;
      --shadow: rgba(45, 32, 10, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(255, 255, 255, 0.6), transparent 36%),
        radial-gradient(circle at top right, rgba(212, 234, 245, 0.5), transparent 28%),
        linear-gradient(180deg, #efe2cc 0%, var(--bg) 45%, #f8f4ed 100%);
      font: 14px/1.5 ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    }
    .wrap {
      max-width: 1360px;
      margin: 0 auto;
      padding: 24px;
    }
    .hero {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 18px;
      margin-bottom: 18px;
    }
    .hero h1 {
      margin: 0 0 6px;
      font-size: 30px;
      letter-spacing: 0.02em;
    }
    .sub {
      color: var(--muted);
      font-size: 13px;
    }
    .controls {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      justify-content: flex-end;
    }
    .btn {
      appearance: none;
      border: 1px solid var(--line);
      background: var(--panel-strong);
      color: var(--ink);
      padding: 10px 14px;
      border-radius: 12px;
      font: inherit;
      cursor: pointer;
      box-shadow: 0 8px 24px var(--shadow);
    }
    .btn:hover {
      border-color: #b9a88f;
      transform: translateY(-1px);
    }
    .btn:disabled {
      opacity: 0.5;
      cursor: wait;
      transform: none;
    }
    .btn-primary {
      background: linear-gradient(180deg, #f8fbfc 0%, var(--accent-soft) 100%);
      border-color: #a9c8d7;
    }
    .btn-danger {
      background: linear-gradient(180deg, #fff6f4 0%, #f5ddd8 100%);
      border-color: #d8b0aa;
    }
    .btn-warn {
      background: linear-gradient(180deg, #fff9ee 0%, #f3dfbf 100%);
      border-color: #d6bf95;
    }
    .action-status {
      margin: 0 0 18px;
      padding: 10px 12px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: rgba(255, 251, 245, 0.7);
      color: var(--muted);
      min-height: 44px;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .summary-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 14px;
      margin-bottom: 16px;
    }
    .layout-2 {
      display: grid;
      grid-template-columns: 1.2fr 1fr;
      gap: 14px;
      margin-bottom: 14px;
    }
    .layout-3 {
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      gap: 14px;
      margin-bottom: 14px;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 16px;
      box-shadow: 0 14px 34px var(--shadow);
      backdrop-filter: blur(10px);
    }
    .panel h2 {
      margin: 0 0 10px;
      font-size: 15px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--accent);
    }
    .metric-label {
      color: var(--muted);
      font-size: 12px;
    }
    .metric {
      font-size: 30px;
      font-weight: 700;
      margin-top: 4px;
    }
    .good { color: var(--good); }
    .warn { color: var(--warn); }
    .bad { color: var(--bad); }
    .table {
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }
    .table th, .table td {
      border-top: 1px solid var(--line);
      padding: 8px 6px;
      text-align: left;
      vertical-align: top;
    }
    .table th {
      color: var(--muted);
      font-weight: 600;
    }
    pre {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font-size: 12px;
      color: var(--muted);
    }
    .badge {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 999px;
      border: 1px solid currentColor;
      font-size: 12px;
    }
    .mini-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 12px;
      margin-bottom: 12px;
    }
    .chart {
      width: 100%;
      height: 220px;
      border: 1px dashed var(--line);
      border-radius: 14px;
      background: linear-gradient(180deg, rgba(255,255,255,0.6) 0%, rgba(255,255,255,0.3) 100%);
      overflow: hidden;
    }
    .chart-empty {
      display: flex;
      align-items: center;
      justify-content: center;
      height: 220px;
      color: var(--muted);
      font-size: 12px;
      border: 1px dashed var(--line);
      border-radius: 14px;
    }
    .positions {
      margin-top: 8px;
    }
    @media (max-width: 1080px) {
      .layout-2, .layout-3 { grid-template-columns: 1fr; }
      .hero { flex-direction: column; }
      .controls { justify-content: flex-start; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <div>
        <h1>qount 交易看板</h1>
        <div class="sub" id="subtitle">正在准备远端数据...</div>
      </div>
      <div class="controls">
        <button class="btn btn-primary" id="btn-refresh">手动刷新</button>
        <button class="btn" id="btn-healthcheck">健康检查</button>
        <button class="btn btn-danger" id="btn-run-once">执行一轮 run-once</button>
      </div>
    </div>
    <div class="action-status" id="action-status">操作就绪。</div>

    <div class="summary-grid" id="summary"></div>

    <div class="panel" style="margin-bottom: 16px;">
      <h2>运行控制</h2>
      <div class="mini-grid" id="control-status">正在加载...</div>
      <div class="controls" style="justify-content:flex-start; margin-top:10px;">
        <button class="btn" id="btn-timer-enable">启用自动运行</button>
        <button class="btn" id="btn-timer-disable">停止自动运行</button>
        <button class="btn" id="btn-mode-live">切到 Live</button>
        <button class="btn" id="btn-mode-paper">切到 Paper</button>
        <button class="btn btn-warn" id="btn-enable-live">启用 Live 放行</button>
        <button class="btn" id="btn-disable-live">关闭 Live 放行</button>
        <button class="btn btn-warn" id="btn-clear-halt">Clear Halt</button>
      </div>
    </div>

    <div class="layout-2">
      <div class="panel">
        <h2>当前 Live 账户</h2>
        <div id="live-account">正在加载...</div>
      </div>
      <div class="panel">
        <h2>模拟账户</h2>
        <div id="paper-account">正在加载...</div>
      </div>
    </div>

    <div class="layout-2">
      <div class="panel">
        <h2>Live 收益曲线</h2>
        <div id="live-curve">正在加载...</div>
      </div>
      <div class="panel">
        <h2>Paper 收益曲线</h2>
        <div id="paper-curve">正在加载...</div>
      </div>
    </div>

    <div class="layout-2">
      <div class="panel">
        <h2>最近 Live 成交 / 订单</h2>
        <div id="live-orders">正在加载...</div>
      </div>
      <div class="panel">
        <h2>最近 Live 运行</h2>
        <div id="live-runs">正在加载...</div>
      </div>
    </div>

    <div class="layout-2">
      <div class="panel">
        <h2>最近 Paper 运行</h2>
        <div id="paper-runs">正在加载...</div>
      </div>
      <div class="panel">
        <h2>信号复盘</h2>
        <div id="review">正在加载...</div>
      </div>
    </div>

    <div class="layout-2">
      <div class="panel">
        <h2>实盘保护</h2>
        <div id="guard">正在加载...</div>
      </div>
      <div class="panel">
        <h2>定时任务</h2>
        <pre id="systemd"></pre>
      </div>
    </div>
  </div>
  <script>
    const actionState = {
      running: false,
    };

    function badge(ok, text) {
      const cls = ok ? "good" : "bad";
      return `<span class="badge ${cls}">${text}</span>`;
    }

    function fmtNum(value, digits = 2) {
      if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
      return Number(value).toFixed(digits);
    }

    function fmtSigned(value, digits = 2) {
      if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
      const num = Number(value);
      const sign = num > 0 ? "+" : "";
      return `${sign}${num.toFixed(digits)}`;
    }

    function fmtTs(value) {
      if (!value) return "-";
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return String(value);
      return new Intl.DateTimeFormat("zh-CN", {
        timeZone: "Asia/Shanghai",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      }).format(date).replace(/\\//g, "-");
    }

    function escapeHtml(text) {
      return String(text)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;");
    }

    function triStateValue(ok, yesText, noText, unknownText = "未检查") {
      if (ok === true) return yesText;
      if (ok === false) return noText;
      return unknownText;
    }

    function triStateClass(ok) {
      if (ok === true) return "good";
      if (ok === false) return "bad";
      return "warn";
    }

    function setActionStatus(text, isError = false) {
      const el = document.getElementById("action-status");
      el.textContent = text;
      el.style.color = isError ? "var(--bad)" : "var(--muted)";
    }

    function setButtonsDisabled(disabled) {
      actionState.running = disabled;
      document.getElementById("btn-refresh").disabled = disabled;
      document.getElementById("btn-healthcheck").disabled = disabled;
      document.getElementById("btn-run-once").disabled = disabled;
      document.getElementById("btn-timer-enable").disabled = disabled;
      document.getElementById("btn-timer-disable").disabled = disabled;
      document.getElementById("btn-mode-live").disabled = disabled;
      document.getElementById("btn-mode-paper").disabled = disabled;
      document.getElementById("btn-enable-live").disabled = disabled;
      document.getElementById("btn-disable-live").disabled = disabled;
      document.getElementById("btn-clear-halt").disabled = disabled;
    }

    function renderSummary(data) {
      const health = data.healthcheck || {};
      const live = data.live_status || {};
      const preflight = live.preflight || {};
      const overview = live.account_overview || {};
      const guard = data.live_guard || {};
      const marketType = live.market_type || health.market_type || preflight.market_type || "spot";
      const freeLabel = marketType === "future" ? "可用保证金" : "现货可用";
      const cards = [
        { title: "Relay", value: triStateValue(health.relay_ok, "正常", "失败"), cls: triStateClass(health.relay_ok), sub: health.relay_error || data.remote.host },
        { title: "交易所", value: triStateValue(health.binance_ok, "正常", "失败"), cls: triStateClass(health.binance_ok), sub: health.binance_error || `${health.exchange_id || "-"} / ${marketType}` },
        { title: "总权益", value: fmtNum(overview.equity_quote), cls: "good", sub: `${live.exchange_id || "-"} / ${live.mode || "-"} / ${marketType}` },
        { title: freeLabel, value: fmtNum((preflight.credentials || {}).quote_free), cls: "good", sub: `${(preflight.credentials || {}).quote_currency || "USDT"}` },
        { title: "实盘保护", value: guard.ok ? "已放行" : "已拦截", cls: guard.ok ? "warn" : "good", sub: guard.reason || (guard.armed ? "持续放行" : "未启用") },
      ];
      document.getElementById("summary").innerHTML = cards.map(card => `
        <div class="panel">
          <div class="metric-label">${card.title}</div>
          <div class="metric ${card.cls}">${card.value}</div>
          <div class="metric-label">${escapeHtml(card.sub || "")}</div>
        </div>
      `).join("");
    }

    function renderControlStatus(data) {
      const live = data.live_status || {};
      const preflight = live.preflight || {};
      const guard = data.live_guard || {};
      const runtime = data.runtime_status || {};
      const timer = data.timer_status || {};
      const marketType = live.market_type || runtime.market_type || preflight.market_type || "spot";
      const cards = [
        { title: "当前模式", value: live.mode || "-", cls: (live.mode || "") === "live" ? "warn" : "good", sub: `${live.exchange_id || "-"} / ${marketType}` },
        { title: "自动运行", value: timer.active ? "运行中" : "已停止", cls: timer.active ? "warn" : "good", sub: timer.enabled ? "已启用" : "未启用" },
        { title: "Live 开关", value: preflight.live_guard?.live_enable ? "开启" : "关闭", cls: preflight.live_guard?.live_enable ? "warn" : "good", sub: preflight.live_guard?.confirmation_ok ? "确认短语已设置" : "确认短语未设置" },
        { title: "放行状态", value: guard.ok ? "已放行" : "未放行", cls: guard.ok ? "warn" : "good", sub: guard.reason || (guard.armed ? "持续生效" : "未启用") },
        { title: "系统停机", value: runtime.halted ? "已停机" : "未停机", cls: runtime.halted ? "bad" : "good", sub: `AI 连败 ${runtime.ai_failure_streak ?? 0}` },
      ];
      document.getElementById("control-status").innerHTML = cards.map(card => `
        <div>
          <div class="metric-label">${card.title}</div>
          <div class="metric ${card.cls}">${card.value}</div>
          <div class="metric-label">${escapeHtml(card.sub || "")}</div>
        </div>
      `).join("");
    }

    function renderLiveAccount(data) {
      const live = data.live_status || {};
      const preflight = live.preflight || {};
      const overview = live.account_overview || {};
      const credentials = preflight.credentials || {};
      const marketType = live.market_type || preflight.market_type || "spot";
      const isContract = marketType === "future";
      const positions = overview.positions || [];
      const positionRows = positions.map(item => isContract ? `
        <tr>
          <td>${escapeHtml(item.symbol)}</td>
          <td>${escapeHtml(item.side || "-")}</td>
          <td>${fmtNum(item.quantity, 6)}</td>
          <td>${fmtNum(item.leverage, 1)}</td>
          <td>${escapeHtml(item.margin_mode || "-")}</td>
          <td>${fmtNum(item.last_price, 2)}</td>
          <td>${fmtNum(item.average_entry_price, 2)}</td>
          <td>${fmtNum(item.liquidation_price, 2)}</td>
          <td class="${Number(item.unrealized_pnl_quote) >= 0 ? "good" : "bad"}">${fmtSigned(item.unrealized_pnl_quote)}</td>
        </tr>
      ` : `
        <tr>
          <td>${escapeHtml(item.symbol)}</td>
          <td>${fmtNum(item.quantity, 6)}</td>
          <td>${fmtNum(item.last_price, 2)}</td>
          <td>${fmtNum(item.average_entry_price, 2)}</td>
          <td class="${Number(item.unrealized_pnl_quote) >= 0 ? "good" : "bad"}">${fmtSigned(item.unrealized_pnl_quote)}</td>
        </tr>
      `).join("");
      const positionHead = isContract
        ? "<tr><th>交易对</th><th>方向</th><th>数量</th><th>杠杆</th><th>保证金模式</th><th>标记价</th><th>均价</th><th>强平价</th><th>未实现盈亏</th></tr>"
        : "<tr><th>交易对</th><th>数量</th><th>现价</th><th>均价</th><th>未实现盈亏</th></tr>";
      const positionEmpty = isContract
        ? '<tr><td colspan="9">当前没有 contract live 持仓。</td></tr>'
        : '<tr><td colspan="5">当前没有 live 持仓。</td></tr>';
      const totalLabel = isContract ? "保证金余额" : "现货总 USDT";
      const freeLabel = isContract ? "可用保证金" : "现货可用 USDT";
      const walletCard = isContract
        ? `<div><div class="metric-label">钱包余额</div><div class="metric">${fmtNum(overview.wallet_balance_quote)}</div></div>`
        : "";
      document.getElementById("live-account").innerHTML = `
        <div class="mini-grid">
          <div><div class="metric-label">当前模式</div><div class="metric">${escapeHtml(live.mode || "-")}</div></div>
          <div><div class="metric-label">市场类型</div><div class="metric">${escapeHtml(marketType)}</div></div>
          <div><div class="metric-label">${freeLabel}</div><div class="metric">${fmtNum(credentials.quote_free)}</div></div>
          <div><div class="metric-label">${totalLabel}</div><div class="metric">${fmtNum(credentials.quote_total)}</div></div>
          ${walletCard}
          <div><div class="metric-label">已实现盈亏</div><div class="metric ${Number(overview.realized_pnl_quote) >= 0 ? "good" : "bad"}">${fmtSigned(overview.realized_pnl_quote)}</div></div>
          <div><div class="metric-label">未实现盈亏</div><div class="metric ${Number(overview.unrealized_pnl_quote) >= 0 ? "good" : "bad"}">${fmtSigned(overview.unrealized_pnl_quote)}</div></div>
          <div><div class="metric-label">总权益</div><div class="metric">${fmtNum(overview.equity_quote)}</div></div>
        </div>
        <div class="positions">
          <table class="table">
            <thead>${positionHead}</thead>
            <tbody>${positionRows || positionEmpty}</tbody>
          </table>
        </div>`;
    }

    function renderPaperAccount(data) {
      const replay = data.paper_replay || {};
      const status = data.paper_status || {};
      const positions = status.paper_portfolio?.positions || {};
      const rows = Object.entries(positions).map(([symbol, pos]) => `
        <tr><td>${escapeHtml(symbol)}</td><td>${fmtNum(pos.quantity, 6)}</td><td>${fmtNum(pos.average_entry_price, 2)}</td></tr>
      `).join("");
      document.getElementById("paper-account").innerHTML = `
        <div class="mini-grid">
          <div><div class="metric-label">模拟现金</div><div class="metric">${fmtNum(replay.cash)}</div></div>
          <div><div class="metric-label">模拟总权益</div><div class="metric">${fmtNum(replay.total_equity)}</div></div>
          <div><div class="metric-label">已实现盈亏</div><div class="metric ${Number(replay.realized_pnl) >= 0 ? "good" : "bad"}">${fmtSigned(replay.realized_pnl)}</div></div>
          <div><div class="metric-label">未实现价值</div><div class="metric">${fmtNum(replay.unrealized_value)}</div></div>
        </div>
        <table class="table">
          <thead><tr><th>交易对</th><th>数量</th><th>平均开仓价</th></tr></thead>
          <tbody>${rows || '<tr><td colspan="3">当前没有模拟持仓。</td></tr>'}</tbody>
        </table>`;
    }

    function renderCurve(targetId, series, lineColor, emptyText) {
      const root = document.getElementById(targetId);
      if (!series || series.length < 2) {
        root.innerHTML = `<div class="chart-empty">${emptyText}</div>`;
        return;
      }
      const values = series.map(item => Number(item.equity_quote || 0));
      const width = 720;
      const height = 220;
      const pad = 18;
      const min = Math.min(...values);
      const max = Math.max(...values);
      const span = max - min || 1;
      const points = values.map((value, index) => {
        const x = pad + ((width - pad * 2) * index / Math.max(values.length - 1, 1));
        const y = height - pad - (((value - min) / span) * (height - pad * 2));
        return `${x},${y}`;
      }).join(" ");
      root.innerHTML = `
        <div class="mini-grid" style="margin-bottom:8px;">
          <div><div class="metric-label">起点</div><div class="metric">${fmtNum(values[0])}</div></div>
          <div><div class="metric-label">终点</div><div class="metric">${fmtNum(values[values.length - 1])}</div></div>
          <div><div class="metric-label">样本点</div><div class="metric">${values.length}</div></div>
        </div>
        <svg class="chart" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
          <polyline points="${points}" fill="none" stroke="${lineColor}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"></polyline>
        </svg>`;
    }

    function renderLiveOrders(data) {
      const live = data.live_status || {};
      const recentOrders = live.recent_orders || [];
      const recentTrades = (live.account_overview || {}).recent_trades || [];
      let rows = "";
      if (recentOrders.length) {
        rows = recentOrders.map(item => `
          <tr>
            <td>${escapeHtml(fmtTs(item.created_at))}</td>
            <td>${escapeHtml(item.symbol || "-")}</td>
            <td>${escapeHtml(item.action || "-")}</td>
            <td>${escapeHtml(item.status || "-")}</td>
            <td>${fmtNum(item.notional_quote)}</td>
          </tr>
        `).join("");
      } else {
        rows = recentTrades.map(item => `
          <tr>
            <td>${escapeHtml(fmtTs(item.timestamp))}</td>
            <td>${escapeHtml(item.symbol || "-")}</td>
            <td>${escapeHtml(item.side || "-")}</td>
            <td>${fmtNum(item.amount, 6)}</td>
            <td>${fmtNum(item.cost)}</td>
          </tr>
        `).join("");
      }
      document.getElementById("live-orders").innerHTML = `
        <table class="table">
          <thead><tr><th>时间</th><th>交易对</th><th>动作</th><th>${recentOrders.length ? "状态" : "数量"}</th><th>${recentOrders.length ? "名义额" : "成交额"}</th></tr></thead>
          <tbody>${rows || '<tr><td colspan="5">当前还没有 live 订单/成交。</td></tr>'}</tbody>
        </table>`;
    }

    function renderRunTable(targetId, runs, emptyText) {
      if (!runs.length) {
        document.getElementById(targetId).innerHTML = `<div>${emptyText}</div>`;
        return;
      }
      document.getElementById(targetId).innerHTML = `
        <table class="table">
          <thead><tr><th>开始时间</th><th>模式</th><th>状态</th><th>摘要</th></tr></thead>
          <tbody>
            ${runs.map(run => `
              <tr>
                <td>${escapeHtml(fmtTs(run.started_at))}</td>
                <td>${escapeHtml(run.mode || "-")}</td>
                <td>${escapeHtml(run.status || "-")}</td>
                <td><pre>${escapeHtml(JSON.stringify(run.summary || {}, null, 2))}</pre></td>
              </tr>
            `).join("")}
          </tbody>
        </table>`;
    }

    function renderReview(data) {
      const review = data.signal_review || {};
      if (review.skipped) {
        document.getElementById("review").innerHTML = `<div class="metric-label">默认监控快照已跳过 review 回填，避免持续拉取 Binance K 线。</div>`;
        return;
      }
      const aggregate = review.aggregate || {};
      const overall = aggregate.overall || {};
      const hold = aggregate.hold || {};
      const actionable = aggregate.actionable || {};
      const reviews = review.reviews || [];
      document.getElementById("review").innerHTML = `
        <div class="mini-grid">
          <div><div class="metric-label">已评估</div><div class="metric">${aggregate.reviewed ?? 0}</div></div>
          <div><div class="metric-label">未完成</div><div class="metric warn">${aggregate.incomplete ?? 0}</div></div>
          <div><div class="metric-label">总体好信号</div><div class="metric good">${(overall.good ?? 0) + (overall.good_hold ?? 0)}</div></div>
          <div><div class="metric-label">总体 flat</div><div class="metric">${overall.flat ?? 0}</div></div>
        </div>
        <div class="mini-grid">
          <div><div class="metric-label">Hold 已评估</div><div class="metric">${hold.reviewed ?? 0}</div></div>
          <div><div class="metric-label">Hold 正确</div><div class="metric good">${hold.good_hold ?? 0}</div></div>
          <div><div class="metric-label">Hold 错过</div><div class="metric warn">${hold.missed_move ?? 0}</div></div>
          <div><div class="metric-label">非 Hold 已评估</div><div class="metric">${actionable.reviewed ?? 0}</div></div>
          <div><div class="metric-label">非 Hold 好</div><div class="metric good">${actionable.good ?? 0}</div></div>
          <div><div class="metric-label">非 Hold 坏</div><div class="metric bad">${actionable.bad ?? 0}</div></div>
          <div><div class="metric-label">非 Hold flat</div><div class="metric">${actionable.flat ?? 0}</div></div>
        </div>
        <table class="table">
          <thead><tr><th>运行</th><th>交易对</th><th>动作</th><th>分组</th><th>结果</th><th>未来涨跌%</th></tr></thead>
          <tbody>
            ${reviews.slice(0, 10).map(item => `
              <tr>
                <td>${escapeHtml(item.run_id ?? "-")}</td>
                <td>${escapeHtml(item.symbol ?? "-")}</td>
                <td>${escapeHtml(item.decision_action || item.action || "-")}</td>
                <td>${escapeHtml(item.review_group || (((item.decision_action || item.action) === "hold") ? "hold" : "actionable") || "-")}</td>
                <td>${escapeHtml(item.outcome || item.reason || item.status || "-")}</td>
                <td>${item.market_future_return_pct !== undefined ? fmtNum(item.market_future_return_pct) : "-"}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>`;
    }

    function renderGuard(data) {
      const guard = data.live_guard || {};
      document.getElementById("guard").innerHTML = `
        <div style="margin-bottom:10px;">${badge(!!guard.ok, guard.ok ? "允许实盘" : "禁止实盘")}</div>
        <pre>${escapeHtml(JSON.stringify(guard, null, 2))}</pre>`;
    }

    function renderError(message) {
      document.getElementById("subtitle").textContent = `加载失败：${message}`;
      document.getElementById("summary").innerHTML = `
        <div class="panel">
          <div class="metric-label">状态</div>
          <div class="metric bad">错误</div>
          <div class="metric-label">${escapeHtml(message)}</div>
        </div>`;
    }

    function applyDashboard(data) {
      const stateText = data.stale ? "显示缓存，后台刷新中" : "最新";
      document.getElementById("subtitle").textContent = `远端：${data.remote.host} / ${data.remote.wsl_user}@${data.remote.wsl_distro} / ${stateText} / 刷新于北京时间 ${fmtTs(data.generated_at)}`;
      renderSummary(data);
      renderControlStatus(data);
      renderLiveAccount(data);
      renderPaperAccount(data);
      renderCurve("live-curve", (data.live_status?.account_overview || {}).equity_curve || [], "#145b7d", "当前还没有足够的 live 权益样本。");
      renderCurve("paper-curve", (data.paper_replay || {}).equity_curve || [], "#9c5e17", "当前还没有足够的 paper 权益样本。");
      renderLiveOrders(data);
      renderRunTable("live-runs", (data.live_status || {}).recent_runs || [], "当前还没有 live 运行记录。");
      renderRunTable("paper-runs", (data.paper_status || {}).recent_runs || [], "当前还没有 paper 运行记录。");
      renderReview(data);
      renderGuard(data);
      document.getElementById("systemd").textContent = data.systemd_status || "";
    }

    async function fetchDashboard() {
      const response = await fetch("/api/dashboard");
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || `HTTP ${response.status}`);
      }
      return data;
    }

    async function load() {
      try {
        const data = await fetchDashboard();
        if (data.loading) {
          document.getElementById("subtitle").textContent = "正在拉取首轮远端数据...";
          return;
        }
        applyDashboard(data);
      } catch (error) {
        renderError(error.message || String(error));
      }
    }

    async function runAction(action) {
      if (actionState.running) return;
      if (action === "run-once") {
        const ok = window.confirm("run-once 可能触发真实下单。确认继续？");
        if (!ok) return;
      } else if (action === "mode-live") {
        const ok = window.confirm("把 qount 切到 Live 模式？");
        if (!ok) return;
      } else if (action === "mode-paper") {
        const ok = window.confirm("把 qount 切到 Paper 模式？");
        if (!ok) return;
      } else if (action === "enable-live") {
        const ok = window.confirm("启用 Live 放行？后续 run-once 和 timer 会按当前 live 配置持续允许真实交易。");
        if (!ok) return;
      } else if (action === "disable-live") {
        const ok = window.confirm("关闭 Live 放行？会立即阻止后续真实下单。");
        if (!ok) return;
      } else if (action === "clear-halt") {
        const ok = window.confirm("清除 halted 并把 AI 连续失败计数归零？");
        if (!ok) return;
      }
      setButtonsDisabled(true);
      setActionStatus(`正在执行 ${action} ...`);
      try {
        const response = await fetch(`/api/actions/${action}`, { method: "POST" });
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data.error || `HTTP ${response.status}`);
        }
        if (data.dashboard) {
          applyDashboard(data.dashboard);
        } else if (data.result) {
          setActionStatus(JSON.stringify(data.result, null, 2));
        }
        setActionStatus(`${action} 完成。\n${JSON.stringify(data.result || {}, null, 2)}`);
      } catch (error) {
        setActionStatus(`${action} 失败：${error.message || String(error)}`, true);
      } finally {
        setButtonsDisabled(false);
      }
    }

    document.getElementById("btn-refresh").addEventListener("click", () => runAction("refresh"));
    document.getElementById("btn-healthcheck").addEventListener("click", () => runAction("healthcheck"));
    document.getElementById("btn-run-once").addEventListener("click", () => runAction("run-once"));
    document.getElementById("btn-timer-enable").addEventListener("click", () => runAction("timer-enable"));
    document.getElementById("btn-timer-disable").addEventListener("click", () => runAction("timer-disable"));
    document.getElementById("btn-mode-live").addEventListener("click", () => runAction("mode-live"));
    document.getElementById("btn-mode-paper").addEventListener("click", () => runAction("mode-paper"));
    document.getElementById("btn-enable-live").addEventListener("click", () => runAction("enable-live"));
    document.getElementById("btn-disable-live").addEventListener("click", () => runAction("disable-live"));
    document.getElementById("btn-clear-halt").addEventListener("click", () => runAction("clear-halt"));

    load();
    setInterval(load, 60000);
  </script>
</body>
</html>
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="qount-monitor")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--ssh-host", default="home")
    parser.add_argument("--wsl-distro", default="Ubuntu")
    parser.add_argument("--wsl-user", default="alyaloale")
    parser.add_argument("--remote-project-dir", default="~/Code/qount")
    parser.add_argument("--open", action="store_true", help="Open the browser after starting the server.")
    parser.add_argument("--once", action="store_true", help="Print one dashboard JSON snapshot and exit.")
    return parser


class RemoteQount:
    def __init__(self, ssh_host: str, wsl_distro: str, wsl_user: str, remote_project_dir: str) -> None:
        self.ssh_host = ssh_host
        self.wsl_distro = wsl_distro
        self.wsl_user = wsl_user
        self.remote_project_dir = remote_project_dir

    def _remote_shell(self, command: str, timeout: int = 60) -> str:
        shell_script = "\n".join(
            [
                "set -euo pipefail",
                f"cd {self.remote_project_dir}",
                "set -a",
                ". ./.env",
                "set +a",
                ". .venv/bin/activate",
                command,
                "",
            ]
        )
        proc = subprocess.run(
            [
                "ssh",
                self.ssh_host,
                "cmd",
                "/c",
                "wsl",
                "-d",
                self.wsl_distro,
                "-u",
                self.wsl_user,
                "--",
                "bash",
                "-s",
            ],
            input=shell_script,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"remote command failed: {command}")
        return proc.stdout

    def qount_json(self, subcommand: str, timeout: int = 120) -> dict[str, Any]:
        raw = self._remote_shell(f"python -m qount.main {subcommand}", timeout=timeout)
        return json.loads(raw)

    def systemd_status(self) -> str:
        return self._remote_shell("systemctl --user status qount-runner.timer --no-pager --lines=20 || true", timeout=30).strip()

    def timer_status(self) -> dict[str, Any]:
        raw = self._remote_shell(
            "\n".join(
                [
                    "ACTIVE=$(systemctl --user is-active qount-runner.timer 2>/dev/null || true)",
                    "ENABLED=$(systemctl --user is-enabled qount-runner.timer 2>/dev/null || true)",
                    "printf '{\"active\":\"%s\",\"enabled\":\"%s\"}\\n' \"$ACTIVE\" \"$ENABLED\"",
                ]
            ),
            timeout=30,
        )
        payload = json.loads(raw)
        return {
            "active": payload.get("active") == "active",
            "enabled": payload.get("enabled") == "enabled",
            "active_raw": payload.get("active"),
            "enabled_raw": payload.get("enabled"),
        }

    def update_env(self, updates: dict[str, str], clear_keys: list[str] | None = None) -> dict[str, Any]:
        clear_keys = clear_keys or []
        payload = json.dumps({"updates": updates, "clear_keys": clear_keys}, ensure_ascii=False)
        command = (
            "python3 - <<'PY'\n"
            "import json\n"
            "from pathlib import Path\n"
            f"payload = json.loads({payload!r})\n"
            "path = Path('.env')\n"
            "lines = path.read_text(encoding='utf-8').splitlines()\n"
            "mapping = {}\n"
            "order = []\n"
            "for line in lines:\n"
            "    if '=' in line and not line.lstrip().startswith('#'):\n"
            "        k, v = line.split('=', 1)\n"
            "        mapping[k] = v\n"
            "        order.append(k)\n"
            "    else:\n"
            "        order.append(line)\n"
            "for key, value in payload['updates'].items():\n"
            "    mapping[key] = value\n"
            "    if key not in order:\n"
            "        order.append(key)\n"
            "for key in payload['clear_keys']:\n"
            "    mapping[key] = ''\n"
            "    if key not in order:\n"
            "        order.append(key)\n"
            "out = []\n"
            "seen = set()\n"
            "for item in order:\n"
            "    if item in mapping and item not in seen:\n"
            "        out.append(f'{item}={mapping[item]}')\n"
            "        seen.add(item)\n"
            "    elif item not in mapping:\n"
            "        out.append(item)\n"
            "path.write_text('\\n'.join(out) + '\\n', encoding='utf-8')\n"
            "print('{\"ok\": true}')\n"
            "PY"
        )
        return json.loads(self._remote_shell(command, timeout=60))

    def clear_live_guard(self) -> dict[str, Any]:
        command = (
            "python3 - <<'PY'\n"
            "import sqlite3\n"
            "conn = sqlite3.connect('state/qount.db')\n"
            "conn.execute(\"DELETE FROM runtime_state WHERE key = 'live_guard'\")\n"
            "conn.commit()\n"
            "conn.close()\n"
            "print('{\"ok\": true}')\n"
            "PY"
        )
        return json.loads(self._remote_shell(command, timeout=60))

    def dashboard(self) -> dict[str, Any]:
        payload = self.qount_json(
            "dashboard-snapshot --review-limit 10 --review-horizon-bars 1",
            timeout=180,
        )
        payload["generated_at"] = subprocess.check_output(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"], text=True).strip()
        payload["remote"] = {
            "host": self.ssh_host,
            "wsl_distro": self.wsl_distro,
            "wsl_user": self.wsl_user,
        }
        payload["systemd_status"] = self.systemd_status()
        payload["timer_status"] = self.timer_status()
        return payload

    def run_action(self, action: str) -> dict[str, Any]:
        if action == "healthcheck":
            result = self.qount_json("healthcheck", timeout=120)
        elif action == "run-once":
            result = self.qount_json("run-once", timeout=300)
        elif action == "timer-enable":
            self._remote_shell("systemctl --user daemon-reload && systemctl --user enable --now qount-runner.timer", timeout=60)
            result = {"ok": True, "message": "timer enabled"}
        elif action == "timer-disable":
            self._remote_shell("systemctl --user stop qount-runner.timer && systemctl --user disable qount-runner.timer", timeout=60)
            result = {"ok": True, "message": "timer disabled"}
        elif action == "mode-live":
            self.update_env({"QOUNT_MODE": "live"})
            result = {"ok": True, "message": "mode switched to live"}
        elif action == "mode-paper":
            self.update_env({"QOUNT_MODE": "paper"})
            result = {"ok": True, "message": "mode switched to paper"}
        elif action == "enable-live":
            self.update_env(
                {
                    "QOUNT_MODE": "live",
                    "QOUNT_LIVE_ENABLE": "true",
                    "QOUNT_LIVE_CONFIRMATION": "I_UNDERSTAND_LIVE_TRADING",
                }
            )
            result = self.qount_json("preflight-live", timeout=180)
        elif action == "disable-live":
            self.update_env(
                {
                    "QOUNT_LIVE_ENABLE": "false",
                    "QOUNT_LIVE_CONFIRMATION": "",
                }
            )
            self.clear_live_guard()
            result = self.qount_json("live-guard-status", timeout=60)
        elif action == "clear-halt":
            result = self.qount_json("clear-halt", timeout=60)
        elif action == "refresh":
            result = {"ok": True, "message": "manual refresh requested"}
        else:
            raise ValueError(f"unsupported action: {action}")
        return result


class DashboardCache:
    def __init__(self, remote: RemoteQount, refresh_interval: int = 60) -> None:
        self.remote = remote
        self.refresh_interval = refresh_interval
        self.payload: dict[str, Any] | None = None
        self.error: str | None = None
        self.last_refresh = 0.0
        self.fetching = False
        self._lock = threading.Lock()

    def refresh_sync(self) -> dict[str, Any] | None:
        with self._lock:
            self.fetching = True
        try:
            payload = self.remote.dashboard()
            with self._lock:
                self.payload = payload
                self.error = None
                self.last_refresh = time.time()
                return self.payload
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self.error = str(exc)
                return self.payload
        finally:
            with self._lock:
                self.fetching = False

    def refresh_async_if_needed(self) -> None:
        with self._lock:
            stale = (time.time() - self.last_refresh) > self.refresh_interval
            if self.fetching or not stale:
                return
            self.fetching = True
        threading.Thread(target=self._refresh_background, daemon=True).start()

    def _refresh_background(self) -> None:
        try:
            payload = self.remote.dashboard()
            with self._lock:
                self.payload = payload
                self.error = None
                self.last_refresh = time.time()
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self.error = str(exc)
        finally:
            with self._lock:
                self.fetching = False

    def snapshot(self) -> tuple[dict[str, Any] | None, str | None, bool]:
        with self._lock:
            stale = (time.time() - self.last_refresh) > self.refresh_interval if self.last_refresh else True
            return self.payload, self.error, stale


class MonitorHandler(BaseHTTPRequestHandler):
    remote: RemoteQount
    cache: DashboardCache

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html(HTML_PAGE)
            return
        if parsed.path == "/api/dashboard":
            try:
                self.cache.refresh_async_if_needed()
                payload, error, stale = self.cache.snapshot()
                if payload is not None:
                    data = dict(payload)
                    data["stale"] = stale
                    data["loading"] = False
                    if error:
                        data["background_error"] = error
                    self._send_json(data)
                elif error:
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": error}, ensure_ascii=False).encode("utf-8"))
                else:
                    self._send_json({"loading": True})
            except Exception as exc:  # noqa: BLE001
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8"))
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/actions/"):
            self.send_response(404)
            self.end_headers()
            return
        action = parsed.path.rsplit("/", 1)[-1]
        try:
            result = self.remote.run_action(action)
            dashboard = self.cache.refresh_sync()
            self._send_json({"result": result, "dashboard": dashboard})
        except Exception as exc:  # noqa: BLE001
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8"))

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    args = build_parser().parse_args()
    remote = RemoteQount(args.ssh_host, args.wsl_distro, args.wsl_user, args.remote_project_dir)
    if args.once:
        json.dump(remote.dashboard(), sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return

    MonitorHandler.remote = remote
    MonitorHandler.cache = DashboardCache(remote)
    MonitorHandler.cache.refresh_sync()
    server = ThreadingHTTPServer((args.host, args.port), MonitorHandler)
    url = f"http://{args.host}:{args.port}/"
    if args.open:
        webbrowser.open(url)
    print(f"qount monitor listening on {url}")
    server.serve_forever()


if __name__ == "__main__":
    main()
