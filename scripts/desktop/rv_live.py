#!/usr/bin/env python3
"""RV-C cash-and-carry LIVE ops runner (线 C 实盘腿).

Daily: derive the delta-neutral carry legs (long spot + short the active dated quarterly COIN-M)
-> read current spot balances + COIN-M positions across BOTH venues -> reconcile into band-gated
orders (incl. the quarterly roll) -> place (dry default). Mirrors scripts/desktop/x4_live.py.

  # safe: prints intended two-venue orders, sends nothing, no keys needed
  .venv/bin/python scripts/desktop/rv_live.py dry

  # live: places real spot + COIN-M market orders -- requires BOTH:
  #   QOUNT_RV_LIVE_ENABLE=1  and  QOUNT_BINANCE_API_KEY/SECRET with SPOT + COIN-M (delivery) perms
  QOUNT_RV_LIVE_ENABLE=1 .venv/bin/python scripts/desktop/rv_live.py live

Two venues: spot (long) + COIN-M dated (short, isolated, liq_leverage). Delta-neutral by construction;
the edge is the basis F→S convergence (the hard anchor), always-on (A1 timing falsified). COIN-M is a
SEPARATE wallet from USDⓈ-M -- the trend leg's futures key does NOT grant delivery access.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

import ccxt  # noqa: E402
from qount.settings import Settings  # noqa: E402
from qount.exchange_utils import build_exchange  # noqa: E402
from qount.rv.live import (  # noqa: E402
    CarryConfig,
    compute_carry_orders,
    from_ccxt_dated,
    place_carry_orders,
    rv_live_enabled,
    target_legs,
    to_ccxt_dated,
    to_ccxt_spot,
)

STATE_DIR = REPO / "state" / "rv" / "live"


def _build_coinm(settings: Settings, private: bool):
    """Raw ccxt COIN-M (delivery) client — build_exchange only does spot/linear."""
    opts = {"enableRateLimit": True, "options": {"defaultType": "delivery", "adjustForTimeDifference": True}}
    if settings.https_proxy:
        opts["httpsProxy"] = settings.https_proxy
    elif settings.http_proxy:
        opts["httpProxy"] = settings.http_proxy
    if private:
        opts["apiKey"] = settings.binance_api_key
        opts["secret"] = settings.binance_api_secret
    return ccxt.binance(opts)


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else "dry"
    if mode not in ("dry", "live"):
        raise SystemExit("usage: rv_live.py [dry|live]")
    # capital overridable via env (C×D orchestrator sets the 40% carry slice); else CarryConfig default
    _cap = float(os.environ.get("QOUNT_RV_CAPITAL", "0") or 0)
    cfg = CarryConfig(capital_usdt=_cap) if _cap > 0 else CarryConfig()
    now = dt.datetime.now(dt.UTC)
    now_ms = int(now.timestamp() * 1000)
    legs = target_legs(now_ms, cfg)
    dated_syms = [l.symbol for l in legs if l.kind == "dated"]
    print(f"[RV-LIVE {mode}] {now:%Y-%m-%d}  capital ${cfg.capital_usdt:.0f}  pairs {len(cfg.pairs)}  "
          f"L={cfg.liq_leverage:g}  active dated: {', '.join(dated_syms) or '—'}")

    settings = Settings.from_env()
    live = (mode == "live")
    spot_ex = build_exchange(dataclasses.replace(settings, market_type="spot"), private=live)
    cm_ex = _build_coinm(settings, private=live)
    spot_ex.load_markets()
    cm_ex.load_markets()

    # prices: spot per pair + the active dated per pair
    prices: dict[str, float] = {}
    for spot_sym, _base in cfg.pairs:
        prices[spot_sym] = float(spot_ex.fetch_ticker(to_ccxt_spot(spot_sym, cfg.quote))["last"])
    for ds in dated_syms:
        prices[ds] = float(cm_ex.fetch_ticker(to_ccxt_dated(ds))["last"])

    # current signed notionals: +long spot / −short dated (dry / no-key -> assume flat)
    current: dict[str, float] = {}
    holdings_ok = True

    def _read():
        bal = spot_ex.fetch_balance()
        for spot_sym, _b in cfg.pairs:
            base = spot_sym[: -len(cfg.quote)]
            qty = float((bal.get("total") or {}).get(base, 0.0) or 0.0)
            if qty > 0 and spot_sym in prices:
                current[spot_sym] = qty * prices[spot_sym]
        for p in cm_ex.fetch_positions():
            sym = p.get("symbol") or ""
            # only DATED COIN-M (e.g. "BTC/USD:BTC-260626"); the delivery client also returns USDⓈ-M
            # ("ETH/USDT:USDT", no "-") and COIN-M perps ("BTC/USD:BTC", no "-") -- skip those, they
            # are a different venue/leg and would garble from_ccxt_dated.
            if ":" not in sym or "-" not in sym:
                continue
            internal = from_ccxt_dated(sym)
            amt = float(p.get("contracts") or 0.0)
            if amt == 0:
                continue
            notional = abs(float(p.get("notional") or 0.0)) or abs(amt) * prices.get(internal, 0.0)
            current[internal] = -notional if (p.get("side") or "short") == "short" else notional

    try:
        _read()
    except Exception as exc:
        holdings_ok = False
        print(f"  (no holdings access: {type(exc).__name__}) -> assuming flat")
        if live and rv_live_enabled():
            print("  [ALERT] live+armed but cannot read holdings (need SPOT+COIN-M key) -> SKIP this run")

    res = compute_carry_orders(legs, current, cfg)
    if live and rv_live_enabled() and not holdings_ok:
        res.orders = []   # SAFETY: never trade against an unknown two-venue book

    net_delta = sum(current.values())   # balanced carry -> ~0
    print(f"  current Δ ${net_delta:+.0f} (target ~0)  {len(res.orders)} order(s), {len(res.skipped)} skipped"
          + (f"  ROLL: {', '.join(res.rolled)}" if res.rolled else ""))
    for sk in res.skipped:
        print(f"    skip {sk}")

    placed = place_carry_orders(spot_ex, cm_ex, res.orders, mode=mode, cfg=cfg)

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": now.isoformat(), "mode": mode, "armed": rv_live_enabled(),
        "capital": cfg.capital_usdt, "n_pairs": len(cfg.pairs), "liq_leverage": cfg.liq_leverage,
        "active_dated": dated_syms, "net_delta": round(net_delta, 2),
        "target": {k: round(v, 2) for k, v in res.target_usdt.items()},
        "current": {k: round(v, 2) for k, v in current.items()},
        "rolled": res.rolled,
        "orders": [{"symbol": o.symbol, "side": o.side, "notional": round(o.notional_usdt, 2),
                    "roll": o.is_roll} for o in res.orders],
        "n_placed": sum(1 for p in placed if p.get("result")),
    }
    if res.orders or rec["n_placed"]:
        with (STATE_DIR / "orders.jsonl").open("a") as f:
            f.write(json.dumps(rec, default=float) + "\n")
    (STATE_DIR / "latest.json").write_text(json.dumps(rec, indent=2, default=float))
    print(f"  logged -> {STATE_DIR}/latest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
