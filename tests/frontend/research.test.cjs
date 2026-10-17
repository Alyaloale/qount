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
  assert.deepEqual(research.summary(lines), { all: 3, available: 1, waiting: 1, archived: 1, stale: 1, missing: 2 });
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
