"use strict";

// 固定 TOP7 现货币池(线 D §21,逆波动率 · 1x · BTC 200d 大盘闸)
const UNIVERSE = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "LINK"];

// ---- helpers ----
const $ = (id) => document.getElementById(id);
const cls = (n) => (n > 0 ? "pos" : n < 0 ? "neg" : "dim");
const sign = (n) => (n > 0 ? "+" : "");
const arw = (n) => (n > 0 ? '<span class="arw">▲</span>' : n < 0 ? '<span class="arw">▼</span>' : "");
const store = {};
const livePx = {};                 // live mark prices fetched client-side (real-time tick between cron runs)
let liveOnly = false;              // true during a price-tick re-render -> skip count-up (no constant re-animate)
let liveCurveMode = "intra";       // 加密实盘权益曲线:"intra"=盘中实时 / "daily"=日线

// proper signed money (+$1.23 / -$0.45) — `sign()` alone drops the minus after Math.abs
function signed(x, cur) {
  if (x == null || isNaN(x)) return "—";
  return (x >= 0 ? "+" : "-") + (cur || "") + money(Math.abs(x));
}

// ---- theme (dark / light, persisted) ----
function applyTheme(t) {
  document.documentElement.setAttribute("data-theme", t);
  try { localStorage.setItem("qount-theme", t); } catch (e) {}
  const b = document.getElementById("theme-btn");
  if (b) { b.textContent = t === "light" ? "☾" : "☀"; b.title = t === "light" ? "切换深色" : "切换浅色"; }
}
function toggleTheme() {
  const cur = document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
  applyTheme(cur === "light" ? "dark" : "light");
}

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
    if (REDUCE || liveOnly || from === to) { el.textContent = grp(to, dec); return; }
    const dur = 850, t0 = performance.now();
    (function step(t) {
      const p = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - p, 4);
      el.textContent = grp(from + (to - from) * e, dec);
      if (p < 1) requestAnimationFrame(step); else el.textContent = grp(to, dec);
    })(t0);
  });
}

// ---- page subtitle: per-route compact status line in the header ----
function pageSub(route) {
  const el = $("page-sub");
  if (!el) return;
  const c = store.cta, l = store.live, p = store.paper;
  let s = "";
  if (route === "overview") {
    if (l && l.btc_px) s = `BTC $${money(l.btc_px)} · 距开闸 ${pct(l.btc_to_sma || 0, 1)}`;
  } else if (route === "live" && l) {
    const { longOn, shortOn } = liveNetState(l);
    s = `${longOn ? "做多" : shortOn ? "做空对冲" : "空仓"} · ${l.armed ? "已武装" : "未武装"} · 更新 ${ago(l.ts)}`;
  } else if (route === "cta" && c) {
    s = `累计 ${pct(c.total_pnl_pct || 0)} · 数据 ${c.data_date || "—"}`;
  } else if (route === "cxd" && store.cxd) {
    s = `编排 · 趋势 60% + carry 40%`;
  } else if (route === "paper" && p) {
    s = `各 $100k 前向 · ${(p.holdings && p.holdings.deploy_date) || "—"}`;
  }
  el.textContent = s;
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
function fmtAxis(v, cur, dec) {
  const a = Math.abs(v);
  const s = a >= 1e6 ? (v / 1e6).toFixed(2) + "M" : a >= 1e4 ? Math.round(v / 1e3) + "k" : grp(v, dec || 0);
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
  // y-axis decimals scale to the value RANGE so a tight curve (e.g. $483.6–$484.4) isn't all "$484"
  const axSpan = maxV - minV;
  const axDec = axSpan === 0 ? (Math.abs(maxV) < 100 ? 2 : 0)
    : axSpan < 2 ? 3 : axSpan < 20 ? 2 : axSpan < 200 ? 1 : 0;
  for (let k = 0; k <= TICKS; k++) {
    const val = minV + (maxV - minV) * k / TICKS, y = Y(val).toFixed(1);
    grid += `<line class="grid" x1="${L}" y1="${y}" x2="${L + plotW}" y2="${y}"/>` +
            `<text class="ylbl" x="${L - 7}" y="${(+y + 3).toFixed(1)}">${fmtAxis(val, cur, axDec)}</text>`;
  }
  let xlab = "";
  const XT = Math.min(cz ? 3 : 4, n);
  for (let k = 0; k < XT; k++) {
    const i = Math.round((k / (XT - 1)) * (n - 1));
    const raw = dates ? String(dates[i]) : "#" + i;
    // only slice the year off ISO dates ("2026-06-18"->"26-06-18"); leave time/short labels intact
    const lab = /^\d{4}-\d{2}-\d{2}/.test(raw) ? raw.slice(2) : raw;
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

// ---- mini sparkline (no axes/hover) for the sidebar nav ----
function spark(input) {
  const vals = normCurve(input).vals;
  if (vals.length < 2) return "";
  const W = 100, H = 22, n = vals.length;
  const mn = Math.min(...vals), mx = Math.max(...vals), sp = (mx - mn) || 1;
  const X = (i) => (i / (n - 1)) * W, Y = (v) => H - 2 - ((v - mn) / sp) * (H - 4);
  const dd = vals.map((v, i) => (i ? "L" : "M") + X(i).toFixed(1) + " " + Y(v).toFixed(1)).join(" ");
  const up = vals[n - 1] >= vals[0];
  const col = up ? "var(--ac)" : "var(--neg)";
  return `<svg class="spk" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    <path d="${dd} L${W} ${H} L0 ${H} Z" fill="${col}" opacity=".10"/>
    <path d="${dd}" fill="none" stroke="${col}" stroke-width="1.4" stroke-linejoin="round"/></svg>`;
}
function updateSparks() {
  const set = (id, input) => { const el = $(id); if (el) el.innerHTML = spark(input); };
  set("spark-live", store.live && (store.live.equity_curve_daily && store.live.equity_curve_daily.length > 1
    ? store.live.equity_curve_daily : store.live.equity_curve));
  set("spark-cta", store.cta && store.cta.equity_curve);
  const cb = store.paper && store.paper.combo && store.paper.combo.portfolio;
  set("spark-paper", cb && cb.equity_curve);
}

// ---- 全局概览 ----
function renderOverview() {
  const el = $("overview");
  const c = store.cta, l = store.live, p = store.paper;
  const tiles = [];

  // 加密实盘(主账,置顶)
  if (l && l.capital != null) {
    const { longOn, shortOn } = liveNetState(l);
    const lUp = l.unrealized_pnl;
    const state = longOn ? "做多 · 持多仓" : shortOn ? "做空 · 对冲" : "空仓 · 观望";
    tiles.push(`<div class="otile" data-route="live">
      <div class="ok"><span class="live-dot"></span>加密实盘 · X4 趋势<span class="ot-tag real">实盘</span></div>
      <div class="oe"><span class="cur">$</span>${counted("ov-live", l.equity != null ? l.equity : l.capital, 2)}</div>
      <div class="os ${l.total_pnl != null ? cls(l.total_pnl) : ""}">${state}${l.total_pnl != null ? ` · 总盈亏 ${signed(l.total_pnl, "$")}` : lUp != null ? ` · ${arw(lUp)}未实现 ${signed(lUp, "$")}` : ""} · ${l.armed ? "已武装" : "未武装"}</div>
    </div>`);
    const tag = $("nav-live-tag");
    if (tag) { tag.textContent = longOn ? "做多" : shortOn ? "做空" : "空仓";
               tag.className = "ni-tag " + (longOn ? "long" : shortOn ? "short" : ""); }
  } else tiles.push(`<div class="otile" data-route="live"><div class="ok">加密实盘</div><div class="oe dim">—</div></div>`);

  // A股
  if (c && c.equity != null) {
    const day = c.day_pnl || 0, dayPct = c.equity ? day / (c.equity - day) : 0;
    tiles.push(`<div class="otile" data-route="cta">
      <div class="ok">A股 · CTA-R<span class="ot-tag paper">模拟</span></div>
      <div class="oe"><span class="cur">¥</span>${counted("ov-cta", c.equity)}</div>
      <div class="os ${cls(day)}">${arw(day)}今日 ${signed(day, "¥")} · ${pct(dayPct, 2)}</div>
    </div>`);
  } else tiles.push(`<div class="otile" data-route="cta"><div class="ok">A股 · 模拟盘</div><div class="oe dim">—</div></div>`);

  // 加密模拟(3 本 book 合计)
  if (p && p.holdings && p.holdings.books) {
    const bk = p.holdings.books;
    const eq = Object.values(bk).reduce((s, b) => s + (b.fwd_equity || 0), 0);
    const base = Object.keys(bk).length * (p.holdings.initial_capital || 100000);
    const ret = base ? eq / base - 1 : 0;
    tiles.push(`<div class="otile" data-route="paper">
      <div class="ok">加密 · 模拟盘(前向)<span class="ot-tag paper">模拟</span></div>
      <div class="oe"><span class="cur">$</span>${counted("ov-paper", eq)}</div>
      <div class="os ${cls(ret)}">${Object.keys(bk).length} 本 · 前向 ${arw(ret)}${pct(ret)}</div>
    </div>`);
  } else tiles.push(`<div class="otile" data-route="paper"><div class="ok">加密模拟盘</div><div class="oe dim">—</div></div>`);

  el.innerHTML = tiles.join("");
  renderSummary();
  updateSparks();
}

// 概览汇总卡:真实资金头条 + 跨账户 今日 P&L 汇总(分币种,不混真/模拟)
function renderSummary() {
  const el = $("ov-summary");
  if (!el) return;
  const c = store.cta, l = store.live, p = store.paper;
  const lUp = l && l.unrealized_pnl;
  const cDay = c && (c.day_pnl || 0);
  // 真实头条 = 加密实盘权益(唯一真金账户)
  const realEq = l && (l.equity != null ? l.equity : l.capital);
  const realTot = l && l.total_pnl;
  const realChg = realTot != null
    ? `<span class="sc-chg ${cls(realTot)}">${arw(realTot)}总盈亏 ${signed(realTot, "$")} · ${pct(l.total_pnl_pct || 0)}</span>`
    : lUp != null ? `<span class="sc-chg ${cls(lUp)}">${arw(lUp)}未实现 ${signed(lUp, "$")}</span>` : "";
  // 模拟合计(两币种分列,不与真金混合)
  const paperEq = p && p.holdings && p.holdings.books
    ? Object.values(p.holdings.books).reduce((s, b) => s + (b.fwd_equity || 0), 0) : null;
  const cells = [];
  cells.push(`<div class="sc-cell"><div class="sc-ck">A股 CTA-R · 模拟</div>
    <div class="sc-cv">${c ? "¥" + money(c.equity) : "—"}</div>
    <div class="sc-cs ${cls(cDay || 0)}">${c ? `今日 ${signed(cDay, "¥")} · ${pct(c.total_pnl_pct || 0)}` : ""}</div></div>`);
  cells.push(`<div class="sc-cell"><div class="sc-ck">加密模拟 · 前向</div>
    <div class="sc-cv">${paperEq != null ? "$" + money(paperEq) : "—"}</div>
    <div class="sc-cs dim">各 $100k · 纯模拟</div></div>`);
  cells.push(`<div class="sc-cell"><div class="sc-ck">今日盈亏汇总(分币种)</div>
    <div class="sc-cv sc-sum">${cDay != null ? `<span class="${cls(cDay)}">${signed(cDay, "¥")}</span>` : "—"}
      ${lUp != null ? `<span class="${cls(lUp)}">${signed(lUp, "$")}</span>` : ""}</div>
    <div class="sc-cs dim">A股(¥)+ 加密实盘未实现($)</div></div>`);

  el.innerHTML = `
    <div class="sc-main">
      <div class="sc-k"><span class="live-dot"></span>真实资金 · 加密实盘 X4</div>
      <div class="sc-v"><span class="cur">$</span>${realEq != null ? counted("sum-real", realEq, 2) : "—"} ${realChg}</div>
    </div>
    <div class="sc-cells">${cells.join("")}</div>`;
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
  const lo = Math.min(btc, sma) * 0.93, hi = Math.max(btc, sma) * 1.04;
  const pos = (v) => Math.max(3, Math.min(97, (v - lo) / (hi - lo) * 100));
  const pb = pos(btc), ps = pos(sma);
  const above = btc >= sma;
  const gapL = Math.min(pb, ps), gapW = Math.abs(ps - pb);
  // edge-aware label anchor: near right edge → extend left (translateX -100%), near left → extend right
  const anchor = (p) => p > 76 ? "transform:translateX(-100%);padding-right:10px"
    : p < 24 ? "transform:translateX(0);padding-left:10px" : "transform:translateX(-50%)";
  return `<div class="gate ${above ? "long" : "risk"}">
    <div class="gate-bar">
      <div class="gate-fill" style="width:${pb}%"></div>
      <div class="gate-gap" style="left:${gapL}%;width:${gapW}%"></div>
      <div class="gate-th" style="left:${ps}%"></div>
      <div class="gate-btc" style="left:${pb}%"></div>
      <div class="gate-lbl gate-th-lbl" style="left:${ps}%;${anchor(ps)}">开闸线 $${money(sma)}</div>
      <div class="gate-lbl gate-btc-lbl" style="left:${pb}%;${anchor(pb)}">BTC $${money(btc)}</div>
    </div>
    <div class="gate-need ${above ? "on" : ""}">${above
      ? "✓ BTC 已站上 200 日线 · 多头闸开启 · 做多"
      : "大盘闸关闭 · 当前做空对冲 → BTC 需重回 200 日线上方才切多头闸"}</div>
  </div>`;
}
// 3-态闸:多头闸(站上 200 线)/ 空头闸(熊市对冲)/ 空仓,互斥,高亮当前态
function liveNetState(d) {
  const longOn = !!d.gate_open;
  const shortOn = !longOn && (!!d.shorting || (d.holdings || []).some((h) => (h.value || 0) < 0));
  return { longOn, shortOn, flatOn: !longOn && !shortOn };
}
function gateStates(d) {
  const { longOn, shortOn, flatOn } = liveNetState(d);
  // 两道闸(各自独立 on/off,始终都清晰显示)+ 推导出的净态
  const gcard = (on, kind, name, status, desc) => `<div class="gcard ${on ? "on " + kind : "off"}">
    <div class="gc-k"><span class="gc-dot"></span>${name}</div>
    <div class="gc-v">${status}</div><div class="gc-d">${desc}</div></div>`;
  const netKind = longOn ? "long" : shortOn ? "short" : "flat";
  const netTxt = longOn ? "做多 · 持多仓" : shortOn ? "做空 · 持空仓" : "空仓 · 现金";
  return `<div class="gates2">
    ${gcard(longOn, "long", "① 多头闸", longOn ? "开启" : "关闭", "BTC 站上 200 日线")}
    ${gcard(shortOn, "short", "② 空头闸", shortOn ? "触发" : d.short_gate ? "待命" : "未启用", "真熊 → 做空对冲")}
    <div class="gnet ${netKind}">
      <div class="gn-k">当前净态(二选一闸 → 三态)</div>
      <div class="gn-v">${netTxt}</div>
    </div>
  </div>`;
}
// 权益曲线 + 24小时/日线切换
function liveCurveBlock(d) {
  const cutoff = Date.now() - 24 * 3600 * 1000;             // 真正的滚动 24h:按时间戳过滤最近 24 小时的点
  const intra = (d.equity_curve || []).filter((p) => p.ts && new Date(p.ts).getTime() >= cutoff);
  const daily = d.equity_curve_daily || [];
  const series = liveCurveMode === "daily" ? daily : intra;
  const hasDaily = daily.length > 1, hasIntra = intra.length > 1;
  if (!hasDaily && !hasIntra) return "";
  const seg = (mode, label, enabled) =>
    `<button class="seg ${liveCurveMode === mode ? "on" : ""}" data-curve="${mode}" ${enabled ? "" : "disabled"}>${label}</button>`;
  const toggle = `<div class="segbar">${seg("intra", "24 小时", hasIntra)}${seg("daily", "日线", hasDaily)}</div>`;
  const cap = liveCurveMode === "daily" ? "账户权益 · 日线" : "账户权益 · 滚动 24 小时(10 分钟/点)";
  const body = series.length > 1
    ? chart(series, { cur: "$" })
    : `<div class="empty">${liveCurveMode === "daily" ? "日线(次日起)" : "24 小时"}数据累积中…</div>`;
  return `<div class="cap-row"><div class="chart-cap">${cap}</div>${toggle}</div>${body}`;
}
function renderLive(d) {
  store.live = d;
  const body = $("body-live");
  const head = $("panel-live").querySelector(".panel-head");
  head.querySelectorAll(".badge.gate-open,.badge.gate-closed,.badge.shorting,.badge.lev").forEach((e) => e.remove());
  const isPerp = d.market_type === "swap";
  const lev = d.max_leverage || 2;
  if (d.market_type) {
    const lb = document.createElement("span");
    lb.className = "badge lev";
    lb.textContent = isPerp ? `USDⓈ-M 永续 ${lev}x` : "现货 1x";
    head.appendChild(lb);
  }
  const holdings = d.holdings || [];
  const shorting = !!d.shorting || holdings.some((h) => (h.value || 0) < 0);
  const gb = document.createElement("span");
  gb.className = "badge " + (d.gate_open ? "gate-open" : shorting ? "shorting" : "gate-closed");
  gb.textContent = d.gate_open ? "做多" : shorting ? "做空" : "空仓";
  head.appendChild(gb);

  const toSma = d.btc_to_sma || 0;
  const exp = d.gross_exposure || 0;
  const coins = (d.universe && d.universe.length ? d.universe : UNIVERSE)
    .map((c) => `<span class="coin">${c}</span>`).join("");

  // alerts: 盘中硬止损触发 / 杠杆未能确认(拒绝交易)/ 本金过小纳不进的币
  let banners = "";
  if (d.stopped && d.stopped.length)
    banners += `<div class="banner warn">⛔ 盘中硬止损触发,已强平:<b>${d.stopped.join("、")}</b></div>`;
  if (d.leverage_unsafe && d.leverage_unsafe.length)
    banners += `<div class="banner warn">⚠ 杠杆未确认为 ${lev}x,已拒绝交易:<b>${d.leverage_unsafe.join("、")}</b>(去交易所手动设逐仓)</div>`;
  if (d.capital_blocked && d.capital_blocked.length)
    banners += `<div class="banner">ℹ 本金 $${money(d.capital)} 偏小,以下币按逆波动率权重的目标额低于最小下单额、会被跳过:<b>${d.capital_blocked.map((b) => `${b.symbol}(目标$${money(b.target_usdt)}<地板$${money(b.min_usdt)})`).join("、")}</b> · 实盘为集中子集,非完整 ${(d.universe || UNIVERSE).length} 币</div>`;

  const upnl = d.unrealized_pnl;
  const holdHtml = holdings.length
    ? `<div class="subhead">当前持仓 · ${shorting ? "永续做空对冲(§24 做空闸)" : isPerp ? "永续多头(名义)" : "现货"}</div><table class="tbl">
        <thead><tr><th>币种</th><th>方向</th><th class="opt">入场</th><th class="opt">现价</th><th>名义</th><th>浮盈</th><th class="opt">止损</th></tr></thead>
        <tbody>${holdings.map((h) => {
          const sh = h.side === "short" || (h.value || 0) < 0;
          const up = h.upnl || 0;
          return `<tr>
          <td class="name">${h.symbol || h.sym || ""}</td>
          <td><span class="side ${sh ? "neg" : "pos"}">${sh ? "空" : "多"}</span></td>
          <td class="opt">${h.entry != null ? money(h.entry, "$") : "—"}</td>
          <td class="opt">${h.price != null ? money(h.price, "$") : "—"}</td>
          <td>${h.value != null ? money(Math.abs(h.value), "$") : "—"}</td>
          <td class="${cls(up)}">${h.upnl != null ? signed(up, "$") : "—"}</td>
          <td class="opt">${h.stop != null ? money(h.stop, "$") : "—"}</td></tr>`;
        }).join("")}</tbody></table>`
    : `<div class="empty">空仓 — BTC 低于 200 日线,大盘闸关闭,${isPerp ? "永续仓位已全平,资金留在保证金钱包" : "资金全在现金"}</div>`;

  body.innerHTML = `
    ${banners}
    <div class="hero">
      <div class="equity"><span class="cur">$</span>${counted("live-eq", d.equity != null ? d.equity : d.capital, 2)}</div>
      ${d.total_pnl != null ? `<div class="pnl-tag ${cls(d.total_pnl)}">总盈亏 ${arw(d.total_pnl)}${signed(d.total_pnl, "$")} · ${pct(d.total_pnl_pct || 0)}</div>` : ""}
      <div class="sub">实时权益 · 钱包 $${money(d.capital)}${upnl != null ? ` · 未实现 <span class="${cls(upnl)}">${signed(upnl, "$")}</span>` : ""} · 部署名义 $${money(d.deployed)} · 占用保证金 $${money(d.margin_used)}</div>
    </div>
    ${liveCurveBlock(d)}
    <div class="subhead">交易闸 · 两道闸 → 三态(BTC 站上 200 线做多 / 真熊做空对冲 / 否则空仓)</div>
    ${gateStates(d)}
    <div class="subhead">大盘闸门 · BTC vs 200 日线</div>
    ${gateMeter(d.btc_px, d.btc_sma200)}
    <div class="chips">
      <div class="chip"><div class="k">距开闸</div><div class="v ${cls(toSma)}">${arw(toSma)}${pct(toSma, 1)}</div></div>
      <div class="chip"><div class="k">BTC 现价 <span class="live-dot"></span>实时</div><div class="v">$${money(d.btc_px)}</div></div>
      <div class="chip"><div class="k">200日线 · 收盘</div><div class="v dim">$${money(d.btc_sma200)}</div></div>
      <div class="chip"><div class="k">实际敞口 / 上限</div><div class="v ${exp > 0 ? "" : "dim"}">${exp.toFixed(2)}× <span class="dim" style="font-size:12px">/ ${lev}x</span></div></div>
      <div class="chip"><div class="k">状态</div><div class="v ${d.armed ? "" : "dim"}">${d.armed ? "已武装" : "未武装"}</div></div>
    </div>
    <div class="subhead">候选币池 · ${(d.universe || UNIVERSE).length} 币</div>
    <div class="uni">${coins}</div>
    ${holdHtml}
    <div class="note"><b>实盘</b> · ${isPerp ? `USDⓈ-M 永续 ${lev}x · 逆波动率平价` : "现货 1x"}${d.chandelier_mult ? ` · chandelier ${d.chandelier_mult}× 兜底止损` : ""} · 更新于 ${ago(d.ts)}</div>`;
}

// ---- 加密 C×D 合成账(趋势 60% + carry 40%) ----
function renderCxd(d) {
  store.cxd = d;
  const body = $("body-cxd");
  const t = d.trend || {}, c = d.carry || {};
  const w = d.weights || { trend: 0.6, carry: 0.4 };
  const tArmed = !!t.armed, cArmed = !!c.armed;
  const anyArmed = tArmed || cArmed;
  const tCap = t.capital || 0, cCap = c.capital || 0;
  const activeDated = (c.active_dated || []).map((s) => `<span class="coin">${s}</span>`).join("");
  const delta = c.net_delta || 0;

  // 这条与"加密实盘"不同:C×D 是 60/40 编排账,两腿都未武装时是 dry 模拟编排(carry 待注资),武装后才转实盘
  const head = $("panel-cxd").querySelector(".panel-head");
  head.querySelectorAll(".badge.real,.badge.paper").forEach((e) => e.remove());
  const cb = document.createElement("span");
  cb.className = "badge " + (anyArmed ? "real" : "paper");
  cb.textContent = anyArmed ? "实盘" : "模拟编排 · 待注资";
  head.appendChild(cb);

  body.innerHTML = `
    <div class="hero">
      <div class="equity"><span class="cur">$</span>${counted("cxd-eq", d.total_capital || tCap + cCap)}</div>
      <div class="sub">总本金 · 趋势 $${money(tCap)} (${pct(w.trend, 0)}) + carry $${money(cCap)} (${pct(w.carry, 0)})</div>
    </div>
    <div class="chips">
      <div class="chip"><div class="k">趋势腿 · USDⓈ-M ${t.max_leverage ? t.max_leverage + "x" : ""}</div>
        <div class="v ${t.gate_open ? "" : "dim"}">${t.gate_open ? "在场" : "空仓(闸关)"}</div></div>
      <div class="chip"><div class="k">carry 腿 · Δ 中性</div>
        <div class="v ${Math.abs(delta) < (cCap || 1) * 0.05 ? "" : "neg"}">Δ $${money(delta)}</div></div>
      <div class="chip"><div class="k">趋势武装</div><div class="v ${tArmed ? "" : "dim"}">${tArmed ? "已武装" : "未武装"}</div></div>
      <div class="chip"><div class="k">carry 武装</div><div class="v ${cArmed ? "" : "dim"}">${cArmed ? "已武装" : "未武装"}</div></div>
    </div>
    <div class="subhead">carry 当前空头 · 季度 COIN-M</div>
    <div class="uni">${activeDated || '<span class="dim">—</span>'}</div>
    <div class="insight">
      <div class="ins-h">合成命题 · 趋势骑牛市 / carry 吃空窗</div>
      <div class="ins-row">
        <span>负相关 ρ <b>−0.20</b></span>
        <span>回测 Sharpe <b>1.18</b>(扣 funding ~0.9)</span>
        <span>尾砍至 <b>−10%</b></span>
      </div>
    </div>
    <div class="note"><b>${anyArmed ? "实盘" : "模拟编排"}</b> · 与上方「加密实盘」是两套账:这是 60% 趋势永续 + 40% carry(现货多+季度空)的 C×D 合成编排,${anyArmed ? "已部分武装" : "两腿均未武装(carry 待注资 spot+COIN-M),当前为 dry 模拟"} · 更新于 ${ago(t.ts || c.ts)}</div>`;
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
    ["data/cxd_live.json", renderCxd, "body-cxd"],
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
  applyCounts();
  wireCharts();
  pageSub(currentRoute());
  booted = true;
  $("clock").textContent = new Date().toLocaleTimeString("zh-CN", { hour12: false });
}
function tick() {
  const btn = $("refresh");
  btn.classList.add("spin");
  // 先拉 cron JSON 快照,再立刻刷一次币安实时价(否则点刷新只更新 10min 级快照、不动实时价)
  load()
    .then(() => refreshLivePrices())
    .finally(() => setTimeout(() => btn.classList.remove("spin"), 600));
}

// ---- router: hash-based, one view visible at a time (keeps each page short) ----
const ROUTES = {
  overview: "概览", live: "加密实盘 · X4 趋势", cta: "A股 · CTA-R 跨资产",
  cxd: "C×D 合成账", paper: "加密模拟盘",
};
function currentRoute() {
  const r = (location.hash || "").replace(/^#\/?/, "");
  return ROUTES[r] ? r : "overview";
}
function showRoute(route) {
  document.querySelectorAll(".view").forEach((v) => { v.hidden = v.id !== "view-" + route; });
  document.querySelectorAll(".nav-item").forEach((a) => a.classList.toggle("active", a.dataset.route === route));
  const t = $("page-title"); if (t) t.textContent = ROUTES[route] || "概览";
  pageSub(route);
  document.body.classList.remove("nav-open");           // close mobile drawer on navigate
  window.scrollTo(0, 0);
}
function go(route) { location.hash = "#/" + route; }
window.addEventListener("hashchange", () => showRoute(currentRoute()));

// ---- real-time: poll Binance USDⓈ-M public mark prices between the 10-min cron snapshots and re-derive
//      live uPnL / equity / gate distance in the browser (no key, public CORS endpoint) ----
const SPOT_TICKER = "https://api.binance.com/api/v3/ticker/price?symbol=";
function liveSymbols() {
  const u = (store.live && store.live.universe) || UNIVERSE;
  const set = new Set(u.map((c) => (c.endsWith("USDT") ? c : c + "USDT")));
  set.add("BTCUSDT");                                   // always need BTC for the gate
  return [...set];
}
async function refreshLivePrices() {
  if (!store.live || document.hidden) return;
  // per-symbol fetch (the single-symbol endpoint is the simplest/most portable; CORS = * on Binance
  // public market data). A blocked/offline fetch is swallowed -> the cron snapshot stays on screen.
  const results = await Promise.allSettled(
    liveSymbols().map((s) => fetch(SPOT_TICKER + s, { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)))
  );
  let any = false;
  results.forEach((res) => {
    const o = res.status === "fulfilled" && res.value;
    if (o && o.symbol && o.price) { livePx[o.symbol] = parseFloat(o.price); any = true; }
  });
  if (any) patchLive();
}
function patchLive() {
  const base = store.live;
  if (!base) return;
  const d = JSON.parse(JSON.stringify(base));          // clone — never corrupt the cron snapshot
  let acc = 0, anyLive = false;
  (d.holdings || []).forEach((h) => {
    const px = livePx[h.symbol];
    if (px && h.entry && h.qty) {
      anyLive = true;
      const isShort = h.side === "short" || (h.value || 0) < 0;
      h.price = px;
      h.value = (isShort ? -1 : 1) * px * h.qty;
      h.upnl = (isShort ? h.entry - px : px - h.entry) * h.qty;
    }
    if (h.upnl != null) acc += h.upnl;
  });
  if (d.holdings && d.holdings.length && anyLive) {
    d.unrealized_pnl = acc;
    d.equity = (d.capital || 0) + acc;
    if (d.inception_equity) {                            // 总盈亏 also ticks live with equity
      d.total_pnl = d.equity - d.inception_equity;
      d.total_pnl_pct = d.inception_equity ? d.equity / d.inception_equity - 1 : 0;
    }
  }
  const bpx = livePx["BTCUSDT"];
  if (bpx) { d.btc_px = bpx; if (d.btc_sma200) d.btc_to_sma = d.btc_px / d.btc_sma200 - 1; d.live_price = true; }
  liveOnly = true;                                      // skip count-up re-animation on a price tick
  store.live = d;
  renderLive(d);
  renderOverview();
  applyCounts();
  wireCharts();
  // prune chart registry to DOM-present ids (live panel re-renders its chart each tick — avoid leak)
  Object.keys(CHARTS).forEach((id) => { if (!document.querySelector(`[data-cid="${id}"]`)) delete CHARTS[id]; });
  liveOnly = false;
  if (currentRoute() === "live" || currentRoute() === "overview") pageSub(currentRoute());
  $("clock").textContent = new Date().toLocaleTimeString("zh-CN", { hour12: false }) + " · 实时";
}

// ---- wiring ----
$("refresh").addEventListener("click", tick);
$("theme-btn").addEventListener("click", toggleTheme);
$("menu-btn").addEventListener("click", () => document.body.classList.toggle("nav-open"));
$("scrim").addEventListener("click", () => document.body.classList.remove("nav-open"));
document.querySelectorAll(".nav-item").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); go(a.dataset.route); }));
document.addEventListener("click", (e) => { const t = e.target.closest(".otile[data-route]"); if (t) go(t.dataset.route); });
document.addEventListener("click", (e) => {                 // 权益曲线 盘中/日线 切换
  const b = e.target.closest(".seg[data-curve]");
  if (!b || b.disabled || !store.live) return;
  liveCurveMode = b.dataset.curve;
  liveOnly = true; renderLive(store.live); applyCounts(); wireCharts(); liveOnly = false;
});
document.addEventListener("visibilitychange", () => { if (!document.hidden) { load(); refreshLivePrices(); } });
applyTheme(document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark");
showRoute(currentRoute());
tick();
setInterval(load, 45000);                              // cron JSON snapshot (positions/stops/capital)
setInterval(refreshLivePrices, 4000);                  // live spot price -> uPnL/equity/gate, every 4s
