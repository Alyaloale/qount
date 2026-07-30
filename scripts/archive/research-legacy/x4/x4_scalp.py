#!/usr/bin/env python3
"""X4 S5-VEL: minute-level velocity/acceleration impulse scalper kill-test (docs/crypto-x4-plan.md §11).

线 D (X4), isolated. Owner hypothesis: on 1m bars, catch an *accelerating* micro-trend (velocity =
1st derivative of price, acceleration = 2nd) and take profit fast ("见好就收"). Question: does the
burst clear the retail taker round-trip (taker 5bp + slip 2bp each leg)?

Sweeps a small TP/SL/threshold grid and reports, per config: total return, win rate, #round-trips,
fees as % of capital, and avg gross-vs-net per trade. Honest fee accounting (every fill charged).

Run on Mac (needs network to data.binance.vision um 1m klines -- heavy, ~43k bars/month):
    .venv/bin/python scripts/research/x4_scalp.py 2024-03 2024-03
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.research_data.market_data import load_klines  # noqa: E402
from qount.legacy.x4.backtest import run_scalper  # noqa: E402
from qount.legacy.x4.strategies import VelocityScalper  # noqa: E402

CAPITAL = 100_000.0
TAKER_FEE = 0.0005
SLIPPAGE = 0.0002
BARS_PER_YEAR = 365.0 * 24.0 * 60.0  # 1m


def main(argv: list[str]) -> int:
    start = argv[1] if len(argv) > 1 else "2024-03"
    end = argv[2] if len(argv) > 2 else start
    sym = argv[3] if len(argv) > 3 else "BTCUSDT"
    sy, sm = (int(x) for x in start.split("-"))
    ey, em = (int(x) for x in end.split("-"))

    print(f"[S5-VEL] {sym} 1m {start}..{end}; taker {TAKER_FEE:.2%}+slip {SLIPPAGE:.2%}, ${CAPITAL:,.0f}")
    bars = load_klines(sym, "1m", start=(sy, sm), end=(ey, em), market="um", skip_missing=True)
    if len(bars) < 100:
        print(f"  too few 1m bars ({len(bars)})")
        return 2
    bh = bars[-1].close / bars[0].close - 1.0
    print(f"  bars: {len(bars)} ({bars[0].date}..{bars[-1].date}); buy&hold over window: {bh:+.2%}")

    print(f"\n  {'vw/al':>6} {'thr':>6} {'tp/sl':>9} {'total':>8} {'win%':>6} {'trips':>7} "
          f"{'fees%':>7} {'avgNet/trip':>11}")
    grid = []
    for (vw, al) in [(5, 3), (10, 5), (20, 10)]:
        for thr in [0.0005, 0.001, 0.002]:
            for (tp, sl) in [(0.004, 0.002), (0.006, 0.003), (0.010, 0.005)]:
                s = VelocityScalper(vel_window=vw, accel_lag=al, vel_threshold=thr)
                r = run_scalper(bars, s, initial_capital=CAPITAL, taker_fee=TAKER_FEE,
                                slippage=SLIPPAGE, tp=tp, sl=sl, periods_per_year=BARS_PER_YEAR)
                trips = r.extra["round_trips"]
                avg_net = (r.equity_curve[-1] - CAPITAL) / trips if trips else 0.0
                grid.append((r.total_return, vw, al, thr, tp, sl, r.extra["win_rate"], trips,
                             r.fees_paid / CAPITAL, avg_net))
                print(f"  {vw:2d}/{al:<3d} {thr:>6.4f} {tp:.3f}/{sl:.3f} {r.total_return:>+7.2%} "
                      f"{r.extra['win_rate']:>5.1%} {trips:>7d} {r.fees_paid / CAPITAL:>6.1%} "
                      f"{avg_net:>+11.2f}")

    grid.sort(reverse=True)
    best = grid[0]
    pos = sum(1 for g in grid if g[0] > 0)
    print(f"\n  BEST total={best[0]:+.2%} (vw={best[1]}/al={best[2]} thr={best[3]} tp={best[4]}/sl={best[5]}"
          f" win={best[6]:.1%} trips={best[7]})")
    print(f"  positive configs: {pos}/{len(grid)}  (vs buy&hold {bh:+.2%})")
    print("\n  NOTE: a 1m scalper's enemy is the round-trip fee (taker+slip both legs). 'fees%' is the"
          " fee bill as % of capital; if it rivals/exceeds gross, the impulse edge is eaten -- the"
          " honest 线A-L6 / 线B lesson (real micro-signal, not realizable as a retail taker).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
