/* Real-time public market layer: browser-direct Binance streams, no credentials.
 * Positions and entry prices come from the account snapshot; any PnL shown is a
 * local estimate labelled as such and never presented as an exchange reading. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.QountMarket = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const number = (v) => v == null || typeof v === "boolean" || v === "" || !Number.isFinite(Number(v)) ? null : Number(v);

  // Snapshot positions carry quantity/notional/unrealized_pnl but no entry
  // price. Derive it: mark_snapshot = notional/qty, upnl = (mark-entry)*qty*dir.
  function deriveEntry(position) {
    const qty = number(position && position.quantity);
    const notional = number(position && position.notional_usdt);
    const upnl = number(position && position.unrealized_pnl_usdt);
    if (qty == null || qty <= 0 || notional == null || upnl == null) return null;
    const mark = notional / qty;
    const dir = position.side === "short" ? -1 : 1;
    return mark - upnl / (qty * dir);
  }

  function estimatePnl(position, markPrice) {
    const entry = deriveEntry(position);
    const qty = number(position && position.quantity);
    const mark = number(markPrice);
    if (entry == null || qty == null || qty <= 0 || mark == null) return null;
    const dir = position.side === "short" ? -1 : 1;
    return {
      entry_price: entry,
      estimated_pnl_usdt: (mark - entry) * qty * dir,
      estimated_notional_usdt: mark * qty,
    };
  }

  function parseBookTicker(payload) {
    if (!payload || typeof payload !== "object") return null;
    const symbol = typeof payload.s === "string" ? payload.s : null;
    const bid = number(payload.b), ask = number(payload.a), at = number(payload.T);
    if (!symbol || bid == null || ask == null || bid <= 0 || ask <= 0) return null;
    return { symbol, bid, ask, mid: (bid + ask) / 2, at };
  }

  function parsePremium(payload) {
    if (!payload || typeof payload !== "object") return null;
    const symbol = typeof payload.symbol === "string" ? payload.symbol : null;
    const mark = number(payload.markPrice);
    const funding = number(payload.lastFundingRate);
    const at = number(payload.time);
    if (!symbol || mark == null || mark <= 0) return null;
    return { symbol, mark_price: mark, funding_rate: funding, at };
  }

  // Feed states: connecting -> live (WS flowing) or degraded (REST polling),
  // and down only when both channels fail repeatedly.
  function createMarketFeed(options) {
    const o = options || {};
    const symbols = [...new Set(o.symbols || [])];
    const onStatus = typeof o.onStatus === "function" ? o.onStatus : () => {};
    const onUpdate = typeof o.onUpdate === "function" ? o.onUpdate : () => {};
    const WSImpl = o.WebSocketImpl || (typeof WebSocket !== "undefined" ? WebSocket : null);
    const fetchImpl = o.fetchImpl || (typeof fetch !== "undefined" ? fetch : null);
    const wsUrl = o.wsUrl || "wss://fstream.binance.com/ws";
    const restBase = o.restBase || "https://fapi.binance.com/fapi/v1";
    const markPollMs = o.markPollMs || 60_000;
    const fallbackPollMs = o.fallbackPollMs || 5_000;
    const now = o.now || (() => Date.now());

    const rows = new Map(); // symbol -> {symbol, bid, ask, mid, mark_price, funding_rate, at, source}
    let ws = null, stopped = true, state = "down", attempt = 0;
    let markTimer = null, fallbackTimer = null;

    function setState(next, detail) {
      if (state === next) return;
      state = next;
      onStatus(next, detail);
    }
    function emit() {
      onUpdate(symbols.map((s) => rows.get(s)).filter(Boolean));
    }
    function applyMark(updates) {
      for (const u of updates) {
        if (!u) continue;
        const row = rows.get(u.symbol) || { symbol: u.symbol };
        row.mark_price = u.mark_price;
        if (u.funding_rate != null) row.funding_rate = u.funding_rate;
        row.at = u.at || now();
        rows.set(u.symbol, row);
      }
      emit();
    }

    async function pollMarks() {
      if (!fetchImpl) return false;
      let ok = 0;
      for (const symbol of symbols) {
        try {
          const res = await fetchImpl(`${restBase}/premiumIndex?symbol=${encodeURIComponent(symbol)}`, { cache: "no-store" });
          if (!res.ok) continue;
          applyMark([parsePremium(await res.json())]);
          ok += 1;
        } catch (_) { /* network failure: counted below */ }
      }
      return ok > 0;
    }

    function startFallback() {
      if (fallbackTimer) return;
      setState("degraded");
      fallbackTimer = setInterval(async () => {
        const ok = await pollMarks();
        setState(ok ? "degraded" : "down");
      }, fallbackPollMs);
    }
    function stopFallback() {
      if (fallbackTimer) { clearInterval(fallbackTimer); fallbackTimer = null; }
    }

    function connect() {
      if (stopped || !WSImpl) return;
      setState(state === "live" ? "live" : "connecting");
      try {
        ws = new WSImpl(wsUrl);
      } catch (_) {
        startFallback();
        scheduleReconnect();
        return;
      }
      ws.onopen = () => {
        attempt = 0;
        // Message-form SUBSCRIBE: URL-form combined streams proved unreliable
        // for some stream names through some networks; this form is verified.
        ws.send(JSON.stringify({ method: "SUBSCRIBE", params: symbols.map((s) => `${s.toLowerCase()}@bookTicker`), id: 1 }));
        setState("live");
        stopFallback();
        if (markTimer) clearInterval(markTimer);
        pollMarks(); // authoritative mark price + funding immediately
        markTimer = setInterval(pollMarks, markPollMs);
      };
      ws.onmessage = (event) => {
        let payload;
        try { payload = JSON.parse(typeof event.data === "string" ? event.data : String(event.data)); }
        catch (_) { return; }
        if (!payload || typeof payload !== "object" || !("e" in payload)) return; // ack / control frames
        const tick = parseBookTicker(payload);
        if (!tick) return;
        const row = rows.get(tick.symbol) || { symbol: tick.symbol };
        row.bid = tick.bid; row.ask = tick.ask; row.mid = tick.mid;
        if (row.mark_price == null) row.mark_price = tick.mid;
        row.at = tick.at || now();
        row.source = "ws";
        rows.set(tick.symbol, row);
        emit();
      };
      const drop = () => {
        if (stopped) return;
        ws = null;
        startFallback();
        scheduleReconnect();
      };
      ws.onclose = drop;
      ws.onerror = drop;
    }

    function scheduleReconnect() {
      if (stopped) return;
      attempt += 1;
      const delay = Math.min(30_000, 1000 * Math.pow(2, Math.min(attempt, 5)));
      setTimeout(connect, delay);
    }

    return {
      start() {
        if (!stopped) return;
        stopped = false;
        connect();
        pollMarks().then((ok) => { if (!ok && state !== "live") startFallback(); });
      },
      stop() {
        stopped = true;
        stopFallback();
        if (markTimer) { clearInterval(markTimer); markTimer = null; }
        if (ws) { try { ws.close(); } catch (_) {} ws = null; }
        setState("down");
      },
      state: () => state,
      snapshot: () => symbols.map((s) => rows.get(s)).filter(Boolean),
    };
  }

  return { deriveEntry, estimatePnl, parseBookTicker, parsePremium, createMarketFeed };
});
