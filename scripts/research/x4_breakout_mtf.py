#!/usr/bin/env python3
"""X4: 15m consolidation-breakout filtered by a higher-timeframe trend — does multi-TF alignment work? (§11.4).

线 D (X4), isolated. Owner's refined idea: detect the chop/consolidation range, trade the BREAKOUT when
price *leaves* the consolidation (脱离震荡) at the minute/15m level (catch it early), and only take
breakouts that AGREE with the hourly-level trend (multi-timeframe confirmation to filter false breakouts).

This maps exactly onto MomentumBreakout (S4): a Donchian breakout = price leaving the prior-``lookback``
range; ``regime_sma`` = the higher-TF trend gate (no long below it = "符合小时级别趋势"); long-only;
position runs until the opposite break. On 15m bars 1 hour = 4 bars, so regime_sma ∈ {16, 48, 96} ≈
{4h, 12h, 24h} trend filters of increasing strictness. Question: does the higher-TF filter rescue 15m
breakouts (§9 had 1h S4 = −98% from false breakouts), and does ANY version beat the 59-trade daily
baseline (~+68%)? If the best filtered 15m merely ties daily with 100× the trades, the minute edge is
not realizable — false-breakout + fee grind dominates regardless of the filter.

Run on Mac (15m data, ~2.9k bars/month, monthly-cached):
    .venv/bin/python scripts/research/x4_breakout_mtf.py 2021-01 2026-05
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.grid.data import load_klines  # noqa: E402
from qount.x4.backtest import run_directional  # noqa: E402
from qount.x4.strategies import MomentumBreakout  # noqa: E402

CAPITAL = 100_000.0
TAKER_FEE = 0.0005
SLIPPAGE = 0.0002
VOL_TARGET = 0.02
LOOKBACK = 20          # the consolidation channel (breakout = leaving the prior-20-bar range)
SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
# (label, interval, bars/year, regime_sma options). On 15m: 16≈4h, 48≈12h, 96≈24h. Daily baseline = ref.
GRID_15M = [("none", 0), ("4h", 16), ("12h", 48), ("24h", 96)]
PPY_15M = 365.0 * 24.0 * 4.0
PPY_1D = 365.0


def _run(bars, regime_sma, ppy):
    s = MomentumBreakout(lookback=LOOKBACK, allow_short=False, regime_sma=regime_sma)
    r = run_directional(bars, s, initial_capital=CAPITAL, taker_fee=TAKER_FEE, slippage=SLIPPAGE,
                        vol_target=VOL_TARGET, max_leverage=1.0, periods_per_year=ppy)
    return r


def main(argv: list[str]) -> int:
    start = argv[1] if len(argv) > 1 else "2021-01"
    end = argv[2] if len(argv) > 2 else "2026-05"
    sy, sm = (int(x) for x in start.split("-"))
    ey, em = (int(x) for x in end.split("-"))

    print(f"[BREAKOUT-MTF] long-only Donchian(lookback{LOOKBACK}) + higher-TF gate, vol-parity vt"
          f"={VOL_TARGET:.0%}, taker {TAKER_FEE:.2%}+slip {SLIPPAGE:.2%}; {start}..{end}")
    print("  脱离震荡=Donchian break; 符合小时趋势=regime_sma gate. Does multi-TF filter beat daily baseline?\n")

    print(f"  {'sym':>8} {'tf':>5} {'1h-gate':>8} {'total':>9} {'Sharpe':>7} {'maxDD':>7} {'trades':>7}")
    print("  " + "-" * 60)
    for sym in SYMS:
        # daily baseline (the known winner), no intraday gate needed
        bd = load_klines(sym, "1d", start=(sy, sm), end=(ey, em), market="um", skip_missing=True)
        if len(bd) >= LOOKBACK + 10:
            r = _run(bd, 100, PPY_1D)  # daily breakout + 100d regime gate (= §10.1 winner shape)
            print(f"  {sym:>8} {'1d':>5} {'200d~':>8} {r.total_return:>+8.1%} {r.sharpe:>7.2f} "
                  f"{r.max_drawdown:>+6.1%} {r.trade_count:>7d}  <-- daily baseline")
        # 15m breakout, sweeping the higher-TF confirmation strength
        b15 = load_klines(sym, "15m", start=(sy, sm), end=(ey, em), market="um", skip_missing=True)
        if len(b15) < 200:
            print(f"  {sym:>8} {'15m':>5}  too few bars ({len(b15)})")
            continue
        for glabel, rsma in GRID_15M:
            r = _run(b15, rsma, PPY_15M)
            print(f"  {sym:>8} {'15m':>5} {glabel:>8} {r.total_return:>+8.1%} {r.sharpe:>7.2f} "
                  f"{r.max_drawdown:>+6.1%} {r.trade_count:>7d}")
        print()

    print("  Read: if the best multi-TF-filtered 15m breakout fails to beat the daily baseline's Sharpe")
    print("  (and carries 100× the trades / deeper DD), the minute breakout edge is eaten by false")
    print("  breakouts + fees — the higher-TF filter helps but can't make intraday breakouts realizable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
