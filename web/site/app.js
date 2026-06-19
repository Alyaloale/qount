"use strict";

// 固定 TOP7 现货币池(线 D §21,逆波动率 · 1x · BTC 200d 大盘闸)
const UNIVERSE = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "LINK"];

// ---- helpers ----
const $ = (id) => document.getElementById(id);
const cls = (n) => (n > 0 ? "pos" : n < 0 ? "neg" : "dim");
const sign = (n) => (n > 0 ? "+" : "");
const r2 = (n) => Math.round((n + (n >= 0 ? 1 : -1) * Number.EPSILON) * 100) / 100;  // 舍到分,符号一致
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

// ---- 涨跌配色 (红涨绿跌 cn / 绿涨红跌 us, persisted) ----
function applyColor(c) {
  c = c === "us" ? "us" : "cn";
  document.documentElement.setAttribute("data-color", c);
  try { localStorage.setItem("qount-color", c); } catch (e) {}
  const b = document.getElementById("color-btn");
  if (b) b.title = c === "us" ? "涨跌配色 · 当前绿涨红跌 → 切红涨绿跌" : "涨跌配色 · 当前红涨绿跌 → 切绿涨红跌";
}
function toggleColor() {
  applyColor(document.documentElement.getAttribute("data-color") === "us" ? "cn" : "us");
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
    const hasCarry = !!l.carry && !!l.carry.active_dated && l.carry.active_dated.length > 0;
    s = `${longOn ? "做多" : shortOn ? "做空对冲" : "空仓"}${hasCarry ? " · carry" : ""} · ${l.armed ? "已武装" : "未武装"} · 更新 ${ago(l.ts)}`;
  } else if (route === "cta" && c) {
    s = `累计 ${pct(c.total_pnl_pct || 0)} · 数据 ${c.data_date || "—"}`;
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
  // 境内访问墙外 VPS 时 HTTPS 请求可能挂住(既不成功也不报错)。没有超时的话 load() 永不 settle,
  // 刷新按钮会一直转圈、画面停在上一次成功的快照。加 AbortController 兜底:到点中止,让 load() 必定结束。
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 8000);
  try {
    const r = await fetch(path + "?t=" + Date.now(), { cache: "no-store", signal: ctrl.signal });
    if (!r.ok) throw new Error("HTTP " + r.status);
    return await r.json();
  } catch (e) {
    throw ctrl.signal.aborted ? new Error("请求超时(8s)") : e;
  } finally {
    clearTimeout(timer);
  }
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
  // 成本线 / 基准线:折进 y 轴值域,保证始终可见(即便权益一直在成本上方)
  const ref = (opts.ref != null && isFinite(opts.ref)) ? opts.ref : null;
  let minV = Math.min(...vals), maxV = Math.max(...vals);
  if (ref != null) { minV = Math.min(minV, ref); maxV = Math.max(maxV, ref); }
  const pad = (maxV - minV) * 0.06 || Math.abs(maxV) * 0.01 || 1;
  const lo = minV - pad, hi = maxV + pad, span = hi - lo || 1;
  const X = (i) => L + (i / (n - 1)) * plotW;
  const Y = (v) => T + (1 - (v - lo) / span) * plotH;
  const xy = vals.map((v, i) => [X(i), Y(v)]);
  const d = xy.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  const up = vals[n - 1] >= vals[0];
  const color = up ? "var(--up)" : "var(--down)";
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
  // 成本线:横虚线 + 右端标签(权益在线上=盈利,在线下=亏损)
  let refLine = "";
  if (ref != null) {
    const ry = Y(ref).toFixed(1);
    refLine = `<line class="refline" x1="${L}" y1="${ry}" x2="${L + plotW}" y2="${ry}"/>` +
      `<text class="reflbl" x="${L + plotW - 2}" y="${(+ry - 5).toFixed(1)}" text-anchor="end">` +
      `${opts.refLabel || "成本"} ${cur}${grp(ref, Math.abs(ref) < 1000 ? 2 : 0)}</text>`;
  }
  CHARTS[id] = { vals, dates, n, W, H, L, T, plotW, plotH, lo, span, cur, ref };
  return `<div class="chartwrap">
    <svg class="chart${cz ? " compact" : ""}" viewBox="0 0 ${W} ${H}" data-cid="${id}">
      <defs><linearGradient id="${gid}" x1="0" x2="0" y1="0" y2="1">
        <stop offset="0" stop-color="${color}" stop-opacity=".16"/>
        <stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>
      ${grid}
      <path d="${area}" fill="url(#${gid})"/>
      <path d="${d}" fill="none" stroke="${color}" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>
      ${refLine}
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
  // 命中映射:鼠标 → viewBox x → 扣掉绘图区左右边距(L/R)后的数据区比例,再吸附到最近数据点。
  // (宽高比由 viewBox 保持,clientX→viewBox 为线性;此前按整幅宽算、没扣 L 导致点位滞后鼠标。)
  const svgX = (e.clientX - rect.left) / rect.width * c.W;
  let f = c.plotW > 0 ? (svgX - c.L) / c.plotW : 0;
  f = Math.max(0, Math.min(1, f));
  const i = Math.round(f * (c.n - 1)), v = c.vals[i];
  const xv = c.L + (i / (c.n - 1)) * c.plotW;
  const yv = c.T + (1 - (v - c.lo) / c.span) * c.plotH;
  const cx = svg.querySelector(".cx"), hot = svg.querySelector(".hot");
  cx.setAttribute("x1", xv); cx.setAttribute("x2", xv); cx.style.opacity = 1;
  hot.setAttribute("cx", xv); hot.setAttribute("cy", yv); hot.style.opacity = 1;
  const tip = svg.parentNode.querySelector(".chart-tip");
  const dlab = c.dates ? c.dates[i] : "#" + i;
  // 结合本金基线(ref)显示该点盈亏金额 + 百分比(股市做法:浮在点上,红涨绿跌跟随配色)
  let pnlHtml = "";
  if (c.ref != null && isFinite(c.ref) && c.ref !== 0) {
    const pnl = v - c.ref, rate = pnl / c.ref;
    pnlHtml = `<span class="tip-pnl ${cls(pnl)}">${signed(pnl, c.cur)} · ${pct(rate)}</span>`;
  }
  tip.innerHTML = `<b>${c.cur}${grp(v, Math.abs(v) < 1000 ? 2 : 0)}</b><span>${dlab}</span>${pnlHtml}`;
  const px = (xv / c.W) * rect.width, py = (yv / c.H) * rect.height;
  // 不压点:水平跟随光标(夹在边界内),竖直永远放到点的对侧 —— 点在上半区则框落底部,反之升到顶部。
  // 这样十字线 + 圆点始终露出,能看清落在哪个点(股市 tooltip 做法)。
  const tw = tip.offsetWidth || 80, th = tip.offsetHeight || 48;
  tip.style.left = Math.max(tw / 2 + 2, Math.min(rect.width - tw / 2 - 2, px)) + "px";
  tip.style.top = (py < rect.height / 2 ? rect.height - th - 4 : 4) + "px";
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
  const col = up ? "var(--up)" : "var(--down)";
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
    const hasCarry = !!l.carry && !!l.carry.active_dated && l.carry.active_dated.length > 0;
    const state = longOn ? "做多 · 持多仓" : shortOn ? "做空 · 对冲" : "空仓 · 观望";
    tiles.push(`<div class="otile" data-route="live">
      <div class="ok"><span class="live-dot"></span>加密实盘 · ${longOn ? "趋势做多" : shortOn ? "做空对冲" : "空仓"}${hasCarry ? " + carry" : ""}<span class="ot-tag real">实盘</span></div>
      <div class="oe"><span class="cur">$</span>${counted("ov-live", l.equity != null ? l.equity : l.capital, 2)}</div>
      <div class="os ${l.total_pnl != null ? cls(l.total_pnl) : ""}">${state}${l.trend_pnl != null ? ` · 趋势 ${signed(l.trend_pnl, "$")}` : ""}${l.carry_pnl != null ? ` · carry ${signed(l.carry_pnl, "$")}` : ""}${l.total_pnl != null ? ` · 总 ${signed(l.total_pnl, "$")}` : lUp != null ? ` · ${arw(lUp)}未实现 ${signed(lUp, "$")}` : ""} · ${l.armed ? "已武装" : "未武装"}</div>
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
      <div class="sc-k"><span class="live-dot"></span>真实资金 · 加密实盘 C×D</div>
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
    ? chart(series, { cur: "$", ref: d.inception_equity, refLabel: "成本" })
    : `<div class="empty">${liveCurveMode === "daily" ? "日线(次日起)" : "24 小时"}数据累积中…</div>`;
  return `<div class="cap-row"><div class="chart-cap">${cap}</div>${toggle}</div>${body}`;
}
function renderLive(d) {
  store.live = d;
  const body = $("body-live");
  const head = $("panel-live").querySelector(".panel-head");
  head.querySelectorAll(".badge.gate-open,.badge.gate-closed,.badge.shorting,.badge.lev,.badge.carry").forEach((e) => e.remove());
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
  const hasCarry = !!d.carry && !!d.carry.active_dated && d.carry.active_dated.length > 0;
  const gb = document.createElement("span");
  gb.className = "badge " + (d.gate_open ? "gate-open" : shorting ? "shorting" : "gate-closed");
  gb.textContent = d.gate_open ? "做多" : shorting ? "做空对冲" : "空仓";
  head.appendChild(gb);
  if (hasCarry) {
    const cb = document.createElement("span");
    cb.className = "badge carry";
    cb.textContent = "carry Δ" + (d.carry.net_delta != null ? (Math.abs(d.carry.net_delta) < (d.carry.capital || 1) * 0.05 ? "≈0" : "偏" + (d.carry.net_delta > 0 ? "+" : "") + money(d.carry.net_delta)) : "");
    head.appendChild(cb);
  }

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

  // 未实现(总浮盈):严格 = 各标的浮盈「按显示的分」之和,消除分项四舍五入错位(逐个加起来=总数)。
  const upnlShown = holdings.length
    ? holdings.reduce((s, h) => s + (h.upnl != null ? r2(h.upnl) : 0), 0)
    : d.unrealized_pnl;
  const upnl = upnlShown != null ? r2(upnlShown) : d.unrealized_pnl;
  // 已实现 = 钱包余额 − 入金成本(已平仓盈亏 + 资金费 + 手续费,已落袋)。总盈亏 = 已实现 + 未实现,
  // 所以「各标的浮盈之和」(只是未实现)≠ 总盈亏,差额就是这块已实现 —— 显式列出消除歧义。
  const realized = (d.inception_equity != null && d.capital != null) ? r2(d.capital - d.inception_equity) : null;
  // 总盈亏 = 后端算好的「全账户」口径(趋势 + carry vs 入金基线);退回逐项相加仅在旧数据无 total_pnl 时
  const totalShown = d.total_pnl != null ? r2(d.total_pnl)
    : (realized != null && upnl != null) ? r2(realized + upnl) : d.total_pnl;
  // 仓位口径:gross = 各腿名义之和(持仓占比的分母);bp = 购买力(本金 × 杠杆),当前仓位条的满格
  const gross = holdings.reduce((s, h) => s + Math.abs(h.value || 0), 0);
  const bp = (d.capital || 0) * (d.max_leverage || 1) || gross;
  const used = bp > 0 ? gross / bp : 0;
  const posbar = holdings.length
    ? `<div class="subhead">当前仓位 · 部署名义 ${money(gross, "$")} / 购买力 ${money(bp, "$")}</div>
       <div class="posbar">
         <div class="posbar-meta"><span>已用 <b>${pct(used, 0)}</b> 购买力</span><span>空闲保证金 <b>${money(Math.max(0, d.capital - (d.margin_used || 0)), "$")}</b></span></div>
         <div class="posbar-track">${holdings.map((h) => {
           const v = Math.abs(h.value || 0); if (!v || bp <= 0) return "";
           const sh = h.side === "short" || (h.value || 0) < 0;
           return `<div class="posbar-seg${sh ? " short" : ""}" style="width:${(v / bp * 100).toFixed(2)}%" title="${h.symbol || h.sym} ${money(v, "$")}"></div>`;
         }).join("")}<div class="posbar-seg free" style="width:${(Math.max(0, bp - gross) / bp * 100).toFixed(2)}%"></div></div>
       </div>`
    : "";
  const holdHtml = holdings.length
    ? `<div class="subhead">当前持仓 · ${shorting ? "永续做空对冲(§24 做空闸)" : isPerp ? "永续多头(名义)" : "现货"}</div><table class="tbl">
        <thead><tr><th>币种</th><th>方向</th><th class="opt">入场</th><th class="opt">现价</th><th>名义</th><th>占比</th><th>浮盈</th><th title="按名义,不含杠杆">收益率</th><th title="按保证金 ROE,含 ${lev}x 杠杆(同币安持仓页)">ROE</th><th class="opt">止损</th></tr></thead>
        <tbody>${holdings.map((h) => {
          const sh = h.side === "short" || (h.value || 0) < 0;
          const up = h.upnl || 0;
          const share = gross > 0 ? Math.abs(h.value || 0) / gross : 0;
          // 收益率 = 浮盈 / 入场名义(entry×qty);缺入场则退回当前名义。与本行「浮盈」自洽。
          const roeDenom = (h.entry && h.qty) ? Math.abs(h.entry * h.qty) : Math.abs(h.value || 0);
          const roe = (h.upnl != null && roeDenom > 0) ? h.upnl / roeDenom : null;
          // ROE(按保证金,含杠杆)= 收益率 × 杠杆,与币安持仓页一致
          const roeMargin = roe != null ? roe * lev : null;
          return `<tr>
          <td class="name">${h.symbol || h.sym || ""}</td>
          <td><span class="side ${sh ? "neg" : "pos"}">${sh ? "空" : "多"}</span></td>
          <td class="opt">${h.entry != null ? money(h.entry, "$") : "—"}</td>
          <td class="opt">${h.price != null ? money(h.price, "$") : "—"}</td>
          <td>${h.value != null ? money(Math.abs(h.value), "$") : "—"}</td>
          <td>${(share * 100).toFixed(1)}%<span class="wbar" style="width:${Math.round(share * 46)}px"></span></td>
          <td class="${cls(up)}">${h.upnl != null ? signed(r2(up), "$") : "—"}</td>
          <td class="${cls(roe || 0)}">${roe != null ? pct(roe) : "—"}</td>
          <td class="${cls(roeMargin || 0)}">${roeMargin != null ? pct(roeMargin) : "—"}</td>
          <td class="opt">${h.stop != null ? money(h.stop, "$") : "—"}</td></tr>`;
        }).join("")}</tbody></table>`
    : `<div class="empty">空仓 — BTC 低于 200 日线,大盘闸关闭,${isPerp ? "永续仓位已全平,资金留在保证金钱包" : "资金全在现金"}</div>`;

  // C×D 合成账作为实盘页内的一个合成仓位卡片(不再单独成页)
  const cxdBlock = cxdCard(store.cxd);

  body.innerHTML = `
    ${banners}
    <div class="hero">
      <div class="equity"><span class="cur">$</span>${counted("live-eq", d.equity != null ? d.equity : d.capital, 2)}</div>
      ${totalShown != null ? `<div class="pnl-tag ${cls(totalShown)}" title="总盈亏 = 已实现 + 未实现(各标的浮盈只是未实现那部分)">总盈亏 ${arw(totalShown)}${signed(totalShown, "$")} · ${pct(d.total_pnl_pct || 0)}</div>` : ""}
      <div class="sub">全账户 · 趋势权益 $${money(d.trend_equity != null ? d.trend_equity : d.capital)}${d.carry ? ` <span class="dim">+</span> carry $${money(d.carry.equity || d.carry.capital)}` : ""}${d.idle_usdt ? ` <span class="dim">+</span> 闲置 $${money(d.idle_usdt)}` : ""}${d.trend_pnl != null ? ` · 趋势 <span class="${cls(d.trend_pnl)}">${signed(r2(d.trend_pnl), "$")}</span> ${pct(d.trend_pnl_pct || 0)}` : ""}${d.carry_pnl != null ? ` · carry <span class="${cls(d.carry_pnl)}">${signed(r2(d.carry_pnl), "$")}</span> ${pct(d.carry_pnl_pct || 0)}` : ""} · 部署名义 $${money(d.deployed)} · 占用保证金 $${money(d.margin_used)}</div>
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
    ${posbar}
    ${holdHtml}
    ${cxdBlock}
    <div class="note"><b>实盘</b> · ${isPerp ? `USDⓈ-M 永续 ${lev}x · 逆波动率平价` : "现货 1x"}${d.chandelier_mult ? ` · chandelier ${d.chandelier_mult}× 兜底止损` : ""} · 更新于 ${ago(d.ts)}</div>`;
}

// ---- 加密 C×D 合成账(作为实盘页内的一个合成仓位卡片) ----
function cxdCard(d) {
  if (!d) return "";
  const t = d.trend || {}, c = d.carry || {};
  const w = d.weights || { trend: 0.6, carry: 0.4 };          // ACTUAL deployed split
  const tw = d.target_weights || { trend: 0.6, carry: 0.4 };  // design intent
  const tArmed = !!t.armed, cArmed = !!c.armed;
  const anyArmed = tArmed || cArmed;
  const tCap = t.capital || 0, cCap = c.capital || 0;
  const cEq = c.equity || cCap;   // carry 全腿权益(含短腿浮盈),fallback to capital for old data
  const total = d.total_capital || (tCap + cCap);
  const activeDated = (c.active_dated || []).map((s) => `<span class="coin">${s}</span>`).join("");
  const delta = c.net_delta || 0;
  return `
    <div class="subhead">C×D 合成仓位 · 实际 趋势 ${pct(w.trend, 0)} + carry ${pct(w.carry, 0)} <span class="dim">· 目标 ${pct(tw.trend, 0)}/${pct(tw.carry, 0)}</span></div>
    <table class="tbl">
      <thead><tr><th>结构</th><th>方向</th><th>当前合约</th><th>额度</th><th>占比</th><th title="净敞口,≈0 即对冲到位">净 Δ</th><th>状态</th></tr></thead>
      <tbody>
        <tr>
          <td class="name">C×D 合成</td>
          <td><span class="side">对冲+趋势</span></td>
          <td>${activeDated || "—"}</td>
          <td>${money(total, "$")}</td>
          <td>100%</td>
          <td class="${Math.abs(delta) < (cCap || 1) * 0.05 ? "" : "neg"}">${signed(r2(delta), "$")}</td>
          <td class="${anyArmed ? "" : "dim"}">${anyArmed ? "已武装" : "未武装"}</td>
        </tr>
        <tr>
          <td class="name">&nbsp;└ 趋势腿</td>
          <td><span class="side ${t.gate_open ? "pos" : (t.shorting ? "neg" : "dim")}">${t.gate_open ? "多头" : (t.shorting ? "做空" : "空仓")}</span></td>
          <td>USDⓈ-M ${t.max_leverage ? t.max_leverage + "x" : ""}</td>
          <td>${money(tCap, "$")}</td>
          <td>${pct(w.trend, 0)}</td>
          <td>—</td>
          <td class="${tArmed ? "" : "dim"}">${tArmed ? "已武装" : "未武装"}</td>
        </tr>
        <tr>
          <td class="name">&nbsp;└ carry 腿</td>
          <td><span class="side">Δ 中性</span></td>
          <td>${activeDated || "—"}</td>
          <td>${money(cEq, "$")}</td>
          <td>${pct(w.carry, 0)}</td>
          <td class="${Math.abs(delta) < (cCap || 1) * 0.05 ? "" : "neg"}">${signed(r2(delta), "$")}</td>
          <td class="${cArmed ? "" : "dim"}">${cArmed ? "已武装" : "未武装"}</td>
        </tr>
      </tbody>
    </table>
    <div class="note dim">C×D = 趋势永续( riding BTC 200 日大盘闸) + carry(现货多 + 季度 COIN-M 空,吃基差收敛)。carry 额度 = 全腿权益(含短腿浮盈),净 Δ ≈ 0 即对冲到位。</div>`;
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
  // C×D 合成账数据不再单独成页,先取到 store 里供实盘页合成仓位卡片使用
  try { store.cxd = await getJSON("data/cxd_live.json"); } catch (e) { store.cxd = null; }
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
  overview: "概览", live: "加密实盘", cta: "A股 · CTA-R 跨资产",
  paper: "加密模拟盘",
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
  // api.binance.com 在境内被墙;没超时的话被卡住的请求永不 settle -> 把刷新链路一起拖住转圈不停。
  const tfetch6 = (u) => {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 6000);
    return fetch(u, { cache: "no-store", signal: ctrl.signal })
      .then((r) => (r.ok ? r.json() : null))
      .finally(() => clearTimeout(timer));
  };
  const results = await Promise.allSettled(liveSymbols().map((s) => tfetch6(SPOT_TICKER + s)));
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
    d.trend_equity = (d.capital || 0) + acc;             // 趋势腿实时 = USDⓈ-M 钱包 + 未实现
    const carryValue = (d.carry && (d.carry.equity || d.carry.capital)) || 0; // carry 全腿净值(含短腿浮盈)
    d.equity = d.trend_equity + carryValue + (d.idle_usdt || 0); // 全账户实时 = 趋势 + carry + 闲置现金,守恒
    if (d.inception_equity) {                            // 总盈亏 also ticks live with full equity
      d.total_pnl = d.equity - d.inception_equity;
      d.total_pnl_pct = d.inception_equity ? d.equity / d.inception_equity - 1 : 0;
    }
    if (d.trend_inception) {                              // 趋势腿盈亏 live tick
      d.trend_pnl = d.trend_equity - d.trend_inception;
      d.trend_pnl_pct = d.trend_inception ? d.trend_equity / d.trend_inception - 1 : 0;
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
$("color-btn").addEventListener("click", toggleColor);
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
applyColor(document.documentElement.getAttribute("data-color") === "us" ? "us" : "cn");
showRoute(currentRoute());
tick();
setInterval(load, 20000);                              // cron JSON snapshot (positions/stops/capital)
setInterval(refreshLivePrices, 4000);                  // live spot price -> uPnL/equity/gate, every 4s
setInterval(() => pageSub(currentRoute()), 1000);      // “更新 X 分钟前”按墙钟走:UI 不假死,数据卡住时数字一直爬 = stale 指示
