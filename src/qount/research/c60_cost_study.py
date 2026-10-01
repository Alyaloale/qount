"""C60 cost-expectancy study (Trials 149/150). research_only=true / orders_authorized=false.

Replays the frozen Dual-Engine C60 rule (daily candidate re-rank) and the research-original
variant (month-end candidate selection, daily gates) on public Binance spot daily closes, under
turnover costs and an optional one-bar execution delay. Never touches paper state or orders.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from dataclasses import dataclass
from statistics import fmean
from typing import Callable, Mapping, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from qount.contracts import canonical_hash
from qount.dual_engine.contracts import C60_SYMBOLS, DualEnginePaperContract
from qount.dual_engine.strategy import _portfolio_volatility  # identical frozen covariance math
from qount.research_data.metrics import _moments, deflated_sharpe_ratio, expected_max_sharpe

BINANCE_KLINES_URL = "https://data-api.binance.vision/api/v3/klines"
WARMUP_BARS = 100  # the paper keeps the last 100 closed daily bars
MOMENTUM_BARS = 90
GLOBAL_TRIAL_COUNT = 150
GUARDS = {"research_only": True, "orders_authorized": False, "paper_state_modified": False}

PREREGISTRATION = {
    "study_id": "c60_cost_expectancy_v1",
    "trials": {"149": "frozen_daily", "150": "research_monthly"},
    "universe": list(C60_SYMBOLS),
    "base_cost_bps": 25.0,
    "stress_cost_bps": 50.0,
    "break_even_floor_bps": 50.0,
    "sharpe_floor": 0.5,
    "dsr_floor_informational": 0.95,
    "global_trial_count": GLOBAL_TRIAL_COUNT,
    "survivorship_drop": "SOLUSDT",
    "parameter_search_allowed": False,
    "data_role": "consumed_historical_discovery_pool",
    **GUARDS,
}

JsonGetter = Callable[[str, float], object]


class C60CostStudyError(ValueError):
    pass


def _public_get(url: str, timeout: float) -> object:
    request = Request(url, headers={"User-Agent": "qount-research/1.0"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed public https host
        return json.loads(response.read().decode("utf-8"))


def fetch_daily_closes(
    symbol: str,
    *,
    observed_ms: int,
    getter: JsonGetter = _public_get,
    timeout: float = 20.0,
    start_ms: int = 1_500_000_000_000,
) -> dict[str, float]:
    """Return {YYYY-MM-DD (UTC open day): close} for bars fully closed before ``observed_ms``."""

    closes: dict[str, float] = {}
    cursor = start_ms
    for _ in range(20):
        query = urlencode({"symbol": symbol, "interval": "1d", "startTime": cursor, "limit": 1000})
        rows = getter(f"{BINANCE_KLINES_URL}?{query}", timeout)
        if not isinstance(rows, list):
            raise C60CostStudyError(f"klines_invalid:{symbol}")
        for row in rows:
            if not isinstance(row, list) or len(row) < 7:
                raise C60CostStudyError(f"kline_row_invalid:{symbol}")
            if int(row[6]) >= observed_ms:
                continue
            close = float(row[4])
            if not math.isfinite(close) or close <= 0.0:
                raise C60CostStudyError(f"kline_close_invalid:{symbol}")
            day = dt.datetime.fromtimestamp(int(row[0]) / 1000, tz=dt.timezone.utc).date().isoformat()
            closes[day] = close
        if len(rows) < 1000:
            break
        cursor = int(rows[-1][0]) + 1
    else:
        raise C60CostStudyError(f"klines_pagination_exceeded:{symbol}")
    if not closes:
        raise C60CostStudyError(f"klines_empty:{symbol}")
    return closes


@dataclass(frozen=True)
class Panel:
    dates: tuple[str, ...]
    closes: Mapping[str, tuple[float, ...]]

    def subset(self, symbols: Sequence[str]) -> "Panel":
        return Panel(self.dates, {symbol: self.closes[symbol] for symbol in symbols})


def build_panel(series: Mapping[str, Mapping[str, float]]) -> tuple[Panel, dict[str, object]]:
    """Align on the intersection of dates; report per-symbol coverage for the data audit."""

    if set(series) != set(C60_SYMBOLS):
        raise C60CostStudyError("panel_universe_invalid")
    common = sorted(set.intersection(*(set(values) for values in series.values())))
    if len(common) <= WARMUP_BARS + 30:
        raise C60CostStudyError("panel_history_short")
    audit = {
        symbol: {
            "first": min(values),
            "last": max(values),
            "bars": len(values),
            "bars_outside_common": len(values) - len(common),
        }
        for symbol, values in sorted(series.items())
    }
    panel = Panel(tuple(common), {s: tuple(series[s][d] for d in common) for s in C60_SYMBOLS})
    return panel, {"symbols": audit, "common_first": common[0], "common_last": common[-1],
                   "common_bars": len(common), "data_hash": canonical_hash(
                       {s: [[d, series[s][d]] for d in common] for s in sorted(series)})}


def _rank_candidates(window: Mapping[str, tuple[float, ...]]) -> tuple[str, ...]:
    momentum = {s: v[-1] / v[-MOMENTUM_BARS - 1] - 1.0 for s, v in window.items()}
    ranked = sorted(momentum, key=lambda symbol: (-momentum[symbol], symbol))
    return tuple(symbol for symbol in ranked if momentum[symbol] > 0.0)[:2]


def c60_target(
    window: Mapping[str, tuple[float, ...]],
    candidates: Sequence[str],
    contract: DualEnginePaperContract,
) -> dict[str, float]:
    """Frozen C60 gates + vol cap for given candidates; rejected weight stays in cash."""

    btc = window["BTCUSDT"]
    btc_gate = btc[-1] > fmean(btc[-50:])
    base = 0.0 if not candidates else 1.0 / len(candidates)
    pre = {symbol: 0.0 for symbol in window}
    for symbol in candidates:
        own_gate = window[symbol][-1] > fmean(window[symbol][-20:])
        if own_gate and (btc_gate or symbol == "PAXGUSDT"):
            pre[symbol] = base
    vol = _portfolio_volatility(dict(window), pre, window=contract.c60_volatility_window)
    if sum(pre.values()) == 0.0:
        scalar = 0.0
    elif vol == 0.0:
        scalar = 1.0
    else:
        scalar = min(1.0, contract.c60_volatility_target / vol)
    return {symbol: weight * scalar for symbol, weight in pre.items() if weight * scalar > 0.0}


def _is_month_end(dates: Sequence[str], index: int) -> bool:
    if index + 1 < len(dates):
        return dates[index + 1][:7] != dates[index][:7]
    day = dt.date.fromisoformat(dates[index])
    return (day + dt.timedelta(days=1)).day == 1


def target_path(
    panel: Panel,
    *,
    mode: str,
    contract: DualEnginePaperContract | None = None,
) -> list[dict[str, float]]:
    """Targets decided at each close; index < WARMUP_BARS-1 stays empty."""

    contract = contract or DualEnginePaperContract.frozen_v1()
    contract.validate()
    if mode not in {"frozen_daily", "research_monthly"} or "BTCUSDT" not in panel.closes:
        raise C60CostStudyError("target_mode_invalid")
    targets: list[dict[str, float]] = [{} for _ in panel.dates]
    held: tuple[str, ...] = ()
    for index in range(WARMUP_BARS - 1, len(panel.dates)):
        window = {s: v[index - WARMUP_BARS + 1:index + 1] for s, v in panel.closes.items()}
        if mode == "frozen_daily":
            candidates = _rank_candidates(window)
        else:
            if _is_month_end(panel.dates, index):
                held = _rank_candidates(window)
            candidates = held
        targets[index] = c60_target(window, candidates, contract)
    return targets


@dataclass(frozen=True)
class SimResult:
    dates: tuple[str, ...]
    returns: tuple[float, ...]
    turnover: float
    cost_fraction_sum: float
    average_gross: float


def simulate(
    panel: Panel,
    targets: Sequence[Mapping[str, float]],
    *,
    cost_bps: float,
    delay_bars: int = 0,
    start_date: str | None = None,
    records: list[dict[str, object]] | None = None,
) -> SimResult:
    """Daily NAV: trade to target at close (t + delay), pay turnover × cost, earn next-day returns.

    ``start_date`` opens a fresh all-cash account at the first close on/after that date (pre-start
    bars are warmup only). ``records`` receives one entry per day that traded.
    """

    if delay_bars not in (0, 1) or cost_bps < 0.0 or len(targets) != len(panel.dates):
        raise C60CostStudyError("simulation_arguments_invalid")
    rate = cost_bps / 10_000.0
    first = WARMUP_BARS - 1 + delay_bars
    if start_date is not None:
        later = [i for i, day in enumerate(panel.dates) if day >= start_date]
        if not later:
            raise C60CostStudyError("simulation_start_after_panel")
        first = max(first, later[0])
    weights: dict[str, float] = {}
    dates, returns = [], []
    turnover = cost_sum = gross_sum = 0.0
    for index in range(first, len(panel.dates) - 1):
        target = targets[index - delay_bars]
        traded = sum(abs(target.get(s, 0.0) - weights.get(s, 0.0)) for s in set(target) | set(weights))
        cost = traded * rate
        turnover += traded
        cost_sum += cost
        if records is not None and traded > 1e-12:
            records.append({"date": panel.dates[index], "turnover": traded, "cost_fraction": cost,
                            "weights": dict(sorted(target.items()))})
        weights = dict(target)
        asset = {s: panel.closes[s][index + 1] / panel.closes[s][index] - 1.0 for s in weights}
        gross = sum(weights.values())
        gross_sum += gross
        day_return = (1.0 - cost) * (1.0 + sum(w * asset[s] for s, w in weights.items())) - 1.0
        grown = {s: w * (1.0 + asset[s]) for s, w in weights.items()}
        total = 1.0 + day_return
        weights = {s: v * (1.0 - cost) / total for s, v in grown.items()} if total > 0.0 else {}
        dates.append(panel.dates[index + 1])
        returns.append(day_return)
    if not returns:
        raise C60CostStudyError("simulation_empty")
    return SimResult(tuple(dates), tuple(returns), turnover, cost_sum, gross_sum / len(returns))


def cagr(returns: Sequence[float]) -> float:
    nav = math.prod(1.0 + r for r in returns)
    return nav ** (365.0 / len(returns)) - 1.0 if nav > 0.0 else -1.0


def max_drawdown(returns: Sequence[float]) -> float:
    nav = peak = 1.0
    worst = 0.0
    for r in returns:
        nav *= 1.0 + r
        peak = max(peak, nav)
        worst = min(worst, nav / peak - 1.0)
    return worst


def annual_sharpe(returns: Sequence[float]) -> float:
    mean, std, _, _ = _moments(list(returns))
    return 0.0 if std == 0.0 else mean / std * math.sqrt(365.0)


def yearly_returns(result: SimResult) -> dict[str, float]:
    years: dict[str, float] = {}
    for day, r in zip(result.dates, result.returns):
        years[day[:4]] = years.get(day[:4], 1.0) * (1.0 + r)
    return {year: nav - 1.0 for year, nav in sorted(years.items())}


def cagr_excluding_best_year(result: SimResult) -> tuple[str, float]:
    years = yearly_returns(result)
    best = max(years, key=years.get)
    rest = [r for d, r in zip(result.dates, result.returns) if d[:4] != best]
    return best, cagr(rest) if rest else 0.0


def break_even_bps(panel: Panel, targets: Sequence[Mapping[str, float]], *, delay_bars: int = 0) -> float:
    """Single-side cost at which CAGR reaches zero (CAGR is monotone decreasing in cost)."""

    low, high = 0.0, 1_000.0
    if cagr(simulate(panel, targets, cost_bps=low, delay_bars=delay_bars).returns) <= 0.0:
        return 0.0
    if cagr(simulate(panel, targets, cost_bps=high, delay_bars=delay_bars).returns) > 0.0:
        return high
    for _ in range(30):
        mid = (low + high) / 2.0
        if cagr(simulate(panel, targets, cost_bps=mid, delay_bars=delay_bars).returns) > 0.0:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def deflated_sharpe(returns: Sequence[float], *, n_trials: int = GLOBAL_TRIAL_COUNT) -> dict[str, float]:
    """Per-observation DSR; SR variance uses the single-series estimator (documented convention)."""

    mean, std, skew, kurt = _moments(list(returns))
    sr = 0.0 if std == 0.0 else mean / std
    n = len(returns)
    var_sr = max(1e-12, (1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr) / (n - 1))
    benchmark = expected_max_sharpe(n_trials, var_sr)
    return {"dsr": deflated_sharpe_ratio(sr, n_obs=n, sr_benchmark=benchmark, skew=skew, kurt=kurt),
            "sr_daily": sr, "sr_benchmark_daily": benchmark, "n_trials": float(n_trials)}


def _summary(result: SimResult) -> dict[str, object]:
    years = len(result.returns) / 365.0
    return {
        "first": result.dates[0], "last": result.dates[-1], "bars": len(result.returns),
        "cagr": cagr(result.returns), "max_drawdown": max_drawdown(result.returns),
        "sharpe": annual_sharpe(result.returns), "annual_turnover": result.turnover / years,
        "annual_cost_drag": result.cost_fraction_sum / years, "average_gross": result.average_gross,
        "yearly_returns": yearly_returns(result),
    }


def evaluate_trial(panel: Panel, *, mode: str) -> dict[str, object]:
    contract = DualEnginePaperContract.frozen_v1()
    base_bps, stress_bps = contract.c60_cost_bps, contract.c60_stress_cost_bps
    if (base_bps, stress_bps) != (PREREGISTRATION["base_cost_bps"], PREREGISTRATION["stress_cost_bps"]):
        raise C60CostStudyError("frozen_cost_mismatch")
    targets = target_path(panel, mode=mode, contract=contract)
    base = simulate(panel, targets, cost_bps=base_bps)
    stress = simulate(panel, targets, cost_bps=stress_bps, delay_bars=1)
    signal = simulate(panel, targets, cost_bps=0.0)
    no_sol_symbols = [s for s in panel.closes if s != PREREGISTRATION["survivorship_drop"]]
    no_sol = simulate(panel.subset(no_sol_symbols),
                      target_path(panel.subset(no_sol_symbols), mode=mode, contract=contract),
                      cost_bps=base_bps)
    best_year, ex_best = cagr_excluding_best_year(base)
    even = break_even_bps(panel, targets)
    dsr = deflated_sharpe(base.returns)
    gates = {
        "G1_base_cagr_positive": cagr(base.returns) > 0.0,
        "G2_stress_cagr_positive": cagr(stress.returns) > 0.0,
        "G3_break_even_at_least_2x": even >= PREREGISTRATION["break_even_floor_bps"],
        "G4_sharpe_floor": annual_sharpe(base.returns) >= PREREGISTRATION["sharpe_floor"],
        "G5_ex_best_year_positive": ex_best > 0.0,
        "G6_ex_sol_positive": cagr(no_sol.returns) > 0.0,
    }
    return {
        "mode": mode,
        "gates": gates,
        "informational": {"G7_dsr_at_least_0_95": dsr["dsr"] >= PREREGISTRATION["dsr_floor_informational"]},
        "verdict": "retain_for_forward_evidence" if all(gates.values()) else "reject",
        "base_25bps_t0": _summary(base),
        "stress_50bps_t1": _summary(stress),
        "signal_0bps_t0": _summary(signal),
        "ex_sol_25bps_t0": _summary(no_sol),
        "break_even_bps_t0": even,
        "best_year": best_year,
        "cagr_ex_best_year": ex_best,
        "deflated_sharpe": dsr,
    }


def btc_buy_and_hold(panel: Panel) -> dict[str, object]:
    btc = panel.closes["BTCUSDT"]
    returns = [btc[i + 1] / btc[i] - 1.0 for i in range(WARMUP_BARS - 1, len(btc) - 1)]
    return {"cagr": cagr(returns), "max_drawdown": max_drawdown(returns), "sharpe": annual_sharpe(returns)}


def run_study(panel: Panel, audit: Mapping[str, object]) -> dict[str, object]:
    trials = {number: evaluate_trial(panel, mode=mode) for number, mode in PREREGISTRATION["trials"].items()}
    return {
        "schema_version": "c60_cost_expectancy_v1",
        "preregistration_hash": canonical_hash(PREREGISTRATION),
        "data_audit": dict(audit),
        "trials": trials,
        "benchmark_btc_buy_and_hold": btc_buy_and_hold(panel),
        **GUARDS,
        "promotion_evidence": False,
        "data_role": PREREGISTRATION["data_role"],
    }
