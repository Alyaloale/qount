#!/usr/bin/env python3
"""Read-only forward横比: S7-TREND-PORT at vol_target=2% (deployed) vs 3% (盈利档).

Same universe / window / fees / gate as ``x4_paper.py forward-s7``; ONLY ``vol_target`` differs.
vol_target is a Sharpe-neutral SIZE dial (§23): raising it scales total return AND maxDD ~linearly
while leaving Sharpe ~flat. This script just prints the comparison -- it writes NO state files and
touches NO paper track. Pure simulation, no orders.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.grid.data import load_klines  # noqa: E402
from qount.x4.backtest import run_trend_portfolio  # noqa: E402

START = (2021, 1)
S7_UNIVERSE = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "SOLUSDT", "DOTUSDT",
               "LINKUSDT", "LTCUSDT", "BCHUSDT", "AVAXUSDT", "ATOMUSDT", "ETCUSDT", "TRXUSDT"]
BASE_CONFIG = dict(weighting="inverse_vol", master_gate_sym="BTCUSDT", master_gate_sma=200,
                   fast=20, slow=100, regime_sma=200, max_leverage=2.0,
                   rebalance_band=0.25, taker_fee=0.0005, slippage=0.0002, periods_per_year=365.0)
VOL_TARGETS = [0.02, 0.03]


def _load_universe(end_y: int, end_m: int):
    by_sym: dict[str, dict] = {}
    for sym in S7_UNIVERSE:
        bars = load_klines(sym, "1d", start=START, end=(end_y, end_m), market="um", skip_missing=True)
        if len(bars) > 300:
            by_sym[sym] = {b.ts_ms: b for b in bars}
    if "BTCUSDT" not in by_sym:
        return None
    common = sorted(set.intersection(*(set(d) for d in by_sym.values())))
    return {s: [by_sym[s][t] for t in common] for s in by_sym}


def main() -> int:
    now = dt.datetime.now(dt.UTC)
    aligned = _load_universe(now.year, now.month)
    if aligned is None or len(aligned["BTCUSDT"]) < 300:
        print("  too few bars"); return 2
    btc = aligned["BTCUSDT"]
    bc = [b.close for b in btc]
    sma200 = sum(bc[-200:]) / 200
    gate_open = bc[-1] > sma200

    print(f"[X4 vol_target 横比]  bar {btc[-1].date}  ({len(btc)} bars, {len(aligned)} syms)")
    print(f"  BTC 大盘闸: close {bc[-1]:,.0f} vs 200MA {sma200:,.0f} "
          f"= {bc[-1]/sma200-1:+.1%} -> {'OPEN(在场)' if gate_open else 'SHUT(全空仓)'}")
    print()
    print(f"  {'vol_target':>11} | {'total':>9} | {'Sharpe':>6} | {'maxDD':>7} | {'gate活跃':>7} | {'fees':>9}")
    print("  " + "-" * 64)
    rows = {}
    for vt in VOL_TARGETS:
        res = run_trend_portfolio(aligned, initial_capital=100_000.0, vol_target=vt, **BASE_CONFIG)
        rows[vt] = res
        print(f"  {vt:>10.0%} | {res.total_return:>+8.1%} | {res.sharpe:>6.2f} | "
              f"{res.max_drawdown:>+7.1%} | {res.extra['gate_active_frac']:>6.0%} | "
              f"${res.fees_paid:>8,.0f}")
    print()
    base, prof = rows[0.02], rows[0.03]
    print(f"  3% vs 2%:  收益 {base.total_return:+.1%} -> {prof.total_return:+.1%} "
          f"({prof.total_return - base.total_return:+.1%}pp)  |  "
          f"尾 {base.max_drawdown:+.1%} -> {prof.max_drawdown:+.1%} "
          f"({prof.max_drawdown - base.max_drawdown:+.1%}pp)  |  "
          f"Sharpe {base.sharpe:.2f} -> {prof.sharpe:.2f}")
    print("\n  注: in-sample 含 2021-26 牛市,头条收益被灌高;诚实前向 Sharpe 锚 ~0.70 (§17)。")
    print("  vol_target 是 Sharpe 中性的 size 旋钮:放大收益的同时等比放大回撤。")
    print("  READ-ONLY: 未写任何 state 文件、未碰 paper track、无真单。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
