/* Unit tests for the pure market layer: entry derivation, PnL estimate, parsers, feed states. */
const test = require("node:test");
const assert = require("node:assert");
const QountMarket = require("../../web/app/market.js");

const LONG = { symbol: "SOLUSDT", side: "long", quantity: 2, notional_usdt: 200, unrealized_pnl_usdt: 10 };
const SHORT = { symbol: "CLUSDT", side: "short", quantity: 4, notional_usdt: 400, unrealized_pnl_usdt: -20 };

test("deriveEntry inverts snapshot fields for long and short", () => {
  // long: mark=100, upnl=(100-entry)*2=10 -> entry=95
  assert.strictEqual(QountMarket.deriveEntry(LONG), 95);
  // short: mark=100, upnl=(100-entry)*4*(-1)=-20 -> entry=95
  assert.strictEqual(QountMarket.deriveEntry(SHORT), 95);
});

test("deriveEntry rejects incomplete or non-positive inputs", () => {
  assert.strictEqual(QountMarket.deriveEntry(null), null);
  assert.strictEqual(QountMarket.deriveEntry({ quantity: 0, notional_usdt: 1, unrealized_pnl_usdt: 0 }), null);
  assert.strictEqual(QountMarket.deriveEntry({ quantity: 1, notional_usdt: null, unrealized_pnl_usdt: 0 }), null);
  assert.strictEqual(QountMarket.deriveEntry({ quantity: 1, notional_usdt: 1, unrealized_pnl_usdt: NaN }), null);
});

test("estimatePnl marks to live price without touching exchange semantics", () => {
  const est = QountMarket.estimatePnl(LONG, 110);
  assert.strictEqual(est.entry_price, 95);
  assert.strictEqual(est.estimated_pnl_usdt, (110 - 95) * 2);
  assert.strictEqual(est.estimated_notional_usdt, 220);
  const short = QountMarket.estimatePnl(SHORT, 90);
  assert.strictEqual(short.estimated_pnl_usdt, (90 - 95) * 4 * -1);
  assert.strictEqual(QountMarket.estimatePnl(LONG, null), null);
});

test("parseBookTicker keeps only sane quotes", () => {
  const tick = QountMarket.parseBookTicker({ s: "SOLUSDT", b: "93.5", a: "93.6", T: 1793787777000 });
  assert.deepStrictEqual(tick, { symbol: "SOLUSDT", bid: 93.5, ask: 93.6, mid: 93.55, at: 1793787777000 });
  assert.strictEqual(QountMarket.parseBookTicker({ s: "SOLUSDT", b: "0", a: "1" }), null);
  assert.strictEqual(QountMarket.parseBookTicker({ s: "", b: "1", a: "2" }), null);
  assert.strictEqual(QountMarket.parseBookTicker(null), null);
});

test("parsePremium keeps mark price and tolerates missing funding", () => {
  const p = QountMarket.parsePremium({ symbol: "SPYUSDT", markPrice: "763.68", lastFundingRate: "0.0002", time: 1 });
  assert.deepStrictEqual(p, { symbol: "SPYUSDT", mark_price: 763.68, funding_rate: 0.0002, at: 1 });
  const noFunding = QountMarket.parsePremium({ symbol: "SPYUSDT", markPrice: "763.68", time: 1 });
  assert.strictEqual(noFunding.funding_rate, null);
  assert.strictEqual(QountMarket.parsePremium({ symbol: "X", markPrice: "-1" }), null);
});

function fakeWS() {
  const handlers = {};
  const sent = [];
  return {
    sent,
    handlers,
    send(msg) { sent.push(JSON.parse(msg)); },
    close() { handlers.close && handlers.close(); },
    open() { handlers.open && handlers.open(); },
    message(obj) { handlers.message && handlers.message({ data: JSON.stringify(obj) }); },
    set onopen(fn) { handlers.open = fn; },
    set onmessage(fn) { handlers.message = fn; },
    set onclose(fn) { handlers.close = fn; },
    set onerror(fn) { handlers.error = fn; },
  };
}

test("feed subscribes bookTicker via message form and surfaces ticks", async () => {
  const sockets = [];
  const statuses = [];
  const updates = [];
  const feed = QountMarket.createMarketFeed({
    symbols: ["SOLUSDT", "BNBUSDT"],
    WebSocketImpl: function () { const ws = fakeWS(); sockets.push(ws); return ws; },
    fetchImpl: async () => ({ ok: true, json: async () => ({ symbol: "SOLUSDT", markPrice: "100", lastFundingRate: "0.01", time: 5 }) }),
    onStatus: (s) => statuses.push(s),
    onUpdate: (rows) => updates.push(rows),
  });
  feed.start();
  assert.strictEqual(sockets.length, 1);
  sockets[0].open();
  const sub = sockets[0].sent[0];
  assert.strictEqual(sub.method, "SUBSCRIBE");
  assert.deepStrictEqual(sub.params, ["solusdt@bookTicker", "bnbusdt@bookTicker"]);
  sockets[0].message({ e: "bookTicker", s: "SOLUSDT", b: "99.5", a: "100.5", T: 10 });
  const row = feed.snapshot().find((r) => r.symbol === "SOLUSDT");
  assert.strictEqual(row.mid, 100);
  assert.strictEqual(row.source, "ws");
  assert.ok(statuses.includes("live"));
  // ack frames are ignored
  sockets[0].message({ result: null, id: 1 });
  assert.strictEqual(feed.snapshot().length, 1);
  feed.stop();
  assert.strictEqual(feed.state(), "down");
});

test("feed falls back to REST polling when the socket drops", async () => {
  const sockets = [];
  const statuses = [];
  const feed = QountMarket.createMarketFeed({
    symbols: ["SOLUSDT"],
    WebSocketImpl: function () { const ws = fakeWS(); sockets.push(ws); return ws; },
    fetchImpl: async () => ({ ok: true, json: async () => ({ symbol: "SOLUSDT", markPrice: "42", time: 1 }) }),
    onStatus: (s) => statuses.push(s),
    onUpdate: () => {},
    fallbackPollMs: 20,
  });
  feed.start();
  sockets[0].open();
  sockets[0].close(); // drop -> degraded + polling
  assert.ok(statuses.includes("degraded"));
  assert.strictEqual(feed.state(), "degraded");
  await new Promise((r) => setTimeout(r, 50));
  const row = feed.snapshot().find((r) => r.symbol === "SOLUSDT");
  assert.strictEqual(row.mark_price, 42);
  feed.stop();
});
