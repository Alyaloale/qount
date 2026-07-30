#!/usr/bin/env python3
"""X4 S7-TREND-PORT: multi-coin trend portfolio research run (docs/crypto-x4-plan.md §19).

Thesis (§19): NOT cross-sectional *selection* (§16.1 XMOM = falsified, -86% tail) but
*diversification* of the one walk-forward-validated edge -- run the S3 long-only trend (with each
coin's own SMA200 gate) on every coin, risk-combine (inverse-vol), optionally veto with a BTC master
gate. Kill question (§19.4): does it beat (a) S3-on-BTC (Sharpe 0.70 / maxDD -29%) AND (b) naive
equal-weight HOLD of the universe (Sharpe 0.77), while cutting maxDD materially below -25%?

Same intersection-alignment + survivor universe as x4_xmom.py -> apples-to-apples with §16.1.
A second pass adds a "battered survivor" (ICP, ~-95% from launch) to stress survivorship bias: the
per-coin trend gate should exit a dying coin, so the trend portfolio should degrade far less than
equal-weight-hold when such names are added. (A full point-in-time universe with zeroed/delisted
coins needs ragged-listing support in the engine -- documented follow-up.)

Run on Mac (needs network: um 1d klines):
    .venv/bin/python scripts/research/x4_trendport.py 2021-01 2026-05
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.research_data.market_data import Bar, load_klines  # noqa: E402
from qount.legacy.x4.backtest import max_drawdown, run_directional, run_trend_portfolio  # noqa: E402
from qount.legacy.x4.portfolio import sharpe_of  # noqa: E402
from qount.legacy.x4.strategies import TrendFollow  # noqa: E402

CAPITAL = 100_000.0
F, S = 0.0005, 0.0002
# Same 14-coin survivor universe as §16.1 (apples-to-apples with the XMOM kill baselines).
CORE = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "SOLUSDT", "DOTUSDT",
        "LINKUSDT", "LTCUSDT", "BCHUSDT", "AVAXUSDT", "ATOMUSDT", "ETCUSDT", "TRXUSDT"]
# Battered survivors (full history, brutal drawdowns) for the survivorship-bias stress pass.
STRESS_ADD = ["ICPUSDT"]
# S3 validated params (§17 / PaperConfig).
S3 = dict(fast=20, slow=100, regime_sma=200)
SIZING = dict(vol_target=0.03, max_leverage=2.0, rebalance_band=0.25)


def _load_aligned(universe, span):
    (sy, sm), (ey, em) = span
    by_sym: dict[str, dict[int, Bar]] = {}
    for sym in universe:
        bars = load_klines(sym, "1d", start=(sy, sm), end=(ey, em), market="um", skip_missing=True)
        if len(bars) > 300:
            by_sym[sym] = {b.ts_ms: b for b in bars}
    if "BTCUSDT" not in by_sym:
        raise SystemExit("no BTC data")
    common = sorted(set.intersection(*(set(d) for d in by_sym.values())))
    return {s: [by_sym[s][t] for t in common] for s in by_sym}, common


def _stats(curve):
    return curve[-1] / CAPITAL - 1.0, sharpe_of(curve, periods_per_year=365.0), max_drawdown(curve)


def _row(nm, curve):
    t, sh, dd = _stats(curve)
    print(f"  {nm:30} {t:>+9.1%} {sh:>7.2f} {dd:>8.1%}")
    return sh, dd


def _equal_weight_hold(aligned, ts):
    ew = [CAPITAL]
    for i in range(1, len(ts)):
        r = sum(aligned[s][i].close / aligned[s][i - 1].close - 1.0 for s in aligned) / len(aligned)
        ew.append(ew[-1] * (1.0 + r))
    return ew


def _run_universe(label, aligned, ts):
    print(f"\n=== {label}: {len(aligned)} syms, {len(ts)} aligned bars "
          f"({aligned['BTCUSDT'][0].date}..{aligned['BTCUSDT'][-1].date}) ===")
    print(f"  {'strategy':30} {'total':>9} {'Sharpe':>7} {'maxDD':>8}")

    # baselines
    btc = aligned["BTCUSDT"]
    bh = [CAPITAL * btc[i].close / btc[0].close for i in range(len(btc))]
    _row("BTC buy&hold", bh)
    ew_sh, ew_dd = _row("universe equal-wt HOLD", _equal_weight_hold(aligned, ts))
    s3 = run_directional(btc, TrendFollow(allow_short=False, **S3), initial_capital=CAPITAL,
                         taker_fee=F, slippage=S, periods_per_year=365.0, **SIZING).equity_curve
    s3_sh, s3_dd = _row("S3 BTC trend (single)", s3)

    # S7 variants: {equal, inverse_vol} x {master gate off, BTC gate on}
    results = {}
    for wt in ("equal", "inverse_vol"):
        for gate in (None, "BTCUSDT"):
            res = run_trend_portfolio(aligned, weighting=wt, master_gate_sym=gate,
                                      master_gate_sma=200, initial_capital=CAPITAL,
                                      taker_fee=F, slippage=S, periods_per_year=365.0, **S3, **SIZING)
            g = "BTCgate" if gate else "nogate"
            sh, dd = _row(f"S7 {wt}/{g}", res.equity_curve)
            results[(wt, g)] = (sh, dd, res)

    # kill verdict vs §19.4
    best = max(results.values(), key=lambda v: v[0])
    bsh, bdd, bres = best
    print(f"\n  KILL CHECK (§19.4): best S7 Sharpe {bsh:.2f} vs S3-BTC {s3_sh:.2f} & equal-wt-hold {ew_sh:.2f};"
          f" maxDD {bdd:.1%} (target < -25%)")
    pass_sharpe = bsh > s3_sh and bsh > ew_sh
    pass_dd = bdd > -0.25
    verdict = "PASS" if (pass_sharpe and pass_dd) else "FAIL"
    print(f"  -> Sharpe>both={pass_sharpe}, maxDD<-25%={pass_dd}  ==>  {verdict}")
    return {"ew": (ew_sh, ew_dd), "s3": (s3_sh, s3_dd), "best_s7": (bsh, bdd)}


def main(argv: list[str]) -> int:
    start = argv[1] if len(argv) > 1 else "2021-01"
    end = argv[2] if len(argv) > 2 else "2026-05"
    span = (tuple(int(x) for x in start.split("-")), tuple(int(x) for x in end.split("-")))

    print(f"[S7-TREND-PORT] {start}..{end} (1d); S3 params {S3}, sizing {SIZING}")
    core_aligned, core_ts = _load_aligned(CORE, span)
    core = _run_universe("CORE (14 survivors, apples-to-apples §16.1)", core_aligned, core_ts)

    stress_aligned, stress_ts = _load_aligned(CORE + STRESS_ADD, span)
    stress = _run_universe(f"STRESS (CORE + {STRESS_ADD})", stress_aligned, stress_ts)

    print("\n=== SURVIVORSHIP STRESS: degradation when battered coins added (CORE -> STRESS) ===")
    print(f"  equal-wt HOLD Sharpe {core['ew'][0]:.2f} -> {stress['ew'][0]:.2f} "
          f"(maxDD {core['ew'][1]:.1%} -> {stress['ew'][1]:.1%})")
    print(f"  best S7        Sharpe {core['best_s7'][0]:.2f} -> {stress['best_s7'][0]:.2f} "
          f"(maxDD {core['best_s7'][1]:.1%} -> {stress['best_s7'][1]:.1%})")
    print("  thesis: the per-coin trend gate exits a dying coin, so S7 should degrade LESS than"
          " equal-wt HOLD (which rides it down) -> S7 is structurally less survivorship-inflated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
