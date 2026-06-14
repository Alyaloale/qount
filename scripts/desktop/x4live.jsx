// X4 实盘 桌面组件 (Übersicht). 固定 TOP7 纯现货趋势系统(BTC/ETH/BNB/SOL/XRP/ADA/LINK · 1x · 逆波动率 · BTC200d 闸).
// 显示:武装状态 / BTC 大盘闸(及距离) / 资金部署 / 持仓(闸开时)/ 当日订单. 数据全在 Mac 本地
// (state/x4/live/latest.json, 由 x4_live.py 写), 只读. 安装: 放进 ~/Library/Application Support/Übersicht/widgets/.

export const command = "/Users/alyaloale/Code/qount/scripts/desktop/x4live_fetch.sh";
export const refreshFrequency = 300000; // 5 分钟

export const className = `
  top: 56px;
  left: 56px;
  width: 360px;
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

  .hd { display:flex; justify-content:space-between; align-items:center; margin-bottom:2px; }
  .title { font-size: 12.5px; opacity:0.6; letter-spacing:0.3px; }
  .badge { font-size: 11px; padding:3px 9px; border-radius:8px; font-weight:600; margin-left:5px; }
  .b-armed { background:rgba(55,214,122,0.16); color:#37d67a; }
  .b-safe { background:rgba(139,151,168,0.16); color:#b5c0d0; }
  .b-open { background:rgba(55,214,122,0.16); color:#37d67a; }
  .b-shut { background:rgba(255,176,32,0.16); color:#ffb020; }
  .big { font-size: 21px; font-weight:700; letter-spacing:-0.3px; margin: 6px 0 1px;
         font-variant-numeric: tabular-nums; }
  .sub { font-size: 12.5px; opacity:0.85; margin: 2px 0 7px; font-variant-numeric: tabular-nums; }
  .divider { height:1px; background:rgba(255,255,255,0.08); margin: 7px 0 6px; }
  .colhd { display:flex; font-size:11px; opacity:0.4; letter-spacing:0.4px; padding-bottom:3px; }
  .colhd .c1 { flex:1; } .colhd .c2 { width:70px; text-align:right; } .colhd .c3 { width:80px; text-align:right; }
  .prow { display:flex; align-items:baseline; font-size:12.5px; padding:2.5px 0; font-variant-numeric: tabular-nums; }
  .prow .c1 { flex:1; opacity:0.92; } .prow .c2 { width:70px; text-align:right; opacity:0.7; }
  .prow .c3 { width:80px; text-align:right; }
  .green { color:#37d67a; } .red { color:#ff5c5c; } .amber { color:#ffb020; } .gray { color:#8b97a8; }
  .ft { font-size: 11px; opacity:0.45; margin-top: 9px; line-height:1.6; }
`;

const usd = (x) => "$" + (Math.round(x * 100) / 100).toLocaleString(undefined, { maximumFractionDigits: 2 });
const pct = (x) => (x >= 0 ? "+" : "") + (x * 100).toFixed(1) + "%";
const md = (s) => (s && s.length >= 10 ? s.slice(5) : s);
const px = (x) => "$" + x.toLocaleString(undefined, { maximumFractionDigits: x >= 100 ? 0 : 3 });

// --- 拖动 + 记住位置 ---
const POS_KEY = "x4live_widget_pos";
const loadPos = () => {
  try { return JSON.parse(window.localStorage.getItem(POS_KEY)) || { left: 56, top: 56 }; }
  catch (e) { return { left: 56, top: 56 }; }
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
  if (!d || d.error) {
    return (
      <div {...dragProps}>
        <div className="hd"><span className="title">X4 实盘 · 固定 TOP7</span><span className="badge b-safe">无数据</span></div>
        <div className="sub gray">{d && d.error ? d.error : "跑 x4_live.py live 生成 latest.json"} · 可拖动</div>
      </div>
    );
  }
  const gate = d.gate_open;
  const holdings = d.holdings || [];
  const orders = d.orders || [];
  return (
    <div {...dragProps}>
      <div className="hd">
        <span className="title">X4 实盘 · 固定 TOP7 · {usd(d.capital)} 现货</span>
        <span>
          <span className={"badge " + (d.armed ? "b-armed" : "b-safe")}>{d.armed ? "已武装" : "未武装·只读"}</span>
        </span>
      </div>

      <div className="big">
        部署 {usd(d.deployed)} <span className="gray" style={{ fontSize: 13, fontWeight: 400 }}>/ 现金 {usd(d.cash)}</span>
      </div>
      <div className="sub">
        BTC 大盘闸 <span className={gate ? "green" : "amber"}>{gate ? "● 开(顺势)" : "● 关(吃现金)"}</span>
        {"  ·  BTC " + px(d.btc_px) + " vs 200MA " + px(d.btc_sma200) + " "}
        <span className={d.btc_to_sma >= 0 ? "green" : "amber"}>{pct(d.btc_to_sma)}</span>
      </div>

      <div className="divider" />

      {gate && holdings.length > 0 ? (
        <div>
          <div className="colhd"><span className="c1">持仓(逆波动率)</span><span className="c2">权重</span><span className="c3">市值</span></div>
          {holdings.map((h, i) => (
            <div className="prow" key={i}>
              <span className="c1"><span className="green">多</span> {h.symbol.replace("USDT", "")}</span>
              <span className="c2">{(h.weight * 100).toFixed(0)}%</span>
              <span className="c3 green">{usd(h.value)}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="sub amber" style={{ margin: "2px 0 4px" }}>
          全员空仓 · 吃现金 · 等 BTC 站上 200MA(还差 {pct(-d.btc_to_sma)})
        </div>
      )}

      {orders.length > 0 && (
        <div>
          <div className="colhd" style={{ marginTop: 4 }}><span className="c1">今日订单</span><span className="c3">金额</span></div>
          {orders.map((o, i) => (
            <div className="prow" key={i}>
              <span className="c1"><span className={o.side === "buy" ? "green" : "red"}>{o.side === "buy" ? "买" : "卖"}</span> {o.symbol}</span>
              <span className="c3">{usd(o.est_usdt)}{d.armed ? "" : "(拟)"}</span>
            </div>
          ))}
        </div>
      )}

      <div className="ft">
        BTC/ETH/BNB/SOL/XRP/ADA/LINK · 1x · 逆波动率 · 200MA 闸<br />
        数据 bar {md(d.bar)} · {d.armed ? "真单模式" : "未武装(打印拟单不下单)"} · 可拖动
      </div>
    </div>
  );
};
