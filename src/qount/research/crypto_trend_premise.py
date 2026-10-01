"""Descriptive diagnostic of the crypto trend premise behind C60 (not a trial).

Preregistration: docs/crypto-trend-premise-diagnostic-2026-09.md
research_only=true / orders_authorized=false. Offline on the frozen cost-study panel; no rule is evaluated.
"""

from __future__ import annotations

from statistics import fmean, pstdev
from typing import Mapping, Sequence

from qount.research.c60_cost_study import (
    WARMUP_BARS,
    Panel,
    _is_month_end,
    simulate,
    target_path,
    yearly_returns,
)

MODE = "research_monthly"
COST_BPS = 25.0
FIRST_YEAR = "2021"
GUARDS = {"research_only": True, "orders_authorized": False, "trial": False, "global_trial_count": 150}


def _ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2.0
        i = j + 1
    return ranks


def spearman(a: Sequence[float], b: Sequence[float]) -> float:
    ra, rb = _ranks(a), _ranks(b)
    ma, mb = fmean(ra), fmean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return num / den if den else 0.0


def _year(day: str) -> str:
    return day[:4]


def _mean_or_none(values: Sequence[float]) -> float | None:
    return fmean(values) if values else None


def decomposition(panel: Panel) -> dict[str, object]:
    """0-bps additive split: static BTC beta, timing, selection vs BTC; plus per-symbol contribution."""

    targets = target_path(panel, mode=MODE)
    closes, dates = panel.closes, panel.dates
    rows = []
    for t in range(WARMUP_BARS - 1, len(dates) - 1):
        if _year(dates[t + 1]) < FIRST_YEAR:
            continue
        r = {s: closes[s][t + 1] / closes[s][t] - 1.0 for s in closes}
        rows.append((dates[t + 1], targets[t], r))
    g_bar = fmean(sum(w.values()) for _, w, _ in rows)
    years: dict[str, dict[str, float]] = {}
    for day, w, r in rows:
        y = years.setdefault(_year(day), {"beta": 0.0, "timing": 0.0, "selection": 0.0, "total": 0.0,
                                          "gross_sum": 0.0, "bars": 0})
        gross = sum(w.values())
        y["beta"] += g_bar * r["BTCUSDT"]
        y["timing"] += (gross - g_bar) * r["BTCUSDT"]
        y["selection"] += sum(wi * (r[s] - r["BTCUSDT"]) for s, wi in w.items())
        y["total"] += sum(wi * r[s] for s, wi in w.items())
        y["gross_sum"] += gross
        y["bars"] += 1
    by_symbol: dict[str, dict[str, float]] = {}
    for day, w, r in rows:
        for s, wi in w.items():
            by_symbol.setdefault(s, {}).setdefault(_year(day), 0.0)
            by_symbol[s][_year(day)] += wi * r[s]
    return {
        "average_gross": round(g_bar, 4),
        "years": {k: {"beta": round(v["beta"], 4), "timing": round(v["timing"], 4),
                      "selection": round(v["selection"], 4), "total": round(v["total"], 4),
                      "average_gross": round(v["gross_sum"] / v["bars"], 4), "bars": v["bars"]}
                  for k, v in sorted(years.items())},
        "by_symbol": {s: {k: round(v, 4) for k, v in sorted(ys.items())} for s, ys in sorted(by_symbol.items())},
    }


def cost_by_year(panel: Panel) -> dict[str, dict[str, float]]:
    targets = target_path(panel, mode=MODE)
    signal = yearly_returns(simulate(panel, targets, cost_bps=0.0))
    paid = yearly_returns(simulate(panel, targets, cost_bps=COST_BPS))
    return {y: {"signal": round(signal[y], 4), "net_25bps": round(paid[y], 4),
                "cost": round(signal[y] - paid[y], 4)} for y in sorted(signal) if y >= FIRST_YEAR}


def signal_validity(panel: Panel) -> dict[str, dict[str, object]]:
    closes, dates = panel.closes, panel.dates
    symbols = sorted(closes)
    n = len(dates)
    b1: dict[str, tuple[list[float], list[float]]] = {}
    b2: dict[str, tuple[list[float], list[float]]] = {}
    b4: dict[str, list[float]] = {}
    for t in range(50, n - 1):
        y = _year(dates[t])
        up, dn = b1.setdefault(y, ([], []))
        for s in symbols:
            c = closes[s]
            nxt = c[t + 1] / c[t] - 1.0
            (up if c[t] > fmean(c[t - 19:t + 1]) else dn).append(nxt)
            path = sum(abs(c[k] - c[k - 1]) for k in range(t - 19, t + 1))
            b4.setdefault(y, []).append(abs(c[t] - c[t - 20]) / path if path else 0.0)
        btc = closes["BTCUSDT"]
        ew = fmean(closes[s][t + 1] / closes[s][t] - 1.0 for s in symbols)
        on, off = b2.setdefault(y, ([], []))
        (on if btc[t] > fmean(btc[t - 49:t + 1]) else off).append(ew)
    b3: dict[str, list[float]] = {}
    for t in range(90, n - 30):
        if not _is_month_end(dates, t):
            continue
        mom = [closes[s][t] / closes[s][t - 90] - 1.0 for s in symbols]
        fwd = [closes[s][t + 30] / closes[s][t] - 1.0 for s in symbols]
        b3.setdefault(_year(dates[t]), []).append(spearman(mom, fwd))

    def spread(pair):
        a, b = pair
        return None if not a or not b else round((fmean(a) - fmean(b)) * 10_000, 2)

    out = {}
    for y in sorted(set(b1) | set(b3)):
        if y < FIRST_YEAR:
            continue
        ics = b3.get(y, [])
        out[y] = {
            "b1_sma20_next_day_spread_bps": spread(b1.get(y, ([], []))),
            "b1_share_above": round(len(b1[y][0]) / max(1, len(b1[y][0]) + len(b1[y][1])), 3) if y in b1 else None,
            "b2_btc_sma50_ew_next_day_spread_bps": spread(b2.get(y, ([], []))),
            "b2_share_on": round(len(b2[y][0]) / max(1, len(b2[y][0]) + len(b2[y][1])), 3) if y in b2 else None,
            "b3_momentum_ic_mean": None if not ics else round(fmean(ics), 3),
            "b3_ic_positive_share": None if not ics else round(sum(ic > 0 for ic in ics) / len(ics), 3),
            "b3_months": len(ics),
            "b4_efficiency_ratio_20d": None if y not in b4 else round(fmean(b4[y]), 3),
        }
    return out


def market_structure(panel: Panel) -> dict[str, dict[str, float]]:
    closes, dates = panel.closes, panel.dates
    alts = [s for s in sorted(closes) if s != "BTCUSDT"]
    out: dict[str, dict[str, float]] = {}
    grow: dict[str, list[float]] = {}
    disp: dict[str, list[float]] = {}
    for t in range(30, len(dates) - 1):
        y = _year(dates[t + 1])
        g = grow.setdefault(y, [1.0, 1.0])
        g[0] *= closes["BTCUSDT"][t + 1] / closes["BTCUSDT"][t]
        g[1] *= 1.0 + fmean(closes[s][t + 1] / closes[s][t] - 1.0 for s in alts)
        disp.setdefault(y, []).append(pstdev([closes[s][t] / closes[s][t - 30] - 1.0 for s in closes]))
    for y in sorted(grow):
        if y < FIRST_YEAR:
            continue
        btc, alt = grow[y][0] - 1.0, grow[y][1] - 1.0
        out[y] = {"btc_return": round(btc, 4), "alt_ew_return": round(alt, 4),
                  "alt_minus_btc": round(alt - btc, 4), "dispersion_30d": round(fmean(disp[y]), 4)}
    return out


def run(panel: Panel) -> dict[str, object]:
    return {
        "guards": GUARDS,
        "mode": MODE,
        "decomposition": decomposition(panel),
        "cost_by_year": cost_by_year(panel),
        "signal_validity": signal_validity(panel),
        "market_structure": market_structure(panel),
    }
