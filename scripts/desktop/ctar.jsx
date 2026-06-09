// CTA-R 桌面组件 (Übersicht). 常驻桌面:总盈亏/收益率、今日盈亏、净值曲线、分仓、调仓提醒。
// 数据来自 WSL(scripts/desktop/ctar_fetch.sh → ssh → cta_portfolio status --json)。只读,不下单。
// 安装:brew install --cask ubersicht;把本文件放进 ~/Library/Application Support/Übersicht/widgets/。

export const command = "/Users/alyaloale/Code/qount/scripts/desktop/ctar_fetch.sh";
export const refreshFrequency = 300000; // 5 分钟

export const className = `
  top: 56px;
  left: 56px;
  width: 300px;
  color: #e8eef7;
  font-family: -apple-system, "PingFang SC", Menlo, sans-serif;
  background: rgba(20, 24, 33, 0.78);
  backdrop-filter: blur(14px);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 16px;
  padding: 14px 16px;
  box-shadow: 0 10px 30px rgba(0,0,0,0.35);
  -webkit-font-smoothing: antialiased;
  pointer-events: auto;   /* 接收鼠标 -> 可拖 */
  cursor: move;
  user-select: none;

  .hd { display:flex; justify-content:space-between; align-items:center; margin-bottom:1px; }
  .title { font-size: 11px; opacity:0.55; letter-spacing:0.5px; }
  .badge { font-size: 10.5px; padding:2px 8px; border-radius:7px; font-weight:600; }
  .pnl { font-size: 32px; font-weight:700; letter-spacing:-0.5px; margin: 2px 0 0;
         font-variant-numeric: tabular-nums; }
  .sub { font-size: 11.5px; opacity:0.85; margin: 2px 0 6px; font-variant-numeric: tabular-nums; }
  .divider { height:1px; background:rgba(255,255,255,0.08); margin: 5px 0; }
  .colhd { display:flex; align-items:center; font-size:10px; opacity:0.38;
           letter-spacing:0.5px; padding-bottom:2px; }
  .row { display:flex; align-items:center; font-size:11.5px; padding:2.5px 0;
         font-variant-numeric: tabular-nums; }
  .row .nm { flex:1; opacity:0.92; }
  .row .rpc { width:52px; text-align:right; }
  .row .rw  { width:104px; text-align:right; opacity:0.5; }
  .green { color:#37d67a; } .red { color:#ff5c5c; } .gray { color:#8b97a8; }
  .ft { font-size: 10px; opacity:0.45; margin-top: 7px; line-height:1.55; }
  .alert { background: rgba(255,92,92,0.16); border:1px solid rgba(255,92,92,0.38); color:#ff9a9a;
           border-radius:10px; padding:7px 9px; margin-top:7px; font-size:11px; line-height:1.5; }
`;

const yuan = (x) => (x < 0 ? "-" : "") + "¥" + Math.abs(Math.round(x)).toLocaleString();
const pct = (x) => (x >= 0 ? "+" : "") + (x * 100).toFixed(2) + "%";
const md = (s) => (s && s.length >= 10 ? s.slice(5) : s);          // 2026-06-09 -> 06-09
const MODE_CN = { aggressive: "进取", balanced: "均衡", conservative: "稳健" };

// --- 自由拖动 + 记住位置(localStorage 跨刷新/重载持久化)---
const POS_KEY = "ctar_widget_pos";
const loadPos = () => {
  try { return JSON.parse(window.localStorage.getItem(POS_KEY)) || { left: 56, top: 56 }; }
  catch (e) { return { left: 56, top: 56 }; }
};
const savePos = (p) => { try { window.localStorage.setItem(POS_KEY, JSON.stringify(p)); } catch (e) {} };
// Übersicht 把 className(定位)套在外层容器,渲染内容是子元素 → 向上找真正定位的祖先来移动。
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
// ref 回调:每次渲染后把定位容器摆回记住的位置(防止 5 分钟刷新跳回)。
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

function Curve({ pts }) {
  const W = 268, H = 50, M = { sm: "2px 0 6px" };
  if (!pts || pts.length < 1) return <svg width={W} height={H} style={{ display: "block", margin: M.sm }} />;
  if (pts.length < 2) {
    const y = H / 2;
    return (
      <svg width={W} height={H} style={{ display: "block", margin: M.sm }}>
        <line x1="0" y1={y} x2={W} y2={y} stroke="rgba(255,255,255,0.16)" strokeWidth="1" strokeDasharray="3 4" />
        <circle cx={W - 3} cy={y} r="2.5" fill="#8b97a8" />
        <text x="0" y={y - 7} fill="rgba(255,255,255,0.38)" fontSize="10">净值曲线 · 第 {pts.length} 天(明日起成形)</text>
      </svg>
    );
  }
  const vals = pts.map((p) => p.equity);
  const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
  const xy = pts.map((p, i) => [(i / (pts.length - 1)) * W, H - ((p.equity - lo) / span) * (H - 8) - 4]);
  const line = xy.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const up = vals[vals.length - 1] >= vals[0];
  const stroke = up ? "#37d67a" : "#ff5c5c";
  const [lx, ly] = xy[xy.length - 1];
  return (
    <svg width={W} height={H} style={{ display: "block", margin: M.sm }}>
      <polygon points={`0,${H} ${line} ${W},${H}`} fill={stroke} opacity="0.10" />
      <polyline points={line} fill="none" stroke={stroke} strokeWidth="1.6" />
      <circle cx={lx} cy={ly} r="2.4" fill={stroke} />
    </svg>
  );
}

export const render = ({ output }) => {
  const dragProps = { ref: applySavedPos, onMouseDown: startDrag };
  let d;
  try { d = JSON.parse((output || "").trim().split("\n").filter((l) => l.startsWith("{")).pop()); }
  catch (e) { d = null; }
  if (!d) {
    return (
      <div {...dragProps}>
        <div className="hd"><span className="title">CTA-R 组合</span><span className="badge gray">取数失败</span></div>
        <div className="sub gray">检查 ssh home / WSL（{(output || "").slice(0, 40)}）· 可拖动</div>
      </div>
    );
  }
  const tp = d.total_pnl || 0, day = d.day_pnl || 0;
  const cls = tp >= 0 ? "green" : "red";
  return (
    <div {...dragProps}>
      <div className="hd">
        <span className="title">CTA-R · {d.paper ? "模拟盘" : "实盘"}</span>
        {d.due
          ? <span className="badge red">🔔 待调仓</span>
          : <span className="badge gray">{d.price_source === "sina_live" ? "实时" : "收盘"}</span>}
      </div>
      <div className={"pnl " + cls}>{(tp >= 0 ? "+" : "") + yuan(tp)}</div>
      <div className="sub">
        <span className={cls}>{pct(d.total_pnl_pct || 0)}</span>
        {"  ·  今日 "}<span className={day >= 0 ? "green" : "red"}>{(day >= 0 ? "+" : "") + yuan(day)}</span>
        {"  ·  总资产 " + yuan(d.equity || 0)}
      </div>
      <Curve pts={d.equity_curve} />
      <div className="divider" />
      <div className="colhd"><span className="nm" style={{ flex: 1 }}>持仓</span>
        <span className="rpc" style={{ width: 52, textAlign: "right" }}>盈亏</span>
        <span className="rw" style={{ width: 104, textAlign: "right" }}>当前→目标</span></div>
      {(d.positions || []).filter((p) => p.shares > 0).sort((a, b) => b.market_value - a.market_value).map((p) => {
        const pc = (p.pnl_pct || 0) * 100;
        return (
          <div className="row" key={p.symbol}>
            <span className="nm">{p.name}</span>
            <span className={"rpc " + (pc >= 0 ? "green" : "red")}>{(pc >= 0 ? "+" : "") + pc.toFixed(1) + "%"}</span>
            <span className="rw">{(p.weight * 100).toFixed(1)}→{(p.target_weight * 100).toFixed(1)}%</span>
          </div>
        );
      })}
      {d.due && (
        <div className="alert">🔔 需要调仓:{(d.due_reasons || []).join(" + ")}（{(d.orders || []).length} 笔）
          {d.paper ? " · 模拟将自动成交" : " · 实盘请手动下单后 record-fill"}</div>
      )}
      <div className="ft">
        数据 {md(d.data_date)} · 上次调仓 {md(d.last_rebalance_date)} · {MODE_CN[d.mode] || d.mode} · 可拖动
      </div>
    </div>
  );
};
