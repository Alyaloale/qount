#!/usr/bin/env python3
"""X4 S5-VEL-G: does a three-state chop gate rescue the minute scalper? (docs/crypto-x4-plan.md §11 re-test).

线 D (X4), isolated. Owner observation: minute crypto has three regimes — chop / up / down — so add a
震荡因子 to *sit out chop* and only scalp the up-regime. The honest §11 verdict was: the impulse
signal is real but (a) its gross edge ≈ buy&hold (趋势暴露代理, not independent alpha) and (b) the
round-trip fee kills it — survivable only at maker (which a momentum-chaser can't get), dead at taker.

The ONLY lever a regime gate can pull is **cutting the round-trip count** (don't trade in chop). So
this runner pins, for a fixed scalper config, BARE vs GATED across the decisive friction decomposition
(frictionless / maker 1bp / taker 5bp+slip 2bp):
  * does the gate cut trips enough that MAKER clears comfortably (and beats bare's maker)?
  * does it EVER survive TAKER (expected: no — that's the §11 thesis)?
  * is the gated gross still just a buy&hold proxy (it should shrink toward fewer, cleaner trades)?

Run on Mac (needs network to data.binance.vision um 1m klines -- heavy, ~43k bars/month):
    .venv/bin/python scripts/research/x4_scalp_regime.py 2024-03 2024-03
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.research_data.market_data import load_klines  # noqa: E402
from qount.legacy.x4.backtest import run_scalper  # noqa: E402
from qount.legacy.x4.strategies import GatedVelocityScalper, VelocityScalper  # noqa: E402

CAPITAL = 100_000.0
BARS_PER_YEAR = 365.0 * 24.0 * 60.0  # 1m

# The decisive view (§11): same trade logic, three execution-cost buckets.
FRICTION = {
    "frictionless": (0.0, 0.0),
    "maker 1bp": (0.0001, 0.0),
    "taker+slip": (0.0005, 0.0002),
}

# Fix the §11 "slow" best scalper config (the only one that survived maker) so the ONLY thing changing
# is the regime gate. Sweep the gate's chop threshold + window to see how hard it cuts the trip count.
SCALP = dict(vel_window=20, accel_lag=10, vel_threshold=0.001)
TP, SL = 0.010, 0.005
GATES = [
    ("bare", None),
    ("er30/0.30", (30, 0.30)),
    ("er30/0.40", (30, 0.40)),
    ("er60/0.40", (60, 0.40)),
    ("er60/0.50", (60, 0.50)),
]


def main(argv: list[str]) -> int:
    start = argv[1] if len(argv) > 1 else "2024-03"
    end = argv[2] if len(argv) > 2 else start
    sym = argv[3] if len(argv) > 3 else "BTCUSDT"
    sy, sm = (int(x) for x in start.split("-"))
    ey, em = (int(x) for x in end.split("-"))

    print(f"[S5-VEL-G] {sym} 1m {start}..{end}; ${CAPITAL:,.0f}; scalp={SCALP} tp={TP}/sl={SL}")
    bars = load_klines(sym, "1m", start=(sy, sm), end=(ey, em), market="um", skip_missing=True)
    if len(bars) < 100:
        print(f"  too few 1m bars ({len(bars)})")
        return 2
    bh = bars[-1].close / bars[0].close - 1.0
    print(f"  bars: {len(bars)} ({bars[0].date}..{bars[-1].date}); buy&hold over window: {bh:+.2%}\n")

    hdr = f"  {'gate':>10} {'trips':>6} {'win%':>6}"
    for fname in FRICTION:
        hdr += f" | {fname:>14}"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))

    rows = []
    for label, gate in GATES:
        # build the strategy once per gate (stateful) but we need a fresh instance per friction run
        trips = None
        cells = []
        win = 0.0
        for fname, (fee, slip) in FRICTION.items():
            if gate is None:
                s = VelocityScalper(**SCALP)
            else:
                s = GatedVelocityScalper(**SCALP, er_window=gate[0], er_threshold=gate[1])
            r = run_scalper(bars, s, initial_capital=CAPITAL, taker_fee=fee, slippage=slip,
                            tp=TP, sl=SL, periods_per_year=BARS_PER_YEAR)
            trips = r.extra["round_trips"]
            win = r.extra["win_rate"]
            cells.append(f"{r.total_return:>+8.2%}({r.fees_paid / CAPITAL:>4.0%})")
        line = f"  {label:>10} {trips:>6d} {win:>5.1%}"
        for c in cells:
            line += f" | {c:>14}"
        print(line)
        rows.append((label, trips))

    print("\n  cells = total_return(fees% of capital). Thesis (§11): the chop gate should CUT trips,")
    print("  lift maker, but TAKER stays negative — minute scalping is not realizable for a retail taker.")
    bare_trips = next((t for l, t in rows if l == "bare"), None)
    if bare_trips:
        best_cut = min((t for l, t in rows if l != "bare"), default=bare_trips)
        print(f"  trip cut: bare {bare_trips} -> gated min {best_cut} "
              f"({(1 - best_cut / bare_trips):.0%} fewer round-trips).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
