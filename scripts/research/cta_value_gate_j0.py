#!/usr/bin/env python3
"""V-GATE J0 qualification gate (docs/cta-r-value-gate-plan.md §4 J0, §5 step 2).

The cheapest possible kill for the valuation filter. Before touching Tushare, it asks one
structural question: can the gate even reach the money?

The gate only acts on sleeves with a real PE/PB -> A-share equity indices (Tushare
``index_dailybasic``). Gold / bond / QDII have no PE/PB, so the gate is BLIND to them. This
script (a) prints which classes are reachable, and (b) on the validated long-only TSMOM book,
decomposes realized contribution into the gate-reachable group vs the gate-blind group, by
regime. R1's claim: the reachable group (A-share equity) contributed ~0 over 2023-2026 while
the blind group (gold/bond/foreign) carried -> the gate can only filter a near-zero sleeve.

Part (a) needs no data (paper-decisive on any host). Part (b) reads the local akshare cache.

Run on WSL:  .venv/bin/python scripts/research/cta_value_gate_j0.py
Structural-only (no cache):  python scripts/research/cta_value_gate_j0.py --structural-only
"""
from __future__ import annotations

import math
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.cta_data import AKSHARE_DEFAULT_UNIVERSE, ETF_ASSET_CLASS  # noqa: E402

CACHE = REPO / "state" / "etf_cache"

# Classes whose ETF maps to an A-share index with a Tushare index_dailybasic PE/PB series.
# Everything else (gold/bond/foreign_equity/commodity) has no usable valuation -> gate-blind.
GATE_REACHABLE_CLASSES = {"cn_equity"}
# ETF -> tracked index (the series the gate would actually percentile-rank). For the record.
ETF_TO_INDEX = {
    "510300.SH": "000300.SH",  # 沪深300
    "510500.SH": "000905.SH",  # 中证500
    "159915.SZ": "399006.SZ",  # 创业板指
    "510050.SH": "000016.SH",  # 上证50
}


def _reachable(symbol: str) -> bool:
    return ETF_ASSET_CLASS.get(symbol) in GATE_REACHABLE_CLASSES


def print_structural_coverage() -> None:
    print("=" * 72)
    print("J0 (a) STRUCTURAL COVERAGE — can the valuation gate reach each sleeve?")
    print("=" * 72)
    print(f"{'ETF':<12}{'class':<16}{'gate':<10}{'valuation source'}")
    n_reach = 0
    for s in AKSHARE_DEFAULT_UNIVERSE:
        cls = ETF_ASSET_CLASS.get(s, "?")
        reach = _reachable(s)
        n_reach += reach
        src = f"Tushare idx {ETF_TO_INDEX.get(s, '?')}" if reach else "— none (PE/PB undefined)"
        print(f"{s:<12}{cls:<16}{'REACH' if reach else 'BLIND':<10}{src}")
    n = len(AKSHARE_DEFAULT_UNIVERSE)
    print(f"\nreachable: {n_reach}/{n} sleeves; blind: {n - n_reach}/{n} "
          "(gold/bond/QDII — the gate cannot filter these).")


def _load_aligned() -> tuple[list[str], dict[str, list[float]]]:
    from qount.cta_data import load_etf_cache  # lazy: only when running part (b)

    symbols = sorted(p.stem for p in CACHE.glob("*.csv"))
    by_symbol = {s: load_etf_cache(str(CACHE), s) for s in symbols}
    common: set[str] | None = None
    for s in symbols:
        d = set(by_symbol[s])
        common = d if common is None else (common & d)
    dates = sorted(common or [])
    prices = {s: [by_symbol[s][dt] for dt in dates] for s in symbols}
    return dates, prices


def run_empirical_contribution() -> None:
    from qount.cta_sim import SimConfig, _target_weights  # lazy

    dates, prices = _load_aligned()
    names = list(prices)
    length = len(dates)
    config = SimConfig(
        lookback_days=(63, 126, 252), vol_lookback_days=63, rebalance_days=21,
        target_vol=0.12, max_leverage=1.0, long_only=True, max_weight=1.0,
    )
    rets: dict[str, list[float | None]] = {}
    for n in names:
        s: list[float | None] = [None]
        for t in range(1, length):
            prev = prices[n][t - 1]
            s.append(prices[n][t] / prev - 1.0 if prev > 0 else None)
        rets[n] = s

    warmup = max(max(config.lookback_days), config.vol_lookback_days) + 1
    equity, peak = 1.0, 1.0
    weights: dict[str, float] = {}
    yr_contrib: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for t in range(1, length):
        year = dates[t][:4]
        port = 0.0
        for n, w in weights.items():
            r = rets[n][t]
            if r is not None:
                yr_contrib[year][n] += w * r
                port += w * r
        equity *= 1.0 + port
        peak = max(peak, equity)
        if t >= warmup and t % config.rebalance_days == 0:
            nw = _target_weights(prices, rets, t, config, equity, peak)
            union = set(nw) | set(weights)
            turn = sum(abs(nw.get(n, 0.0) - weights.get(n, 0.0)) for n in union)
            equity *= 1.0 - config.cost_per_side_pct * turn
            weights = nw
            peak = max(peak, equity)

    def regime(years_pred) -> dict[str, float]:
        out: dict[str, float] = defaultdict(float)
        for y in yr_contrib:
            if years_pred(y):
                for n, v in yr_contrib[y].items():
                    out[n] += v
        return out

    early = regime(lambda y: y <= "2022")
    late = regime(lambda y: y >= "2023")

    print("\n" + "=" * 72)
    print("J0 (b) REALIZED CONTRIBUTION — reachable vs blind, by regime")
    print("=" * 72)
    print(f"dates {dates[0]} -> {dates[-1]}  ({length} days)  validated long-only book\n")
    print(f"{'ETF':<12}{'class':<16}{'gate':<7}{'2012-2022':>12}{'2023-2026':>12}")
    reach_late = blind_late = reach_early = blind_early = 0.0
    for n in names:
        reach = _reachable(n)
        e, l = early.get(n, 0.0), late.get(n, 0.0)
        if reach:
            reach_early += e; reach_late += l
        else:
            blind_early += e; blind_late += l
        print(f"{n:<12}{ETF_ASSET_CLASS.get(n,'?'):<16}{'REACH' if reach else 'BLIND':<7}"
              f"{e*100:>11.1f}%{l*100:>11.1f}%")
    tot_late = reach_late + blind_late
    print("-" * 59)
    print(f"{'GATE-REACHABLE (A-share eq)':<35}{'':<0}{reach_early*100:>11.1f}%{reach_late*100:>11.1f}%")
    print(f"{'GATE-BLIND (gold/bond/QDII)':<35}{'':<0}{blind_early*100:>11.1f}%{blind_late*100:>11.1f}%")

    print("\n" + "=" * 72)
    print("J0 VERDICT")
    print("=" * 72)
    share = (reach_late / tot_late * 100) if abs(tot_late) > 1e-9 else float("nan")
    print(f"2023-2026 total gross contribution:      {tot_late*100:+.1f}%")
    print(f"  ...of which gate-REACHABLE (filterable): {reach_late*100:+.1f}%  ({share:.0f}% of total)")
    print(f"  ...of which gate-BLIND (untouchable):    {blind_late*100:+.1f}%")
    # FAIL if the only thing the gate can filter contributed ~nothing recently.
    fail = abs(reach_late) < 0.03 or (abs(tot_late) > 1e-9 and reach_late / tot_late < 0.20)
    if fail:
        print("\n=> J0 FAIL (as R1 predicted): the gate can only touch the A-share equity "
              "sleeve, which contributed ~0 over 2023-2026. Filtering a near-zero sleeve "
              "cannot move total EV. Do NOT wire Tushare; record kill in plan §6.")
    else:
        print("\n=> J0 PASS: the reachable sleeve carries enough recent contribution to be "
              "worth filtering. Proceed to wire Tushare index_dailybasic and run J1-J4.")


def main() -> None:
    print_structural_coverage()
    if "--structural-only" in sys.argv:
        print("\n(--structural-only: skipping empirical part; run on WSL with the etf_cache "
              "for the J0 verdict.)")
        return
    if not CACHE.exists() or not any(CACHE.glob("*.csv")):
        print(f"\n[no etf_cache at {CACHE}] — run on WSL for J0 (b)/verdict, or pass "
              "--structural-only here.")
        return
    run_empirical_contribution()


if __name__ == "__main__":
    main()
