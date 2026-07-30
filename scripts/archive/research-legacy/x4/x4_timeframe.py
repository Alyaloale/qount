#!/usr/bin/env python3
"""X4: does an intraday (15m/1h) trend with long+short beat the daily long-only? (docs/crypto-x4-plan.md §11.2).

线 D (X4), isolated. Owner's refined idea: read the trend on a higher intraday timeframe (1h or 15m),
go LONG or SHORT accordingly, flip/flat the moment the trend turns ("见好就收"), per-coin vol-scaled.
This re-tests the two LOAD-BEARING variables of that idea against §9/§10's finding (the killers were
the 1h timeframe = noise whipsaw, and allowing SHORT on a structurally-rising asset):

  TrendFollow (the S3 crossover — already flips on a trend change = the "见好就收" exit) is run across
  {1d, 1h, 15m} × {long-only, long+short}, everything else fixed (1x, same fast/slow, same fees), so the
  ONLY things changing are timeframe and direction. Per §9→§10 the answer was: daily + long-only wins,
  1h + short loses. This pins it on BTC+ETH with fresh numbers on the owner's exact timeframes.

Run on Mac (needs network to data.binance.vision; 15m over 5y is ~2.9k bars/month, monthly-cached):
    .venv/bin/python scripts/research/x4_timeframe.py 2021-01 2026-05
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.research_data.market_data import load_klines  # noqa: E402
from qount.legacy.x4.backtest import run_directional  # noqa: E402
from qount.legacy.x4.strategies import TrendFollow  # noqa: E402

CAPITAL = 100_000.0
TAKER_FEE = 0.0005
SLIPPAGE = 0.0002
FAST, SLOW = 20, 100
SYMS = ["BTCUSDT", "ETHUSDT"]
# (interval, bars-per-year for Sharpe annualization)
TFS = [("1d", 365.0), ("1h", 365.0 * 24.0), ("15m", 365.0 * 24.0 * 4.0)]


def main(argv: list[str]) -> int:
    start = argv[1] if len(argv) > 1 else "2021-01"
    end = argv[2] if len(argv) > 2 else "2026-05"
    sy, sm = (int(x) for x in start.split("-"))
    ey, em = (int(x) for x in end.split("-"))

    print(f"[TF×DIR] S3-trend (fast{FAST}/slow{SLOW}), 1x, taker {TAKER_FEE:.2%}+slip {SLIPPAGE:.2%}, "
          f"${CAPITAL:,.0f}; {start}..{end}")
    print("  '趋势变了平仓' = the crossover flips by construction; question is timeframe × direction.\n")

    print(f"  {'sym':>8} {'tf':>4} {'dir':>10} {'bars':>8} {'total':>9} {'CAGR':>7} {'Sharpe':>7} "
          f"{'maxDD':>7} {'trades':>7}")
    print("  " + "-" * 78)
    for sym in SYMS:
        for interval, ppy in TFS:
            bars = load_klines(sym, interval, start=(sy, sm), end=(ey, em), market="um",
                               skip_missing=True)
            if len(bars) < SLOW + 10:
                print(f"  {sym:>8} {interval:>4}  too few bars ({len(bars)})")
                continue
            for label, allow_short in [("long-only", False), ("long+short", True)]:
                s = TrendFollow(fast=FAST, slow=SLOW, allow_short=allow_short)
                r = run_directional(bars, s, initial_capital=CAPITAL, taker_fee=TAKER_FEE,
                                    slippage=SLIPPAGE, periods_per_year=ppy)
                cagr = (r.equity_curve[-1] / CAPITAL) ** (ppy / len(bars)) - 1.0
                print(f"  {sym:>8} {interval:>4} {label:>10} {len(bars):>8d} {r.total_return:>+8.1%} "
                      f"{cagr:>+6.1%} {r.sharpe:>7.2f} {r.max_drawdown:>+6.1%} {r.trade_count:>7d}")
        print()

    print("  Read: if intraday (1h/15m) and/or long+short underperform daily long-only, the owner's")
    print("  '15m/1h trend, both directions, 见好就收' frame is re-confirming §9/§10 — the killers are")
    print("  the intraday timeframe (noise whipsaw) and shorting a structurally-rising asset, NOT the")
    print("  exit rule. Per-coin vol-parity / range stops are refinements that can't flip a negative core.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
