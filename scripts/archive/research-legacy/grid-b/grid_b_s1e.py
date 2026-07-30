#!/usr/bin/env python3
"""GRID-B S1e: three-state hybrid construction kill-test (v0.5 §3-§4).

线 B (GRID-B). UPTREND holds (= hold-above-200MA leg), RANGE seeds an O-A0 grid (no
look-ahead [L,U] from trailing realized vol, ~half-position seed), BELOW is flat. Quoted
against the same hold-above-200MA baseline as S1/S1d (run_s1's hold leg, byte-identical
via the shared ``_hold_above_ma`` helper).

Pre-registered verdict (v0.5 §4, do not change after seeing the numbers; all three must
pass):
    (1) Δ(s1e - hold) > 0
    (2) >= 3/6 years grid_minus_hold > 0
    (3) switch_tax < range_harvest / 3

Run on Mac:
    .venv/bin/python scripts/research/grid_b_s1e.py
"""
from __future__ import annotations

import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.legacy.grid_b.backtest import run_s1e  # noqa: E402
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
    # need >= 200d SMA + 90d r90 + 30d sigma history before the window starts
    dsy, dsm = (sy - 1, sm) if sm <= 6 else (sy, 1)

    print(f"[grid-b S1e] {SYMBOL} hourly {START}..{END}, step={STEP:.3%} "
          f"-- three-state hybrid construction (S1e)")
    daily = load_klines(SYMBOL, "1d", start=(dsy, dsm), end=(ey, em), skip_missing=True)
    hourly = load_klines(SYMBOL, "1h", start=(sy, sm), end=(ey, em), skip_missing=True)
    print(f"  daily bars: {len(daily)} ({daily[0].date}..{daily[-1].date})")
    print(f"  hourly bars: {len(hourly)} ({hourly[0].date}..{hourly[-1].date})")

    res = run_s1e(hourly, daily, step=STEP, confirm_bars=CONFIRM_BARS)

    print(f"\n=== S1e result ===\n  {res.verdict}")
    print(f"  maxDD s1e {res.grid_max_drawdown:+.1%} / hold {res.hold_max_drawdown:+.1%}")
    print(f"  regime fractions: uptrend {res.regime_fractions['uptrend']:.1%} / "
          f"range {res.regime_fractions['range']:.1%} / below {res.regime_fractions['below']:.1%}")
    print(f"  whipsaw_cost (diagnostic): {res.whipsaw_cost:+.2%}")

    print("\n  per-year:  year   s1e       hold      Δ")
    won = 0
    for y in res.per_year:
        mark = ""
        if y.grid_minus_hold > 0:
            won += 1
            mark = "  (s1e wins)"
        print(f"             {y.year}  {y.grid_return:+7.2%}  {y.hold_return:+7.2%}  "
              f"{y.grid_minus_hold:+7.2%}{mark}")

    delta = res.grid_minus_hold
    crit1 = delta > 0
    crit2 = won >= 3
    crit3 = res.switch_tax < res.range_harvest / 3 if res.range_harvest > 0 else False

    print("\n=== S1e verdict (v0.5 §4 pre-registered) ===")
    print(f"  (1) Δ(s1e-hold) > 0:                {delta:+.2%}  -> {'PASS' if crit1 else 'FAIL'}")
    print(f"  (2) >= 3/6 years positive:          {won}/{len(res.per_year)}  "
          f"-> {'PASS' if crit2 else 'FAIL'}")
    tax_ratio = (res.switch_tax / res.range_harvest) if res.range_harvest > 0 else float("inf")
    print(f"  (3) switch_tax < range_harvest/3:   tax {res.switch_tax:.2%} / "
          f"harvest {res.range_harvest:.2%} (ratio {tax_ratio:.1%}) "
          f"-> {'PASS' if crit3 else 'FAIL'}")

    if crit1 and crit2 and crit3:
        verdict = "PASS: 三项全过 -> 进 §6 Track A 优化序列"
    elif crit1 and not (crit2 and crit3):
        verdict = "中间带: Δ>0 但 (2)/(3) 不满 -> 仅 O-A3 切换税重测一次(救援,一次不过即收口)"
    else:
        verdict = "FAIL: H1 关闭 -> §7 收口(H1/H2 双死)"
    print(f"\n  {verdict}")

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ARTIFACT_DIR / f"s1e_{SYMBOL}_{START}_{END}_step{STEP}_{stamp}.json"
    payload = {
        "symbol": SYMBOL, "start": START, "end": END, "step": STEP,
        "confirm_bars": CONFIRM_BARS,
        "grid_total_return": res.grid_total_return,
        "hold_total_return": res.hold_total_return,
        "grid_minus_hold": res.grid_minus_hold,
        "grid_max_drawdown": res.grid_max_drawdown,
        "hold_max_drawdown": res.hold_max_drawdown,
        "switch_count": res.switch_count,
        "switch_tax": res.switch_tax,
        "range_harvest": res.range_harvest,
        "whipsaw_cost": res.whipsaw_cost,
        "regime_fractions": res.regime_fractions,
        "per_year": [dataclasses.asdict(y) for y in res.per_year],
        "criteria": {
            "delta_positive": crit1,
            "won_years": won,
            "won_at_least_3of6": crit2,
            "switch_tax_under_third_of_harvest": crit3,
            "tax_over_harvest": None if tax_ratio == float("inf") else tax_ratio,
        },
        "verdict": verdict,
    }
    out.write_text(json.dumps(payload, indent=2, default=float))
    print(f"\n  artifact: {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
