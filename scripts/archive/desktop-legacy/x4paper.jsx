// X4 加密模拟盘 桌面组件 (Übersicht). 以部署日为起点的前向模拟账(非回测收益):
// 显示 C×D 合成账的实际持仓(币种/方向/数量/现价/市值)+ 现金 + 自部署起的收益,以及 3腿/S7 的前向收益。
// 数据全在 Mac 本地(state/x4/paper/holdings_latest.json,由 x4_paper.py holdings 写),只读不下单。
// 安装:把本文件放进 ~/Library/Application Support/Übersicht/widgets/(线 A 的 ctar.jsx 同款宿主)。

export const command = "/Users/alyaloale/Code/qount/scripts/desktop/x4paper_fetch.sh";
export const refreshFrequency = 300000; // 5 分钟

export const className = `
  top: 56px;
  left: 460px;
  width: 372px;
  color: #e8eef7;
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  text-rendering: optimizeLegibility;
  background: rgba(20, 24, 33, 0.93);
  backdrop-filter: blur(14px);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 18px;
  padding: 18px 20px;
  box-shadow: 0 10px 30px rgba(0,0,0,0.35);
  -webkit-font-smoothing: antialiased;
  pointer-events: auto;
  cursor: move;
  user-select: none;

  .hd { display:flex; justify-content:space-between; align-items:center; margin-bottom:1px; }
  .title { font-size: 12.5px; opacity:0.6; letter-spacing:0.3px; }
  .badge { font-size: 11.5px; padding:3px 9px; border-radius:8px; font-weight:600; }
  .pnl { font-size: 34px; font-weight:700; letter-spacing:-0.5px; margin: 3px 0 0;
         font-variant-numeric: tabular-nums; }
  .sub { font-size: 12.5px; opacity:0.85; margin: 3px 0 8px; font-variant-numeric: tabular-nums; }
  .divider { height:1px; background:rgba(255,255,255,0.08); margin: 8px 0 6px; }
  .colhd { display:flex; font-size:11px; opacity:0.4; letter-spacing:0.4px; padding-bottom:4px; }
  .colhd .c1 { flex:1; } .colhd .c2 { width:74px; text-align:right; }
  .colhd .c3 { width:84px; text-align:right; } .colhd .c4 { width:74px; text-align:right; }
  .prow { display:flex; align-items:baseline; font-size:12.5px; padding:3px 0;
          font-variant-numeric: tabular-nums; }
  .prow .c1 { flex:1; opacity:0.92; } .prow .c2 { width:74px; text-align:right; opacity:0.7; }
  .prow .c3 { width:84px; text-align:right; opacity:0.7; } .prow .c4 { width:74px; text-align:right; }
  .long { color:#37d67a; } .short { color:#ff5c5c; }
  .green { color:#37d67a; } .red { color:#ff5c5c; } .gray { color:#8b97a8; }
  .cash { font-size:12px; opacity:0.6; margin:6px 0 2px; }
  .ft { font-size: 11px; opacity:0.45; margin-top: 9px; line-height:1.6; }
`;

const usd = (x) => "$" + Math.round(x).toLocaleString();
const pct = (x) => (x >= 0 ? "+" : "") + (x * 100).toFixed(2) + "%";
const md = (s) => (s && s.length >= 10 ? s.slice(5) : s);
const qty = (x) => (Math.abs(x) >= 1 ? x.toFixed(2) : x.toFixed(4));
const px = (x) => "$" + x.toLocaleString(undefined, { maximumFractionDigits: x >= 100 ? 0 : 2 });

// --- 拖动 + 记住位置 ---
const POS_KEY = "x4paper_widget_pos";
const loadPos = () => {
  try { return JSON.parse(window.localStorage.getItem(POS_KEY)) || { left: 460, top: 56 }; }
  catch (e) { return { left: 460, top: 56 }; }
};
const savePos = (p) => { try { window.localStorage.setItem(POS_KEY, JSON.stringify(p)); } catch (e) {} };
const positionedEl = (node) => {
  let el = node;
  while (el && el.parentElement && !["absolute", "fixed"].includes(window.getComputedStyle(el).position)) {
    el = el.parentElement;
  }
  return el || node;
};
const place = (el, p) => {
  el.style.left = p.left + "px"; el.style.top = p.top + "px"; el.style.right = "auto"; el.style.bottom = "auto";
};
const applySavedPos = (node) => { if (node) place(positionedEl(node), loadPos()); };
const startDrag = (e) => {
  const el = positionedEl(e.currentTarget);
  const base = loadPos();
  const sx = e.clientX, sy = e.clientY;
  const onMove = (ev) => {
    const p = { left: Math.max(0, base.left + (ev.clientX - sx)), top: Math.max(0, base.top + (ev.clientY - sy)) };
    place(el, p); savePos(p);
  };
  const onUp = () => { window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp); };
  window.addEventListener("mousemove", onMove);
  window.addEventListener("mouseup", onUp);
  e.preventDefault();
};

export const render = ({ output }) => {
  const dragProps = { ref: applySavedPos, onMouseDown: startDrag };
  let d;
  try { d = JSON.parse((output || "").trim().split("\n").filter((l) => l.startsWith("{")).pop()); }
  catch (e) { d = null; }
  const combo = d && d.books && d.books.combo;
  if (!combo) {
    return (
      <div {...dragProps}>
        <div className="hd"><span className="title">X4 加密模拟盘</span><span className="badge gray">无数据</span></div>
        <div className="sub gray">跑 x4_paper.py holdings 生成 holdings_latest.json · 可拖动</div>
      </div>
    );
  }
  const three = d.books["3leg"], s7 = d.books.s7;
  const cls = combo.fwd_return >= 0 ? "green" : "red";
  return (
    <div {...dragProps}>
      <div className="hd">
        <span className="title">X4 加密模拟盘 · 以 {md(d.deploy_date)} 部署 · 纯模拟</span>
        <span className="badge gray">只读不下单</span>
      </div>
      <div className={"pnl " + cls}>{(combo.fwd_pnl >= 0 ? "+" : "") + usd(combo.fwd_pnl)}</div>
      <div className="sub">
        C×D 合成账 {usd(combo.fwd_equity)} · 自部署 <span className={cls}>{pct(combo.fwd_return)}</span>
        {"  ·  现金 " + usd(combo.cash)}
      </div>

      <div className="colhd">
        <span className="c1">持仓 · {combo.trend_flat ? "趋势空仓 · carry 在场" : "趋势在场 · carry 在场"}</span>
        <span className="c2">数量</span><span className="c3">现价</span><span className="c4">市值</span>
      </div>
      {(combo.positions || []).map((p, i) => (
        <div className="prow" key={i}>
          <span className="c1"><span className={p.side === "多" ? "long" : "short"}>{p.side}</span> {p.instrument}</span>
          <span className="c2">{qty(p.qty)}</span>
          <span className="c3">{px(p.price)}</span>
          <span className="c4">{usd(p.value)}</span>
        </div>
      ))}
      <div className="cash gray">现金 {usd(combo.cash)}(趋势 60% {combo.trend_flat ? "空仓待 BTC 站上 200MA" : "在场"})</div>

      <div className="divider" />
      <div className="prow gray" style={{ fontSize: 11.5 }}>
        <span className="c1">其它账(自部署前向收益)</span>
        <span className="c3">3腿 {three ? pct(three.fwd_return) : "—"}</span>
        <span className="c4">S7 {s7 ? pct(s7.fwd_return) : "—"}</span>
      </div>

      <div className="ft">
        数据 bar {md(combo.as_of)} · 收益自部署起算(非回测)· 持仓按日收盘价标记 · 可拖动
      </div>
    </div>
  );
};
