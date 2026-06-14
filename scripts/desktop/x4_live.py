#!/usr/bin/env python3
"""X4 small-cap LIVE spot ops runner (线 D §21).

Daily: load the 7-coin small-cap universe -> derive S7-mini target weights -> read Binance spot
balances -> reconcile into band-gated, capped, lot-rounded market orders -> place (dry default).

  # safe: prints intended orders, sends nothing, no keys needed
  .venv/bin/python scripts/desktop/x4_live.py dry

  # live: actually places spot market orders -- requires BOTH:
  #   QOUNT_X4_LIVE_ENABLE=1  and  QOUNT_BINANCE_API_KEY/SECRET (trade-only, no withdrawal)
  QOUNT_X4_LIVE_ENABLE=1 .venv/bin/python scripts/desktop/x4_live.py live

Spot-only -> no liquidation. Reconciliation is idempotent (reruns on an unchanged book = no-op).
The BTC master gate means: while BTC is below its 200d SMA the book is flat -> zero orders (safe
burn-in window to validate the read/diff path before any real fill).
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.grid.data import load_klines  # noqa: E402
from qount.settings import Settings  # noqa: E402
from qount.exchange_utils import build_exchange  # noqa: E402
from qount.x4.live import (  # noqa: E402
    LiveConfig,
    compute_orders,
    fetch_filters,
    place_orders,
    target_weights,
    to_ccxt_symbol,
    x4_live_enabled,
)

START = (2021, 1)
STATE_DIR = REPO / "state" / "x4" / "live"


def _load_universe(cfg: LiveConfig):
    now = dt.datetime.now(dt.UTC)
    by_sym: dict[str, dict] = {}
    for sym in cfg.universe:
        bars = load_klines(sym, "1d", start=START, end=(now.year, now.month),
                           market="um", skip_missing=True)
        if len(bars) > 300:
            by_sym[sym] = {b.ts_ms: b for b in bars}
    if cfg.gate_sym not in by_sym:
        raise SystemExit("no BTC data — cannot evaluate master gate")
    common = sorted(set.intersection(*(set(d) for d in by_sym.values())))
    return {s: [by_sym[s][t] for t in common] for s in by_sym}


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else "dry"
    if mode not in ("dry", "live"):
        raise SystemExit("usage: x4_live.py [dry|live]")
    cfg = LiveConfig()

    aligned = _load_universe(cfg)
    last_date = aligned[cfg.gate_sym][-1].date
    tw = target_weights(aligned, cfg)
    gate_open = bool(tw)
    print(f"[X4-LIVE {mode}] bar {last_date}  gate={'OPEN' if gate_open else 'SHUT (flat -> cash)'}  "
          f"capital ${cfg.capital_usdt:.0f}  universe {len(cfg.universe)} coins")
    if tw:
        print("  target weights: " + ", ".join(f"{t.symbol}={t.weight:.2f}" for t in tw))

    settings = Settings.from_env()
    ex = build_exchange(settings, private=(mode == "live"))
    ex.load_markets()
    filters = fetch_filters(ex, list(cfg.universe), cfg.quote)

    # current spot balances (base units) + prices
    prices, balances = {}, {}
    for s in cfg.universe:
        sym = to_ccxt_symbol(s, cfg.quote)
        prices[s] = float(ex.fetch_ticker(sym)["last"])
    if mode == "live" and x4_live_enabled():
        bal = ex.fetch_balance()
        for s in cfg.universe:
            base = s[: -len(cfg.quote)]
            balances[s] = float((bal.get("total") or {}).get(base, 0.0) or 0.0)
    else:
        # dry / blocked: read balances if keys present, else assume flat (read-only public client)
        try:
            bal = ex.fetch_balance()
            for s in cfg.universe:
                base = s[: -len(cfg.quote)]
                balances[s] = float((bal.get("total") or {}).get(base, 0.0) or 0.0)
        except Exception as exc:  # no keys in dry -> treat as flat
            print(f"  (no private balance access in dry: {type(exc).__name__}) -> assuming flat")

    res = compute_orders(tw, balances, prices, filters, cfg)
    print(f"  current ${sum(res.current_usdt.values()):.2f} deployed; "
          f"{len(res.orders)} order(s), {len(res.skipped)} skipped")
    for sk in res.skipped:
        print(f"    skip {sk}")

    placed = place_orders(ex, res.orders, mode=mode)

    # gate distance (BTC last close vs its SMA) for the panel
    btc_closes = [b.close for b in aligned[cfg.gate_sym]]
    btc_px = btc_closes[-1]
    btc_sma = sum(btc_closes[-cfg.gate_sma:]) / cfg.gate_sma if len(btc_closes) >= cfg.gate_sma else 0.0
    deployed = sum(res.current_usdt.values())
    holdings = [{"symbol": s, "value": round(res.current_usdt[s], 2),
                 "weight": round({t.symbol: t.weight for t in tw}.get(s, 0.0), 4)}
                for s in cfg.universe if res.current_usdt.get(s, 0.0) > 0.01]

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": dt.datetime.now(dt.UTC).isoformat(), "bar": last_date, "mode": mode,
        "gate_open": gate_open, "armed": x4_live_enabled(),
        "capital": cfg.capital_usdt, "deployed": round(deployed, 2),
        "cash": round(cfg.capital_usdt - deployed, 2),
        "btc_px": round(btc_px, 2), "btc_sma200": round(btc_sma, 2),
        "btc_to_sma": round(btc_px / btc_sma - 1.0, 4) if btc_sma > 0 else 0.0,
        "n_universe": len(cfg.universe),
        "targets": {t.symbol: round(t.weight, 4) for t in tw},
        "holdings": holdings,
        "orders": [{"symbol": o.symbol, "side": o.side, "base": o.base_amount,
                    "quote": o.quote_amount, "est_usdt": o.est_usdt} for o in res.orders],
        "n_placed": sum(1 for p in placed if p.get("result")),
    }
    with (STATE_DIR / "orders.jsonl").open("a") as f:
        f.write(json.dumps(rec, default=float) + "\n")
    (STATE_DIR / "latest.json").write_text(json.dumps(rec, indent=2, default=float))
    print(f"  logged -> {STATE_DIR}/latest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
