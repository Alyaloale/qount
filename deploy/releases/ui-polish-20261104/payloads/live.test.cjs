const test=require('node:test');
const assert=require('node:assert/strict');
const {accountView}=require('../../web/app/live.js');
const now=Date.now();
const fixture=()=>({status:'AVAILABLE',read_only:true,observed_at:new Date(now).toISOString(),
  usdm_margin_balance_usdt:15,usdm_available_balance_usdt:12,futures_positions_complete:true,
  futures_positions:[{market:'usdm',symbol:'SPYUSDT',quantity:1},{market:'coinm',symbol:'BTCUSD'}]});
test('capital is recomputed from each account snapshot, not fixed15USDT',()=>{
  const a=fixture();assert.equal(accountView(a,now).equity,15);
  assert.equal('risk' in accountView(a,now),false);
  a.usdm_margin_balance_usdt=80;a.usdm_available_balance_usdt=60;
  const b=accountView(a,now);assert.equal(b.equity,80);assert.equal(b.available,60);assert.equal(b.positions.length,1);
});
test('missing and partial coverage do not imply empty confirmed account',()=>{
  assert.equal(accountView(null,now).complete,false);
  const a=fixture();a.futures_positions_complete=false;assert.equal(accountView(a,now).status,'PARTIAL');
  a.usdm_margin_balance_usdt=null;assert.equal(accountView(a,now).equity,null);
});
test('stale/future timestamps and invalid money remain explicit',()=>{
  const a=fixture();a.observed_at=new Date(now-901000).toISOString();assert.equal(accountView(a,now).status,'STALE');
  a.observed_at=new Date(now+61000).toISOString();assert.equal(accountView(a,now).status,'UNKNOWN');
  a.observed_at=new Date(now).toISOString();a.usdm_margin_balance_usdt=true;assert.equal(accountView(a,now).equity,null);
});
test('real fills and transfer income stay separate and unassigned',()=>{
 const {renderRecords}=require('../../web/app/live.js');const nodes=new Map();
 global.document={getElementById:id=>{if(!nodes.has(id))nodes.set(id,{});return nodes.get(id);}};
 try {
  renderRecords({status:'AVAILABLE',read_only:true,observed_at:new Date(now).toISOString(),fill_count:1,income_count:1,completed_symbols:['SPYUSDT'],
   fills:[{time:now,symbol:'<script>bad()</script>',side:'BUY',position_side:'BOTH',price:100,quantity:.1,commission:.005,commission_asset:'USDT',realized_pnl:0,pnl_asset:'USDT'}],
   income:[{time:now,income_type:'TRANSFER',amount:20,asset:'USDT',symbol:''}]});
  assert.match(nodes.get('real-trades-body').innerHTML,/未归属策略/);
  assert.ok(!nodes.get('real-trades-body').innerHTML.includes('<script>'));
  assert.match(nodes.get('real-income-body').innerHTML,/划转/);
  renderRecords(null);assert.match(nodes.get('real-trades-body').innerHTML,/来源不可用/);
  assert.ok(!nodes.get('real-trades-body').innerHTML.includes('SPY'));
 } finally{delete global.document;}
});
test('macro handover shows preserved legacy stop without attributing old fills to the new strategy',()=>{
 const {renderOneAtr}=require('../../web/app/live.js');const nodes=new Map();
 global.document={getElementById:id=>{if(!nodes.has(id))nodes.set(id,{});return nodes.get(id);}};
 try {
  renderOneAtr({status:'AVAILABLE',execution_mode:'auto_live',handover:'waiting_for_legacy_flat',auto_action:'HOLD_LEGACY_POSITION',
    protection_check:{status:'PROTECTED',stop_price:90.06},orders:[],legacy_orders:[{client_order_id:'old'}]});
  assert.match(nodes.get('one-atr-signal').textContent,/旧 CL/);
  assert.equal(nodes.get('one-atr-stop').textContent,'90.06');
  assert.match(nodes.get('one-atr-execution').textContent,/空仓后接管/);
  assert.equal(nodes.get('strategy-assigned-fills').textContent,'--');
  renderOneAtr({status:'AVAILABLE',auto_action:'BLOCKED',execution_blocker:'native_stop_unconfirmed'});
  assert.match(nodes.get('one-atr-execution').textContent,/native_stop_unconfirmed/);
 } finally{delete global.document;}
});

test('real performance requires flow-adjusted provenance and finite historical points',()=>{
 const {performanceView}=require('../../web/app/live.js');
 const d={status:'AVAILABLE',read_only:true,orders_authorized:false,method:'chained_modified_dietz',
   points:[{observed_at:new Date(now).toISOString(),segment_id:0,return_pct:0,net_pnl_usdt:0}]};
 assert.equal(performanceView(d,now),d);
 assert.equal(performanceView({...d,method:'wallet_growth'},now),null);
 assert.equal(performanceView({...d,orders_authorized:true},now),null);
 assert.equal(performanceView({...d,points:[{...d.points[0],return_pct:NaN}]},now),null);
 assert.equal(performanceView({...d,points:[{...d.points[0],observed_at:new Date(now+61000).toISOString()}]},now),null);
});

test('runtime observations, halt and failures are not inferred from an auto_live receipt',()=>{
 const {renderOneAtr}=require('../../web/app/live.js');const nodes=new Map();
 global.document={getElementById:id=>{if(!nodes.has(id))nodes.set(id,{});return nodes.get(id);}};
 try {
  const data={status:'AVAILABLE',execution_mode:'auto_live',auto_action:'WAIT_NY_1000'};
  renderOneAtr(data);
  assert.match(nodes.get('one-atr-status').textContent,/调度未核实/);
  renderOneAtr({...data,runtime:{state:'DISABLED',observed_at:new Date().toISOString(),stale:false}});
  assert.match(nodes.get('one-atr-status').textContent,/定时器未运行/);
  renderOneAtr({...data,runtime:{state:'AUTO',observed_at:new Date().toISOString(),stale:true}});
  assert.match(nodes.get('one-atr-status').textContent,/过期/);
  renderOneAtr({...data,auto_action:'BLOCKED',execution_blocker:'native_stop_unconfirmed'});
  assert.equal(nodes.get('one-atr-status').textContent,'执行受阻');
  renderOneAtr({...data,halted:true});
  assert.match(nodes.get('one-atr-status').textContent,/持仓管理已停/);
  assert.match(nodes.get('strategy-runtime-note').textContent,/原生止损保留/);
  renderOneAtr({...data,last_decision:{created_at:new Date().toISOString(),candidate_count:0,rejections:{friction_budget:2}}});
  assert.match(nodes.get('strategy-last-decision').textContent,/成本超出预算 2/);
  renderOneAtr({...data,runtime:{state:'AUTO',stale:false,notification_delivery:{status:'LAST_ATTEMPT_FAILED',last_error:'openclaw_weixin_response_rejected:-2'}}});
  assert.match(nodes.get('strategy-runtime-note').textContent,/微信最近发送被拒绝/);
 } finally{delete global.document;}
});

test('g20v3 status renders contract state without inventing numbers',()=>{
 const {renderG20V3}=require('../../web/app/live.js');const nodes=new Map();
 global.document={getElementById:id=>{if(!nodes.has(id))nodes.set(id,{});return nodes.get(id);}};
 try {
  renderG20V3({status:'AVAILABLE',execution_mode:'auto_live',orders_authorized:true,halted:false,
    signal_date:'2026-11-03',capital_usdt:43.8711,auto_action:'RESIZE',scheduled_resize:true,drift_breach:false,
    plan:[{symbol:'SOLUSDT',action:'BUY',target_notional:7.98},{symbol:'CLUSDT',action:'SKIP',target_notional:7.98}],
    order_counts:{submitted:1,skipped_rule:0,planned_only:0},
    orders:[{client_order_id:'v3-20261103-SOLUSDT-b',symbol:'SOLUSDT',side:'buy',status:'FILLED'}],
    cycle:{cycle_count:0,last_signal_date:'2026-11-03'},
    next_cycle_at:'2026-11-04T00:00:05+00:00'});
  assert.equal(nodes.get('g20v3-status').textContent,'自动实盘运行中');
  assert.equal(nodes.get('g20v3-signal').textContent,'2026-11-03');
  assert.match(nodes.get('g20v3-equity').textContent,/43\.87/);
  assert.match(nodes.get('g20v3-action').textContent,/再平衡执行/);
  assert.match(nodes.get('g20v3-mode').textContent,/周度调仓/);
  assert.match(nodes.get('g20v3-plan').textContent,/2 腿/);
  assert.match(nodes.get('g20v3-plan').textContent,/买入1/);
  assert.match(nodes.get('g20v3-plan').textContent,/跳过1/);
  assert.match(nodes.get('g20v3-orders').textContent,/提交 1/);
  assert.match(nodes.get('g20v3-cycle').textContent,/第 0 周期/);
  assert.equal(nodes.get('g20v3-halt').textContent,'未停止');
  renderG20V3({status:'AVAILABLE',auto_action:'NO_ACTION',reason:'signal_date_already_processed'});
  assert.match(nodes.get('g20v3-action').textContent,/同信号日已处理/);
  renderG20V3({status:'AVAILABLE',auto_action:'BLOCKED',execution_blocker:'inflight_orders_present'});
  assert.match(nodes.get('g20v3-action').textContent,/inflight_orders_present/);
  renderG20V3({halted:true,status:'AVAILABLE'});
  assert.match(nodes.get('g20v3-status').textContent,/完整停止/);
  renderG20V3(null);
  assert.equal(nodes.get('g20v3-status').textContent,'无数据');
  assert.equal(nodes.get('g20v3-plan').textContent,'无数据');
  assert.equal(nodes.get('g20v3-equity').textContent,'--');
 } finally{delete global.document;}
});
