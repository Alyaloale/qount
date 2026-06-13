#!/usr/bin/env python3
"""X4 S6-XMOM: cross-sectional altcoin momentum rotation (docs/crypto-x4-plan.md §16).

线 D (X4). Owner roadmap item: in a crypto bull, capital rotates -> rank a liquid alt universe by
vol-adjusted momentum and hold the top-K above their SMA200. Kill question: does cross-sectional
*selection* beat simply (a) holding BTC, (b) equal-weight holding the whole universe, and (c) the
single-asset trend (S3) -- after turnover fees and the violent alt tails (线 C breadth lesson)?

Run on Mac (needs network: um 1d klines for the universe):
    .venv/bin/python scripts/research/x4_xmom.py 2021-01 2026-05
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.grid.data import load_klines, Bar  # noqa: E402
from qount.x4.backtest import run_cross_sectional, run_directional, max_drawdown  # noqa: E402
from qount.x4.strategies import TrendFollow  # noqa: E402
from qount.x4.portfolio import sharpe_of  # noqa: E402

CAPITAL = 100_000.0
F, S = 0.0005, 0.0002
UNIVERSE = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "SOLUSDT", "DOTUSDT",
            "LINKUSDT", "LTCUSDT", "BCHUSDT", "AVAXUSDT", "ATOMUSDT", "ETCUSDT", "TRXUSDT"]


def main(argv: list[str]) -> int:
    start = argv[1] if len(argv) > 1 else "2021-01"
    end = argv[2] if len(argv) > 2 else "2026-05"
    sy, sm = (int(x) for x in start.split("-"))
    ey, em = (int(x) for x in end.split("-"))

    print(f"[S6-XMOM] cross-sectional momentum {start}..{end} (1d), universe={len(UNIVERSE)} syms")
    by_sym: dict[str, dict[int, Bar]] = {}
    for sym in UNIVERSE:
        bars = load_klines(sym, "1d", start=(sy, sm), end=(ey, em), market="um", skip_missing=True)
        if len(bars) > 300:
            by_sym[sym] = {b.ts_ms: b for b in bars}
    if "BTCUSDT" not in by_sym:
        print("  no BTC data"); return 2
    common = set.intersection(*(set(d) for d in by_sym.values()))
    ts = sorted(common)
    aligned = {s: [by_sym[s][t] for t in ts] for s in by_sym}
    print(f"  loaded {len(aligned)} syms; common aligned bars: {len(ts)} "
          f"({aligned['BTCUSDT'][0].date}..{aligned['BTCUSDT'][-1].date})")

    def stats(curve):
        return curve[-1] / CAPITAL - 1.0, sharpe_of(curve, periods_per_year=365.0), max_drawdown(curve)

    # baselines
    btc = aligned["BTCUSDT"]
    bh = [CAPITAL * btc[i].close / btc[0].close for i in range(len(btc))]
    ew = [CAPITAL]
    for i in range(1, len(ts)):
        r = sum(aligned[s][i].close / aligned[s][i - 1].close - 1.0 for s in aligned) / len(aligned)
        ew.append(ew[-1] * (1.0 + r))
    s3 = run_directional(btc, TrendFollow(fast=20, slow=100, allow_short=False, regime_sma=200),
                         initial_capital=CAPITAL, taker_fee=F, slippage=S, rebalance_band=0.25,
                         vol_target=0.03, max_leverage=2.0, periods_per_year=365.0).equity_curve

    print(f"\n  {'strategy':22} {'total':>9} {'Sharpe':>7} {'maxDD':>8}")
    for nm, c in [("BTC buy&hold", bh), ("universe equal-wt hold", ew), ("S3 BTC trend", s3)]:
        t, sh, dd = stats(c)
        print(f"  {nm:22} {t:>+8.1%} {sh:>7.2f} {dd:>7.1%}")

    print("\n  === S6-XMOM cross-sectional (sweep top_k / lookback / rebalance) ===")
    best = None
    for lb in (20, 30, 60):
        for tk in (1, 3, 5):
            for rb in (7, 14):
                r = run_cross_sectional(aligned, lookback=lb, top_k=tk, regime_sma=200,
                                        rebalance_days=rb, initial_capital=CAPITAL,
                                        taker_fee=F, slippage=S, periods_per_year=365.0)
                t, sh, dd = stats(r.equity_curve)
                tag = f"lb{lb}/top{tk}/rb{rb}"
                print(f"  {tag:22} {t:>+8.1%} {sh:>7.2f} {dd:>7.1%}  (rebal {r.extra['rebalances']}, fees ${r.fees_paid:,.0f})")
                if best is None or sh > best[1]:
                    best = (tag, sh, t, dd)
    print(f"\n  BEST by Sharpe: {best[0]} -> Sharpe {best[1]:.2f}, total {best[2]:+.1%}, maxDD {best[3]:.1%}")
    print("  KILL CHECK: does the best XMOM beat S3 BTC-trend Sharpe? If not, cross-sectional"
          " selection adds no alpha over just trading BTC's trend.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
