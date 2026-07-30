#!/usr/bin/env python3
"""GRID-B H3 panel: point-in-time delta-neutral carry across a candidate universe.

线 B (GRID-B). The real §4 kill-test: rather than hand-pick one high-funding symbol, run
H3-A (static delta-neutral carry) on a *pre-registered candidate set*, select the universe
point-in-time each month by trailing 30d ADV (洞2: liquidity, never funding), and form an
equal-weight monthly-rebalanced portfolio. Dead names (LUNA) stay in the candidate set --
they drop out of selection once data ends, and their collapse month is carried by their own
delta-neutral run (does the perp short save the carry through a -99% crash? -- the honest
tail). Funding is observed, never selected on (洞2). LUNA tail = 洞6.

Pre-registered verdict (§4, do not change after seeing numbers) on the PORTFOLIO:
    (1) annualized net > +2%
    (2) >= 66% years net-positive
    (3) tail survival: total net > 0 with ADL/basis/collapse included (modelled inline)
    All three -> carry alive; else -> grid family dead at its deepest layer -> §6 收口.

Honest prior (§7): funding mania-positive but dump-period negative + basis + ADL highly
correlated -> expect the full window pulled back to ~0 or negative. A 2-month positive
window (§8.1) is NOT this test.

Run on Mac (heavy: downloads spot+um 1h + funding for the candidate set, full window):
    .venv/bin/python scripts/research/grid_b_h3_panel.py
"""
from __future__ import annotations

import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.legacy.grid_b.backtest import run_h3_carry  # noqa: E402
from qount.research_data.market_data import Bar, load_funding, load_klines  # noqa: E402
from qount.legacy.grid_b.universe import select_universe  # noqa: E402

ARTIFACT_DIR = REPO / "state" / "grid_b" / "research_runs"

# Pre-registered candidate set: liquid UM perps with long history + LUNA as the tail name.
CANDIDATES = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "DOGEUSDT", "AVAXUSDT", "LINKUSDT",
    "LUNAUSDT",  # tail (collapsed 2022-05); 洞6
]
START = "2021-01"
END = "2026-05"
TOP_N = 5
ADV_WINDOW_DAYS = 30
DAY_MS = 86_400_000
# Equity-normalized carry (§8.5 fix): notional = K_GROSS × equity, rebalanced daily.
K_GROSS = 1.0
REBALANCE_HOURS = 24
# Physical liquidation tail: sweep short leverage (None = no liquidation / margin-infinite).
# Verdict uses a conservative carry leverage; the sweep is the sensitivity read.
LIQ_SWEEP = [None, 10.0, 5.0, 3.0]
VERDICT_LEVERAGE = 3.0


def _month_keys(start: str, end: str) -> list[str]:
    sy, sm = (int(x) for x in start.split("-"))
    ey, em = (int(x) for x in end.split("-"))
    out = []
    y, m = sy, sm
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def _month_start_ts(month: str) -> int:
    y, m = (int(x) for x in month.split("-"))
    dt = datetime(y, m, 1, tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _align(spot: list[Bar], perp: list[Bar], *,
           max_basis: float = 1.0) -> tuple[list[Bar], list[Bar], int]:
    """Intersect spot/perp on ts, dropping bars whose |basis| exceeds ``max_basis``.

    A real perp-spot basis stays well under 100% even in the worst liquidation cascade;
    anything above is a data artifact (e.g. LUNA/LUNC redenomination -> 159x basis), not a
    tradeable price -- excluded. Returns (spot, perp, n_dropped)."""
    perp_by_ts = {b.ts_ms: b for b in perp}
    s, p, dropped = [], [], 0
    for b in spot:
        q = perp_by_ts.get(b.ts_ms)
        if q is None:
            continue
        if b.close > 0 and abs(b.close - q.close) / b.close > max_basis:
            dropped += 1
            continue
        s.append(b)
        p.append(q)
    return s, p, dropped


def _monthly_returns(bars: list[Bar], curve: list[float]) -> dict[str, float]:
    """Per-month return from an equity curve aligned 1:1 with ``bars``."""
    first: dict[str, float] = {}
    last: dict[str, float] = {}
    for b, eq in zip(bars, curve):
        mk = b.date[:7]
        first.setdefault(mk, eq)
        last[mk] = eq
    return {mk: (last[mk] / first[mk] - 1.0 if first[mk] else 0.0) for mk in first}


def main() -> int:
    sy, sm = (int(x) for x in START.split("-"))
    ey, em = (int(x) for x in END.split("-"))

    print(f"[grid-b H3 panel] {len(CANDIDATES)} candidates {START}..{END}, "
          f"top_n={TOP_N} by {ADV_WINDOW_DAYS}d ADV -- delta-neutral carry")

    spot_bars: dict[str, list[Bar]] = {}
    loaded: dict[str, tuple] = {}

    for sym in CANDIDATES:
        try:
            spot = load_klines(sym, "1h", start=(sy, sm), end=(ey, em), market="spot",
                               skip_missing=True)
            perp = load_klines(sym, "1h", start=(sy, sm), end=(ey, em), market="um",
                               skip_missing=True)
            funding = load_funding(sym, start=(sy, sm), end=(ey, em), skip_missing=True)
        except Exception as e:  # noqa: BLE001
            print(f"  {sym:10s} load failed: {e}")
            continue
        spot, perp, dropped = _align(spot, perp)
        if not spot:
            print(f"  {sym:10s} no overlapping spot/perp bars -- skipped")
            continue
        spot_bars[sym] = spot
        loaded[sym] = (spot, perp, funding)
        print(f"  {sym:10s} {spot[0].date}..{spot[-1].date}  {len(spot)} bars  "
              f"funding {len(funding)}  dropped {dropped}")

    if not loaded:
        print("  no symbols loaded -- aborting")
        return 2

    sweep = {}
    for liq in LIQ_SWEEP:
        sweep[liq] = _portfolio(loaded, spot_bars, liq_leverage=liq)

    print("\n=== H3-A static carry: liquidation-leverage sweep (top-5 EW portfolio) ===")
    print(f"  {'leverage':<12} {'ann':>9} {'net':>11} {'won':>6} {'liq_cost':>10}  verdict")
    for liq in LIQ_SWEEP:
        p = sweep[liq]
        tag = "∞ (upper bound)" if liq is None else f"{liq:g}x"
        vd = "PASS" if p["passed"] else "FAIL"
        print(f"  {tag:<12} {p['ann']:>+8.2%} {p['net']:>+10.2%} "
              f"{p['won']}/{p['n_years']:<3} {p['liq_cost_mean']:>9.2%}  {vd}")

    # Pre-registered physical verdict leverage (conservative carry): L = VERDICT_LEVERAGE.
    g = sweep[VERDICT_LEVERAGE]
    print(f"\n=== H3 verdict (§4; physical tail gate @ L={VERDICT_LEVERAGE:g}x, pre-registered) ===")
    for y in g["years"]:
        print(f"    {y}: {g['per_year'][y]:+7.2%}")
    print(f"  (1) annualized net > +2%        : {'PASS' if g['c1'] else 'FAIL'}  ({g['ann']:+.2%})")
    print(f"  (2) >= 66% years net-positive   : {'PASS' if g['c2'] else 'FAIL'}  ({g['won']}/{g['n_years']})")
    print(f"  (3) tail-survival net > 0       : {'PASS' if g['c3'] else 'FAIL'}  ({g['net']:+.2%})")
    verdict = ("H3-A carry 活(物理尾部门后三项仍全过)→ carry sleeve 成立,网格仍判死(H3-B≪H3-A)"
               if g["passed"] else
               "H3-A 不过(物理尾部门吃掉 carry)→ 网格族最深一层证伪 → §6 收口")
    print(f"  → {verdict}")

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ARTIFACT_DIR / f"h3panel_{START}_{END}_top{TOP_N}_{stamp}.json"
    out.write_text(json.dumps({
        "candidates": CANDIDATES, "start": START, "end": END, "top_n": TOP_N,
        "adv_window_days": ADV_WINDOW_DAYS, "verdict_leverage": VERDICT_LEVERAGE,
        "sweep": {("inf" if k is None else k): {kk: vv for kk, vv in v.items()
                                                if kk not in ("years",)}
                  for k, v in sweep.items()},
        "verdict": verdict,
    }, indent=2, default=float))
    print(f"\n  artifact: {out.relative_to(REPO)}")
    return 0


def _portfolio(loaded: dict, spot_bars: dict, *, liq_leverage) -> dict:
    """Build the point-in-time top-N EW portfolio under a given liquidation leverage."""
    monthly_ret: dict[tuple[str, str], float] = {}
    liq_costs = []
    per_symbol = {}
    for sym, (spot, perp, funding) in loaded.items():
        r = run_h3_carry(spot, perp, funding, k_gross=K_GROSS, liq_leverage=liq_leverage,
                         rebalance_hours=REBALANCE_HOURS)
        for mk, ret in _monthly_returns(spot, r.curve).items():
            monthly_ret[(sym, mk)] = ret
        liq_costs.append(r.liq_cost)
        per_symbol[sym] = {"net": r.net_return, "funding": r.funding_pnl,
                           "liq_cost": r.liq_cost, "liq_events": r.liq_events,
                           "offset_residual": r.offset_residual}

    port_curve = [1.0]
    yr_first: dict[str, float] = {}
    yr_last: dict[str, float] = {}
    for mk in _month_keys(START, END):
        uni = select_universe(spot_bars, _month_start_ts(mk), top_n=TOP_N,
                              window_days=ADV_WINDOW_DAYS)
        rets = [monthly_ret[(s, mk)] for s in uni if (s, mk) in monthly_ret]
        if not rets:
            continue
        port_curve.append(port_curve[-1] * (1.0 + sum(rets) / len(rets)))
        yr = mk[:4]
        yr_first.setdefault(yr, port_curve[-2])
        yr_last[yr] = port_curve[-1]

    net = port_curve[-1] - 1.0
    years = sorted(yr_first)
    per_year = {y: yr_last[y] / yr_first[y] - 1.0 for y in years}
    won = sum(1 for y in years if per_year[y] > 0)
    n_months = len(port_curve) - 1
    ann = (1.0 + net) ** (12.0 / n_months) - 1.0 if n_months and 1.0 + net > 0 else (
        -1.0 if 1.0 + net <= 0 else 0.0)
    c1, c2, c3 = ann > 0.02, (len(years) > 0 and won / len(years) >= 0.66), net > 0.0
    return {"net": net, "ann": ann, "per_year": per_year, "years": years, "won": won,
            "n_years": len(years), "n_months": n_months,
            "liq_cost_mean": sum(liq_costs) / len(liq_costs) if liq_costs else 0.0,
            "per_symbol": per_symbol, "c1": c1, "c2": c2, "c3": c3,
            "passed": c1 and c2 and c3}


if __name__ == "__main__":
    raise SystemExit(main())
