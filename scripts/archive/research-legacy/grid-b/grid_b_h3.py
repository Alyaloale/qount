#!/usr/bin/env python3
"""GRID-B H3: delta-neutral funding carry kill-test (docs/grid-binance-h3-plan.md).

线 B (GRID-B), 收口后授权的新假设. Strips the grid skin: a long-only grid is a degenerate
short-gamma position; delta-hedged with a perp short, harvest and rehedge cancel, leaving
funding carry as the only possible edge. Runs both configs on one symbol:

    H3-A (static): constant spot long + constant perp short -> the *true* carry baseline.
    H3-B (grid)  : spot grid, perp rehedges inventory to Δ=0 -> predicted < H3-A (洞1).

Pre-registered verdict (§4, do not change after seeing the number) -- H3-A is the gate:
    (1) annualized net > +2%
    (2) >= 4/6 (>=66%) tradeable years net-positive
    (3) tail survival: total net > 0 with ADL/basis tail included (modelled inline)
    All three -> carry alive; else -> grid family dead at its deepest layer -> 收口.

Point-in-time top-N universe selection is Increment 3; this script judges one symbol.

Run on Mac (needs network to data.binance.vision: spot + um klines + fundingRate):
    .venv/bin/python scripts/research/grid_b_h3.py DOGEUSDT 2021-01 2026-05
"""
from __future__ import annotations

import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.legacy.grid_b.backtest import run_h3  # noqa: E402
from qount.research_data.market_data import Bar, load_funding, load_klines  # noqa: E402

ARTIFACT_DIR = REPO / "state" / "grid_b" / "research_runs"
STEP = 0.01


def _align(spot: list[Bar], perp: list[Bar]) -> tuple[list[Bar], list[Bar]]:
    """Intersect spot and perp on open timestamp (perp histories start later than spot)."""
    perp_by_ts = {b.ts_ms: b for b in perp}
    s, p = [], []
    for b in spot:
        q = perp_by_ts.get(b.ts_ms)
        if q is not None:
            s.append(b)
            p.append(q)
    return s, p


def _annualized(net: float, n_hours: int) -> float:
    years = n_hours / (24.0 * 365.0)
    if years <= 0:
        return 0.0
    if 1.0 + net <= 0.0:   # total loss or worse: annualization undefined
        return -1.0
    return (1.0 + net) ** (1.0 / years) - 1.0


def main(argv: list[str]) -> int:
    symbol = argv[1] if len(argv) > 1 else "DOGEUSDT"
    start = argv[2] if len(argv) > 2 else "2021-01"
    end = argv[3] if len(argv) > 3 else "2026-05"
    sy, sm = (int(x) for x in start.split("-"))
    ey, em = (int(x) for x in end.split("-"))

    print(f"[grid-b H3] {symbol} {start}..{end} -- delta-neutral funding carry")
    spot = load_klines(symbol, "1h", start=(sy, sm), end=(ey, em), market="spot",
                       skip_missing=True)
    perp = load_klines(symbol, "1h", start=(sy, sm), end=(ey, em), market="um",
                       skip_missing=True)
    funding = load_funding(symbol, start=(sy, sm), end=(ey, em), skip_missing=True)
    spot, perp = _align(spot, perp)
    if not spot:
        print("  no overlapping spot/perp bars -- symbol may lack one leg on binance.vision")
        return 2
    print(f"  aligned bars: {len(spot)} ({spot[0].date}..{spot[-1].date}); "
          f"funding settlements: {len(funding)}")

    results = {}
    for mode in ("static", "grid"):
        kw = dict(lower=None, upper=None, step=STEP) if mode == "grid" else {}
        r = run_h3(spot, perp, funding, mode=mode, **kw)
        results[mode] = r
        ann = _annualized(r.net_return, r.n_hours)
        won = sum(1 for y in r.per_year if y.net_return > 0)
        print(f"\n=== H3-{'A' if mode == 'static' else 'B'} ({mode}) ===")
        print(f"  {r.verdict}")
        print(f"  net {r.net_return:+.2%} (annualized {ann:+.2%}); "
              f"net-positive years {won}/{len(r.per_year)}")
        print(f"  decomposition: harvest {r.harvest_pnl:+.2%} + spot_inv "
              f"{r.spot_inventory_pnl:+.2%} + perp_dir {r.perp_directional_pnl:+.2%} "
              f"+ funding {r.funding_pnl:+.2%} − fees {r.fee_cost:.2%}")
        print(f"  offset_residual {r.offset_residual:+.2%} (≈0 = hedge works); "
              f"maxDD {r.max_drawdown:.2%}; adl {r.adl_events}; "
              f"worst_basis {r.worst_basis:.1%}")

    a = results["static"]
    ann_a = _annualized(a.net_return, a.n_hours)
    won_a = sum(1 for y in a.per_year if y.net_return > 0)
    n_years = len(a.per_year)
    c1 = ann_a > 0.02
    c2 = n_years > 0 and won_a / n_years >= 0.66
    c3 = a.net_return > 0.0  # tail (ADL/basis) already in net
    passed = c1 and c2 and c3
    print("\n=== H3 verdict (§4 pre-registered; H3-A is the gate) ===")
    print(f"  (1) annualized net > +2%        : {'✓' if c1 else '✗'}  ({ann_a:+.2%})")
    print(f"  (2) >= 66% years net-positive   : {'✓' if c2 else '✗'}  ({won_a}/{n_years})")
    print(f"  (3) tail-survival net > 0       : {'✓' if c3 else '✗'}  ({a.net_return:+.2%})")
    if passed:
        b_lt_a = results["grid"].net_return < a.net_return
        verdict = (f"H3-A carry 活(三项全过);H3-B {'< A(网格减分,预期)' if b_lt_a else '>= A(意外,复查)'}"
                   f" → carry sleeve 成立,网格仍判死" if b_lt_a else
                   "H3-A carry 活;H3-B 意外不减分 → 复查")
    else:
        verdict = "H3-A 不过 → 网格族最深一层证伪(连 carry 都救不了)→ §6 收口"
    print(f"  → {verdict}")

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ARTIFACT_DIR / f"h3_{symbol}_{start}_{end}_step{STEP}_{stamp}.json"
    payload = {
        "symbol": symbol, "start": start, "end": end, "step": STEP,
        "n_aligned_bars": len(spot), "n_funding": len(funding),
        "criteria": {"c1_ann_gt_2pct": c1, "c2_years": c2, "c3_tail": c3, "passed": passed},
        "verdict": verdict,
        "results": {
            mode: {k: v for k, v in dataclasses.asdict(r).items() if k != "curve"}
            for mode, r in results.items()
        },
    }
    out.write_text(json.dumps(payload, indent=2, default=float))
    print(f"\n  artifact: {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
