"""Trial 151: frozen CTA-R rule replicated on a class-matched US ETF universe.

Preregistration: docs/cta-r-us-replication-and-c60-vol-matched-2026-09.md (section A)
research_only=true / orders_authorized=false. Public Tiingo daily adjClose only; no orders, no paper state.
The weight rule is imported unchanged from ``cta_r_paper``; the accounting mirrors its replay
(weights held constant between 21-day rebalances, cost = turnover x rate on the rebalance day).
"""

from __future__ import annotations

import datetime as dt
import json
import math
from statistics import fmean
from typing import Callable, Mapping, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from qount.contracts import canonical_hash
from qount.research.c60_cost_study import deflated_sharpe
from qount.research.cta_r_paper import LOOKBACKS, REBALANCE_DAYS, _weights
from qount.research_data.metrics import _moments

TRIAL = "151"
GLOBAL_TRIAL_COUNT = 151
UNIVERSE = {
    "SPY": "domestic_large", "IWM": "domestic_small_mid", "QQQ": "domestic_growth", "DIA": "domestic_large_value",
    "GLD": "gold", "IEF": "government_bond", "EFA": "foreign_equity", "EEM": "foreign_equity",
}
A_SHARE_MAP = {"510300": "SPY", "510500": "IWM", "159915": "QQQ", "510050": "DIA",
               "518880": "GLD", "511010": "IEF", "513100": "EFA", "513500": "EEM"}
BASE_COST = 0.0010
STRESS_COST = 0.0020
SPLIT_DATE = "2014-01-01"
FOLDS = 5
GATES = {"R1_sharpe_10bps": 0.5, "R2_sharpe_20bps": 0.4, "R3_positive_folds_min": 4,
         "R4_both_halves_positive": True, "R5_max_drawdown_floor": -0.25}
PREREGISTRATION = {
    "trial": TRIAL, "rule": "cta_r_paper._weights frozen (63/126/252 sign mean, 63d inverse vol, cap 0.35, long-only)",
    "rebalance_days": REBALANCE_DAYS, "first_signal_index": max(LOOKBACKS) + 1,
    "universe": UNIVERSE, "a_share_map": A_SHARE_MAP, "costs_per_side": [BASE_COST, STRESS_COST],
    "gates": GATES, "split_date": SPLIT_DATE, "folds": FOLDS,
    "document": "docs/cta-r-us-replication-and-c60-vol-matched-2026-09.md",
}
GUARDS = {"research_only": True, "orders_authorized": False, "promotion_evidence": False}
TIINGO_URL = "https://api.tiingo.com/tiingo/daily/{symbol}/prices"


class CtaRUsReplicationError(ValueError):
    pass


def fetch_adjusted_closes(
    symbol: str,
    *,
    token: str,
    end: dt.date,
    start: dt.date = dt.date(2004, 1, 1),
    getter: Callable[[str, Mapping[str, str]], object] | None = None,
) -> dict[str, float]:
    """Daily adjClose keyed by ISO date; token goes in a header only and is never returned or logged."""

    if not token:
        raise CtaRUsReplicationError("tiingo_token_missing")
    url = TIINGO_URL.format(symbol=symbol) + "?" + urlencode(
        {"startDate": start.isoformat(), "endDate": end.isoformat(), "resampleFreq": "daily"})
    headers = {"Authorization": f"Token {token}", "Content-Type": "application/json"}

    def default_getter(target: str, head: Mapping[str, str]) -> object:
        with urlopen(Request(target, headers=dict(head)), timeout=30) as response:
            return json.loads(response.read())

    rows = (getter or default_getter)(url, headers)
    if not isinstance(rows, list) or not rows:
        raise CtaRUsReplicationError(f"tiingo_rows_invalid:{symbol}")
    out: dict[str, float] = {}
    for row in rows:
        day = str(row.get("date", ""))[:10]
        value = row.get("adjClose")
        if len(day) == 10 and isinstance(value, (int, float)) and value > 0 and math.isfinite(value):
            out[day] = float(value)
    if not out:
        raise CtaRUsReplicationError(f"tiingo_rows_empty:{symbol}")
    return out


def align(series: Mapping[str, Mapping[str, float]]) -> tuple[list[str], dict[str, list[float]], dict[str, object]]:
    if set(series) != set(UNIVERSE):
        raise CtaRUsReplicationError("universe_mismatch")
    dates = sorted(set.intersection(*(set(v) for v in series.values())))
    if len(dates) <= max(LOOKBACKS) + 2 * REBALANCE_DAYS:
        raise CtaRUsReplicationError("history_too_short")
    prices = {s: [series[s][d] for d in dates] for s in sorted(UNIVERSE)}
    audit = {"first": dates[0], "last": dates[-1], "bars": len(dates),
             "per_symbol": {s: {"first": min(v), "last": max(v), "bars": len(v)} for s, v in sorted(series.items())},
             "data_hash": canonical_hash({s: [[d, series[s][d]] for d in dates] for s in sorted(series)})}
    return dates, prices, audit


def replay(dates: Sequence[str], prices: Mapping[str, Sequence[float]], *, cost: float) -> dict[str, object]:
    """Returns daily net returns from the first signal onward, plus rebalances and per-symbol contribution."""

    symbols = sorted(prices)
    returns = {s: [0.0] + [prices[s][i] / prices[s][i - 1] - 1.0 for i in range(1, len(dates))] for s in symbols}
    start = max(LOOKBACKS) + 1
    weights: dict[str, float] = {}
    out_dates, out_returns = [], []
    contribution = {s: 0.0 for s in symbols}
    turnover_sum = gross_sum = 0.0
    rebalances = 0
    for index in range(start, len(dates)):
        day = sum(weights.get(s, 0.0) * returns[s][index] for s in symbols)
        for s, w in weights.items():
            contribution[s] += w * returns[s][index]
        equity_factor = 1.0 + day
        if index % REBALANCE_DAYS == 0:
            new = _weights({s: list(prices[s]) for s in symbols}, returns, index)
            traded = sum(abs(new.get(s, 0.0) - weights.get(s, 0.0)) for s in symbols)
            equity_factor *= 1.0 - cost * traded
            turnover_sum += traded
            weights = new
            rebalances += 1
        if out_dates or weights:
            out_dates.append(dates[index])
            out_returns.append(equity_factor - 1.0)
            gross_sum += sum(weights.values())
    if not out_returns:
        raise CtaRUsReplicationError("replay_empty")
    years = len(out_returns) / 252.0
    return {"dates": out_dates, "returns": out_returns, "rebalances": rebalances,
            "annual_turnover": turnover_sum / years, "average_gross": gross_sum / len(out_returns),
            "contribution": contribution}


def sharpe(returns: Sequence[float]) -> float:
    mean, std, _, _ = _moments(list(returns))
    return 0.0 if std == 0.0 else mean / std * math.sqrt(252.0)


def cagr(returns: Sequence[float]) -> float:
    nav = math.prod(1.0 + r for r in returns)
    return nav ** (252.0 / len(returns)) - 1.0 if nav > 0.0 else -1.0


def max_drawdown(returns: Sequence[float]) -> float:
    nav = peak = 1.0
    worst = 0.0
    for r in returns:
        nav *= 1.0 + r
        peak = max(peak, nav)
        worst = min(worst, nav / peak - 1.0)
    return worst


def fold_sharpes(returns: Sequence[float], folds: int = FOLDS) -> list[float]:
    size = len(returns) // folds
    return [sharpe(returns[i * size:(i + 1) * size if i < folds - 1 else len(returns)]) for i in range(folds)]


def yearly(dates: Sequence[str], returns: Sequence[float]) -> dict[str, float]:
    years: dict[str, float] = {}
    for d, r in zip(dates, returns):
        years[d[:4]] = years.get(d[:4], 1.0) * (1.0 + r)
    return {y: round(v - 1.0, 4) for y, v in sorted(years.items())}


def benchmark(dates: Sequence[str], prices: Mapping[str, Sequence[float]], weights: Mapping[str, float],
              *, first: str, cost: float) -> list[float]:
    """Fixed weights rebalanced at each month's first trading day; drift in between."""

    held: dict[str, float] = {}
    out = []
    for index in range(1, len(dates)):
        if dates[index] < first:
            continue
        month_start = not held or dates[index][:7] != dates[index - 1][:7]
        traded = sum(abs(weights.get(s, 0.0) - held.get(s, 0.0)) for s in set(weights) | set(held)) if month_start else 0.0
        if month_start:
            held = dict(weights)
        r = {s: prices[s][index] / prices[s][index - 1] - 1.0 for s in held}
        day = sum(w * r[s] for s, w in held.items())
        out.append((1.0 + day) * (1.0 - cost * traded) - 1.0)
        total = 1.0 + day
        held = {s: w * (1.0 + r[s]) / total for s, w in held.items()}
    return out


def summary(dates: Sequence[str], returns: Sequence[float]) -> dict[str, object]:
    mean, std, _, _ = _moments(list(returns))
    return {"first": dates[0], "last": dates[-1], "bars": len(returns), "sharpe": round(sharpe(returns), 4),
            "cagr": round(cagr(returns), 4), "max_drawdown": round(max_drawdown(returns), 4),
            "annual_vol": round(std * math.sqrt(252.0), 4), "yearly": yearly(dates, returns)}


def evaluate(series: Mapping[str, Mapping[str, float]]) -> dict[str, object]:
    dates, prices, audit = align(series)
    base = replay(dates, prices, cost=BASE_COST)
    stress = replay(dates, prices, cost=STRESS_COST)
    b_dates, b_ret = base["dates"], base["returns"]
    folds = fold_sharpes(b_ret)
    pre = [r for d, r in zip(b_dates, b_ret) if d < SPLIT_DATE]
    post = [r for d, r in zip(b_dates, b_ret) if d >= SPLIT_DATE]
    if not pre or not post:
        raise CtaRUsReplicationError("split_empty")
    base_summary = summary(b_dates, b_ret)
    gates = {
        "R1_sharpe_10bps": base_summary["sharpe"] >= GATES["R1_sharpe_10bps"],
        "R2_sharpe_20bps": sharpe(stress["returns"]) >= GATES["R2_sharpe_20bps"],
        "R3_positive_folds": sum(s > 0.0 for s in folds) >= GATES["R3_positive_folds_min"],
        "R4_both_halves_positive": sharpe(pre) > 0.0 and sharpe(post) > 0.0,
        "R5_max_drawdown": base_summary["max_drawdown"] >= GATES["R5_max_drawdown_floor"],
    }
    first = b_dates[0]
    ew = benchmark(dates, prices, {s: 1.0 / len(prices) for s in prices}, first=first, cost=BASE_COST)
    sixty = benchmark(dates, prices, {"SPY": 0.6, "IEF": 0.4}, first=first, cost=BASE_COST)
    bench_dates = [d for d in dates[1:] if d >= first]
    by_class: dict[str, float] = {}
    for s, v in base["contribution"].items():
        by_class[UNIVERSE[s]] = by_class.get(UNIVERSE[s], 0.0) + v
    return {
        "trial": TRIAL, "guards": GUARDS, "preregistration": PREREGISTRATION,
        "preregistration_hash": canonical_hash(PREREGISTRATION), "data": audit,
        "base_10bps": base_summary | {"annual_turnover": round(base["annual_turnover"], 3),
                                      "average_gross": round(base["average_gross"], 4),
                                      "rebalances": base["rebalances"]},
        "stress_20bps": summary(stress["dates"], stress["returns"]),
        "fold_sharpes": [round(s, 4) for s in folds],
        "halves": {"pre_2014_sharpe": round(sharpe(pre), 4), "post_2014_sharpe": round(sharpe(post), 4),
                   "pre_2014_cagr": round(cagr(pre), 4), "post_2014_cagr": round(cagr(post), 4)},
        "gates": gates,
        "verdict": "replicated" if all(gates.values()) else "not_replicated",
        "informational": {
            "deflated_sharpe": {k: round(v, 6) for k, v in deflated_sharpe(b_ret, n_trials=GLOBAL_TRIAL_COUNT).items()},
            "equal_weight_monthly": summary(bench_dates, ew),
            "sixty_forty_spy_ief": summary(bench_dates, sixty),
            "contribution_by_class": {k: round(v, 4) for k, v in sorted(by_class.items())},
            "contribution_by_symbol": {k: round(v, 4) for k, v in sorted(base["contribution"].items())},
            "mean_daily_return_bps": round(fmean(b_ret) * 10_000, 3),
        },
    }
