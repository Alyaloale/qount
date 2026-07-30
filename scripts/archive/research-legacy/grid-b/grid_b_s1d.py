#!/usr/bin/env python3
"""GRID-B S1d: hindsight regime-slice attribution (v0.3 §1).

线 B (GRID-B). Reuses the S1 harness (same grid spec, same data) but additionally
labels each calendar month by its hindsight 91-day return/volatility (chop / trend /
down / other) and reports the compounded-annualized Δ(grid-hold) within each bucket.
This is the cheapest possible existence check for H1 (a time-dimension "chop home
turf" where a regime-aware hybrid construction could plausibly beat hold-above-200MA).

Pre-registered verdict (v0.3 §1, do not change after seeing the number):
    chop bucket annualized Δ(grid-hold) >= +2%  -> H1 alive, S1e justified
    chop bucket annualized Δ(grid-hold) <= 0    -> H1 dead, S1e cancelled
    in between (0 < Δ < 2%)                     -> too thin, treat as dead

Run on Mac:
    .venv/bin/python scripts/research/grid_b_s1d.py
"""
from __future__ import annotations

import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.legacy.grid_b.backtest import regime_slices, run_s1  # noqa: E402
from qount.research_data.market_data import load_klines  # noqa: E402

ARTIFACT_DIR = REPO / "state" / "grid_b" / "research_runs"

SYMBOL = "BTCUSDT"
START = "2021-01"
END = "2026-05"
STEP = 0.01
CONFIRM_BARS = 2


def main() -> int:
    sy, sm = (int(x) for x in START.split("-"))
    ey, em = (int(x) for x in END.split("-"))
    dsy, dsm = (sy - 1, sm) if sm <= 6 else (sy, 1)

    print(f"[grid-b S1d] {SYMBOL} hourly {START}..{END}, step={STEP:.3%} "
          f"-- regime-slice attribution")
    daily = load_klines(SYMBOL, "1d", start=(dsy, dsm), end=(ey, em), skip_missing=True)
    hourly = load_klines(SYMBOL, "1h", start=(sy, sm), end=(ey, em), skip_missing=True)
    print(f"  daily bars: {len(daily)} ({daily[0].date}..{daily[-1].date})")
    print(f"  hourly bars: {len(hourly)} ({hourly[0].date}..{hourly[-1].date})")

    res = run_s1(hourly, daily, step=STEP, confirm_bars=CONFIRM_BARS)
    slices = regime_slices(hourly, daily, res.grid_curve, res.hold_curve)

    print("\n=== S1d regime-slice attribution (hindsight labels) ===")
    print("  month     regime   r91      ann_vol   grid     hold     Δ(grid-hold)")
    for m in slices.months:
        print(f"  {m.month}  {m.regime:<6}  {m.r91:+7.1%}  {m.annualized_vol:7.1%}  "
              f"{m.grid_return:+7.2%}  {m.hold_return:+7.2%}  {m.grid_minus_hold:+7.2%}")

    print("\n  bucket summary:")
    for regime in ("chop", "trend", "down", "other"):
        bucket = slices.bucket(regime)
        delta = slices.annualized_delta(regime)
        delta_s = f"{delta:+.2%}" if delta is not None else "n/a"
        print(f"    {regime:<6} n_months={len(bucket):3d}  annualized Δ(grid-hold) = {delta_s}")

    chop_delta = slices.annualized_delta("chop")
    print("\n=== H1 verdict (v0.3 §1 pre-registered) ===")
    if chop_delta is None:
        verdict = "H1 死(chop 桶为空,无法判定;视为死)"
    elif chop_delta >= 0.02:
        verdict = f"H1 活:chop 桶 Δ {chop_delta:+.2%}/yr >= +2% -> S1e 有意义"
    elif chop_delta <= 0.0:
        verdict = f"H1 死:chop 桶 Δ {chop_delta:+.2%}/yr <= 0 -> S1e 取消"
    else:
        verdict = f"H1 死(中间带):chop 桶 Δ {chop_delta:+.2%}/yr 在 (0, +2%) 之间,按死处理"
    print(f"  {verdict}")

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ARTIFACT_DIR / f"s1d_{SYMBOL}_{START}_{END}_step{STEP}_{stamp}.json"
    payload = {
        "symbol": SYMBOL, "start": START, "end": END, "step": STEP,
        "confirm_bars": CONFIRM_BARS,
        "months": [dataclasses.asdict(m) for m in slices.months],
        "bucket_summary": {
            regime: slices.annualized_delta(regime) for regime in ("chop", "trend", "down", "other")
        },
        "bucket_n_months": {
            regime: len(slices.bucket(regime)) for regime in ("chop", "trend", "down", "other")
        },
        "verdict": verdict,
    }
    out.write_text(json.dumps(payload, indent=2, default=float))
    print(f"\n  artifact: {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
