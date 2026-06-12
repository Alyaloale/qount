#!/usr/bin/env python3
"""CTA-R gold/bond regime-dependence stress test (research-only, deployment gate).

V-GATE's J0 confirmed recent return (2023-2026) rides the gate-blind sleeves: gold/bond/QDII
carried +23.9% while A-share equity carried +1.8%. Before deploying real capital into a book
that leans this hard on a gold+bond carry regime, this asks two honest questions:

  Q1 CONCENTRATION (ablation): strip gold and/or bond from the universe and re-run the
     validated book. How much of full-history and recent equity actually depends on them?
     Does cross-asset breadth reallocate, or does the book collapse?

  Q2 PROTECTION (reversal): inject a gold+bond reversal from a 2023 pivot and compare the
     TREND book vs a no-timing 1/N buy-and-hold on the SAME shocked prices. Trend-following's
     whole claim is that it cuts a reversing sleeve (long-Gamma: truncate losses). If the
     trend book bleeds far less than buy-hold, the structure is robust-by-design and the
     deployment risk is bounded. If not, it is a concentrated carry bet in a trend costume.
     Three shock modes: mirror (sharp reversal), carry_off (drift -> 0, pure noise),
     whipsaw (alternating +/- blocks, the trend follower's real weakness).

No network, no orders. Reads the local akshare date,close cache.
Run on WSL:  PYTHONPATH=src .venv/bin/python scripts/research/cta_regime_stress.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.cta_data import ETF_ASSET_CLASS, load_etf_cache  # noqa: E402
from qount.cta_sim import SimConfig, TRADING_DAYS_PER_YEAR, run_paper_sim  # noqa: E402

CACHE = REPO / "state" / "etf_cache"
GOLD, BOND = "518880.SH", "511010.SH"
PIVOT = "2023-01-01"  # reversal starts here; ~last 3.5y where gold/bond carried the book

CONFIG = SimConfig(
    lookback_days=(63, 126, 252), vol_lookback_days=63, rebalance_days=21,
    target_vol=0.12, max_leverage=1.0, long_only=True, max_weight=1.0,
)


def load_aligned() -> tuple[list[str], dict[str, list[float]]]:
    symbols = sorted(p.stem for p in CACHE.glob("*.csv"))
    by_symbol = {s: load_etf_cache(str(CACHE), s) for s in symbols}
    common: set[str] | None = None
    for s in symbols:
        d = set(by_symbol[s])
        common = d if common is None else (common & d)
    dates = sorted(common or [])
    prices = {s: [by_symbol[s][dt] for dt in dates] for s in symbols}
    return dates, prices


def _max_dd(curve: list[float]) -> float:
    peak, worst = curve[0], 0.0
    for v in curve:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, v / peak - 1.0)
    return worst


def _curve_from_daily(daily: list[float]) -> list[float]:
    eq, out = 1.0, [1.0]
    for r in daily:
        eq *= 1.0 + r
        out.append(eq)
    return out


def tail_stats(net_daily: list[float], dates: list[str], since: str) -> dict[str, float]:
    """Total return / CAGR / maxDD over the window dates >= since. net_daily aligns to dates[1:]."""
    idx = [i for i in range(1, len(dates)) if dates[i] >= since]
    if not idx:
        return {"total": 0.0, "cagr": 0.0, "maxdd": 0.0, "days": 0}
    seg = [net_daily[i - 1] for i in idx]
    curve = _curve_from_daily(seg)
    total = curve[-1] - 1.0
    yrs = len(seg) / TRADING_DAYS_PER_YEAR
    cagr = (curve[-1] ** (1.0 / yrs) - 1.0) if yrs > 0 and curve[-1] > 0 else 0.0
    return {"total": total, "cagr": cagr, "maxdd": _max_dd(curve), "days": len(seg)}


def equal_weight_daily(prices: dict[str, list[float]]) -> list[float]:
    """1/N continuously-rebalanced daily return series (the no-timing buy-hold baseline)."""
    names = list(prices)
    length = len(prices[names[0]])
    out: list[float] = []
    for t in range(1, length):
        rs = [prices[n][t] / prices[n][t - 1] - 1.0 for n in names if prices[n][t - 1] > 0]
        out.append(sum(rs) / len(rs) if rs else 0.0)
    return out


def apply_tail_transform(series: list[float], pivot_idx: int, mode: str) -> list[float]:
    """Rebuild a price path whose returns from ``pivot_idx`` are transformed by ``mode``."""
    rets = [0.0] + [series[t] / series[t - 1] - 1.0 if series[t - 1] > 0 else 0.0
                    for t in range(1, len(series))]
    tail = rets[pivot_idx:]
    mu = sum(tail) / len(tail) if tail else 0.0
    new = list(rets)
    for j, t in enumerate(range(pivot_idx, len(series))):
        r = rets[t]
        if mode == "mirror":          # sharp reversal: flip the whole return
            new[t] = -r
        elif mode == "carry_off":     # drift -> 0, keep the noise around zero
            new[t] = r - mu
        elif mode == "whipsaw":       # alternating +/-mu blocks (~42d) + residual noise
            block = 1.0 if (j // 42) % 2 == 0 else -1.0
            new[t] = -block * abs(mu) + (r - mu)
        else:
            raise ValueError(mode)
    out = list(series[: pivot_idx + 1])  # path up to pivot unchanged
    for t in range(pivot_idx + 1, len(series)):
        out.append(out[-1] * (1.0 + new[t]))
    return out


def shocked_prices(prices: dict[str, list[float]], dates: list[str], mode: str) -> dict[str, list[float]]:
    p0 = next(i for i, d in enumerate(dates) if d >= PIVOT)
    out = {n: list(v) for n, v in prices.items()}
    for sleeve in (GOLD, BOND):
        if sleeve in out:
            out[sleeve] = apply_tail_transform(out[sleeve], p0, mode)
    return out


def main() -> None:
    dates, prices = load_aligned()
    print(f"universe ({len(prices)}): " + ", ".join(
        f"{n}/{ETF_ASSET_CLASS.get(n, '?')}" for n in prices))
    print(f"dates {dates[0]} -> {dates[-1]}  pivot={PIVOT}  validated long-only book\n")

    # ---- Q1 CONCENTRATION: ablate gold/bond -------------------------------------------
    print("=" * 78)
    print("Q1 CONCENTRATION — strip gold/bond, full history vs 2023+ tail")
    print("=" * 78)
    ablations = {
        "full (8)": prices,
        "-gold": {n: v for n, v in prices.items() if n != GOLD},
        "-bond": {n: v for n, v in prices.items() if n != BOND},
        "-gold&bond": {n: v for n, v in prices.items() if n not in (GOLD, BOND)},
    }
    print(f"{'book':<14}{'full CAGR':>11}{'full maxDD':>12}   {'2023+ tot':>10}{'2023+ CAGR':>12}{'2023+ maxDD':>13}")
    for label, pr in ablations.items():
        res = run_paper_sim(pr, CONFIG)
        t = tail_stats(res["net_daily_returns"], dates, PIVOT)
        print(f"{label:<14}{res['cagr']*100:>10.1f}%{res['max_drawdown']*100:>11.1f}%   "
              f"{t['total']*100:>9.1f}%{t['cagr']*100:>11.1f}%{t['maxdd']*100:>12.1f}%")

    # ---- Q2 PROTECTION: reversal, trend book vs 1/N buy-hold ---------------------------
    print("\n" + "=" * 78)
    print(f"Q2 PROTECTION — gold+bond reversal from {PIVOT}: does trend cut the loss? (2023+ window)")
    print("=" * 78)
    print(f"{'shock':<12}{'trend tot':>11}{'trend maxDD':>13}   {'buy-hold tot':>13}{'buy-hold maxDD':>16}   {'maxDD saved':>12}")
    for mode in ("mirror", "carry_off", "whipsaw"):
        sp = shocked_prices(prices, dates, mode)
        trend = run_paper_sim(sp, CONFIG)
        tt = tail_stats(trend["net_daily_returns"], dates, PIVOT)
        bh = tail_stats(equal_weight_daily(sp), dates, PIVOT)
        # both maxdd are negative; trend shallower (less negative) than buy-hold -> positive = trend protected.
        saved = tt["maxdd"] - bh["maxdd"]
        print(f"{mode:<12}{tt['total']*100:>10.1f}%{tt['maxdd']*100:>12.1f}%   "
              f"{bh['total']*100:>12.1f}%{bh['maxdd']*100:>15.1f}%   {saved*100:>+11.1f}pp")

    print("\n" + "=" * 78)
    print("READING")
    print("=" * 78)
    print("Q1: if '-gold&bond' 2023+ return collapses to ~0/negative, recent equity IS the")
    print("    gold+bond carry; if breadth reallocates and it holds up, the book is diversified.")
    print("Q2: 'maxDD saved' >0 means the trend overlay truncated the reversal (long-Gamma earns")
    print("    its keep -> deployment risk bounded). ~0 or negative under whipsaw = the real")
    print("    soft spot; size/timing accordingly.")


if __name__ == "__main__":
    main()
