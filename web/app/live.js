/* Real-account presentation only: no exchange client, order calls or activation. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.QountLive = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const number = (v) => v == null || typeof v === "boolean" || v === "" || !Number.isFinite(Number(v)) ? null : Number(v);
  function accountView(data, now = Date.now()) {
    const unknown = { status: "UNKNOWN", equity: null, available: null, positions: [], complete: false, observed_at: null };
    if (!data || data.read_only !== true || !["AVAILABLE", "PARTIAL"].includes(data.status)) return unknown;
    const stamp = Date.parse(data.observed_at);
    if (!Number.isFinite(stamp) || stamp-now > 60000) return unknown;
    const equity = number(data.usdm_margin_balance_usdt), available = number(data.usdm_available_balance_usdt);
    if (equity == null || available == null || Math.min(equity, available) < 0) return unknown;
    if (!Array.isArray(data.futures_positions) || data.futures_positions.some(p => !p || typeof p !== "object")) return unknown;
    const positions = data.futures_positions.filter(p => p.market === "usdm");
    const complete = data.futures_positions_complete === true;
    return { status: now-stamp > 900000 ? "STALE" : complete ? "FRESH" : "PARTIAL", equity, available,
      positions, complete, observed_at: data.observed_at };
  }
  function render(data) {
    const view = accountView(data);
    const text = (id,value) => { const node=document.getElementById(id); if(node) node.textContent=value; };
    const amount = value => value == null ? "--" : value.toLocaleString("zh-CN", { minimumFractionDigits:2, maximumFractionDigits:4 });
    const escape = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));
    const fresh = view.status === "FRESH";
    text("strategy-equity",amount(view.equity)); text("strategy-available",amount(view.available));
    text("strategy-observed-at",view.observed_at ? `账户观测 ${view.observed_at}` : "账户观测 --");
    text("strategy-account-state",({FRESH:"账户观测已更新",STALE:"快照已过期",PARTIAL:"持仓覆盖待核对",UNKNOWN:"无数据"})[view.status]);
    text("strategy-data-status",fresh ? "账户快照已更新；交易执行状态见策略收据。" : view.status === "STALE" ? "以下余额为旧快照，等待采集更新。" : "无法确认完整USDⓈ-M账户状态。");
    text("strategy-position-count",view.complete ? `${view.positions.length} 项账户持仓` : "持仓待采集");
    const body=document.getElementById("strategy-positions-body");
    if(body) body.innerHTML = view.positions.length ? view.positions.map(p => `<tr><td>${escape(p.symbol)}</td><td>${escape(({long:"多头",short:"空头"})[p.side] || "未知")}</td><td class="numeric">${amount(number(p.quantity))}</td><td class="numeric">${amount(number(p.notional_usdt))}</td><td class="numeric">${amount(number(p.unrealized_pnl_usdt))}</td></tr>`).join("") : `<tr><td colspan="5" class="table-empty">${view.complete ? "该次观测确认USDⓈ-M账户无持仓" : "持仓覆盖不完整，不能确认空仓"}</td></tr>`;
    return view;
  }
  function renderRecords(data) {
    const text=(id,v)=>{const n=document.getElementById(id);if(n)n.textContent=v;};
    const html=(id,v)=>{const n=document.getElementById(id);if(n)n.innerHTML=v;};
    const escape=v=>String(v ?? "").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));
    const amount=v=>number(v)==null ? "--" : number(v).toLocaleString("zh-CN",{maximumFractionDigits:8});
    const time=v=>Number.isFinite(Number(v)) ? new Date(Number(v)).toISOString().replace('T',' ').replace('.000Z',' UTC') : "--";
    if(!data || data.read_only!==true || data.status==='MISSING' || !Array.isArray(data.fills) || !Array.isArray(data.income)) {
      text('real-trades-status','无数据');text('real-income-count','无数据');
      text('real-trades-scope','真实成交来源不可用；不使用模拟流水填充。');
      html('real-trades-body','<tr><td colspan="8" class="table-empty">真实成交来源不可用</td></tr>');
      html('real-income-body','<tr><td colspan="5" class="table-empty">真实资金流水来源不可用</td></tr>');return;
    }
    const complete=data.status==='AVAILABLE';
    text('real-trades-status',`${complete?'已采集':'采集有缺项'} · ${data.fill_count ?? '--'} 笔成交`);
    text('real-income-count',`${data.income_count ?? '--'} 条资金流水`);
    text('real-trades-scope',`采集 ${data.observed_at || '--'} · 覆盖 ${(data.completed_symbols || []).join('、') || '待核对'}。首次查询近7天，持续保留已采集记录；仅按交易所订单ID归属策略，其余保留未归属。${complete?'':'本次采集有缺项，已有记录仅供核对。'}`);
    html('real-trades-body',data.fills.length ? data.fills.map(r=>`<tr><td>${escape(time(r.time))}</td><td>${escape(r.symbol)}</td><td>${escape(r.side)} / ${escape(r.position_side)}</td><td class="numeric">${amount(r.price)}</td><td class="numeric">${amount(r.quantity)}</td><td class="numeric">${amount(r.commission)} ${escape(r.commission_asset)}</td><td class="numeric">${amount(r.realized_pnl)} ${escape(r.pnl_asset || '币种待核对')}</td><td>${r.strategy_id ? escape(r.strategy_id) : "账户成交 · 未归属策略"}</td></tr>`).join('') : `<tr><td colspan="8" class="table-empty">${complete?'已采集范围内暂无成交':'已有记录为空，本次覆盖不完整'}</td></tr>`);
    const names={TRANSFER:'划转',FUNDING_FEE:'资金费',COMMISSION:'手续费',REALIZED_PNL:'已实现盈亏'};
    html('real-income-body',data.income.length ? data.income.map(r=>`<tr><td>${escape(time(r.time))}</td><td>${escape(names[r.income_type] || r.income_type)}</td><td>${escape(r.symbol || '—')}</td><td class="numeric">${amount(r.amount)}</td><td>${escape(r.asset)}</td></tr>`).join('') : `<tr><td colspan="5" class="table-empty">${complete?'已采集范围内暂无资金流水':'资金流水覆盖待核对'}</td></tr>`);
  }
  function renderOneAtr(data) {
    const text=(id,v)=>{const n=document.getElementById(id);if(n)n.textContent=v;};
    const selected=data?.selected;
    const execution=data?.last_execution;
    const protective=execution?.protective || data?.protective_orders?.[0];
    const runtime=data?.runtime;
    const runtimeNames={AUTO:"自动调度已核对",HALTED:"完整停止",DISABLED:"自动定时器未运行",FAILED:"自动任务失败",BLOCKED:"执行受阻",STALE:"执行收据已过期",UNKNOWN:"调度状态待核对"};
    const status=data?.halted ? "完整停止 · 持仓管理已停" : data?.status === "STALE" ? "运行记录已过期" : data?.status === "AVAILABLE" ? (data.auto_action === "BLOCKED" ? "执行受阻" : runtime?.stale ? "调度观测已过期" : runtime ? runtimeNames[runtime.state] || "调度状态待核对" : data.execution_mode === "auto_live" ? "自动实盘收据 · 调度未核实" : data.strategy_live ? "手动实盘收据" : "计划模式") : "无数据";
    text("one-atr-status",status);
    const clock=v=>Number.isFinite(Date.parse(v)) ? `${new Date(v).toLocaleString("zh-CN",{timeZone:"Asia/Singapore",hour12:false})} UTC+8` : "--";
    const retry=runtime?.units?.['qount-notification-retry.service'];
    text("strategy-runtime-note",data?.halted ? "HALT停止整个执行周期及持仓管理；已有交易所原生止损保留。" : runtime ? `调度核对 ${clock(runtime.observed_at)}${runtime.stale ? ' · 观测过期' : ''}${runtime.reason ? ` · ${runtime.reason}` : ''}${retry?.ActiveState === 'failed' || (retry?.Result && retry.Result !== 'success') ? ' · 通知重试任务异常' : ''}${String(runtime.notification_enqueue_status || '').startsWith('ERROR:') ? ' · 异常通知入队失败' : ''}` : "当前仅有后端收据，定时器是否仍在运行尚未核实。");
    const delivery=runtime?.notification_delivery;
    const runtimeNote=document.getElementById("strategy-runtime-note");
    if(runtimeNote && delivery?.status === "LAST_ATTEMPT_FAILED") runtimeNote.textContent += delivery.last_error === "openclaw_weixin_response_rejected:-2" ? " · 微信最近发送被拒绝（ret=-2），需核对会话" : " · 微信最近发送失败";
    const decision=data?.last_decision;
    const reasons={regime_off:'趋势条件未通过',friction_budget:'成本超出预算',liquidity_unknown:'流动性数据不足',minimum_order:'低于最小订单',stale_equity_features:'信号数据过期',atr_warmup:'ATR预热不足',funding_unknown:'资金费数据不足'};
    const rejected=Object.entries(decision?.rejections || data?.rejections || {}).map(([key,value])=>`${reasons[key] || key} ${value}`).join('；');
    text("strategy-last-decision",decision ? `最近正式决策 ${clock(decision.created_at)} · ${decision.candidate_count ?? '--'} 个合格候选${decision.selected?.symbol ? ` · ${decision.selected.symbol}` : ''}${rejected ? ` · ${rejected}` : ''}` : rejected ? `本次未入场原因：${rejected}` : "尚无正式入场决策摘要。");
    text("strategy-last-run",clock(data?.last_result_at));
    text("strategy-next-check",data?.expected_next_check_at ? `${clock(data.expected_next_check_at)}（预计）` : "--");
    text("strategy-next-entry",!data ? "无数据" : data?.next_entry_at ? `${clock(data.next_entry_at)}（纽约10:00）` : "待运行日历确认");
    const risk=data?.position || selected;
    text("strategy-stress-loss",!data ? "无数据" : number(risk?.stress_risk_usdt) == null ? "本次无待执行仓位" : `${Number(risk.stress_risk_usdt).toFixed(4)} USDT`);
    text("strategy-margin-leverage",number(risk?.margin_usdt) == null ? "--" : `${Number(risk.margin_usdt).toFixed(4)} USDT ／ ${risk.leverage ?? '--'}倍`);
    const legacy=data?.handover === "waiting_for_legacy_flat";
    text("one-atr-signal",!data ? "无数据" : legacy ? "旧 CL 仓位交接中" : selected ? `${selected.symbol} · ${selected.eligible ? "多头信号" : "空仓"}` : data?.position ? `${data.position.symbol} · 持有` : data?.auto_action === "HOLD_NO_SIGNAL" ? "本次无合格信号" : "等待纽约10:00信号");
    const stop=data?.position?.stop ?? selected?.stop_price ?? data?.protection_check?.stop_price;
    text("one-atr-stop",stop == null ? "--" : Number(stop).toFixed(2));
    text("one-atr-execution",!data ? "无数据" : execution?.entry?.status ? `${execution.entry.status} · ${execution.entry.executed_quantity ?? "--"}` : "本次无执行");
    text("one-atr-protection",protective?.status ? `${protective.status} · ${protective.stop_price ?? "--"}` : "保护单待核对");
    text("one-atr-ledger",!data ? "无数据" : data?.orders?.length ? `${data.orders.length} 条策略订单` : "本次无策略订单");
    text("one-atr-halt",data ? (data.halted ? "完整停止 · 持仓管理已停" : "未停止") : "无数据");
    const actionNames={HOLD_EXISTING_POSITION:"账户已有持仓，保持",HOLD_NO_SIGNAL:"无入场信号",ENTRY_SUBMITTED:"入场已提交",HOLD_PROTECTION_REVIEW:"保护状态待复核，暂停新入场",HOLD_LEGACY_POSITION:"保留旧 CL 和原保护单，空仓后接管",WAIT_NY_1000:"等待纽约交易日10:00",HOLD_MACRO_POSITION:"按宏观策略持有并管理",ENTRY_FILLED_PROTECTED:"实际成交已核对，原生止损已确认",ENTRY_IOC_UNFILLED:"限价未成交，本次不追单",POSITION_CLOSED:"仓位已结束",BLOCKED:"执行暂停，查看原因",HOLD_ALREADY_PROCESSED:"本次决策已处理",PLAN_MACRO_ENTRY:"宏观入场计划 · 尚未执行"};
    actionNames.HOLD_MISSED_DECISION="本次入场窗口已过，等待下次决策";
    actionNames.CHECK_MANAGED_POSITION="核对持仓与保护";
    actionNames.POSITION_FLAT_RECONCILE="空仓，正在核对执行记录";
    if(data?.auto_action) text("one-atr-execution",actionNames[data.auto_action] || data.auto_action);
    if(data?.auto_action === "BLOCKED") text("one-atr-execution",`执行暂停 · ${data.execution_blocker || "待核对"}`);
    const entry=execution?.entry;
    text("strategy-order-notional",entry?.average_price != null && entry?.executed_quantity != null ? (Number(entry.average_price)*Number(entry.executed_quantity)).toFixed(4) : "--");
    text("strategy-net-pnl",data?.accounting?.net_pnl_usdt == null ? "--" : Number(data.accounting.net_pnl_usdt).toFixed(4));
    text("strategy-pnl-note",data?.accounting?.note || "成交归属、资金费和资金分配完整后计算");
    text("strategy-assigned-fills",data?.accounting?.assigned_fill_count == null ? "--" : `${data.accounting.assigned_fill_count} 笔`);
    text("strategy-realized-pnl",data?.accounting?.realized_pnl_usdt == null ? "--" : `${Number(data.accounting.realized_pnl_usdt).toFixed(4)} USDT`);
    text("strategy-assigned-fees",Object.entries(data?.accounting?.commission_by_asset || {}).map(([asset,value])=>`${Number(value).toFixed(6)} ${asset}`).join(" / ") || "--");
    if(data?.protection_check) text("one-atr-protection",({PROTECTED:"交易所保护单已核对",UNPROTECTED:"保护不足，已暂停",UNKNOWN:"交易所保护状态未知",FLAT:"账户空仓",UNASSIGNED:"非本策略持仓"})[data.protection_check.status] || "保护状态待核对");
  }
  function renderG20V3(data) {
    const text=(id,v)=>{const n=document.getElementById(id);if(n)n.textContent=v;};
    const clock=v=>Number.isFinite(Date.parse(v)) ? `${new Date(v).toLocaleString("zh-CN",{timeZone:"Asia/Singapore",hour12:false})} UTC+8` : "--";
    const amount=v=>v==null || !Number.isFinite(Number(v)) ? "--" : Number(v).toLocaleString("zh-CN",{minimumFractionDigits:2,maximumFractionDigits:4});
    const status=data?.halted ? "完整停止 · HALT 生效" : data?.status === "STALE" ? "运行记录已过期（错过周期）" : data?.status === "AVAILABLE" ? (data.auto_action === "BLOCKED" ? "执行受阻" : data.orders_authorized ? "自动实盘运行中" : "计划模式 · 未授权下单") : "无数据";
    text("g20v3-status",status);
    text("g20v3-last-run",clock(data?.last_result_at));
    text("g20v3-signal",data?.signal_date || "--");
    text("g20v3-equity",data?.capital_usdt == null ? "--" : `${amount(data.capital_usdt)} USDT`);
    const actions={RESIZE:"再平衡执行",NO_ACTION:"带内不动",BLOCKED:"执行受阻"};
    let action=data?.auto_action ? actions[data.auto_action] || data.auto_action : "--";
    if(data?.auto_action === "NO_ACTION" && data?.reason === "signal_date_already_processed") action="同信号日已处理";
    if(data?.auto_action === "BLOCKED") action=`执行受阻 · ${data.execution_blocker || "原因待核对"}`;
    text("g20v3-action",action);
    const mode=data?.scheduled_resize && data?.drift_breach ? "周度调仓 · 触发漂移带" : data?.scheduled_resize ? "周度调仓" : data?.drift_breach ? "漂移带触发" : "带内不动";
    text("g20v3-mode",data ? mode : "无数据");
    const plan=data?.plan || [];
    const counts=plan.reduce((acc,leg)=>{acc[leg.action]=(acc[leg.action]||0)+1;return acc;},{});
    const target=plan[0]?.target_notional;
    text("g20v3-plan",!data ? "无数据" : plan.length ? `${plan.length} 腿 · ${Object.entries(counts).map(([k,v])=>`${{BUY:"买入",SELL:"卖出",CLOSE:"清仓",HOLD:"持有",SKIP:"跳过"}[k]||k}${v}`).join(" / ")}${target != null ? ` · 单腿目标 ${Number(target).toFixed(2)}U` : ""}` : "本次无调仓计划");
    const oc=data?.order_counts;
    text("g20v3-orders",!data ? "无数据" : oc ? `提交 ${oc.submitted ?? 0} · 规则拒绝 ${oc.skipped_rule ?? 0} · 仅计划 ${oc.planned_only ?? 0}` : data?.orders?.length ? `${data.orders.length} 条执行记录` : "本次无订单");
    text("g20v3-ledger",!data ? "无数据" : data?.orders?.length ? `${data.orders.length} 条执行库订单` : "执行库无订单");
    text("g20v3-cycle",!data ? "无数据" : data?.cycle ? `第 ${data.cycle.cycle_count ?? 0} 周期 · 上次信号 ${data.cycle.last_signal_date || "--"}` : "暂无实盘周期");
    text("g20v3-next",clock(data?.next_cycle_at));
    text("g20v3-halt",data ? (data.halted ? "已停止（HALT 文件存在）" : "未停止") : "无数据");
  }
  function performanceView(data, now=Date.now()) {
    if (!data || data.read_only !== true || data.orders_authorized !== false ||
        data.method !== "chained_modified_dietz" || !["AVAILABLE","PARTIAL"].includes(data.status) ||
        !Array.isArray(data.points) || !data.points.length) return null;
    if (data.points.some(p=>!Number.isFinite(Date.parse(p.observed_at)) || Date.parse(p.observed_at)>now+60000 ||
        !Number.isInteger(p.segment_id) || number(p.return_pct)==null || number(p.net_pnl_usdt)==null)) return null;
    return data;
  }
  return { accountView, render, renderRecords, renderOneAtr, renderG20V3, performanceView };
});
