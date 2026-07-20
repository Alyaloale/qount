"""Capacity audit for the fixed LiquidTrend10 research universe."""

from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.grid.data import Bar, Funding
from qount.mini_trend.futures_recovery import canonical_hash
from qount.models import utc_now
from qount.settings import Settings


LIQUID_TREND_CAPACITY_VERSION = "liquid_trend10_capacity_audit_v0.2"
LIQUID_TREND_UNIVERSE = (
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "ADAUSDT",
    "LINKUSDT",
    "AVAXUSDT",
    "LTCUSDT",
)
_DAY_MS = 86_400_000


@dataclass(frozen=True)
class LiquidTrendPreprocessingContract:
    """Pre-PnL frozen choices for the first LiquidTrend hypothesis family."""

    score_transform: str = "cross_sectional_percentile_rank"
    winsorization: str = "none_rank_transform_is_robust"
    minimum_cross_section: int = 8
    funding_missing_policy: str = "exclude_symbol_for_rebalance"
    listing_warmup_completed_bars: int = 121
    extreme_volatility_policy: str = "retain_finite_observations"
    tie_break: str = "score_desc_then_symbol_asc"
    decision_time: str = "monday_00:05:00_utc_after_completed_sunday_bar"
    execution_quote_window: str = "monday_00:05:00_to_00:10:00_utc"
    signal_price: str = "completed_daily_close"
    execution_price: str = "buy_at_executable_ask_sell_at_executable_bid"
    missing_execution_quote_policy: str = "no_trade"
    mark_price_usage: str = "risk_and_margin_only"

    def __post_init__(self) -> None:
        if self.score_transform != "cross_sectional_percentile_rank":
            raise ValueError("first LiquidTrend trial must use frozen robust ranks")
        if self.winsorization != "none_rank_transform_is_robust":
            raise ValueError("LiquidTrend winsorization contract changed")
        if self.minimum_cross_section < 8:
            raise ValueError("LiquidTrend requires at least eight ranked symbols")
        if self.listing_warmup_completed_bars < 121:
            raise ValueError("LiquidTrend warm-up must cover the 120-day return")
        if self.execution_price != "buy_at_executable_ask_sell_at_executable_bid":
            raise ValueError("LiquidTrend trial requires executable-side quotes")

    @property
    def contract_hash(self) -> str:
        return canonical_hash(asdict(self))


@dataclass(frozen=True)
class LiquidTrendCapacityConfig:
    universe: tuple[str, ...] = LIQUID_TREND_UNIVERSE
    start_date: str = "2021-07-20"
    end_date: str = "2026-05-31"
    capital_usdt: float = 1_000.0
    maximum_symbol_weight: float = 0.25
    filter_buffer: float = 1.05
    minimum_symbol_bar_coverage: float = 0.99
    minimum_common_bar_coverage: float = 0.99
    minimum_funding_coverage: float = 0.99
    minimum_funding_settlements_per_day: int = 3
    funding_settlement_round_ms: int = 60_000
    minimum_median_quote_volume_usdt: float = 25_000_000.0
    minimum_effective_breadth: float = 2.0
    cluster_abs_correlation: float = 0.85
    preprocessing: LiquidTrendPreprocessingContract = field(
        default_factory=LiquidTrendPreprocessingContract
    )

    def __post_init__(self) -> None:
        if not self.universe or len(self.universe) != len(set(self.universe)):
            raise ValueError("LiquidTrend universe must be non-empty and unique")
        if "BTCUSDT" not in self.universe:
            raise ValueError("LiquidTrend capacity audit requires BTCUSDT")
        if self.start_date > self.end_date:
            raise ValueError("LiquidTrend capacity dates are reversed")
        if self.capital_usdt <= 0.0:
            raise ValueError("LiquidTrend capacity capital must be positive")
        if not 0.0 < self.maximum_symbol_weight <= 1.0:
            raise ValueError("LiquidTrend maximum symbol weight must be in (0, 1]")
        if self.funding_settlement_round_ms <= 0:
            raise ValueError("LiquidTrend funding settlement rounding must be positive")

    @property
    def contract_hash(self) -> str:
        return canonical_hash(
            {
                "config": asdict(self),
                "effective_breadth": "N / (1 + (N - 1) * mean_abs_pairwise_correlation)",
                "effective_breadth_eigen": "sum(eigenvalues)^2 / sum(eigenvalues^2)",
                "funding_day": (
                    "round exchange timestamp to nearest configured settlement unit, then "
                    "bar_open < settlement <= bar_open + 24h"
                ),
                "quote_volume": "Binance quote_volume, fallback close * base_volume",
                "score_reserved_for_later_trial": (
                    "rank_cs(r20)+rank_cs(r60)+0.5*rank_cs(r120)"
                    "-rank_cs(vol20)-rank_cs(funding30_ann)"
                ),
                "strategy_results_evaluated": False,
                "paper_or_live_allowed": False,
            }
        )


def _mean(values: Sequence[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _percentile(values: Sequence[float], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _correlation(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = _mean(left)
    right_mean = _mean(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right))
    left_var = sum((x - left_mean) ** 2 for x in left)
    right_var = sum((y - right_mean) ** 2 for y in right)
    denominator = math.sqrt(left_var * right_var)
    return numerator / denominator if denominator > 0.0 else None


def _symmetric_eigenvalues(matrix: Sequence[Sequence[float]]) -> list[float]:
    """Return eigenvalues of a small symmetric matrix using Jacobi rotations."""

    size = len(matrix)
    if size == 0:
        return []
    values = [list(map(float, row)) for row in matrix]
    if any(len(row) != size for row in values):
        raise ValueError("eigenvalue matrix must be square")
    for _ in range(max(1, 100 * size * size)):
        p, q = 0, 0
        maximum = 0.0
        for left in range(size):
            for right in range(left + 1, size):
                candidate = abs(values[left][right])
                if candidate > maximum:
                    p, q, maximum = left, right, candidate
        if maximum < 1e-12:
            break
        angle = 0.5 * math.atan2(
            2.0 * values[p][q], values[q][q] - values[p][p]
        )
        cosine, sine = math.cos(angle), math.sin(angle)
        app, aqq, apq = values[p][p], values[q][q], values[p][q]
        for index in range(size):
            if index in {p, q}:
                continue
            aip, aiq = values[index][p], values[index][q]
            values[index][p] = values[p][index] = cosine * aip - sine * aiq
            values[index][q] = values[q][index] = sine * aip + cosine * aiq
        values[p][p] = (
            cosine * cosine * app
            - 2.0 * sine * cosine * apq
            + sine * sine * aqq
        )
        values[q][q] = (
            sine * sine * app
            + 2.0 * sine * cosine * apq
            + cosine * cosine * aqq
        )
        values[p][q] = values[q][p] = 0.0
    return sorted((max(0.0, values[index][index]) for index in range(size)), reverse=True)


def _beta(asset: Sequence[float], benchmark: Sequence[float]) -> float | None:
    if len(asset) != len(benchmark) or len(asset) < 2:
        return None
    benchmark_mean = _mean(benchmark)
    asset_mean = _mean(asset)
    variance = sum((value - benchmark_mean) ** 2 for value in benchmark)
    if variance <= 0.0:
        return None
    covariance = sum(
        (left - asset_mean) * (right - benchmark_mean)
        for left, right in zip(asset, benchmark)
    )
    return covariance / variance


def effective_breadth(return_panel: Mapping[str, Sequence[float]]) -> dict[str, Any]:
    symbols = list(return_panel)
    lengths = {len(return_panel[symbol]) for symbol in symbols}
    if len(lengths) > 1:
        raise ValueError("effective breadth return series must be aligned")
    pairs = []
    correlations: dict[tuple[str, str], float] = {}
    for left_index, left in enumerate(symbols):
        for right in symbols[left_index + 1 :]:
            correlation = _correlation(return_panel[left], return_panel[right])
            if correlation is not None:
                correlations[(left, right)] = correlation
                correlations[(right, left)] = correlation
                pairs.append(
                    {
                        "left": left,
                        "right": right,
                        "correlation": correlation,
                        "absolute_correlation": abs(correlation),
                    }
                )
    mean_abs = _mean([float(row["absolute_correlation"]) for row in pairs])
    count = len(symbols)
    breadth = count / (1.0 + (count - 1) * mean_abs) if count else 0.0
    correlation_matrix = [
        [
            1.0 if left == right else correlations.get((left, right), 0.0)
            for right in symbols
        ]
        for left in symbols
    ]
    eigenvalues = _symmetric_eigenvalues(correlation_matrix)
    eigen_sum = sum(eigenvalues)
    eigen_square_sum = sum(value * value for value in eigenvalues)
    eigen_breadth = (
        eigen_sum * eigen_sum / eigen_square_sum if eigen_square_sum > 0.0 else 0.0
    )
    benchmark = return_panel.get("BTCUSDT")
    btc_betas = (
        {
            symbol: _beta(return_panel[symbol], benchmark)
            for symbol in symbols
        }
        if benchmark is not None
        else {}
    )
    return {
        "symbol_count": count,
        "pair_count": len(pairs),
        "mean_abs_pairwise_correlation": mean_abs,
        "maximum_abs_pairwise_correlation": max(
            (float(row["absolute_correlation"]) for row in pairs), default=0.0
        ),
        "effective_breadth": breadth,
        "effective_breadth_eigen": eigen_breadth,
        "first_principal_component_share": (
            eigenvalues[0] / eigen_sum if eigenvalues and eigen_sum > 0.0 else 0.0
        ),
        "eigenvalues": eigenvalues,
        "correlation_matrix_symbols": symbols,
        "correlation_matrix": correlation_matrix,
        "btc_beta_by_symbol": btc_betas,
        "pairs": pairs,
    }


def _correlation_clusters(
    symbols: Sequence[str], pairs: Sequence[Mapping[str, Any]], threshold: float
) -> list[list[str]]:
    parent = {symbol: symbol for symbol in symbols}

    def find(symbol: str) -> str:
        while parent[symbol] != symbol:
            parent[symbol] = parent[parent[symbol]]
            symbol = parent[symbol]
        return symbol

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for row in pairs:
        if float(row["absolute_correlation"]) >= threshold:
            union(str(row["left"]), str(row["right"]))
    groups: dict[str, list[str]] = {}
    for symbol in symbols:
        groups.setdefault(find(symbol), []).append(symbol)
    return sorted((sorted(group) for group in groups.values()), key=lambda row: (-len(row), row))


def _funding_by_bar_open(
    rows: Sequence[Funding], settlement_round_ms: int
) -> dict[int, list[float]]:
    result: dict[int, list[float]] = {}
    for row in rows:
        timestamp = int(row.ts_ms)
        canonical = (
            (timestamp + settlement_round_ms // 2) // settlement_round_ms
        ) * settlement_round_ms
        bar_open = ((canonical - 1) // _DAY_MS) * _DAY_MS
        result.setdefault(bar_open, []).append(float(row.rate))
    return result


def _analysis_bars(
    rows: Sequence[Bar], start_date: str, end_date: str
) -> dict[str, Bar]:
    return {
        row.date: row
        for row in rows
        if start_date <= row.date <= end_date
    }


def _return_panel(
    bars: Mapping[str, Mapping[str, Bar]], dates: Sequence[str]
) -> dict[str, list[float]]:
    return {
        symbol: [
            bars[symbol][dates[index]].close / bars[symbol][dates[index - 1]].close - 1.0
            for index in range(1, len(dates))
        ]
        for symbol in bars
    }


def _segment_breadth(
    bars: Mapping[str, Mapping[str, Bar]],
    dates: Sequence[str],
    start: str,
    end: str,
    cluster_threshold: float,
) -> dict[str, Any]:
    selected = [date for date in dates if start <= date <= end]
    if len(selected) < 3:
        return {
            "start": selected[0] if selected else None,
            "end": selected[-1] if selected else None,
            "bar_count": len(selected),
            "effective_breadth": None,
        }
    result = effective_breadth(_return_panel(bars, selected))
    clusters = _correlation_clusters(
        tuple(bars), result["pairs"], cluster_threshold
    )
    high_correlation_edges = sorted(
        [str(row["left"]), str(row["right"])]
        for row in result["pairs"]
        if float(row["absolute_correlation"]) >= cluster_threshold
    )
    return {
        "start": selected[0],
        "end": selected[-1],
        "bar_count": len(selected),
        **{
            key: value
            for key, value in result.items()
            if key not in {"pairs", "correlation_matrix"}
        },
        "cluster_count": len(clusters),
        "clusters": clusters,
        "high_correlation_edges": high_correlation_edges,
    }


def _edge_jaccard(left: Sequence[Sequence[str]], right: Sequence[Sequence[str]]) -> float:
    left_set = {tuple(edge) for edge in left}
    right_set = {tuple(edge) for edge in right}
    union = left_set | right_set
    return len(left_set & right_set) / len(union) if union else 1.0


def build_liquid_trend_capacity_report(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    funding_by_symbol: Mapping[str, Sequence[Funding]],
    exchange_rules: Mapping[str, Any],
    config: LiquidTrendCapacityConfig | None = None,
) -> dict[str, Any]:
    config = config or LiquidTrendCapacityConfig()
    missing_bars = sorted(set(config.universe) - set(bars_by_symbol))
    missing_funding = sorted(set(config.universe) - set(funding_by_symbol))
    if missing_bars or missing_funding:
        raise ValueError(
            f"LiquidTrend inputs missing bars={missing_bars} funding={missing_funding}"
        )

    bars = {
        symbol: _analysis_bars(
            bars_by_symbol[symbol], config.start_date, config.end_date
        )
        for symbol in config.universe
    }
    reference_dates = sorted(bars["BTCUSDT"])
    if len(reference_dates) < 3:
        raise ValueError("LiquidTrend capacity audit has insufficient BTC dates")
    common_dates = sorted(set.intersection(*(set(bars[symbol]) for symbol in config.universe)))
    if len(common_dates) < 3:
        raise ValueError("LiquidTrend capacity audit has insufficient common dates")

    symbol_rows = {}
    funding_rows = {}
    funding_index = {
        symbol: _funding_by_bar_open(
            funding_by_symbol[symbol], config.funding_settlement_round_ms
        )
        for symbol in config.universe
    }
    for symbol in config.universe:
        quote_volumes = [
            float(bar.quote_volume)
            if bar.quote_volume is not None and float(bar.quote_volume) > 0.0
            else float(bar.close) * float(bar.volume)
            for bar in bars[symbol].values()
        ]
        symbol_rows[symbol] = {
            "bar_count": len(bars[symbol]),
            "first_date": min(bars[symbol], default=None),
            "last_date": max(bars[symbol], default=None),
            "coverage_vs_btc": len(set(bars[symbol]) & set(reference_dates))
            / len(reference_dates),
            "median_daily_quote_volume_usdt": statistics.median(quote_volumes)
            if quote_volumes
            else 0.0,
            "p10_daily_quote_volume_usdt": _percentile(quote_volumes, 0.10),
        }
        eligible_dates = common_dates[:-1]
        complete = sum(
            len(funding_index[symbol].get(bars[symbol][date].ts_ms, []))
            >= config.minimum_funding_settlements_per_day
            for date in eligible_dates
        )
        funding_rows[symbol] = {
            "eligible_day_count": len(eligible_dates),
            "complete_day_count": complete,
            "coverage": complete / len(eligible_dates) if eligible_dates else 0.0,
            "minimum_settlements_per_day": config.minimum_funding_settlements_per_day,
        }

    full_breadth = effective_breadth(_return_panel(bars, common_dates))
    clusters = _correlation_clusters(
        config.universe,
        full_breadth["pairs"],
        config.cluster_abs_correlation,
    )
    full_high_correlation_edges = sorted(
        [str(row["left"]), str(row["right"])]
        for row in full_breadth["pairs"]
        if float(row["absolute_correlation"]) >= config.cluster_abs_correlation
    )
    full_return_panel = _return_panel(bars, common_dates)
    downside_indices = [
        index
        for index, value in enumerate(full_return_panel["BTCUSDT"])
        if value < 0.0
    ]
    downside_panel = {
        symbol: [values[index] for index in downside_indices]
        for symbol, values in full_return_panel.items()
    }
    downside_breadth = (
        effective_breadth(downside_panel)
        if len(downside_indices) >= 2
        else None
    )
    segments = [
        {
            "label": label,
            **_segment_breadth(
                bars,
                common_dates,
                start,
                end,
                config.cluster_abs_correlation,
            ),
        }
        for label, start, end in (
            ("2021-2022", "2021-07-20", "2022-12-31"),
            ("2023-2024", "2023-01-01", "2024-12-31"),
            ("2025-2026", "2025-01-01", config.end_date),
        )
    ]
    cluster_stability = [
        {
            "label": segment["label"],
            "high_correlation_edge_jaccard_vs_full": _edge_jaccard(
                full_high_correlation_edges,
                segment.get("high_correlation_edges", []),
            ),
        }
        for segment in segments
    ]

    rules_valid = (
        exchange_rules.get("market") == "um"
        and exchange_rules.get("source_type") == "runtime_exchange_info"
    )
    indexed_rules = {
        str(row.get("symbol", "")).upper(): dict(row)
        for row in exchange_rules.get("rules", [])
        if isinstance(row, Mapping) and row.get("symbol")
    }
    rule_rows = {}
    for symbol in config.universe:
        rule = indexed_rules.get(symbol)
        latest = bars[symbol][common_dates[-1]]
        if rule is None:
            rule_rows[symbol] = {"present": False, "trading": False, "feasible": False}
            continue
        floor = max(
            float(rule.get("min_notional") or 0.0),
            float(rule.get("min_qty") or 0.0) * float(latest.close),
        ) * config.filter_buffer
        minimum_weight = floor / config.capital_usdt
        rule_rows[symbol] = {
            "present": True,
            "trading": rule.get("status") == "TRADING",
            "minimum_order_floor_usdt": floor,
            "minimum_weight_at_capital": minimum_weight,
            "maximum_symbol_weight": config.maximum_symbol_weight,
            "feasible": minimum_weight <= config.maximum_symbol_weight,
        }

    gates = {
        "runtime_um_rules_artifact": rules_valid,
        "all_rules_present": all(row["present"] for row in rule_rows.values()),
        "all_symbols_trading": all(row["trading"] for row in rule_rows.values()),
        "all_filters_feasible_at_1000": all(row["feasible"] for row in rule_rows.values()),
        "all_symbol_bar_coverage": all(
            row["coverage_vs_btc"] >= config.minimum_symbol_bar_coverage
            for row in symbol_rows.values()
        ),
        "common_bar_coverage": (
            len(common_dates) / len(reference_dates) >= config.minimum_common_bar_coverage
        ),
        "all_funding_coverage": all(
            row["coverage"] >= config.minimum_funding_coverage
            for row in funding_rows.values()
        ),
        "all_median_quote_volume": all(
            row["median_daily_quote_volume_usdt"]
            >= config.minimum_median_quote_volume_usdt
            for row in symbol_rows.values()
        ),
        "effective_breadth_at_least_2": (
            full_breadth["effective_breadth"] >= config.minimum_effective_breadth
        ),
    }
    data_execution_gates = {
        key: value
        for key, value in gates.items()
        if key != "effective_breadth_at_least_2"
    }
    if not all(data_execution_gates.values()):
        verdict = "block_liquid_trend_g0_data_or_execution"
    elif not gates["effective_breadth_at_least_2"]:
        verdict = "block_liquid_trend_g0_breadth"
    else:
        verdict = "pass_liquid_trend_g0_capacity"

    data_hash = canonical_hash(
        {
            "bars": {
                symbol: [
                    [
                        bars[symbol][date].ts_ms,
                        bars[symbol][date].open,
                        bars[symbol][date].high,
                        bars[symbol][date].low,
                        bars[symbol][date].close,
                        bars[symbol][date].volume,
                        bars[symbol][date].quote_volume,
                    ]
                    for date in sorted(bars[symbol])
                ]
                for symbol in config.universe
            },
            "funding": {
                symbol: [[row.ts_ms, row.rate] for row in funding_by_symbol[symbol]]
                for symbol in config.universe
            },
            "rules_hash": exchange_rules.get("raw_exchange_info_hash"),
        }
    )
    return {
        "schema_version": LIQUID_TREND_CAPACITY_VERSION,
        "artifact_type": "liquid_trend10_capacity_audit",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "consumed_historical_capacity_diagnostic",
            "existing_cache_only": True,
            "network_download_used": False,
            "strategy_results_evaluated": False,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "contract": {
            **asdict(config),
            "contract_hash": config.contract_hash,
            "preprocessing_contract_hash": config.preprocessing.contract_hash,
            "trial_count": 0,
            "score_formula_reserved_not_evaluated": (
                "rank_cs(r20)+rank_cs(r60)+0.5*rank_cs(r120)"
                "-rank_cs(vol20)-rank_cs(funding30_ann)"
            ),
        },
        "data_hash": data_hash,
        "coverage": {
            "btc_reference_bar_count": len(reference_dates),
            "common_bar_count": len(common_dates),
            "common_bar_coverage": len(common_dates) / len(reference_dates),
            "symbols": symbol_rows,
            "funding": funding_rows,
        },
        "breadth": {
            **full_breadth,
            "cluster_threshold": config.cluster_abs_correlation,
            "clusters": clusters,
            "cluster_count": len(clusters),
            "high_correlation_edges": full_high_correlation_edges,
            "downside_observation_count": len(downside_indices),
            "downside_btc_negative": (
                {
                    key: value
                    for key, value in downside_breadth.items()
                    if key not in {"pairs", "correlation_matrix"}
                }
                if downside_breadth is not None
                else None
            ),
            "cluster_stability": cluster_stability,
            "segments": segments,
        },
        "execution_capacity": {
            "capital_usdt": config.capital_usdt,
            "rules_artifact_market": exchange_rules.get("market"),
            "rules_artifact_source_type": exchange_rules.get("source_type"),
            "rules": rule_rows,
        },
        "diagnostics": {
            "gates": gates,
            "passed_gate_count": sum(gates.values()),
            "gate_count": len(gates),
            "blockers": [key for key, passed in gates.items() if not passed],
            "verdict": verdict,
            "frozen_strategy_trial_allowed": verdict == "pass_liquid_trend_g0_capacity",
            "interpretation": (
                "Capacity and breadth only. No momentum score, portfolio return, or strategy "
                "promotion was evaluated."
            ),
        },
    }


def write_liquid_trend_capacity_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="liquid-trend10-capacity",
        path_key="artifact_path",
        default_filename="liquid_trend10_capacity.json",
        explicit_path=explicit_path,
    )
