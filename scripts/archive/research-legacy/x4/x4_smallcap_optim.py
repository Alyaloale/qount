#!/usr/bin/env python3
"""X4 small-cap S7-mini optimization candidates (docs/crypto-x4-plan.md §21.B/C/D).

Tests the reviewer's proposed enhancements ONE AT A TIME against the TOP7 spot baseline, judging
each by the project's anti-overfit rule: a real improvement must beat the baseline Sharpe in BOTH
the TRAIN (2021-23) and TEST (2024-26) slices without materially worse maxDD. Anything that only
helps the full-period headline (= the recent-bull window) is curve-fit, reported as such.

Slices are measured off the full-series equity curve (no re-warm-up) -> walk-forward-honest, mirroring
x4_walkforward.py. Run on Mac (needs network: um 1d klines):
    .venv/bin/python scripts/research/x4_smallcap_optim.py 2021-01 2026-05
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.research_data.market_data import Bar, load_klines  # noqa: E402
from qount.legacy.x4.backtest import max_drawdown, run_trend_portfolio  # noqa: E402
from qount.legacy.x4.portfolio import sharpe_of  # noqa: E402

CAP = 100_000.0
F, S = 0.0005, 0.0002
TOP7 = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "LINKUSDT"]
# §21 spot deployable base config.
BASE = dict(weighting="inverse_vol", master_gate_sym="BTCUSDT", master_gate_sma=200,
            fast=20, slow=100, regime_sma=200, vol_target=0.02, max_leverage=1.0,
            rebalance_band=0.25, vol_lookback=30)
TEST_FROM = "2024-01"   # train < this <= test


def _load(universe, span):
    (sy, sm), (ey, em) = span
    by: dict[str, dict[int, Bar]] = {}
    for s in universe:
        b = load_klines(s, "1d", start=(sy, sm), end=(ey, em), market="um", skip_missing=True)
        if len(b) > 300:
            by[s] = {x.ts_ms: x for x in b}
    common = sorted(set.intersection(*(set(d) for d in by.values())))
    return {s: [by[s][t] for t in common] for s in by}


def _slice_idx(bars, ym):
    for i, b in enumerate(bars):
        if b.date >= f"{ym}-01":
            return i
    return len(bars)


def _metrics(curve, split):
    """Full / train / test (Sharpe, maxDD) off one full-series curve (no re-warmup)."""
    def m(c):
        return sharpe_of(c, periods_per_year=365.0), max_drawdown(c)
    return {"full": m(curve), "train": m(curve[:split + 1]), "test": m(curve[split:])}


def _row(label, curve, split, base=None):
    me = _metrics(curve, split)
    tot = curve[-1] / CAP - 1.0
    fs, fd = me["full"]; rs, rd = me["train"]; ts, td = me["test"]
    verdict = ""
    if base is not None:
        bt, bv, bf = base["train"][0], base["test"][0], base["full"][0]
        bdd_worst = min(base["train"][1], base["test"][1])
        eps = 1e-9
        if rs > bt + eps and ts > bv + eps:
            verdict = "  REAL (both regimes)"          # robust across train AND test
        elif rs > bt + eps and ts > bv - 0.02:
            verdict = "  weak-regime+ (neutral bull)"   # helps chop/bear, doesn't hurt bull = credible
        elif min(rd, td) > bdd_worst + 0.02 and fs > bf - 0.03:
            verdict = "  risk-reducer (DD<, Sharpe~)"    # trades headline for lower drawdown
        elif fs > bf + eps and rs <= bt + eps:
            verdict = "  curve-fit (only bull headline)"
        else:
            verdict = "  worse"
    print(f"  {label:26} {tot:>8.1%} | full {fs:>5.2f}/{fd:>6.1%} | train {rs:>5.2f}/{rd:>6.1%} "
          f"| test {ts:>5.2f}/{td:>6.1%}{verdict}")
    return me


def main(argv):
    start = argv[1] if len(argv) > 1 else "2021-01"
    end = argv[2] if len(argv) > 2 else "2026-05"
    span = (tuple(int(x) for x in start.split("-")), tuple(int(x) for x in end.split("-")))
    aligned = _load(TOP7, span)
    btc = aligned["BTCUSDT"]
    split = _slice_idx(btc, TEST_FROM)
    print(f"[X4-SMALLCAP-OPTIM] {start}..{end}; TOP7 spot; train<{TEST_FROM}<=test "
          f"({btc[0].date}..{btc[-1].date}, split bar {btc[split].date})")
    print(f"  {'variant':26} {'total':>8} | {'full S/DD':>13} | {'train S/DD':>14} | {'test S/DD':>14}")

    base_curve = run_trend_portfolio(aligned, initial_capital=CAP, taker_fee=F, slippage=S,
                                     periods_per_year=365.0, **BASE).equity_curve
    base = _row("BASELINE (TOP7 spot)", base_curve, split)

    variants = {
        "B breadth-OR 0.5": {**BASE, "breadth_gate": 0.5, "breadth_combine": "or"},
        "B breadth-AND 0.5": {**BASE, "breadth_gate": 0.5, "breadth_combine": "and"},
        "B breadth-only 0.5": {**BASE, "breadth_gate": 0.5, "breadth_combine": "breadth"},
        "C ADX>=20": {**BASE, "adx_min": 20.0},
        "C ADX>=25": {**BASE, "adx_min": 25.0},
        "D corr-penalty": {**{k: v for k, v in BASE.items() if k != "weighting"},
                           "weighting": "inverse_vol_corr"},
        "B-OR + D (combo)": {**{k: v for k, v in BASE.items() if k != "weighting"},
                             "weighting": "inverse_vol_corr", "breadth_gate": 0.5,
                             "breadth_combine": "or"},
    }
    for label, cfg in variants.items():
        curve = run_trend_portfolio(aligned, initial_capital=CAP, taker_fee=F, slippage=S,
                                    periods_per_year=365.0, **cfg).equity_curve
        _row(label, curve, split, base=base)

    print("\n  RULE: REAL = beats baseline Sharpe in BOTH train AND test, DD not >3pp worse "
          "(worst slice). curve-fit = only the full/recent-bull headline improves.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
