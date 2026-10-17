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
