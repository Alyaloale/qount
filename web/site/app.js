"use strict";

// 固定 TOP7 现货币池(线 D §21,逆波动率 · 1x · BTC 200d 大盘闸)
const UNIVERSE = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "LINK"];

// ---- helpers ----
const $ = (id) => document.getElementById(id);
const cls = (n) => (n > 0 ? "pos" : n < 0 ? "neg" : "dim");
const sign = (n) => (n > 0 ? "+" : "");
const arw = (n) => (n > 0 ? '<span class="arw">▲</span>' : n < 0 ? '<span class="arw">▼</span>' : "");
const store = {};

// ---- count-up animation for big numbers ----
let booted = false;
const prevVals = {};
const REDUCE = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const grp = (v, dec) => (dec ? v.toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec })
                              : Math.round(v).toLocaleString("en-US"));
function counted(key, value, dec = 0) {
  if (value == null || isNaN(value)) return "—";
  return `<span class="num" data-count data-key="${key}" data-val="${value}" data-dec="${dec}">${grp(value, dec)}</span>`;
}
function applyCounts() {
  document.querySelectorAll("[data-count]").forEach((el) => {
    const key = el.dataset.key, to = parseFloat(el.dataset.val), dec = +(el.dataset.dec || 0);
    if (isNaN(to)) return;
    const from = booted && key in prevVals ? prevVals[key] : 0;
    prevVals[key] = to;
    if (REDUCE || from === to) { el.textContent = grp(to, dec); return; }
    const dur = 850, t0 = performance.now();
    (function step(t) {
      const p = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - p, 4);
      el.textContent = grp(from + (to - from) * e, dec);
      if (p < 1) requestAnimationFrame(step); else el.textContent = grp(to, dec);
    })(t0);
  });
}

// ---- top ticker ----
function renderTicker() {
  const c = store.cta, l = store.live, p = store.paper, parts = [];
  if (l && l.btc_px) parts.push(`BTC <b>$${money(l.btc_px)}</b>`);
  if (l && l.btc_to_sma != null) parts.push(`距开闸 <b>${pct(l.btc_to_sma, 1)}</b>`);
  if (c && c.equity != null) {
    const day = c.day_pnl || 0;
    parts.push(`A股今日 <b>${sign(day)}¥${money(Math.abs(day))}</b>`);
    parts.push(`A股累计 <b>${pct(c.total_pnl_pct || 0)}</b>`);
  }
  if (l && l.capital != null) parts.push(`实盘 <b>$${money(l.capital)}</b> ${l.gate_open ? "闸开" : "闸关"}`);
  if (p && p.combo && p.combo.portfolio) parts.push(`模拟合成 Sharpe <b>${(p.combo.portfolio.sharpe || 0).toFixed(2)}</b>`);
  const el = $("ticker");
  if (!parts.length) { el.innerHTML = ""; return; }
  const seq = parts.join('<span class="sep">◆</span>') + '<span class="sep">◆</span>';
  el.innerHTML = `<div class="ticker-track"><span>${seq}</span><span>${seq}</span></div>`;
}

function money(x, cur) {
  if (x == null || isNaN(x)) return "—";
  const s = Math.abs(x) >= 1000 ? Math.round(x).toLocaleString("en-US")
                                : x.toLocaleString("en-US", { maximumFractionDigits: 2 });
  return (cur || "") + s;
}
function pct(x, digits = 2) {
  if (x == null || isNaN(x)) return "—";
  return sign(x) + (x * 100).toFixed(digits) + "%";
}
function ago(iso) {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (isNaN(t)) return "";
  const s = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (s < 90) return s + " 秒前";
  if (s < 5400) return Math.floor(s / 60) + " 分钟前";
  if (s < 172800) return Math.floor(s / 3600) + " 小时前";
  return Math.floor(s / 86400) + " 天前";
}
async function getJSON(path) {
  const r = await fetch(path + "?t=" + Date.now(), { cache: "no-store" });
  if (!r.ok) throw new Error("HTTP " + r.status);
  return r.json();
}

// ---- interactive equity chart (axes + hover crosshair/tooltip; vanilla SVG, no CDN) ----
const CHARTS = {};
let CHART_N = 0;
function normCurve(input) {
  if (!input) return { vals: [], dates: null };
  if (Array.isArray(input)) {
    if (input.length && typeof input[0] === "object")
      return { vals: input.map((p) => p.equity).filter((v) => v != null), dates: input.map((p) => p.date) };
    return { vals: input.filter((v) => v != null), dates: null };
  }
  if (input.curve) return { vals: input.curve, dates: input.dates || null };
  return { vals: [], dates: null };
}
function fmtAxis(v, cur) {
  const a = Math.abs(v);
  const s = a >= 1e6 ? (v / 1e6).toFixed(2) + "M" : a >= 1e4 ? Math.round(v / 1e3) + "k" : grp(v, 0);
  return (cur || "") + s;
}
function chart(input, opts) {
  opts = opts || {};
  const cur = opts.cur || "";
  const { vals, dates } = normCurve(input);
  const n = vals.length;
  if (n < 2) return "";
  const cz = !!opts.compact;   // narrow book cards: smaller viewBox so axis text isn't shrunk away
  const W = cz ? 340 : 600, H = cz ? 150 : 170;
  const L = cz ? 46 : 58, R = cz ? 10 : 12, T = cz ? 10 : 12, B = cz ? 22 : 24;
  const plotW = W - L - R, plotH = H - T - B, baseY = T + plotH;
  const minV = Math.min(...vals), maxV = Math.max(...vals);
  const pad = (maxV - minV) * 0.06 || Math.abs(maxV) * 0.01 || 1;
  const lo = minV - pad, hi = maxV + pad, span = hi - lo || 1;
  const X = (i) => L + (i / (n - 1)) * plotW;
  const Y = (v) => T + (1 - (v - lo) / span) * plotH;
  const xy = vals.map((v, i) => [X(i), Y(v)]);
  const d = xy.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  const up = vals[n - 1] >= vals[0];
  const color = up ? "var(--ac)" : "var(--neg)";
  const area = d + ` L${X(n - 1).toFixed(1)} ${baseY} L${X(0).toFixed(1)} ${baseY} Z`;
  const id = "ch" + CHART_N, gid = "cg" + CHART_N;
  CHART_N++;
  let grid = "";
  const TICKS = cz ? 3 : 4;
  for (let k = 0; k <= TICKS; k++) {
    const val = minV + (maxV - minV) * k / TICKS, y = Y(val).toFixed(1);
    grid += `<line class="grid" x1="${L}" y1="${y}" x2="${L + plotW}" y2="${y}"/>` +
            `<text class="ylbl" x="${L - 7}" y="${(+y + 3).toFixed(1)}">${fmtAxis(val, cur)}</text>`;
  }
  let xlab = "";
  const XT = Math.min(cz ? 3 : 4, n);
  for (let k = 0; k < XT; k++) {
    const i = Math.round((k / (XT - 1)) * (n - 1));
    const lab = dates ? String(dates[i]).slice(2) : "#" + i;
    const anchor = k === 0 ? "start" : k === XT - 1 ? "end" : "middle";
    xlab += `<text class="axlbl" x="${X(i).toFixed(1)}" y="${H - 7}" text-anchor="${anchor}">${lab}</text>`;
  }
  CHARTS[id] = { vals, dates, n, W, H, L, T, plotW, plotH, lo, span, cur };
  return `<div class="chartwrap">
    <svg class="chart${cz ? " compact" : ""}" viewBox="0 0 ${W} ${H}" data-cid="${id}">
      <defs><linearGradient id="${gid}" x1="0" x2="0" y1="0" y2="1">
        <stop offset="0" stop-color="${color}" stop-opacity=".16"/>
        <stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>
      ${grid}
      <path d="${area}" fill="url(#${gid})"/>
      <path d="${d}" fill="none" stroke="${color}" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>
      ${xlab}
      <line class="cx" x1="0" y1="${T}" x2="0" y2="${baseY}"/>
      <circle class="hot" r="3.6" cx="0" cy="0"/>
    </svg>
    <div class="chart-tip"></div>
  </div>`;
}
function onChartMove(e) {
  const svg = e.currentTarget, c = CHARTS[svg.dataset.cid];
  if (!c) return;
  const rect = svg.getBoundingClientRect();
  let f = (e.clientX - rect.left) / rect.width;
  f = Math.max(0, Math.min(1, f));
  const i = Math.round(f * (c.n - 1)), v = c.vals[i];
  const xv = c.L + (i / (c.n - 1)) * c.plotW;
  const yv = c.T + (1 - (v - c.lo) / c.span) * c.plotH;
  const cx = svg.querySelector(".cx"), hot = svg.querySelector(".hot");
  cx.setAttribute("x1", xv); cx.setAttribute("x2", xv); cx.style.opacity = 1;
  hot.setAttribute("cx", xv); hot.setAttribute("cy", yv); hot.style.opacity = 1;
  const tip = svg.parentNode.querySelector(".chart-tip");
  const dlab = c.dates ? c.dates[i] : "#" + i;
  tip.innerHTML = `<b>${c.cur}${grp(v, Math.abs(v) < 1000 ? 2 : 0)}</b><span>${dlab}</span>`;
  const px = (xv / c.W) * rect.width, py = (yv / c.H) * rect.height;
  tip.style.left = Math.max(38, Math.min(rect.width - 38, px)) + "px";
  tip.style.top = Math.max(0, py - 44) + "px";
  tip.style.opacity = 1;
}
function onChartLeave(e) {
  const svg = e.currentTarget;
  svg.querySelector(".cx").style.opacity = 0;
  svg.querySelector(".hot").style.opacity = 0;
  const tip = svg.parentNode.querySelector(".chart-tip");
  if (tip) tip.style.opacity = 0;
}
function wireCharts() {
  document.querySelectorAll("svg.chart").forEach((svg) => {
    if (svg._wired) return;
    svg._wired = true;
    svg.addEventListener("pointermove", onChartMove);
    svg.addEventListener("pointerleave", onChartLeave);
  });
}

// ---- 全局概览 ----
function renderOverview() {
  const el = $("overview");
  const c = store.cta, l = store.live, p = store.paper;
  const tiles = [];

  // A股
  if (c && c.equity != null) {
    const day = c.day_pnl || 0, dayPct = c.equity ? day / (c.equity - day) : 0;
    tiles.push(`<div class="otile">
      <div class="ok">A股 · 模拟盘</div>
      <div class="oe"><span class="cur">¥</span>${counted("ov-cta", c.equity)}</div>
      <div class="os ${cls(day)}">${arw(day)}今日 ${sign(day)}¥${money(Math.abs(day))} · ${pct(dayPct, 2)}</div>
    </div>`);
  } else tiles.push(`<div class="otile"><div class="ok">A股 · 模拟盘</div><div class="oe dim">—</div></div>`);

  // 加密实盘
  if (l && l.capital != null) {
    tiles.push(`<div class="otile">
      <div class="ok"><span class="live-dot"></span>加密实盘</div>
      <div class="oe"><span class="cur">$</span>${counted("ov-live", l.capital)}</div>
      <div class="os">${l.gate_open ? "闸开 · 持仓" : "闸关 · 空仓"} · ${l.armed ? "已武装" : "未武装"}</div>
    </div>`);
  } else tiles.push(`<div class="otile"><div class="ok">加密实盘</div><div class="oe dim">—</div></div>`);

  // 加密模拟(3 本 book 合计)
  if (p && p.holdings && p.holdings.books) {
    const bk = p.holdings.books;
    const eq = Object.values(bk).reduce((s, b) => s + (b.fwd_equity || 0), 0);
    const base = Object.keys(bk).length * (p.holdings.initial_capital || 100000);
    const ret = base ? eq / base - 1 : 0;
    tiles.push(`<div class="otile">
      <div class="ok">加密模拟盘</div>
      <div class="oe"><span class="cur">$</span>${counted("ov-paper", eq)}</div>
      <div class="os ${cls(ret)}">${Object.keys(bk).length} 本 · 前向 ${arw(ret)}${pct(ret)}</div>
    </div>`);
  } else tiles.push(`<div class="otile"><div class="ok">加密模拟盘</div><div class="oe dim">—</div></div>`);

  el.innerHTML = tiles.join("");
}

// ---- A股 CTA-R ----
function renderCTA(d) {
  store.cta = d;
  const body = $("body-cta");
  const totPct = d.total_pnl_pct || 0, day = d.day_pnl || 0, tot = d.total_pnl || 0;
  const live = d.price_source === "sina_live";
  const positions = (d.positions || []).slice().sort((a, b) => b.market_value - a.market_value);
  const maxW = Math.max(...positions.map((p) => p.target_weight || p.weight || 0), 0.01);
  const elapsed = d.trading_days_elapsed || 0, cycle = 21;
  const drift = (d.max_weight_drift || 0) * 100;

  let rows = positions.map((p) => {
    const pp = p.pnl_pct || 0, w = (p.weight || 0) * 100;
    return `<tr>
      <td class="name">${p.name || p.symbol}<span class="sym">${p.symbol}</span></td>
      <td class="opt">${money(p.last_px, "¥")}</td>
      <td class="opt">${money(p.market_value, "¥")}</td>
      <td class="${cls(pp)}">${sign(pp)}${(pp * 100).toFixed(1)}%</td>
      <td>${w.toFixed(1)}%<span class="wbar" style="width:${Math.round((p.weight || 0) / maxW * 40)}px"></span></td>
    </tr>`;
  }).join("");

  body.innerHTML = `
    <div class="hero">
      <div class="equity"><span class="cur">¥</span>${counted("cta-eq", d.equity)}</div>
      <div class="sub">总资产 · 现金 ¥${money(d.cash)} · 持仓市值 ¥${money(d.total_market_value)}</div>
    </div>
    ${chart(d.equity_curve, { cur: "¥" })}
    <div class="chips">
      <div class="chip"><div class="k">今日盈亏</div><div class="v ${cls(day)}">${arw(day)}${sign(day)}¥${money(Math.abs(day))}</div></div>
      <div class="chip"><div class="k">累计盈亏</div><div class="v ${cls(tot)}">${arw(tot)}${sign(tot)}¥${money(Math.abs(tot))}</div></div>
      <div class="chip"><div class="k">累计收益率</div><div class="v ${cls(totPct)}">${arw(totPct)}${pct(totPct)}</div></div>
      <div class="chip"><div class="k">持仓 / 漂移</div><div class="v dim">${positions.length} · ${drift.toFixed(1)}%</div></div>
    </div>
    <div class="subhead">持仓明细</div>
    <table class="tbl">
      <thead><tr><th>标的</th><th class="opt">现价</th><th class="opt">市值</th><th>收益</th><th>权重</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <div class="progblock">
      <div class="prog-meta"><span>调仓周期</span><span>${d.due ? "⚠ 已到调仓点" : `${elapsed} / ${cycle} 交易日`}</span></div>
      <div class="prog"><i style="width:${Math.min(100, elapsed / cycle * 100)}%"></i></div>
    </div>
    <div class="note"><b>模拟盘</b> · 数据 ${d.data_date} · ${live ? "新浪实时价" : "缓存收盘价"}</div>`;
}

// ---- 加密实盘 ----
function gateMeter(btc, sma) {
  if (!btc || !sma) return "";
  const lo = Math.min(btc, sma) * 0.94, hi = Math.max(btc, sma) * 1.05;
  const pos = (v) => ((v - lo) / (hi - lo) * 100).toFixed(1);
  const pb = pos(btc), ps = pos(sma);
  return `<div class="gate">
    <div class="gate-track">
      <span class="gate-fill" style="width:${pb}%"></span>
      <span class="gate-line" style="left:${ps}%"><span class="lbl">开闸线 $${money(sma)}</span></span>
      <span class="gate-dot" style="left:${pb}%"><span class="lbl">BTC $${money(btc)}</span></span>
    </div>
  </div>`;
}
function renderLive(d) {
  store.live = d;
  const body = $("body-live");
  const head = $("panel-live").querySelector(".panel-head");
  head.querySelectorAll(".badge.gate-open,.badge.gate-closed").forEach((e) => e.remove());
  const gb = document.createElement("span");
  gb.className = "badge " + (d.gate_open ? "gate-open" : "gate-closed");
  gb.textContent = d.gate_open ? "闸开" : "闸关";
  head.appendChild(gb);

  const toSma = d.btc_to_sma || 0;
  const holdings = d.holdings || [];
  const coins = (d.universe && d.universe.length ? d.universe : UNIVERSE)
    .map((c) => `<span class="coin">${c}</span>`).join("");

  const holdHtml = holdings.length
    ? `<div class="subhead">当前持仓</div><table class="tbl">
        <thead><tr><th>币种</th><th>数量</th><th class="opt">价格</th><th>市值</th></tr></thead>
        <tbody>${holdings.map((h) => `<tr>
          <td class="name">${h.symbol || h.sym || ""}</td>
          <td>${money(h.qty != null ? h.qty : h.amount, "")}</td>
          <td class="opt">${h.price != null ? money(h.price, "$") : "—"}</td>
          <td>${h.value != null ? money(h.value, "$") : "—"}</td></tr>`).join("")}</tbody></table>`
    : `<div class="empty">空仓 — BTC 低于 200 日线,大盘闸关闭,资金全在现金</div>`;

  body.innerHTML = `
    <div class="hero">
      <div class="equity"><span class="cur">$</span>${counted("live-eq", d.capital)}</div>
      <div class="sub">本金 · 已部署 $${money(d.deployed)} · 现金 $${money(d.cash)}</div>
    </div>
    <div class="subhead">大盘闸门 · BTC vs 200 日线</div>
    ${gateMeter(d.btc_px, d.btc_sma200)}
    <div class="chips">
      <div class="chip"><div class="k">距开闸</div><div class="v ${cls(toSma)}">${arw(toSma)}${pct(toSma, 1)}</div></div>
      <div class="chip"><div class="k">BTC 现价 <span class="live-dot"></span>实时</div><div class="v">$${money(d.btc_px)}</div></div>
      <div class="chip"><div class="k">200日线 · 收盘</div><div class="v dim">$${money(d.btc_sma200)}</div></div>
      <div class="chip"><div class="k">状态</div><div class="v ${d.armed ? "" : "dim"}">${d.armed ? "已武装" : "未武装"}</div></div>
    </div>
    <div class="subhead">候选币池 · ${(d.universe || UNIVERSE).length} 币</div>
    <div class="uni">${coins}</div>
    ${holdHtml}
    <div class="note"><b>实盘</b> · 现货 1x 逆波动率 · 站上 200 日线开仓 · 更新于 ${ago(d.ts)}</div>`;
}

// ---- 加密模拟盘 ----
function bookCard(name, b, btReturn, btSharpe, btDD, curve) {
  if (!b) return "";
  const ret = b.fwd_return || 0, flat = b.flat;
  let holdHtml = (b.positions && b.positions.length)
    ? `<div class="meta-row" style="flex-wrap:wrap">` + b.positions.map((p) => `<span>${p.instrument} <b>${p.side}</b></span>`).join("") + `</div>`
    : `<div class="meta-row"><span>${flat ? "当前空仓" : (b.n_held != null ? b.n_held + " 个持仓" : "")}</span></div>`;
  const curveHtml = (curve && curve.curve && curve.curve.length > 1)
    ? `<div class="chart-cap">回测净值 · 样本内</div>${chart(curve, { cur: "$", compact: true })}` : "";
  return `<div class="bookcard">
    <div class="bh"><span class="bn">${name}</span>
      <span class="badge ${flat ? "flat" : "paper"}">${flat ? "空仓" : "持仓"}</span></div>
    <div class="be">$${money(b.fwd_equity)}</div>
    <div class="br ${cls(ret)}">${arw(ret)}${pct(ret)} <span class="dim" style="font-size:11px">前向</span></div>
    ${curveHtml}
    ${holdHtml}
    <div class="meta-row">
      ${btSharpe != null ? `<span>回测 Sharpe <b>${btSharpe.toFixed(2)}</b></span>` : ""}
      ${btReturn != null ? `<span>回测 <b>${pct(btReturn, 0)}</b></span>` : ""}
      ${btDD != null ? `<span>回撤 <b>${pct(btDD, 0)}</b></span>` : ""}
    </div>
  </div>`;
}
function renderPaper(d) {
  store.paper = d;
  const body = $("body-paper");
  const books = (d.holdings && d.holdings.books) || {};
  const three = d.three && d.three.portfolio, s7 = d.s7 && d.s7.portfolio, combo = d.combo && d.combo.portfolio;
  // S7 盈利档(vol_target=3%):真前向在 s7_vt3.forward,回测在 s7_vt3.portfolio(非 holdings.books)
  const v3 = d.s7_vt3, v3p = v3 && v3.portfolio;
  const v3book = v3 && v3.forward ? { ...v3.forward, flat: v3.trend_flat } : null;

  const cards = [
    bookCard("3腿组合 · S1+S3+S4", books["3leg"], three && three.total_return, three && three.sharpe, three && three.max_drawdown, three && three.equity_curve),
    bookCard("S7 多币趋势", books["s7"], s7 && s7.total_return, s7 && s7.sharpe, s7 && s7.max_drawdown, s7 && s7.equity_curve),
    bookCard("S7 盈利档 · vol_target 3%", v3book, v3p && v3p.total_return, v3p && v3p.sharpe, v3p && v3p.max_drawdown, v3 && v3.equity_curve),
    bookCard("C×D 趋势+carry", books["combo"], combo && combo.total_return, combo && combo.sharpe, combo && combo.max_drawdown, combo && combo.equity_curve),
  ].join("");

  // 分散度洞察(combo:趋势 + carry 负相关压舱石)
  let insight = "";
  if (d.combo && d.combo.corr != null) {
    const cb = d.combo, ta = cb.trend_alone || {}, ca = cb.carry_alone || {};
    insight = `<div class="insight">
      <div class="ins-h">分散效应 · C×D 组合</div>
      <div class="ins-row">
        <span>趋势腿 Sharpe <b>${(ta.sharpe || 0).toFixed(2)}</b></span>
        <span>carry 腿 Sharpe <b>${(ca.sharpe || 0).toFixed(2)}</b></span>
        <span>相关性 ρ <b>${(cb.corr).toFixed(2)}</b></span>
        <span>合成 Sharpe <b>${(combo.sharpe || 0).toFixed(2)}</b> · 回撤砍至 <b>${pct(combo.max_drawdown, 0)}</b></span>
      </div>
    </div>`;
  }

  body.innerHTML = `
    <div class="cards">${cards}</div>
    ${insight}
    <div class="note"><b>模拟盘</b> · 各 $100k 前向部署于 ${d.holdings && (d.holdings.deploy_date || d.holdings.as_of) || "—"} · 回测数字仅样本内参考</div>`;
}

// ---- orchestration ----
async function load() {
  for (const k in CHARTS) delete CHARTS[k];   // charts are rebuilt fresh each render
  const tasks = [
    ["data/cta.json", renderCTA, "body-cta"],
    ["data/x4_live.json", renderLive, "body-live"],
    ["data/x4_paper.json", renderPaper, "body-paper"],
  ];
  await Promise.all(tasks.map(async ([path, render, bodyId]) => {
    try {
      const d = await getJSON(path);
      if (d && d.error) throw new Error(d.error);
      render(d);
    } catch (e) {
      $(bodyId).innerHTML = `<div class="err">取数失败:${e.message}</div>`;
    }
  }));
  renderOverview();
  renderTicker();
  applyCounts();
  wireCharts();
  booted = true;
  $("clock").textContent = new Date().toLocaleTimeString("zh-CN", { hour12: false }) + " 刷新";
}
function tick() {
  const btn = $("refresh");
  btn.classList.add("spin");
  load().finally(() => setTimeout(() => btn.classList.remove("spin"), 600));
}
$("refresh").addEventListener("click", tick);
document.addEventListener("visibilitychange", () => { if (!document.hidden) load(); });
tick();
setInterval(load, 60000);
