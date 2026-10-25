const test = require("node:test");
const assert = require("node:assert/strict");
const research = require("../../web/app/research.js");

const lines = [
  { line_id: "dual_g20", presentation:{name:"美股轮动 G20",category:"美股"}, status: "ACTIVE_PAPER", data_status: "AVAILABLE", freshness: "STALE" },
  { line_id: "universal_regime", status: "ACTIVE_PAPER", data_status: "MISSING" },
  { line_id: "ashare_master", presentation:{name:"麒麟",category:"A 股"}, status: "STOPPED", data_status: "MISSING" },
];

test("stale results remain available while missing sources do not change research lifecycle", () => {
  assert.equal(research.group(lines[0]), "available");
  assert.equal(research.dataState(lines[0]).label, "数据待更新");
  assert.deepEqual(research.summary(lines), { all: 3, available: 1, forward: 0, historical: 2, waiting: 1, archived: 1, stale: 1, missing: 2 });
});

test("forward filter retains unhealthy enabled accounts and intersects market and search", () => {
  const active = {...lines[0], sample_kind: "forward", paper_enabled: true};
  const missing = {...lines[1], sample_kind: "forward", paper_enabled: true};
  const archived = {...lines[2], sample_kind: "forward", paper_enabled: true};
  const all = [active, missing, archived, lines[0]];
  assert.deepEqual(research.select(all, "forward"), [active, missing]);
  assert.deepEqual(research.select(all, "forward", "G20", "美股"), [active]);
  assert.equal(research.summary(all).forward, 2);
  assert.equal(research.summary(all).historical, 1);
  const continuous={...active,sample_kind:"mixed"};
  assert.equal(research.forward(continuous),true);
  assert.equal(research.lifecycle(continuous),"模拟已启用");
});

test("a paper run timestamp never becomes a historical experiment query", () => {
  const paper = {run_id: "2026-10-22T05:50:29Z", sample_kind: "forward", source: {observation_kind: "forward_paper"}};
  assert.equal(research.experimentRunId(paper), null);
  assert.equal(research.experimentRunId(undefined), null);
  assert.equal(research.experimentRunId({run_id: "opaque"}), null);
  assert.equal(research.experimentRunId({run_id: "hash", sample_kind: "historical", source: {observation_kind: "historical_backtest"}}), "hash");
});

test("explicitly known empty snapshots retain date and differ from unknown snapshots", () => {
  assert.deepEqual(research.positionSnapshot({status: "KNOWN", as_of: "2026-10-21", positions: []}),
    {positions: [], as_of: "2026-10-21", confirmed: true});
  for (const status of ["UNKNOWN", "MISSING"]) {
    assert.throws(() => research.positionSnapshot({status, positions: []}));
  }
  assert.throws(() => research.positionSnapshot({status: "KNOWN"}));
  assert.equal(research.positionSnapshot([]).confirmed, false);
  assert.equal(research.positionSnapshot([{date: "2026-10-21", symbol: "SPY"}]).confirmed, true);
});

test("search, lifecycle and market filters intersect and can find archived research", () => {
  assert.deepEqual(research.select(lines, "available", "G20", "美股"), [lines[0]]);
  assert.deepEqual(research.select(lines, "available", "G20", "ETF"), []);
  assert.deepEqual(research.select(lines, "archived", " 麒麟 ", "A 股"), [lines[2]]);
});

test("a connected future source replaces the pending-source explanation", () => {
  const connected = { ...lines[1], data_status: "AVAILABLE", freshness: "FRESH" };
  assert.equal(research.profile({...connected, sample_kind:"forward"}).sample, "前向模拟");
  assert.doesNotMatch(research.profile(connected).note, /没有可展示/);
  assert.equal(research.group({ ...connected, error: "unreadable" }), "waiting");
});

test("disabled simulations retain historical research without stale-data alarms",()=>{
 const historical={...lines[0],paper_enabled:false,sample_kind:"historical"};
 assert.equal(research.group(historical),"available");
 assert.equal(research.dataState(historical).label,"历史样本");
 assert.equal(research.summary([historical]).stale,0);
});

test("historical artifacts do not imply a currently paused or running strategy", () => {
  for (const research_status of ['paused', 'research', 'forward']) {
    const historical = {...lines[0], sample_kind: 'historical', paper_enabled: false, research_status};
    assert.equal(research.lifecycle(historical), '历史记录');
    assert.equal(research.lifecycle({...historical, sample_kind: 'forward', paper_enabled: true}), '前向已启用');
  }
  assert.equal(research.lifecycle(lines[2]), '已停止');
  assert.equal(research.lifecycle({research_status: 'archived'}), '已封存');
  assert.equal(research.lifecycle({research_status: 'research'}), '状态待确认');
});
