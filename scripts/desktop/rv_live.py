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
    CONTRACT_USD,
    compute_carry_orders,
    execute_funding,
    from_ccxt_dated,
    neutralize_spot_targets,
    place_carry_orders,
    plan_funding,
    rv_live_enabled,
    target_legs,
    to_ccxt_dated,
    to_ccxt_spot,
)

STATE_DIR = REPO / "state" / "rv" / "live"


def _build_coinm(settings: Settings, private: bool):
    """Raw ccxt COIN-M (delivery) client — build_exchange only does spot/linear."""
    # timeout: ccxt defaults to 10s. dapi.binance.com (COIN-M) occasionally has slow spells; a single 10s
    # read timeout would fail the whole carry leg -> a noisy 实盘告警 for a leg that is delta-neutral / no
    # leverage / no liquidation and safely skips the bar. Give it more headroom (2026-06-21 timeout storm).
    opts = {"enableRateLimit": True, "timeout": 30000,
            "options": {"defaultType": "delivery", "adjustForTimeDifference": True}}
    if settings.https_proxy:
        opts["httpsProxy"] = settings.https_proxy
    elif settings.http_proxy:
        opts["httpProxy"] = settings.http_proxy
    if private:
        opts["apiKey"] = settings.binance_api_key
        opts["secret"] = settings.binance_api_secret
    return ccxt.binance(opts)


def _resilient(fn, *, what: str, retries: int = 3, base_delay: float = 2.0):
    """Call ``fn()`` with retry on transient network errors (timeout / DDoS-protection / exchange-not-
    available). A momentary dapi/api blip should not page as an 实盘告警 — the carry leg is delta-neutral
    and safely skips a bar. Real errors (auth, bad request) are NOT NetworkError -> still raise at once.

    Wraps every COIN-M / spot read on the path (load_markets AND fetch_ticker): dapi.binance.com has slow
    spells where a single 24hr-ticker read times out and fails the whole leg + fires a false alert (the
    2026-06-25 ticker-timeout storm — fde09db had only covered load_markets)."""
    import time
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except ccxt.NetworkError as exc:
            if attempt == retries:
                raise
            wait = base_delay * attempt
            print(f"  ({what} transient {type(exc).__name__}, retry {attempt}/{retries - 1} in {wait:g}s)")
            time.sleep(wait)


def _load_markets_resilient(ex, *, retries: int = 3, base_delay: float = 2.0):
    """load_markets() with transient-network retry (see :func:`_resilient`)."""
    _resilient(ex.load_markets, what="load_markets", retries=retries, base_delay=base_delay)


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else "dry"
    if mode not in ("dry", "live"):
        raise SystemExit("usage: rv_live.py [dry|live]")
    # capital overridable via env (C×D orchestrator sets the 40% carry slice); else CarryConfig default
    _cap = float(os.environ.get("QOUNT_RV_CAPITAL", "0") or 0)
    # auto-funding (owner「用合约账户闲置资金」): QOUNT_RV_AUTOFUND=1 pulls idle USDⓈ-M USDT to fund the
    # carry wallets (needs the key's Permits Universal Transfer). Default off = byte-identical.
    _autofund = os.environ.get("QOUNT_RV_AUTOFUND", "").lower() in ("1", "true", "yes")
    _um_buffer = float(os.environ.get("QOUNT_RV_UM_BUFFER_USDT", "") or 200.0)
    _kw: dict = {"autofund": True} if _autofund else {}
    if _cap > 0:
        _kw["capital_usdt"] = _cap
    if _autofund:
        _kw["um_buffer_usdt"] = _um_buffer
    cfg = CarryConfig(**_kw)
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
    _load_markets_resilient(spot_ex)
    _load_markets_resilient(cm_ex)

    # prices: spot per pair + the active dated per pair (each ticker read retried — dapi/api blips)
    prices: dict[str, float] = {}
    for spot_sym, _base in cfg.pairs:
        ccxt_sym = to_ccxt_spot(spot_sym, cfg.quote)
        prices[spot_sym] = float(_resilient(lambda s=ccxt_sym: spot_ex.fetch_ticker(s),
                                            what=f"fetch_ticker {ccxt_sym}")["last"])
    for ds in dated_syms:
        ccxt_ds = to_ccxt_dated(ds)
        prices[ds] = float(_resilient(lambda s=ccxt_ds: cm_ex.fetch_ticker(s),
                                      what=f"fetch_ticker {ccxt_ds}")["last"])

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
        # COIN-M dated positions: ccxt fetch_positions() only returns PERPETUAL (USDT-M / COIN-M
        # perp) positions, NOT dated quarterly contracts. Use Binance dapiPrivateGetPositionRisk
        # which returns ALL COIN-M positions including dated quarterlies.
        try:
            for r in cm_ex.dapiPrivateGetPositionRisk():
                sym = r.get("symbol") or ""
                amt = float(r.get("positionAmt") or 0)
                if amt == 0 or "_" not in sym:
                    continue
                # Sym from Binance dapi API is already in internal format (e.g. "ETHUSD_260626")
                internal = sym
                notional = abs(amt) * CONTRACT_USD.get(internal.split("_")[0] if "_" in internal else "", 10.0)
                current[internal] = -notional if amt < 0 else notional
        except Exception:
            # fallback: try ccxt fetch_positions (returns perps but not dated)
            for p in cm_ex.fetch_positions():
                sym = p.get("symbol") or ""
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

    # --- delta-neutralize: re-aim the CONTINUOUS spot leg against the QUANTIZED short the executor will
    # actually hold (whole-contract floor) + the COIN-M margin coin, so net Δ≈0. Without this, spot+margin
    # were sized off the un-floored model N while the short floored below it -> a permanent +residual long
    # Δ (the 2026-06-25 +12.5 drift). Run BEFORE autofund so it provisions the (lower) neutralizing spot
    # target, not the model's. Needs the COIN-M margin read (live key); dry / keyless -> model legs. ---
    if holdings_ok:
        try:
            _mb = cm_ex.fetch_balance()
            margin_usdt: dict[str, float] = {}
            for _ss, _b in cfg.pairs:
                _coin = _ss[: -len(cfg.quote)]
                _amt = float((_mb.get("total") or {}).get(_coin, 0.0) or 0.0)
                if _amt > 0 and _ss in prices:
                    margin_usdt[_ss] = _amt * prices[_ss]
            if margin_usdt:
                legs = neutralize_spot_targets(legs, margin_usdt, cfg)
                print(f"  [Δ-neutralize] spot re-aimed vs floored short − COIN-M margin "
                      f"{[(k, round(v)) for k, v in margin_usdt.items()]}")
        except Exception as exc:
            print(f"  (Δ-neutralize margin read failed: {type(exc).__name__}) -> model legs")

    # --- auto-funding: pull idle USDⓈ-M USDT -> spot longs + COIN-M margin coins (before reconcile) ---
    fund_plan = None
    if cfg.autofund:
        spot_usdt = 0.0
        cm_coin_usdt: dict[str, float] = {}
        um_available = 0.0
        try:
            sb = spot_ex.fetch_balance()
            spot_usdt = float((sb.get("free") or {}).get(cfg.quote, 0.0) or 0.0)
            cb = cm_ex.fetch_balance()
            for spot_sym, _b in cfg.pairs:
                coin = spot_sym[: -len(cfg.quote)]
                amt = float((cb.get("total") or {}).get(coin, 0.0) or 0.0)
                if amt > 0 and spot_sym in prices:
                    cm_coin_usdt[spot_sym] = amt * prices[spot_sym]
            um_ex = build_exchange(dataclasses.replace(settings, market_type="future"), private=live)
            ub = um_ex.fetch_balance()
            um_available = float((ub.get(cfg.quote) or {}).get("free", 0.0) or 0.0)
        except Exception as exc:
            print(f"  (autofund read failed: {type(exc).__name__}) -> skip funding this run")
        else:
            # credit the spot BASE already held so funding only tops up the SHORTFALL (not the full N
            # every run -> would slowly bleed the trend wallet into idle spot USDT). `current` holds the
            # signed spot long notionals read above (FREE spot only).
            cur_spot = {s: v for s, v in current.items() if "_" not in s and v > 0}
            # ALSO credit base coin parked in Simple Earn (flexible savings): Binance reports it as a
            # separate LD* asset OUTSIDE spot.total, so a hedge coin auto-swept into Earn looks "missing"
            # -> funding re-buys it every run -> the long drifts past delta-neutral (the 2026-06-20 stray
            # -ETH incident). Crediting earn here keeps funding at target. We deliberately do NOT add it to
            # `current` (the trade-reconcile position): earn coin is locked, not free to sell, so a sell
            # diff against it would fail. (Belt-and-suspenders: ETH001 auto-subscribe was also disabled.)
            try:
                earn: dict[str, float] = {}
                for _p in (spot_ex.sapiGetSimpleEarnFlexiblePosition().get("rows") or []):
                    earn[_p.get("asset")] = earn.get(_p.get("asset"), 0.0) + float(_p.get("totalAmount") or 0)
                for spot_sym, _b in cfg.pairs:
                    base = spot_sym[: -len(cfg.quote)]
                    amt = earn.get(base, 0.0)
                    if amt > 0 and spot_sym in prices:
                        cur_spot[spot_sym] = cur_spot.get(spot_sym, 0.0) + amt * prices[spot_sym]
            except Exception:
                pass
            fund_plan = plan_funding(legs, spot_usdt, cm_coin_usdt, prices, um_available, cfg,
                                     cur_spot_usdt=cur_spot)
            print(f"  [autofund] spot ${spot_usdt:.0f} | UMFUTURE 可用 ${um_available:.0f} (缓冲 ${cfg.um_buffer_usdt:.0f}) "
                  f"| 计划 {len(fund_plan.actions)} 步, 抽 UMFUTURE ${fund_plan.um_draw_usdt:.0f}")
            for sk in fund_plan.skipped:
                print(f"    skip {sk}")
            execute_funding(spot_ex, fund_plan, mode=mode, cfg=cfg)

    res = compute_carry_orders(legs, current, cfg)
    if live and rv_live_enabled() and not holdings_ok:
        res.orders = []   # SAFETY: never trade against an unknown two-venue book

    # net delta — UNIFIED with cxd_publish.py. The naive sum(current.values()) = spot_long − short_notional
    # OMITS the COIN-M margin coin: an inverse (COIN-M) short is COLLATERALIZED IN THE BASE COIN, so the ETH
    # sitting in the delivery wallet (+ any base parked in Simple Earn) is itself LONG delta and MUST be
    # counted. Omitting it made this metric read ~−$(margin) (e.g. −26.78) on a book cxd_publish correctly
    # reports as ~+12.51 → the two publishers disagreed by the margin value (~$39). Mirror cxd_publish:
    # long = spot(total)+earn+COIN-M margin coin; short = |dated notional|. Falls back to the naive sum if
    # the extra balance reads fail (a delta-neutral leg must never page on a transient read).
    delta_long_usd = 0.0   # deployed long (spot+earn+margin) — denominator for the drift guard
    delta_unified = False  # True only when the margin-coin read succeeded (else net_delta is the naive sum)
    try:
        _long = sum(v for v in current.values() if v > 0)
        _short = sum(-v for v in current.values() if v < 0)
        _cb = cm_ex.fetch_balance()
        _earn: dict[str, float] = {}
        try:
            for _p in (spot_ex.sapiGetSimpleEarnFlexiblePosition().get("rows") or []):
                _earn[_p.get("asset")] = _earn.get(_p.get("asset"), 0.0) + float(_p.get("totalAmount") or 0)
        except Exception:
            pass
        for _spot_sym, _b in cfg.pairs:
            if _spot_sym not in prices:
                continue
            _base = _spot_sym[: -len(cfg.quote)]
            _margin = float((_cb.get("total") or {}).get(_base, 0.0) or 0.0)   # COIN-M collateral coin = long Δ
            _long += (_margin + _earn.get(_base, 0.0)) * prices[_spot_sym]      # + Earn-parked base = long Δ
        net_delta = _long - _short
        delta_long_usd = _long
        delta_unified = True
    except Exception as exc:
        print(f"  (net_delta margin read failed: {type(exc).__name__}) -> naive sum")
        net_delta = sum(current.values())

    # delta-neutral guard: alert when the carry book drifts off Δ≈0 (e.g. the short under-fills by a whole
    # COIN-M contract / −2019). Only trustworthy on the UNIFIED path (needs the margin-coin read = live key);
    # denominator is the actual deployed long, not the config pin. The cron reads `delta_breach` from state
    # and notifies once per episode. QOUNT_RV_DELTA_ALERT_FRAC overrides the 10%-of-deployed-long threshold.
    delta_alert_frac = float(os.environ.get("QOUNT_RV_DELTA_ALERT_FRAC", "") or 0.10)
    delta_breach = bool(delta_unified and delta_long_usd > 1.0
                        and abs(net_delta) > delta_alert_frac * delta_long_usd)
    print(f"  current Δ ${net_delta:+.0f} (target ~0)  {len(res.orders)} order(s), {len(res.skipped)} skipped"
          + (f"  ROLL: {', '.join(res.rolled)}" if res.rolled else "")
          + (f"  [RV-DELTA-BREACH] |Δ| > {delta_alert_frac:.0%} of deployed ${delta_long_usd:.0f}" if delta_breach else ""))
    for sk in res.skipped:
        print(f"    skip {sk}")

    placed = place_carry_orders(spot_ex, cm_ex, res.orders, mode=mode, cfg=cfg)

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": now.isoformat(), "mode": mode, "armed": rv_live_enabled(),
        "capital": cfg.capital_usdt, "n_pairs": len(cfg.pairs), "liq_leverage": cfg.liq_leverage,
        "active_dated": dated_syms, "net_delta": round(net_delta, 2),
        "delta_long_usd": round(delta_long_usd, 2), "delta_unified": delta_unified,
        "delta_breach": delta_breach, "delta_alert_frac": delta_alert_frac,
        "autofund": cfg.autofund,
        "autofund_draw_usdt": round(fund_plan.um_draw_usdt, 2) if fund_plan else 0.0,
        "autofund_actions": len(fund_plan.actions) if fund_plan else 0,
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
