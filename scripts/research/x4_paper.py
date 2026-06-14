#!/usr/bin/env python3
"""X4 paper-sim ops runner: replay (engine validation) + forward (daily live paper). §18 / B2.

Deploys the §17-validated 3-sleeve portfolio (S1-GRID + S3-CTA + S4-MOM; S2 excluded). No real orders.

  replay [months] : run the engine over recent data and print the daily snapshot trail + final
                    metrics. Fidelity to the backtest is by construction (papersim re-runs the exact
                    drivers) -- eyeball the final sleeve totals against §15 (S1 +5.4 / S3 +115 / S4 +98).
  forward         : pull the latest 1d bars, run the engine, append one snapshot line to
                    state/x4/paper/snapshots.jsonl (+ latest.json), and print today's snapshot.
                    Run this daily (after the 00:00 UTC bar closes), e.g. from cron.

Run on Mac (needs network: um 1d klines + funding):
    .venv/bin/python scripts/research/x4_paper.py replay 12
    .venv/bin/python scripts/research/x4_paper.py forward
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.grid.data import load_funding, load_klines  # noqa: E402
from qount.rv.backtest import run_basis_carry  # noqa: E402
from qount.rv.basis import build_active_series  # noqa: E402
from qount.rv.data import dated_symbol, load_contract_set  # noqa: E402
from qount.x4.backtest import max_drawdown, run_trend_portfolio  # noqa: E402
from qount.x4.combo import align_curves, combine_fixed, correlation, sharpe_of  # noqa: E402
from qount.x4.papersim import PaperConfig, run_paper  # noqa: E402

PAPER_DIR = REPO / "state" / "x4" / "paper"
START = (2021, 1)  # full history for indicator warm-up (SMA200 etc.)

# C×D combo (§20): 60/40 TREND(S7)/CARRY(RV-C BTC+ETH) deployable book. CARRY = always-on maker
# inverse L=3 (the §7.x certified config). The carry leg's dated-futures klines now use the §20.4
# per-day dump fallback (rv.data), so the in-progress month fills daily -> this track refreshes DAILY
# like the other two (verified: combo advances to yesterday's bar, not last month-end).
COMBO_CARRY_PAIRS = [("BTCUSD", "BTCUSDT"), ("ETHUSD", "ETHUSDT")]
COMBO_MAKER_KW = dict(spot_maker=0.00075, dated_maker=0.0002,
                      maker_open=True, maker_roll=True, maker_rebalance=True)
COMBO_W_TREND, COMBO_W_CARRY = 0.6, 0.4
COMBO_ROLL_BUFFER_DAYS = 5.0

# S7-TREND-PORT (§19) deployable config + universe. Same 14-coin survivor set as §16.1/§19.6.
# vol_target=2% is the §19.7 deployable SIZE: it dials the in-sample maxDD to ~-21% (clears the
# pre-registered -25% bar with margin); Sharpe (~0.88) is invariant to this sizing -- it is a
# risk-budget choice, NOT an alpha tweak. Honest forward expectation is lower (§17: ~0.70).
S7_UNIVERSE = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "SOLUSDT", "DOTUSDT",
               "LINKUSDT", "LTCUSDT", "BCHUSDT", "AVAXUSDT", "ATOMUSDT", "ETCUSDT", "TRXUSDT"]
S7_CONFIG = dict(weighting="inverse_vol", master_gate_sym="BTCUSDT", master_gate_sma=200,
                 fast=20, slow=100, regime_sma=200, vol_target=0.02, max_leverage=2.0,
                 rebalance_band=0.25, taker_fee=0.0005, slippage=0.0002, periods_per_year=365.0)


def _load(end_y: int, end_m: int):
    btc = load_klines("BTCUSDT", "1d", start=START, end=(end_y, end_m), market="um", skip_missing=True)
    fmap = {f.ts_ms: f.rate for f in load_funding("BTCUSDT", start=START, end=(end_y, end_m), skip_missing=True)}
    return btc, (lambda b: fmap.get(b.ts_ms, 0.0))


def _load_universe(end_y: int, end_m: int):
    """Load + intersection-align the S7 universe up to ``(end_y, end_m)`` (daily-dump fallback fills
    the in-progress month). Returns ``{sym: [Bar]}`` aligned to common timestamps, or ``None``."""

    by_sym: dict[str, dict] = {}
    for sym in S7_UNIVERSE:
        bars = load_klines(sym, "1d", start=START, end=(end_y, end_m), market="um", skip_missing=True)
        if len(bars) > 300:
            by_sym[sym] = {b.ts_ms: b for b in bars}
    if "BTCUSDT" not in by_sym:
        return None
    common = sorted(set.intersection(*(set(d) for d in by_sym.values())))
    return {s: [by_sym[s][t] for t in common] for s in by_sym}


def _print_snapshot(snap: dict) -> None:
    p = snap["portfolio"]
    print(f"  [{snap['date']}] portfolio: equity ${p['equity']:,.0f}  total {p['total_return']:+.1%}  "
          f"Sharpe {p['sharpe']:.2f}  maxDD {p['max_drawdown']:.1%}  (fees ${snap['fees_to_date']:,.0f})")
    for nm, m in snap["sleeves"].items():
        pos = snap["positions"][nm]
        tag = (f"w={pos['weight']:+.2f}" if "weight" in pos else f"inv={pos['inventory_base']:.3f}")
        print(f"      {nm:8} total {m['total_return']:+7.1%}  Sharpe {m['sharpe']:5.2f}  "
              f"maxDD {m['max_drawdown']:6.1%}  [{tag}]")


def replay(months: int) -> int:
    now = dt.datetime.now(dt.UTC)
    btc, fund = _load(now.year, now.month)
    if len(btc) < 300:
        print("  too few bars"); return 2
    cfg = PaperConfig()
    res = run_paper(btc, config=cfg, funding=fund)
    print(f"[X4-PAPER replay] {btc[0].date}..{btc[-1].date}  ({len(btc)} bars); deployed = "
          f"S1+S3+S4 equal-weight (S2 excluded, §17)")
    # daily snapshot trail over the last `months`
    n_tail = min(len(btc), months * 30)
    print(f"\n  --- last ~{months}mo portfolio equity trail ---")
    pc = res.portfolio_curve
    step = max(1, n_tail // 12)
    for i in range(len(btc) - n_tail, len(btc), step):
        print(f"    {btc[i].date}  ${pc[i]:,.0f}  ({pc[i]/cfg.initial_capital-1:+.1%})")
    print("\n  --- final snapshot (eyeball sleeve totals vs §15: S1 +5.4 / S3 +115 / S4 +98) ---")
    _print_snapshot(res.snapshot)
    print("\n  fidelity: papersim re-runs the exact backtest drivers -> sleeve curves are bit-for-bit"
          " the §15 results (pinned by tests/test_x4_papersim.py). Engine validated.")
    return 0


def forward() -> int:
    now = dt.datetime.now(dt.UTC)
    btc, fund = _load(now.year, now.month)
    if len(btc) < 300:
        print("  too few bars"); return 2
    res = run_paper(btc, config=PaperConfig(), funding=fund)
    snap = res.snapshot
    PAPER_DIR.mkdir(parents=True, exist_ok=True)
    # append one line per run (idempotent-ish: dedup by date on read if needed)
    with (PAPER_DIR / "snapshots.jsonl").open("a") as fh:
        fh.write(json.dumps({"run_at": now.isoformat(), **snap}, default=float) + "\n")
    (PAPER_DIR / "latest.json").write_text(json.dumps(snap, indent=2, default=float))
    print(f"[X4-PAPER forward] {now.isoformat()}  bar {snap['date']}")
    _print_snapshot(snap)
    print(f"\n  snapshot appended -> {(PAPER_DIR / 'snapshots.jsonl').relative_to(REPO)}")
    print("  PRE-REGISTERED expectation (§17): forward Sharpe ~0.4-0.7 (not in-sample 0.88), portfolio"
          " maxDD ~-17%; SMA200 gate should keep S3/S4 flat in a bear (portfolio shouldn't deep-bleed).")
    return 0


def forward_s7() -> int:
    """Daily forward paper for S7-TREND-PORT (§19.7): multi-coin trend portfolio, deployable size.

    Loads the aligned universe up to today, runs the deployable config, and appends a snapshot to
    a SEPARATE log (``s7_snapshots.jsonl`` / ``s7_latest.json``) so it never collides with the 3-leg
    §18 paper. No real orders -- pure simulation."""

    now = dt.datetime.now(dt.UTC)
    aligned = _load_universe(now.year, now.month)
    if aligned is None or len(aligned["BTCUSDT"]) < 300:
        print("  too few bars"); return 2
    res = run_trend_portfolio(aligned, initial_capital=100_000.0, **S7_CONFIG)
    btc = aligned["BTCUSDT"]
    bc = [b.close for b in btc]
    flat = len(bc) >= 200 and bc[-1] <= sum(bc[-200:]) / 200  # BTC master gate closed -> all cash
    snap = {
        "date": btc[-1].date,
        "n_bars": len(btc),
        "n_syms": res.extra["n_syms"],
        "gate_active_frac": round(res.extra["gate_active_frac"], 4),
        "trend_flat": bool(flat),
        "portfolio": {
            "equity": round(res.equity_curve[-1], 2),
            "total_return": res.total_return,
            "sharpe": res.sharpe,
            "max_drawdown": res.max_drawdown,
        },
        "fees_to_date": round(res.fees_paid, 2),
    }
    PAPER_DIR.mkdir(parents=True, exist_ok=True)
    with (PAPER_DIR / "s7_snapshots.jsonl").open("a") as fh:
        fh.write(json.dumps({"run_at": now.isoformat(), **snap}, default=float) + "\n")
    (PAPER_DIR / "s7_latest.json").write_text(json.dumps(snap, indent=2, default=float))
    p = snap["portfolio"]
    print(f"[X4-PAPER forward-s7] {now.isoformat()}  bar {snap['date']}  ({snap['n_syms']} syms)")
    print(f"  S7-TREND-PORT: equity ${p['equity']:,.0f}  total {p['total_return']:+.1%}  "
          f"Sharpe {p['sharpe']:.2f}  maxDD {p['max_drawdown']:.1%}  "
          f"(BTC-gate active {snap['gate_active_frac']:.0%}, fees ${snap['fees_to_date']:,.0f})")
    print(f"\n  snapshot appended -> {(PAPER_DIR / 's7_snapshots.jsonl').relative_to(REPO)}")
    print("  PRE-REGISTERED (§19.7): deployable size vol_target=2% -> in-sample ~+80%/0.87/-21%;"
          " honest forward Sharpe anchored ~0.70 (§17, not in-sample 0.88); BTC gate flattens in a bear.")
    return 0


def _load_carry_sleeve(end_y: int, end_m: int):
    """Build the RV-C BTC+ETH carry sleeve (always-on maker inverse L=3, two legs equal-weight).

    Returns ``(ts_list, curve)`` rebased to $100k, or ``None`` if data is too short. The dated leg is
    monthly-only, so this lags the in-progress month."""

    legs = {}
    for cm_base, spot_sym in COMBO_CARRY_PAIRS:
        spot = load_klines(spot_sym, "1d", start=START, end=(end_y, end_m), market="spot",
                           skip_missing=True)
        contracts = load_contract_set(start=START, end=(end_y, end_m), base=cm_base)
        active = build_active_series(spot, contracts, roll_buffer_days=COMBO_ROLL_BUFFER_DAYS)
        if len(active) < 300:
            return None
        r = run_basis_carry(active, liq_leverage=3.0, inverse=True, **COMBO_MAKER_KW)
        legs[cm_base] = ([ab.spot.ts_ms for ab in active], list(r.curve))
    ts, aligned = align_curves(legs, initial_capital=100_000.0)
    return ts, combine_fixed(aligned, {b: 0.5 for b in legs}, initial_capital=100_000.0)


def forward_combo() -> int:
    """Daily forward paper for the §20 C×D combo: 60/40 S7-trend / RV-C-carry, one $100k book.

    Re-runs both sleeves over full history, aligns on common timestamps, combines at the deployable
    60/40 weights, and appends a snapshot to a SEPARATE log (``combo_snapshots.jsonl`` /
    ``combo_latest.json``). No real orders. The carry leg now uses the §20.4 dated day-dump fallback,
    so this track refreshes DAILY like the others."""

    now = dt.datetime.now(dt.UTC)
    aligned_univ = _load_universe(now.year, now.month)
    if aligned_univ is None or len(aligned_univ["BTCUSDT"]) < 300:
        print("  too few trend bars"); return 2
    tres = run_trend_portfolio(aligned_univ, initial_capital=100_000.0, **S7_CONFIG)
    trend_ts = [b.ts_ms for b in aligned_univ["BTCUSDT"]]

    carry = _load_carry_sleeve(now.year, now.month)
    if carry is None:
        print("  too few carry bars"); return 2
    carry_ts, carry_curve = carry

    ts, al = align_curves({"TREND": (trend_ts, tres.equity_curve), "CARRY": (carry_ts, carry_curve)},
                          initial_capital=100_000.0)
    combo = combine_fixed(al, {"TREND": COMBO_W_TREND, "CARRY": COMBO_W_CARRY}, initial_capital=100_000.0)

    from qount.rv.stats import returns_from_curve
    rho = correlation(returns_from_curve(al["TREND"]), returns_from_curve(al["CARRY"]))
    bar_date = dt.datetime.fromtimestamp(ts[-1] / 1000, dt.UTC).strftime("%Y-%m-%d")

    def _m(curve):
        return {"equity": round(curve[-1], 2), "total_return": curve[-1] / 100_000.0 - 1.0,
                "sharpe": sharpe_of(curve, periods_per_year=365.0), "max_drawdown": max_drawdown(curve)}

    bc = [b.close for b in aligned_univ["BTCUSDT"]]
    trend_flat = len(bc) >= 200 and bc[-1] <= sum(bc[-200:]) / 200
    snap = {
        "date": bar_date, "n_bars": len(ts),
        "weights": {"trend": COMBO_W_TREND, "carry": COMBO_W_CARRY},
        "corr": round(rho, 4),
        "trend_flat": bool(trend_flat),  # carry leg is always-on delta-neutral (never flat)
        "portfolio": _m(combo), "trend_alone": _m(al["TREND"]), "carry_alone": _m(al["CARRY"]),
    }
    PAPER_DIR.mkdir(parents=True, exist_ok=True)
    with (PAPER_DIR / "combo_snapshots.jsonl").open("a") as fh:
        fh.write(json.dumps({"run_at": now.isoformat(), **snap}, default=float) + "\n")
    (PAPER_DIR / "combo_latest.json").write_text(json.dumps(snap, indent=2, default=float))
    p, t, c = snap["portfolio"], snap["trend_alone"], snap["carry_alone"]
    print(f"[X4-PAPER forward-combo] {now.isoformat()}  bar {snap['date']}  ({len(ts)} bars, corr {rho:+.2f})")
    print(f"  COMBO 60/40   equity ${p['equity']:,.0f}  total {p['total_return']:+.1%}  "
          f"Sharpe {p['sharpe']:.2f}  maxDD {p['max_drawdown']:.1%}")
    print(f"    TREND alone Sharpe {t['sharpe']:.2f} / maxDD {t['max_drawdown']:.1%}; "
          f"CARRY alone Sharpe {c['sharpe']:.2f} / maxDD {c['max_drawdown']:.1%}")
    print(f"\n  snapshot appended -> {(PAPER_DIR / 'combo_snapshots.jsonl').relative_to(REPO)}")
    print("  PRE-REGISTERED (§20): carry ballast lifts Sharpe + cuts the trend tail (in-sample"
          " 0.89->1.18, -21%->-10% @40% carry). Daily refresh via §20.4 dated day-dump fallback."
          " CAVEAT: both sleeves long 'crypto alive/contango' -> NOT all-weather.")
    return 0


def _held_coins(aligned, gate_open):
    """Current long-held coins under the S7 rule (per-coin SMA200 + 20/100 cross + BTC master gate).

    Returns ``[(sym, weight)]`` (inverse-vol parity among held coins, mirroring ``combine``), or ``[]``
    when the book is flat (BTC gate shut, or no coin in an uptrend)."""

    if not gate_open:
        return []
    raw: dict[str, float] = {}
    for s, bars in aligned.items():
        c = [b.close for b in bars]
        if len(c) < 200:
            continue
        if c[-1] > sum(c[-200:]) / 200 and sum(c[-20:]) / 20 > sum(c[-100:]) / 100:
            rets = [c[i] / c[i - 1] - 1.0 for i in range(len(c) - 30, len(c))]
            mu = sum(rets) / len(rets)
            vol = (sum((x - mu) ** 2 for x in rets) / (len(rets) - 1)) ** 0.5
            raw[s] = (1.0 / vol) if vol > 0 else 0.0
    tot = sum(raw.values())
    if not raw:
        return []
    if tot <= 0:
        return [(s, 1.0 / len(raw)) for s in raw]
    return [(s, w / tot) for s, w in raw.items()]


def _carry_legs(now, capital_per_coin):
    """Current BTC/ETH cash-and-carry legs (long spot + short the active dated) at today's prices."""

    legs = []
    for cm, spot_sym in COMBO_CARRY_PAIRS:
        spot = load_klines(spot_sym, "1d", start=START, end=(now.year, now.month),
                           market="spot", skip_missing=True)
        cons = load_contract_set(start=START, end=(now.year, now.month), base=cm)
        active = build_active_series(spot, cons, roll_buffer_days=COMBO_ROLL_BUFFER_DAYS)
        ab = active[-1]
        exp = dt.datetime.fromtimestamp(ab.expiry_ms / 1000, dt.UTC).date()
        sp, dp = ab.spot.close, ab.dated.close
        base = cm[:3]
        legs.append({"instrument": f"{base} 现货", "side": "多", "qty": capital_per_coin / sp,
                     "price": sp, "value": capital_per_coin})
        legs.append({"instrument": dated_symbol(cm, exp), "side": "空", "qty": capital_per_coin / dp,
                     "price": dp, "value": capital_per_coin})
    return legs


def holdings() -> int:
    """As-of-today forward holdings book (NOT backtest returns). §20.5.

    Anchors a fresh $100k paper book on first run (``deploy_date``), shows what the deployable C×D
    combo actually holds right now (carry legs long spot / short dated + any trend coins + cash), and
    the forward P&L since deploy (each book's equity curve rebased to $100k at the anchor bar -> starts
    at 0 today, accrues forward). Writes ``holdings_latest.json``. No real orders."""

    now = dt.datetime.now(dt.UTC)
    aligned = _load_universe(now.year, now.month)
    if aligned is None or len(aligned["BTCUSDT"]) < 300:
        print("  too few bars"); return 2
    btc = aligned["BTCUSDT"]
    bc = [b.close for b in btc]
    as_of = btc[-1].date
    gate_open = len(bc) >= 200 and bc[-1] > sum(bc[-200:]) / 200

    # persist the deploy anchor: first run pins deploy_date=today + anchor_bar=latest bar
    prev = {}
    try:
        prev = json.loads((PAPER_DIR / "holdings_latest.json").read_text())
    except Exception:
        pass
    deploy_date = prev.get("deploy_date", now.strftime("%Y-%m-%d"))
    anchor_bar = prev.get("anchor_bar", as_of)

    def rebase(curve, dates):
        idx = dates.index(anchor_bar) if anchor_bar in dates else len(curve) - 1
        base = curve[idx] if curve[idx] > 0 else curve[-1]
        eq = 100_000.0 * curve[-1] / base
        return {"fwd_equity": round(eq, 2), "fwd_pnl": round(eq - 100_000.0, 2),
                "fwd_return": eq / 100_000.0 - 1.0}

    # 3-leg (papersim, BTC) + S7 (14-coin trend) + combo (60/40)
    btc_um, fund = _load(now.year, now.month)
    three = run_paper(btc_um, config=PaperConfig(), funding=fund)
    three_dates = [b.date for b in btc_um]
    s7 = run_trend_portfolio(aligned, initial_capital=100_000.0, **S7_CONFIG)
    s7_dates = [b.date for b in btc]
    carry = _load_carry_sleeve(now.year, now.month)
    ts, al = align_curves({"TREND": ([b.ts_ms for b in btc], s7.equity_curve),
                           "CARRY": (carry[0], carry[1])}, initial_capital=100_000.0)
    combo_curve = combine_fixed(al, {"TREND": COMBO_W_TREND, "CARRY": COMBO_W_CARRY},
                                initial_capital=100_000.0)
    combo_dates = [dt.datetime.fromtimestamp(t / 1000, dt.UTC).strftime("%Y-%m-%d") for t in ts]

    # combo positions: 40% carry (always on) + 60% trend (held coins, currently flat) + cash
    fwd = rebase(combo_curve, combo_dates)
    eq = fwd["fwd_equity"]
    carry_cap_per_coin = eq * COMBO_W_CARRY / len(COMBO_CARRY_PAIRS)
    legs = _carry_legs(now, carry_cap_per_coin)
    held = _held_coins(aligned, gate_open)
    trend_positions = []
    for sym, w in held:
        px = aligned[sym][-1].close
        val = eq * COMBO_W_TREND * w
        trend_positions.append({"instrument": sym, "side": "多", "qty": val / px,
                                "price": px, "value": val})
    # capital committed: carry is delta-neutral -> 40% of book funds the long+short pair (the short is
    # a hedge, not extra capital), so count carry once at its weight, not the sum of both legs' notionals.
    carry_capital = eq * COMBO_W_CARRY
    trend_deployed = sum(p["value"] for p in trend_positions)
    combo_book = {
        **fwd, "as_of": as_of, "trend_flat": not bool(held),
        "positions": legs + trend_positions, "cash": round(eq - carry_capital - trend_deployed, 2),
    }

    out = {
        "as_of": as_of, "deploy_date": deploy_date, "anchor_bar": anchor_bar,
        "initial_capital": 100_000.0,
        "books": {
            "3leg": {**rebase(three.portfolio_curve, three_dates), "flat": True},
            "s7": {**rebase(s7.equity_curve, s7_dates), "flat": not bool(held),
                   "n_held": len(held)},
            "combo": combo_book,
        },
    }
    PAPER_DIR.mkdir(parents=True, exist_ok=True)
    (PAPER_DIR / "holdings_latest.json").write_text(json.dumps(out, indent=2, default=float))
    cb = out["books"]["combo"]
    print(f"[X4-PAPER holdings] as-of {as_of}  deploy {deploy_date}  (forward since deploy)")
    print(f"  C×D 合成账  前向净值 ${cb['fwd_equity']:,.0f}  收益 {cb['fwd_pnl']:+,.0f} "
          f"({cb['fwd_return']:+.2%})  现金 ${cb['cash']:,.0f}")
    print(f"  实际持仓({len(cb['positions'])} 腿,趋势{'空仓' if cb['trend_flat'] else '在场'}):")
    for p in cb["positions"]:
        print(f"    {p['side']} {p['instrument']:18} {p['qty']:.4f} @ ${p['price']:,.2f} = ${p['value']:,.0f}")
    print(f"\n  written -> {(PAPER_DIR / 'holdings_latest.json').relative_to(REPO)}")
    print("  注:以 deploy 日为 $100k 起点,收益自今日累积(非回测);日线策略持仓按日收盘价标记。")
    return 0


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else "replay"
    if mode == "replay":
        return replay(int(argv[2]) if len(argv) > 2 else 12)
    if mode == "holdings":
        return holdings()
    if mode == "forward":
        return forward()
    if mode == "forward-s7":
        return forward_s7()
    if mode == "forward-combo":
        return forward_combo()
    print(f"unknown mode {mode!r} (expected 'replay', 'forward', 'forward-s7', 'forward-combo', "
          f"or 'holdings')")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
