#!/usr/bin/env python3
"""X4: with a ROBUST regime classifier, does shorting confirmed downtrends pay in crypto? (§11.3).

线 D (X4), isolated. Owner's refined point (not flip-on-every-cross): use a high-conviction 评价因子 to
first DECIDE the dominant regime (up vs down), then hold WITH it — long in a confirmed uptrend, short in
a confirmed downtrend — changing direction only on a real regime shift, not noise.

§11.2 already showed a fast (20/100) classifier whipsaws (24k-98k trades). This isolates the remaining
question cleanly: take a SLOW, robust classifier that flips only a handful of times in 5 years (the
golden/death cross 50/200 = the truest "确定上升还是下降趋势"), on DAILY bars (the timeframe that works),
with per-coin vol-parity (the 动态阈值). Then compare long-only vs long+short, and read the **short leg's
net contribution = (long+short) − (long-only)** directly. If even a robust classifier's short leg bleeds,
the verdict "don't short structurally-rising crypto" holds independent of classifier quality (because
crypto downtrends V-reverse / short-squeeze, not the classifier being wrong).

Run on Mac (daily data, light; cached from §11.2):
    .venv/bin/python scripts/research/x4_regime_short.py 2021-01 2026-05
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
VOL_TARGET = 0.02   # per-coin vol-parity = the owner's "逐币动态阈值结合波动"
MAX_LEV = 1.0
SYMS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]
# Robust regime classifiers: how few flips = how high-conviction the up/down call is.
CLASSIFIERS = [("fast 20/100", 20, 100), ("robust 50/200", 50, 200)]
PPY = 365.0


def main(argv: list[str]) -> int:
    start = argv[1] if len(argv) > 1 else "2021-01"
    end = argv[2] if len(argv) > 2 else "2026-05"
    sy, sm = (int(x) for x in start.split("-"))
    ey, em = (int(x) for x in end.split("-"))

    print(f"[REGIME-SHORT] daily, 1x vol-parity(vt={VOL_TARGET:.0%}), taker {TAKER_FEE:.2%}+slip "
          f"{SLIPPAGE:.2%}, ${CAPITAL:,.0f}; {start}..{end}")
    print("  Q: with a robust up/down 评价因子, does the SHORT leg add or bleed? (Δ = long+short − long-only)\n")

    print(f"  {'sym':>8} {'classifier':>14} {'long-only':>10} {'long+short':>11} {'shortΔ':>8} "
          f"{'L-trades':>9} {'LS-trades':>10}")
    print("  " + "-" * 76)
    for sym in SYMS:
        bars = load_klines(sym, "1d", start=(sy, sm), end=(ey, em), market="um", skip_missing=True)
        if len(bars) < 220:
            print(f"  {sym:>8}  too few daily bars ({len(bars)})")
            continue
        for label, fast, slow in CLASSIFIERS:
            res = {}
            trd = {}
            for dir_label, allow_short in [("lo", False), ("ls", True)]:
                s = TrendFollow(fast=fast, slow=slow, allow_short=allow_short)
                r = run_directional(bars, s, initial_capital=CAPITAL, taker_fee=TAKER_FEE,
                                    slippage=SLIPPAGE, vol_target=VOL_TARGET, max_leverage=MAX_LEV,
                                    periods_per_year=PPY)
                res[dir_label] = r.total_return
                trd[dir_label] = r.trade_count
            delta = res["ls"] - res["lo"]
            flag = "  <-- short HELPS" if delta > 0 else ""
            print(f"  {sym:>8} {label:>14} {res['lo']:>+9.1%} {res['ls']:>+10.1%} {delta:>+7.1%} "
                  f"{trd['lo']:>9d} {trd['ls']:>10d}{flag}")
        print()

    print("  Read: 'shortΔ' is what the short leg adds on top of long-only. A robust 50/200 classifier")
    print("  flips only a few times in 5y (high-conviction up/down call). If shortΔ is still negative")
    print("  there, then shorting confirmed crypto downtrends bleeds regardless of classifier quality")
    print("  (downtrends V-reverse / short-squeeze) — the §10 long-bias fix is structural, not a tuning miss.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
