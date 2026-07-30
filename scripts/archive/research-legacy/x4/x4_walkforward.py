#!/usr/bin/env python3
"""X4 walk-forward / out-of-sample validation (docs/crypto-x4-plan.md §17).

The whole §9-§16 optimization arc selected params on the FULL 2021-26 window -> in-sample. This is
the integrity check. Three parts:
  A. Fixed *current* params, measured separately on TRAIN (2021-23) vs TEST (2024-26): is the edge in
     both halves or concentrated? (Strategies run on the full series for warm-up; only the date-slice
     of the equity curve is measured -- causal, no look-ahead, no warm-up bias.)
  B. True walk-forward: sweep a param grid, pick the best by TRAIN Sharpe, then read its TEST Sharpe.
     Compare to the hindsight test-best. If train-pick ~ test-best -> robust; if far below -> overfit.
  C. Generalization: run the BTC-selected S3/S4 params on ETH. Does the trend edge transfer?

Run on Mac (needs network: um 1d klines):
    .venv/bin/python scripts/research/x4_walkforward.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.research_data.market_data import load_klines, load_funding  # noqa: E402
from qount.legacy.x4.backtest import run_directional, run_grid, run_pair, max_drawdown  # noqa: E402
from qount.legacy.x4.strategies import GridStrategy, PairStrategy, TrendFollow, MomentumBreakout  # noqa: E402
from qount.legacy.x4.portfolio import combine, sharpe_of  # noqa: E402

C, F, S = 100_000.0, 0.0005, 0.0002
TRAIN_END = "2023-12-31"
TEST_START = "2024-01-01"


def _seg(curve, bars, start, end):
    lo = next((i for i, b in enumerate(bars) if b.date >= start), 0)
    hi = max((i for i, b in enumerate(bars) if b.date <= end), default=len(bars) - 1)
    s = curve[lo:hi + 1]
    if len(s) < 3 or s[0] <= 0:
        return 0.0, 0.0, 0.0
    return s[-1] / s[0] - 1.0, sharpe_of(s, periods_per_year=365.0), max_drawdown(s)


def _load(sym, sy=2021, sm=1, ey=2026, em=5):
    return load_klines(sym, "1d", start=(sy, sm), end=(ey, em), market="um", skip_missing=True)


def main(argv: list[str]) -> int:
    btc = _load("BTCUSDT")
    eth_raw = _load("ETHUSDT")
    eby = {b.ts_ms: b for b in eth_raw}
    btc = [b for b in btc if b.ts_ms in eby]
    eth = [eby[b.ts_ms] for b in btc]
    fmap = {f.ts_ms: f.rate for f in load_funding("BTCUSDT", start=(2021, 1), end=(2026, 5), skip_missing=True)}
    fund = lambda b: fmap.get(b.ts_ms, 0.0)  # noqa: E731
    print(f"bars {len(btc)} ({btc[0].date}..{btc[-1].date}); train<= {TRAIN_END}, test>= {TEST_START}")

    def s3(bars, fast=20, slow=100, vt=0.03):
        return run_directional(bars, TrendFollow(fast=fast, slow=slow, allow_short=False, regime_sma=200),
                               initial_capital=C, taker_fee=F, slippage=S, funding=fund,
                               rebalance_band=0.25, vol_target=vt, max_leverage=2.0, periods_per_year=365.0)

    def s4(bars, ch=4.0):
        return run_directional(bars, MomentumBreakout(lookback=20, exit_lookback=10, vol_mult=1.0,
                               allow_short=False, regime_sma=200), initial_capital=C, taker_fee=F, slippage=S,
                               funding=fund, rebalance_band=0.25, vol_target=0.03, max_leverage=2.0,
                               chandelier_mult=ch, chandelier_lookback=22, periods_per_year=365.0)

    s1c = run_grid(btc, GridStrategy(), initial_capital=C, taker_fee=F, slippage=S, atr_mult=5.0,
                   periods_per_year=365.0).equity_curve
    s2c = run_pair(btc, eth, PairStrategy(window=60, entry_z=2.5, exit_z=0.5, stop_z=3.0),
                   initial_capital=C, taker_fee=F, slippage=S, periods_per_year=365.0).equity_curve
    s3c, s4c = s3(btc).equity_curve, s4(btc).equity_curve

    # ---- Part A: current params, train vs test ----
    print("\n=== A. current params: TRAIN(21-23) vs TEST(24-26) [total / Sharpe / maxDD] ===")
    print(f"  {'strat':18}{'TRAIN':>26}{'TEST':>26}")
    curves = {"S1-GRID": s1c, "S2-PAIR": s2c, "S3-CTA": s3c, "S4-MOM": s4c}
    for nm, c in curves.items():
        tr = _seg(c, btc, "2021-01-01", TRAIN_END)
        te = _seg(c, btc, TEST_START, "2026-12-31")
        print(f"  {nm:18}{tr[0]:>+8.1%}/{tr[1]:>5.2f}/{tr[2]:>6.1%}   {te[0]:>+8.1%}/{te[1]:>5.2f}/{te[2]:>6.1%}")
    port = combine({"S1": s1c, "S3": s3c, "S4": s4c}, scheme="equal", initial_capital=C)
    trp, tep = _seg(port, btc, "2021-01-01", TRAIN_END), _seg(port, btc, TEST_START, "2026-12-31")
    print(f"  {'S1+S3+S4 eq':18}{trp[0]:>+8.1%}/{trp[1]:>5.2f}/{trp[2]:>6.1%}   {tep[0]:>+8.1%}/{tep[1]:>5.2f}/{tep[2]:>6.1%}")

    # ---- Part B: walk-forward param selection (S3 + S2, the flagship and the suspect) ----
    print("\n=== B. walk-forward: pick by TRAIN Sharpe, read TEST Sharpe (overfit check) ===")
    s3grid = [(f, sl, vt) for f in (10, 20, 30) for sl in (80, 100, 150) for vt in (0.02, 0.03, 0.04)]
    rows = []
    for f, sl, vt in s3grid:
        cc = s3(btc, fast=f, slow=sl, vt=vt).equity_curve
        rows.append(((f, sl, vt), _seg(cc, btc, "2021-01-01", TRAIN_END)[1], _seg(cc, btc, TEST_START, "2026-12-31")[1]))
    train_pick = max(rows, key=lambda r: r[1])
    test_best = max(rows, key=lambda r: r[2])
    print(f"  S3: TRAIN-best param {train_pick[0]} -> train Sharpe {train_pick[1]:.2f}, TEST Sharpe {train_pick[2]:.2f}")
    print(f"      (hindsight TEST-best {test_best[0]} -> TEST Sharpe {test_best[2]:.2f}; gap = overfit cost)")

    s2grid = [(w, ez, sz) for w in (30, 60, 90) for ez in (2.0, 2.5) for sz in (0.0, 3.0)]
    rows2 = []
    for w, ez, sz in s2grid:
        cc = run_pair(btc, eth, PairStrategy(window=w, entry_z=ez, exit_z=0.5, stop_z=sz),
                      initial_capital=C, taker_fee=F, slippage=S, periods_per_year=365.0).equity_curve
        rows2.append(((w, ez, sz), _seg(cc, btc, "2021-01-01", TRAIN_END)[1], _seg(cc, btc, TEST_START, "2026-12-31")[1]))
    tp2, tb2 = max(rows2, key=lambda r: r[1]), max(rows2, key=lambda r: r[2])
    print(f"  S2: TRAIN-best param {tp2[0]} -> train Sharpe {tp2[1]:.2f}, TEST Sharpe {tp2[2]:.2f}")
    print(f"      (hindsight TEST-best {tb2[0]} -> TEST Sharpe {tb2[2]:.2f})")

    # ---- Part C: ETH generalization (BTC-selected params) ----
    print("\n=== C. generalization: BTC-selected S3/S4 params on ETH ===")
    feth = lambda b: 0.0  # noqa: E731 (skip funding for ETH; minor)
    def s3_eth():
        return run_directional(eth, TrendFollow(fast=20, slow=100, allow_short=False, regime_sma=200),
                               initial_capital=C, taker_fee=F, slippage=S, rebalance_band=0.25,
                               vol_target=0.03, max_leverage=2.0, periods_per_year=365.0)
    def s4_eth():
        return run_directional(eth, MomentumBreakout(lookback=20, exit_lookback=10, vol_mult=1.0,
                               allow_short=False, regime_sma=200), initial_capital=C, taker_fee=F, slippage=S,
                               rebalance_band=0.25, vol_target=0.03, max_leverage=2.0, chandelier_mult=4.0,
                               chandelier_lookback=22, periods_per_year=365.0)
    for nm, r in [("S3 on BTC", s3(btc)), ("S3 on ETH", s3_eth()), ("S4 on BTC", s4(btc)), ("S4 on ETH", s4_eth())]:
        full = _seg(r.equity_curve, btc if "BTC" in nm else eth, "2021-01-01", "2026-12-31")
        print(f"  {nm:12} total={full[0]:>+8.1%} Sharpe={full[1]:>5.2f} maxDD={full[2]:>6.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
