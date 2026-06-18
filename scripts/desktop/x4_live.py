#!/usr/bin/env python3
"""X4 small-cap LIVE ops runner (线 D §21; v2 博收益 = USDⓈ-M perp @ 2x).

Daily: load the 7-coin small-cap universe -> derive S7-mini target weights (breadth-OR gate + corr
penalty) -> read Binance positions -> reconcile into band-gated, capped, lot-rounded market orders
-> place (dry default).

  # safe: prints intended orders, sends nothing, no keys needed
  .venv/bin/python scripts/desktop/x4_live.py dry

  # live: actually places perp market orders -- requires BOTH:
  #   QOUNT_X4_LIVE_ENABLE=1  and  QOUNT_BINANCE_API_KEY/SECRET (FUTURES trade-only, no withdrawal)
  QOUNT_X4_LIVE_ENABLE=1 .venv/bin/python scripts/desktop/x4_live.py live

⚠️ v2 runs USDⓈ-M perpetual at LiveConfig.target_leverage (default 2x) -> the position CAN be
liquidated. The BTC master gate (OR breadth) means: while risk-off the book is flat -> zero orders.
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

from qount.grid.data import load_klines  # noqa: E402
from qount.settings import Settings  # noqa: E402
from qount.exchange_utils import build_exchange  # noqa: E402
from qount.x4.live import (  # noqa: E402
    LiveConfig,
    apply_chandelier_stops,
    chandelier_stop_prices,
    compute_orders,
    fetch_filters,
    fetch_open_stops,
    place_orders,
    plan_stop_orders,
    portfolio_gate_open,
    prepare_swap,
    sync_stop_orders,
    target_weights,
    to_ccxt_symbol,
    unreachable_coins,
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


def _perp_usdt_balance(ex) -> float | None:
    """Live USDT wallet balance of the (perp) account — the capital base for ``QOUNT_X4_CAPITAL=auto``.
    Returns None on a read failure so the caller can refuse to size against an unknown balance."""
    try:
        bal = ex.fetch_balance()
    except Exception:
        return None
    u = bal.get("USDT") or {}
    v = u.get("total")
    return float(v) if v not in (None, "") else None


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else "dry"
    if mode not in ("dry", "live"):
        raise SystemExit("usage: x4_live.py [dry|live]")
    # capital: QOUNT_X4_CAPITAL = "auto" -> use the live account USDT wallet balance each run (本账户全部
    # 余额可用,随盈亏自动伸缩,修掉硬编码本金在回撤后按虚高额下单的隐患); = <number> -> fixed cap (旧行为);
    # unset -> LiveConfig default. §24 做空闸 arm: QOUNT_X4_SHORT_GATE=1 turns on the risk-off short book.
    _cap_raw = os.environ.get("QOUNT_X4_CAPITAL", "").strip()
    _cap_auto = _cap_raw.lower() == "auto"
    _cap = 0.0 if _cap_auto else float(_cap_raw or 0)
    _short = os.environ.get("QOUNT_X4_SHORT_GATE", "").lower() in ("1", "true", "yes")
    _base = dict(short_gate=True) if _short else {}
    cfg = LiveConfig(capital_usdt=_cap, **_base) if _cap > 0 else LiveConfig(**_base)

    aligned = _load_universe(cfg)
    last_date = aligned[cfg.gate_sym][-1].date
    tw = target_weights(aligned, cfg)
    master_open = portfolio_gate_open(aligned, cfg)   # the real BTC/breadth gate (NOT bool(tw))
    shorting = bool(tw) and not master_open           # §24: risk-off short book active
    gate_open = master_open
    _state = "OPEN (long)" if master_open else ("SHUT (short book)" if shorting else "SHUT (flat -> cash)")
    _cap_disp = "auto (账户余额,稍后解析)" if _cap_auto else f"${cfg.capital_usdt:.0f}"
    print(f"[X4-LIVE {mode}] bar {last_date}  gate={_state}  "
          f"capital {_cap_disp}  universe {len(cfg.universe)} coins")
    if tw:
        print("  target weights: " + ", ".join(f"{t.symbol}={t.weight:.2f}" for t in tw))

    settings = Settings.from_env()
    if cfg.market_type == "swap":
        settings = dataclasses.replace(settings, market_type="future")  # USDⓈ-M linear perp client
    ex = build_exchange(settings, private=(mode == "live"))
    ex.load_markets()
    filters = fetch_filters(ex, list(cfg.universe), cfg.quote, cfg.market_type)

    # prices + current holdings (spot: base balance; swap: long position size, base units)
    prices, balances = {}, {}
    pos_detail: dict[str, dict] = {}   # data_sym -> {side, entry, qty, upnl} for the 看板 (rich display)
    for s in cfg.universe:
        prices[s] = float(ex.fetch_ticker(to_ccxt_symbol(s, cfg.quote, cfg.market_type))["last"])

    def _read_holdings():
        if cfg.market_type == "swap":
            for p in ex.fetch_positions():
                sym = p.get("symbol")
                for s in cfg.universe:
                    if sym == to_ccxt_symbol(s, cfg.quote, cfg.market_type):
                        amt = float(p.get("contracts") or 0.0)
                        if amt <= 0:
                            continue
                        side = (p.get("side") or "long")
                        # SIGNED: short = negative (§24 做空闸 reconcile needs the sign to cover/flip)
                        balances[s] = -amt if side == "short" else amt
                        pos_detail[s] = {
                            "side": side,
                            "entry": float(p.get("entryPrice") or 0.0) or None,
                            "qty": amt,
                            "upnl": float(p.get("unrealizedPnl") or 0.0),
                        }
        else:
            bal = ex.fetch_balance()
            for s in cfg.universe:
                base = s[: -len(cfg.quote)]
                balances[s] = float((bal.get("total") or {}).get(base, 0.0) or 0.0)

    holdings_ok = True
    try:  # read positions/balances; on failure assume flat (and refuse to trade if armed -- below)
        _read_holdings()
    except Exception as exc:
        holdings_ok = False
        print(f"  (no holdings access: {type(exc).__name__}) -> assuming flat")
        if mode == "live" and x4_live_enabled():
            print("  [ALERT] live+armed but cannot read positions (need a FUTURES-enabled API key for"
                  " swap) -> SKIP trading this run (no blind fills).")

    # auto-capital: size against the LIVE USDT wallet balance (本账户全部余额可用,随盈亏伸缩). Resolved
    # here (after the exchange is live) — capital does NOT affect target_weights/universe, only sizing.
    if _cap_auto:
        bal_usdt = _perp_usdt_balance(ex)
        if bal_usdt and bal_usdt > 0:
            cfg = dataclasses.replace(cfg, capital_usdt=bal_usdt)
            print(f"  [capital] auto = 账户 USDT 余额 ${bal_usdt:.2f} (随盈亏自动伸缩)")
        else:
            holdings_ok = False   # refuse to size against an unknown balance (same guard as holdings)
            print("  [ALERT] auto-capital 无法读取 USDT 余额 -> SKIP trading this run (不按未知本金下单).")

    # 盘中硬止损: trailing Chandelier on the LIVE price (intraday), persisted across the 10-min runs.
    stops_path = STATE_DIR / "stops.json"
    try:
        stop_state = json.loads(stops_path.read_text())
    except Exception:
        stop_state = {}
    tw, stop_state, stopped = apply_chandelier_stops(tw, prices, aligned, stop_state, cfg)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    stops_path.write_text(json.dumps(stop_state, indent=2, default=float))
    if stopped:
        print(f"  [STOP] 盘中硬止损触发,强制平仓: {', '.join(stopped)}")

    # LEVERAGE SAFETY: set + VERIFY 2x/isolated before sizing; refuse any coin whose leverage we can't
    # confirm (an unconfirmed swap leverage may be the 20x exchange default -> ~5% liquidation).
    unsafe: set = set()
    if mode == "live" and x4_live_enabled() and cfg.market_type == "swap":
        unsafe = prepare_swap(ex, list(cfg.universe), cfg)
        if unsafe:
            print(f"  [ALERT] 杠杆未能确认为 {int(cfg.max_leverage)}x/{cfg.margin_mode}: "
                  f"{sorted(unsafe)} -> 拒绝交易这些币(先去交易所手动设)")
            tw = [t for t in tw if t.symbol not in unsafe]

    res = compute_orders(tw, balances, prices, filters, cfg)
    # small-capital honesty: which universe coins can't be held at this capital — judged by the REAL
    # inverse-vol target notional (not an equal-weight proxy), so the list is faithful to the weighting
    blocked = unreachable_coins(aligned, prices, filters, cfg)
    if blocked:
        print(f"  [capital] 本金 ${cfg.capital_usdt:.0f} 过小,以下币按逆波动率权重的目标额低于最小下单额,会被跳过: "
              + ", ".join(f"{b['symbol']}(目标${b['target_usdt']:.0f}<地板${b['min_usdt']:.0f})" for b in blocked))
    # SAFETY: never place orders against an unknown book (would blind-buy full notional).
    if mode == "live" and x4_live_enabled() and not holdings_ok:
        res.orders = []
    print(f"  current ${sum(res.current_usdt.values()):.2f} deployed; "
          f"{len(res.orders)} order(s), {len(res.skipped)} skipped")
    for sk in res.skipped:
        print(f"    skip {sk}")

    placed = place_orders(ex, res.orders, mode=mode, cfg=cfg)

    # T2-2 交易所原生兜底止损: park a reduce-only STOP_MARKET (closePosition) at the Chandelier level
    # so an intraday crash that gaps through it BETWEEN these 10-min runs is closed by the exchange,
    # not only on the next poll. Cancel-then-(re)place, debounced by stop_amend_band; closePosition
    # auto-cancels when the leg goes flat. Swap only; dry/enable-gated like place_orders.
    resting_stops: dict[str, float] = {}
    if cfg.market_type == "swap":
        stop_px = chandelier_stop_prices(tw, aligned, stop_state, cfg)
        existing_stops = fetch_open_stops(ex, list(cfg.universe), cfg) if mode == "live" else {}
        stop_plan = plan_stop_orders(stop_px, balances, existing_stops, cfg)
        sync_stop_orders(ex, stop_plan, mode=mode, cfg=cfg)
        resting_stops = {s: round(px, 6) for s, px in stop_px.items() if balances.get(s, 0.0) != 0}
        if resting_stops:
            print(f"  [stop-guard] 交易所兜底止损 {len(resting_stops)} 腿: "
                  + ", ".join(f"{s}@{px:.6g}" for s, px in resting_stops.items()))

    # The master gate is decided on the DAILY CLOSE (strategy semantics unchanged). For the panel we
    # show the LIVE ticker so the price ticks intraday — BTC is in the universe, so its live `last`
    # was already fetched above (no extra request). SMA + gate distance stay on the close.
    btc_closes = [b.close for b in aligned[cfg.gate_sym]]
    btc_close = btc_closes[-1]
    btc_px = prices.get(cfg.gate_sym, btc_close)   # live last for display; fall back to the close
    btc_sma = sum(btc_closes[-cfg.gate_sma:]) / cfg.gate_sma if len(btc_closes) >= cfg.gate_sma else 0.0
    deployed = sum(abs(v) for v in res.current_usdt.values())   # GROSS notional (long + |short|)
    _twmap = {t.symbol: t.weight for t in tw}
    holdings = []
    for s in cfg.universe:
        if abs(res.current_usdt.get(s, 0.0)) <= 0.01:
            continue
        d = pos_detail.get(s, {})
        holdings.append({
            "symbol": s, "value": round(res.current_usdt[s], 2),   # signed (short = negative)
            "weight": round(_twmap.get(s, 0.0), 4),
            "side": d.get("side") or ("short" if res.current_usdt[s] < 0 else "long"),
            "entry": round(d["entry"], 6) if d.get("entry") else None,
            "qty": d.get("qty"),
            "price": prices.get(s),
            "upnl": round(d["upnl"], 4) if d.get("upnl") is not None else None,
            "stop": resting_stops.get(s),   # exchange-native squeeze/crash backstop trigger px
        })
    account_upnl = round(sum(h["upnl"] for h in holdings if h.get("upnl") is not None), 2)

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": dt.datetime.now(dt.UTC).isoformat(), "bar": last_date, "mode": mode,
        "gate_open": gate_open, "armed": x4_live_enabled(),
        "short_gate": cfg.short_gate, "shorting": shorting,   # §24 做空闸 状态
        "slow": cfg.slow,   # §24.1 trend slow MA (100->60)
        "market_type": cfg.market_type, "max_leverage": cfg.max_leverage,
        "vol_target": cfg.vol_target, "chandelier_mult": cfg.chandelier_mult,
        "stopped": stopped, "leverage_unsafe": sorted(unsafe),
        "resting_stops": resting_stops,   # T2-2 交易所原生兜底止损价 (data_sym -> trigger px)
        "gross_exposure": round(deployed / cfg.capital_usdt, 3) if cfg.capital_usdt else 0.0,  # actual ×
        "capital": cfg.capital_usdt, "deployed": round(deployed, 2),   # deployed NOTIONAL
        "unrealized_pnl": account_upnl,   # 当前持仓未实现盈亏(看板)
        "equity": round(cfg.capital_usdt + account_upnl, 2),   # 钱包余额 + 未实现 = 实时权益
        "margin_used": round(deployed / cfg.max_leverage, 2) if cfg.max_leverage else round(deployed, 2),
        "cash": round(cfg.capital_usdt - deployed / max(cfg.max_leverage, 1.0), 2),  # free margin
        "btc_px": round(btc_px, 2), "btc_close": round(btc_close, 2),
        "btc_sma200": round(btc_sma, 2),
        "btc_to_sma": round(btc_close / btc_sma - 1.0, 4) if btc_sma > 0 else 0.0,  # gate dist = close 口径
        "n_universe": len(cfg.universe),
        "buying_power": round(cfg.capital_usdt * max(cfg.max_leverage, 1.0), 2),
        "capital_blocked": blocked,   # coins whose exchange min order > equal-weight slice @ capital
        "targets": {t.symbol: round(t.weight, 4) for t in tw},
        "holdings": holdings,
        "orders": [{"symbol": o.symbol, "side": o.side, "base": o.base_amount,
                    "quote": o.quote_amount, "est_usdt": o.est_usdt} for o in res.orders],
        "n_placed": sum(1 for p in placed if p.get("result")),
    }
    # latest.json is refreshed every run (drives the panel). The orders.jsonl trade-audit log is
    # appended ONLY on an actual reconciliation event (orders intended or placed), so the 10-minute
    # panel-refresh cadence doesn't flood it with no-op snapshots.
    if res.orders or rec["n_placed"]:
        with (STATE_DIR / "orders.jsonl").open("a") as f:
            f.write(json.dumps(rec, default=float) + "\n")

    # equity history for the 看板 收益曲线: append this run's real equity (wallet + 未实现), dedup the
    # last point if same bar+minute, cap to the last 720 points (~5 days @ 10-min cron). Kept in a small
    # standalone file so it survives across runs; embedded into latest.json as equity_curve for the chart.
    hist_path = STATE_DIR / "equity_history.json"
    try:
        hist = json.loads(hist_path.read_text())
        if not isinstance(hist, list):
            hist = []
    except Exception:
        hist = []
    stamp = rec["ts"][:16]   # minute granularity
    if not (hist and hist[-1].get("ts", "")[:16] == stamp):
        hist.append({"ts": rec["ts"], "date": last_date, "equity": rec["equity"]})
    hist = hist[-720:]
    hist_path.write_text(json.dumps(hist, default=float))
    rec["equity_curve"] = hist   # latest.json only (already wrote orders.jsonl above without it)

    (STATE_DIR / "latest.json").write_text(json.dumps(rec, indent=2, default=float))
    print(f"  logged -> {STATE_DIR}/latest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
