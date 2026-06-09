#!/usr/bin/env python3
"""CTA-R per-year x per-asset attribution diagnostic (research-only).

Reuses cta_sim's EXACT signal/weight functions on the akshare ETF cache to break
the validated long-only TSMOM book (fixed config) down by calendar year and by
asset. Purpose: judge whether the flat 2023-2026 stretch is a normal trend-
following drought (broad, all sleeves quiet) or structural decay (a sleeve that
used to carry is now dead). No network, no orders, reads the local date,close cache.

Run on WSL:  .venv/bin/python scripts/research/cta_yearly_attribution.py
"""
from __future__ import annotations

import math
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.cta_data import ETF_ASSET_CLASS, load_etf_cache  # noqa: E402
from qount.cta_sim import SimConfig, TRADING_DAYS_PER_YEAR, _target_weights  # noqa: E402

CACHE = REPO / "state" / "etf_cache"


def _load_aligned() -> tuple[list[str], dict[str, list[float]]]:
    symbols = sorted(p.stem for p in CACHE.glob("*.csv"))
    by_symbol = {s: load_etf_cache(str(CACHE), s) for s in symbols}
    common: set[str] | None = None
    for s in symbols:
        d = set(by_symbol[s])
        common = d if common is None else (common & d)
    dates = sorted(common or [])
    prices = {s: [by_symbol[s][dt] for dt in dates] for s in symbols}
    return dates, prices


def _sharpe(daily: list[float]) -> float | None:
    if len(daily) < 2:
        return None
    m = sum(daily) / len(daily)
    var = sum((x - m) ** 2 for x in daily) / (len(daily) - 1)
    sd = var ** 0.5
    return (m / sd) * math.sqrt(TRADING_DAYS_PER_YEAR) if sd > 0 else None


def main() -> None:
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
    equity = 1.0
    peak = 1.0
    weights: dict[str, float] = {}
    yr_daily: dict[str, list[float]] = defaultdict(list)   # net daily returns by year
    yr_contrib: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))  # gross w*r by year,asset

    for t in range(1, length):
        year = dates[t][:4]
        eq0 = equity
        port = 0.0
        for n, w in weights.items():
            r = rets[n][t]
            if r is not None:
                port += w * r
                yr_contrib[year][n] += w * r
        equity *= 1.0 + port
        peak = max(peak, equity)
        if t >= warmup and t % config.rebalance_days == 0:
            nw = _target_weights(prices, rets, t, config, equity, peak)
            union = set(nw) | set(weights)
            turn = sum(abs(nw.get(n, 0.0) - weights.get(n, 0.0)) for n in union)
            equity *= 1.0 - config.cost_per_side_pct * turn
            weights = nw
            peak = max(peak, equity)
        yr_daily[year].append(equity / eq0 - 1.0 if eq0 > 0 else 0.0)

    print(f"universe ({len(names)}): " + ", ".join(f"{n}/{ETF_ASSET_CLASS.get(n,'?')}" for n in names))
    print(f"dates {dates[0]} -> {dates[-1]}  ({length} days)  fixed config lb=(63,126,252) reb=21 long_only cap=1.0\n")
    print(f"{'year':<6}{'days':>5}{'net_ret':>9}{'ann_Sharpe':>11}   top contributor / worst dragger")
    for year in sorted(yr_daily):
        daily = yr_daily[year]
        net = 1.0
        for d in daily:
            net *= 1.0 + d
        net -= 1.0
        sh = _sharpe(daily)
        c = yr_contrib[year]
        best = max(c.items(), key=lambda kv: kv[1], default=("-", 0.0))
        worst = min(c.items(), key=lambda kv: kv[1], default=("-", 0.0))
        sh_s = f"{sh:+.2f}" if sh is not None else "  n/a"
        print(f"{year:<6}{len(daily):>5}{net*100:>8.1f}%{sh_s:>11}   "
              f"{best[0]} {best[1]*100:+.1f}%  /  {worst[0]} {worst[1]*100:+.1f}%")

    # per-asset gross contribution, two regimes
    def regime_contrib(years: list[str]) -> dict[str, float]:
        out: dict[str, float] = defaultdict(float)
        for y in years:
            for n, v in yr_contrib[y].items():
                out[n] += v
        return out
    early = regime_contrib([y for y in yr_daily if y <= "2022"])
    late = regime_contrib([y for y in yr_daily if y >= "2023"])
    print(f"\n{'asset':<14}{'class':<16}{'2012-2022':>12}{'2023-2026':>12}")
    for n in names:
        print(f"{n:<14}{ETF_ASSET_CLASS.get(n,'?'):<16}{early.get(n,0.0)*100:>11.1f}%{late.get(n,0.0)*100:>11.1f}%")
    print(f"{'TOTAL gross':<30}{sum(early.values())*100:>11.1f}%{sum(late.values())*100:>11.1f}%")


if __name__ == "__main__":
    main()
