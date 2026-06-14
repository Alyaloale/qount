#!/usr/bin/env python3
"""X4 small-capital S7 optimization (docs/crypto-x4-plan.md §21).

Owner wants a SMALL-CAPITAL (~$415 / 3000 RMB) tradable trend strategy: shrink S7 to ~7 coins,
trend-first (no carry ballast yet), Binance spot+futures available. Two questions only a RUN can
answer (line D = race, not kill-test; but report honestly vs §19.4 baselines):

  1. How much edge do we lose shrinking the 14-coin survivor universe down to 7 / 5 / 4 coins?
     (a priori liquidity tiers, NOT backtest-picked -> no selection bias.)
  2. What does going spot-only (max_leverage 1.0, no liquidation risk) cost vs the 2x deployable?

Reuses run_trend_portfolio unchanged. Run on Mac (needs network: um 1d klines):
    .venv/bin/python scripts/research/x4_smallcap.py 2021-01 2026-05
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.grid.data import Bar, load_klines  # noqa: E402
from qount.x4.backtest import max_drawdown, run_directional, run_trend_portfolio  # noqa: E402
from qount.x4.portfolio import sharpe_of  # noqa: E402
from qount.x4.strategies import TrendFollow  # noqa: E402

CAPITAL = 100_000.0  # backtest is scale-free (returns); $415 sizing is an execution-layer concern.
F, S = 0.0005, 0.0002
S3 = dict(fast=20, slow=100, regime_sma=200)

# A priori liquidity tiers (large-cap spot volume order), NOT chosen by backtest performance.
TIERS = {
    "TOP4": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"],
    "TOP5": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"],
    "TOP7": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "LINKUSDT"],
    "TOP10": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "LINKUSDT",
              "DOTUSDT", "AVAXUSDT", "LTCUSDT"],
    "TOP14": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "SOLUSDT", "DOTUSDT",
              "LINKUSDT", "LTCUSDT", "BCHUSDT", "AVAXUSDT", "ATOMUSDT", "ETCUSDT", "TRXUSDT"],
}
# Leverage variants: deployable 2x (vt 2%) vs spot-only 1x (no liquidation).
SIZINGS = {
    "2x/vt2%": dict(vol_target=0.02, max_leverage=2.0, rebalance_band=0.25),
    "spot/vt2%": dict(vol_target=0.02, max_leverage=1.0, rebalance_band=0.25),
}


def _load_aligned(universe, span):
    (sy, sm), (ey, em) = span
    by_sym: dict[str, dict[int, Bar]] = {}
    for sym in universe:
        bars = load_klines(sym, "1d", start=(sy, sm), end=(ey, em), market="um", skip_missing=True)
        if len(bars) > 300:
            by_sym[sym] = {b.ts_ms: b for b in bars}
    common = sorted(set.intersection(*(set(d) for d in by_sym.values())))
    return {s: [by_sym[s][t] for t in common] for s in by_sym}, common


def _stats(curve):
    return curve[-1] / CAPITAL - 1.0, sharpe_of(curve, periods_per_year=365.0), max_drawdown(curve)


def main(argv: list[str]) -> int:
    start = argv[1] if len(argv) > 1 else "2021-01"
    end = argv[2] if len(argv) > 2 else "2026-05"
    span = (tuple(int(x) for x in start.split("-")), tuple(int(x) for x in end.split("-")))

    # Load the full universe once at the widest tier; subset by tier (same aligned bars per tier load).
    print(f"[X4-SMALLCAP] {start}..{end} (1d); S3 {S3}; config = S7 inverse_vol + BTC master gate")
    print(f"\n  {'tier':6} {'lev':10} {'nsyms':>5} {'total':>9} {'Sharpe':>7} {'maxDD':>8}")

    # baselines on the TOP14 aligned set
    full_aligned, full_ts = _load_aligned(TIERS["TOP14"], span)
    btc = full_aligned["BTCUSDT"]
    s3 = run_directional(btc, TrendFollow(allow_short=False, **S3), initial_capital=CAPITAL,
                         taker_fee=F, slippage=S, periods_per_year=365.0,
                         vol_target=0.02, max_leverage=2.0, rebalance_band=0.25).equity_curve
    s3_t, s3_sh, s3_dd = _stats(s3)
    print(f"  {'--':6} {'S3-BTC':10} {1:>5} {s3_t:>8.1%} {s3_sh:>7.2f} {s3_dd:>8.1%}  (baseline a)")

    rows = {}
    for tier, syms in TIERS.items():
        aligned, ts = _load_aligned(syms, span)
        for lev_name, sizing in SIZINGS.items():
            res = run_trend_portfolio(aligned, weighting="inverse_vol", master_gate_sym="BTCUSDT",
                                      master_gate_sma=200, initial_capital=CAPITAL,
                                      taker_fee=F, slippage=S, periods_per_year=365.0, **S3, **sizing)
            t, sh, dd = _stats(res.equity_curve)
            rows[(tier, lev_name)] = (t, sh, dd, len(aligned))
            print(f"  {tier:6} {lev_name:10} {len(aligned):>5} {t:>8.1%} {sh:>7.2f} {dd:>8.1%}")

    print("\n  read: cost of shrinking 14->7->5->4 coins, and cost of spot-only (1x) vs 2x.")
    print(f"  baselines to beat (§19.4): S3-BTC Sharpe {s3_sh:.2f}/maxDD {s3_dd:.1%}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
