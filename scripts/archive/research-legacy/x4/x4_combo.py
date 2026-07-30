#!/usr/bin/env python3
"""C×D combined-book kill-test: line D trend (S7) + line C carry (RV-C) on one capital base.

Thesis (proposed 2026-06-13, docs/crypto-x4-plan.md §20 / docs/rv-c-plan.md): S7 is directional
crypto-beta trend (honest fwd Sharpe ~0.70, maxDD -21% it cannot self-cut); RV-C BTC/ETH dated
cash-and-carry is delta-neutral (Sharpe ~1.4, thin +6.4%/yr, tiny DD, tail on the UPSIDE squeeze).
Opposite-pointing tails -> a capacity-capped carry sleeve should act as ballast (line A's
"金/债压舱石"), lifting combined Sharpe AND cutting the trend tail.

Pre-registered kill criterion: at a DEPLOYABLE carry weight (<= 40%, capacity-capped to BTC/ETH),
the combo must beat trend-alone on BOTH Sharpe and maxDD. Else the combination adds nothing.
Honest caveat: both sleeves are long the same "crypto alive / contango persists" macro factor ->
diversification is real in the short-term tail, NOT all-weather.

Run on Mac (reuses cached um/spot/COIN-M klines):
    .venv/bin/python scripts/research/x4_combo.py 2021-01 2026-05
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.research_data.market_data import Bar, load_klines  # noqa: E402
from qount.legacy.rv_c.backtest import run_basis_carry  # noqa: E402
from qount.legacy.rv_c.basis import build_active_series  # noqa: E402
from qount.legacy.rv_c.data import load_contract_set  # noqa: E402
from qount.legacy.x4.backtest import max_drawdown, run_trend_portfolio  # noqa: E402
from qount.legacy.x4.combo import align_curves, combine_fixed, correlation, kill_verdict, sharpe_of  # noqa: E402

CAPITAL = 100_000.0
PPY = 365.0
F, S = 0.0005, 0.0002
# S7 deployable config (§19.7): S3 validated params, inverse-vol risk parity, BTC master gate,
# vol_target 2% = the deployable档 (+80%/0.87/-21%).
CORE = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "SOLUSDT", "DOTUSDT",
        "LINKUSDT", "LTCUSDT", "BCHUSDT", "AVAXUSDT", "ATOMUSDT", "ETCUSDT", "TRXUSDT"]
S3 = dict(fast=20, slow=100, regime_sma=200)
SIZING = dict(vol_target=0.02, max_leverage=2.0, rebalance_band=0.25)
# RV-C certified carry config (§7.x): always-on, inverse L=3, maker.
CARRY_PAIRS = [("BTCUSD", "BTCUSDT"), ("ETHUSD", "ETHUSDT")]
MAKER_KW = dict(spot_maker=0.00075, dated_maker=0.0002,
                maker_open=True, maker_roll=True, maker_rebalance=True)
ROLL_BUFFER_DAYS = 5.0
# Capacity-capped carry weights to sweep (carry can't absorb much -> a priori fixed, not vol-parity).
CARRY_WEIGHTS = [0.0, 0.2, 0.3, 0.4, 0.5]


def _stats(curve):
    return curve[-1] / CAPITAL - 1.0, sharpe_of(curve, periods_per_year=PPY), max_drawdown(curve)


def _load_trend(span):
    (sy, sm), (ey, em) = span
    by_sym: dict[str, dict[int, Bar]] = {}
    for sym in CORE:
        bars = load_klines(sym, "1d", start=(sy, sm), end=(ey, em), market="um", skip_missing=True)
        if len(bars) > 300:
            by_sym[sym] = {b.ts_ms: b for b in bars}
    common = sorted(set.intersection(*(set(d) for d in by_sym.values())))
    aligned = {s: [by_sym[s][t] for t in common] for s in by_sym}
    res = run_trend_portfolio(aligned, weighting="inverse_vol", master_gate_sym="BTCUSDT",
                              master_gate_sma=200, initial_capital=CAPITAL, taker_fee=F, slippage=S,
                              periods_per_year=PPY, **S3, **SIZING)
    return common, res.equity_curve


def _load_carry_sleeve(span):
    (sy, sm), (ey, em) = span
    legs = {}
    for cm_base, spot_sym in CARRY_PAIRS:
        spot = load_klines(spot_sym, "1d", start=(sy, sm), end=(ey, em), market="spot",
                           skip_missing=True)
        contracts = load_contract_set(start=(sy, sm), end=(ey, em), base=cm_base)
        active = build_active_series(spot, contracts, roll_buffer_days=ROLL_BUFFER_DAYS)
        r = run_basis_carry(active, liq_leverage=3.0, inverse=True, **MAKER_KW)
        legs[cm_base] = ([ab.spot.ts_ms for ab in active], list(r.curve))
    # equal-weight the two certified legs into one carry sleeve
    ts, aligned = align_curves(legs, initial_capital=CAPITAL)
    sleeve = combine_fixed(aligned, {b: 0.5 for b in legs}, initial_capital=CAPITAL)
    return ts, sleeve


def main(argv: list[str]) -> int:
    start = argv[1] if len(argv) > 1 else "2021-01"
    end = argv[2] if len(argv) > 2 else "2026-05"
    span = (tuple(int(x) for x in start.split("-")), tuple(int(x) for x in end.split("-")))

    print(f"[C×D COMBO] {start}..{end} (1d). TREND=S7(inverse_vol/BTCgate/vt2%), "
          f"CARRY=RV-C BTC+ETH always-on maker inverse L=3")
    trend_ts, trend_curve = _load_trend(span)
    carry_ts, carry_curve = _load_carry_sleeve(span)

    ts, aligned = align_curves(
        {"TREND": (trend_ts, trend_curve), "CARRY": (carry_ts, carry_curve)},
        initial_capital=CAPITAL,
    )
    trend_a, carry_a = aligned["TREND"], aligned["CARRY"]
    from qount.research_data.metrics import returns_from_curve
    rho = correlation(returns_from_curve(trend_a), returns_from_curve(carry_a))

    d0 = datetime.fromtimestamp(ts[0] / 1000, timezone.utc).strftime("%Y-%m-%d")
    d1 = datetime.fromtimestamp(ts[-1] / 1000, timezone.utc).strftime("%Y-%m-%d")
    print(f"\n=== aligned {len(ts)} common daily bars ({d0}..{d1}); corr(TREND,CARRY) = {rho:+.3f} ===")
    print(f"  {'book':22} {'total':>9} {'Sharpe':>7} {'maxDD':>8}")
    for nm, cv in (("TREND alone (S7)", trend_a), ("CARRY alone (BTC+ETH)", carry_a)):
        t, sh, dd = _stats(cv)
        print(f"  {nm:22} {t:>+9.1%} {sh:>7.2f} {dd:>8.1%}")

    print(f"\n  fixed-weight combos (TREND + CARRY, rebalanced; remainder cash):")
    print(f"  {'T/C weight':22} {'total':>9} {'Sharpe':>7} {'maxDD':>8} {'verdict':>9}")
    rows = []
    for w_c in CARRY_WEIGHTS:
        w_t = 1.0 - w_c
        combo = combine_fixed({"TREND": trend_a, "CARRY": carry_a},
                              {"TREND": w_t, "CARRY": w_c}, initial_capital=CAPITAL)
        t, sh, dd = _stats(combo)
        v = kill_verdict(combo, trend_a, periods_per_year=PPY)
        tag = "(base)" if w_c == 0.0 else v["verdict"]
        print(f"  {f'{w_t:.0%}/{w_c:.0%}':22} {t:>+9.1%} {sh:>7.2f} {dd:>8.1%} {tag:>9}")
        rows.append({"w_trend": w_t, "w_carry": w_c, "total": t, "sharpe": sh, "maxdd": dd,
                     "sharpe_delta": v["sharpe_delta"], "maxdd_delta": v["maxdd_delta"],
                     "verdict": v["verdict"]})

    # deployable-band verdict: any carry weight in (0, 0.4] that passes both gates?
    deployable = [r for r in rows if 0.0 < r["w_carry"] <= 0.40 and r["verdict"] == "PASS"]
    print(f"\n  KILL CHECK: carry must lift Sharpe AND cut maxDD at a deployable weight (<=40%).")
    if deployable:
        best = max(deployable, key=lambda r: r["sharpe"])
        print(f"  -> PASS: at {best['w_carry']:.0%} carry, Sharpe {rows[0]['sharpe']:.2f}->"
              f"{best['sharpe']:.2f} (+{best['sharpe_delta']:.2f}), "
              f"maxDD {rows[0]['maxdd']:.1%}->{best['maxdd']:.1%} ({best['maxdd_delta']:+.1%}).")
    else:
        print(f"  -> FAIL: no deployable carry weight beats trend-alone on BOTH Sharpe and maxDD.")
    print(f"  caveat: both sleeves long the same 'crypto alive / contango' macro factor -> ballast"
          f" is real in the short-term tail, NOT all-weather.")

    out_dir = REPO / "state" / "x4" / "research_runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = out_dir / f"combo_{start}_{end}_{stamp}.json"
    out.write_text(json.dumps({
        "start": start, "end": end, "n_bars": len(ts), "span": [d0, d1], "corr": rho,
        "trend_alone": dict(zip(("total", "sharpe", "maxdd"), _stats(trend_a))),
        "carry_alone": dict(zip(("total", "sharpe", "maxdd"), _stats(carry_a))),
        "combos": rows, "deployable_pass": bool(deployable),
    }, indent=2, default=float))
    print(f"\n  artifact: {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
