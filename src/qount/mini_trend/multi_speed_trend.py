"""Bounded multi-speed trend discovery for the TOP3 UM research line."""

from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from qount.contracts import canonical_hash
from qount.grid.data import Bar, Funding
from qount.mini_trend.backtest import align_bars
from qount.mini_trend.forward import TOP3, frozen_top3_config
from qount.mini_trend.futures_recovery import FUTURES_RECOVERY_PROTOCOL
from qount.mini_trend.futures_recovery_backtest import allocate_with_filters, run_variant
from qount.mini_trend.scorecard import max_drawdown_pct
from qount.x4.indicators import ATR


MULTI_SPEED_PREREG_VERSION = "crypto_multi_speed_trend_preregistration_v0.1"
MULTI_SPEED_REPORT_VERSION = "crypto_multi_speed_trend_trial_v0.1"


@dataclass(frozen=True)
class MultiSpeedTrendProtocol:
    hypothesis_family: str = "multi_speed_trend_v1"
    candidate_id: str = "multi_speed_direction_consistency_v1"
    global_trial_number: int = 145
    trial_number_within_family: int = 1
    family_trial_budget: int = 3
    market: str = "um"
    interval: str = "1d"
    universe: tuple[str, ...] = TOP3
    start_month: str = "2020-02"
    end_month: str = "2026-06"
    direction_lookbacks: tuple[int, ...] = (20, 60, 120)
    required_positive_votes: int = 3
    slow_gate_lookback: int = 120
    slow_gate_breadth: float = 2.0 / 3.0
    vol_lookback: int = 20
    atr_lookback: int = 14
    vol_target: float = 0.015
    corr_floor: float = 0.2
    maximum_effective_gross: float = 1.0
    capital_usdt: float = 400.0
    estimated_min_notional_usdt: float = 5.0
    transaction_cost_multiplier_stress: float = 2.0
    signal_delay_stress_bars: int = 1
    maximum_drawdown_worsening_pp: float = 2.0
    minimum_positive_segment_outperformance: int = 2

    @property
    def segments(self) -> tuple[dict[str, str], ...]:
        return (
            {"label": "2020-2021", "start": "2020-02-10", "end": "2021-12-31"},
            {"label": "2022-2023", "start": "2022-01-01", "end": "2023-12-31"},
            {"label": "2024-2026", "start": "2024-01-01", "end": "2026-06-30"},
        )

    @property
    def contract_basis(self) -> dict[str, Any]:
        return {
            "hypothesis_family": self.hypothesis_family,
            "candidate_id": self.candidate_id,
            "trial": {
                "global_trial_number": self.global_trial_number,
                "trial_number_within_family": self.trial_number_within_family,
                "family_trial_budget": self.family_trial_budget,
            },
            "data": {
                "market": self.market,
                "interval": self.interval,
                "universe": list(self.universe),
                "start_month": self.start_month,
                "end_month": self.end_month,
                "data_role": "consumed_historical_discovery_pool",
                "existing_cache_only": True,
            },
            "signal": {
                "factor": "sign of trailing total return",
                "direction_lookbacks": list(self.direction_lookbacks),
                "required_positive_votes": self.required_positive_votes,
                "slow_gate_lookback": self.slow_gate_lookback,
                "slow_gate_breadth": self.slow_gate_breadth,
                "parameter_search_allowed": False,
            },
            "sizing": {
                "vol_lookback": self.vol_lookback,
                "atr_lookback": self.atr_lookback,
                "vol_target": self.vol_target,
                "corr_floor": self.corr_floor,
                "maximum_effective_gross": self.maximum_effective_gross,
            },
            "execution": {
                "control": "MiniTrend-UM-Base-v0.2",
                "capital_usdt": self.capital_usdt,
                "direction": "long_cash",
                "shorting_allowed": False,
                "leverage_boost_allowed": False,
                "estimated_min_notional_usdt": self.estimated_min_notional_usdt,
                "taker_fee_bps": FUTURES_RECOVERY_PROTOCOL.taker_fee_bps,
                "slippage_bps": FUTURES_RECOVERY_PROTOCOL.slippage_bps,
                "funding_included": True,
                "daily_chandelier_atr_multiple": (
                    FUTURES_RECOVERY_PROTOCOL.daily_chandelier_atr_multiple
                ),
                "stop_cooldown_completed_bars": (
                    FUTURES_RECOVERY_PROTOCOL.stop_cooldown_completed_bars
                ),
                "rebalance_band": frozen_top3_config().rebalance_band,
            },
        }

    @property
    def contract_hash(self) -> str:
        return canonical_hash(self.contract_basis)

    @property
    def protocol_basis(self) -> dict[str, Any]:
        return {
            "contract_hash": self.contract_hash,
            "primary_metric": "candidate_minus_base_standalone_cagr",
            "failure_conditions": [
                "candidate_standalone_cagr_not_above_base",
                "candidate_max_drawdown_worsens_more_than_2pp",
                "candidate_top3_beta_residual_cagr_not_positive",
                "candidate_outperforms_base_in_fewer_than_2_of_3_segments",
                "candidate_cagr_not_positive_at_doubled_execution_cost",
                "candidate_cagr_not_positive_with_one_bar_signal_delay",
                "gross_cap_or_nav_reconciliation_failure",
                "funding_history_has_zero_settlement_holding_interval",
            ],
            "allowed_sensitivity_range": {
                "transaction_cost_multiplier": [1.0, self.transaction_cost_multiplier_stress],
                "signal_delay_bars": [0, self.signal_delay_stress_bars],
            },
            "segments": list(self.segments),
            "interpretation": (
                "Formal discovery trial 145. A rejection applies to the direction-consistency "
                "baseline, not to the two separately preregistered multi-speed expressions."
            ),
            "candidate_pnl_ready": False,
            "promotion_evidence": False,
            "orders_authorized": False,
        }

    @property
    def protocol_hash(self) -> str:
        return canonical_hash(self.protocol_basis)


MULTI_SPEED_TREND_PROTOCOL = MultiSpeedTrendProtocol()


def build_multi_speed_preregistration(created_at: str) -> dict[str, Any]:
    protocol = MULTI_SPEED_TREND_PROTOCOL
    return {
        "schema_version": MULTI_SPEED_PREREG_VERSION,
        "artifact_type": "crypto_multi_speed_trend_preregistration",
        "created_at": created_at,
        "meta": {
            "research_only": True,
            "strategy_results_evaluated": False,
            "existing_cache_only": True,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "decision_contract": {**protocol.contract_basis, "contract_hash": protocol.contract_hash},
        "protocol": {**protocol.protocol_basis, "protocol_hash": protocol.protocol_hash},
    }


def validate_multi_speed_preregistration(payload: Mapping[str, Any]) -> None:
    protocol = MULTI_SPEED_TREND_PROTOCOL
    if payload.get("schema_version") != MULTI_SPEED_PREREG_VERSION:
        raise ValueError("unexpected multi-speed preregistration schema")
    decision_contract = dict(payload.get("decision_contract", {}))
    declared_contract_hash = decision_contract.pop("contract_hash", None)
    if (
        declared_contract_hash != protocol.contract_hash
        or canonical_hash(decision_contract) != protocol.contract_hash
    ):
        raise ValueError("multi-speed contract hash mismatch")
    protocol_payload = dict(payload.get("protocol", {}))
    declared_protocol_hash = protocol_payload.pop("protocol_hash", None)
    if (
        declared_protocol_hash != protocol.protocol_hash
        or canonical_hash(protocol_payload) != protocol.protocol_hash
    ):
        raise ValueError("multi-speed protocol hash mismatch")
    if payload.get("meta", {}).get("strategy_results_evaluated") is not False:
        raise ValueError("multi-speed preregistration contains evaluated results")


def research_rules() -> dict[str, dict[str, float]]:
    floor = MULTI_SPEED_TREND_PROTOCOL.estimated_min_notional_usdt
    return {symbol: {"min_notional": floor, "min_qty": 0.0} for symbol in TOP3}


def _daily_returns(bars: Sequence[Bar], lookback: int) -> list[float]:
    closes = [bar.close for bar in bars]
    return [closes[index] / closes[index - 1] - 1.0 for index in range(len(closes) - lookback, len(closes))]


def _trailing_return(bars: Sequence[Bar], lookback: int) -> float:
    return bars[-1].close / bars[-1 - lookback].close - 1.0


def _correlation(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    left_mean = statistics.mean(left)
    right_mean = statistics.mean(right)
    left_dev = [value - left_mean for value in left]
    right_dev = [value - right_mean for value in right]
    denominator = math.sqrt(sum(value * value for value in left_dev) * sum(value * value for value in right_dev))
    return sum(a * b for a, b in zip(left_dev, right_dev)) / denominator if denominator else 0.0


def _atr_pct(bars: Sequence[Bar], lookback: int) -> float | None:
    indicator = ATR(lookback)
    value = None
    for bar in bars:
        value = indicator.update(bar)
    if value is None or bars[-1].close <= 0.0:
        return None
    return value / bars[-1].close


class DirectionConsistencySelector:
    def __init__(self, *, signal_delay_bars: int = 0) -> None:
        if signal_delay_bars < 0:
            raise ValueError("signal delay must be non-negative")
        self.signal_delay_bars = signal_delay_bars

    def __call__(
        self,
        bars: Mapping[str, Sequence[Bar]],
        rules: Mapping[str, Mapping[str, Any]],
        equity: float,
        _base_config: Any,
    ) -> tuple[Mapping[str, float], str, bool]:
        protocol = MULTI_SPEED_TREND_PROTOCOL
        signal_bars = {
            symbol: list(rows[:-self.signal_delay_bars]) if self.signal_delay_bars else list(rows)
            for symbol, rows in bars.items()
        }
        required = max(
            max(protocol.direction_lookbacks),
            protocol.slow_gate_lookback,
            protocol.vol_lookback,
            protocol.atr_lookback,
        ) + 1
        if any(len(signal_bars[symbol]) < required for symbol in TOP3):
            return {symbol: 0.0 for symbol in TOP3}, "cash_warmup", True

        slow_positive = {
            symbol: _trailing_return(signal_bars[symbol], protocol.slow_gate_lookback) > 0.0
            for symbol in TOP3
        }
        gate_on = slow_positive["BTCUSDT"] or (
            sum(slow_positive.values()) / len(TOP3) >= protocol.slow_gate_breadth
        )
        if not gate_on:
            return {symbol: 0.0 for symbol in TOP3}, "cash_slow_gate", True

        returns_by_symbol = {
            symbol: _daily_returns(signal_bars[symbol], protocol.vol_lookback)
            for symbol in TOP3
        }
        raw: dict[str, float] = {}
        scales: dict[str, float] = {}
        for symbol in TOP3:
            votes = sum(
                _trailing_return(signal_bars[symbol], lookback) > 0.0
                for lookback in protocol.direction_lookbacks
            )
            if votes < protocol.required_positive_votes:
                continue
            volatility = statistics.stdev(returns_by_symbol[symbol])
            atr_pct = _atr_pct(signal_bars[symbol], protocol.atr_lookback)
            if volatility <= 0.0 or atr_pct is None or atr_pct <= 0.0:
                continue
            correlations = [
                _correlation(returns_by_symbol[symbol], returns_by_symbol[other])
                for other in TOP3
                if other != symbol
            ]
            average_correlation = statistics.mean(correlations) if correlations else 0.0
            raw[symbol] = 1.0 / volatility / max(average_correlation, protocol.corr_floor)
            scales[symbol] = min(1.0, protocol.vol_target / atr_pct)

        if not raw:
            return {symbol: 0.0 for symbol in TOP3}, "cash_no_consensus", True
        raw_total = sum(raw.values())
        proposed = {
            symbol: raw[symbol] / raw_total * scales[symbol]
            for symbol in raw
        }
        gross = min(sum(proposed.values()), protocol.maximum_effective_gross)
        current_prices = {symbol: bars[symbol][-1].close for symbol in TOP3}
        allocated, feasible = allocate_with_filters(
            proposed,
            gross,
            equity,
            current_prices,
            rules,
        )
        return allocated, "multi_speed_direction_consistency", feasible


def _compound(returns: Sequence[float]) -> float:
    nav = 1.0
    for value in returns:
        nav *= 1.0 + float(value)
    return nav


def _cagr(nav: float, bars: int) -> float:
    return nav ** (365.0 / bars) - 1.0 if nav > 0.0 and bars > 0 else -1.0


def _summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    net = [float(row["net_return"]) for row in rows]
    gross_price = [float(row["gross_price_return"]) for row in rows]
    standalone_nav = _compound(net)
    signal_nav = _compound(gross_price)
    std = statistics.stdev(net) if len(net) > 1 else 0.0
    sharpe = statistics.mean(net) / std * math.sqrt(365.0) if std > 0.0 else 0.0
    standalone_curve = [1.0]
    for value in net:
        standalone_curve.append(standalone_curve[-1] * (1.0 + value))
    turnover = sum(float(row["turnover"]) for row in rows)
    break_even = (
        sum(float(row["gross_price_return"]) + float(row["funding_return"]) for row in rows)
        / turnover
        * 10_000.0
        if turnover > 0.0
        else 0.0
    )
    return {
        "start": rows[0]["decision_date"] if rows else None,
        "end": rows[-1]["outcome_date"] if rows else None,
        "bars": len(rows),
        "signal_nav": signal_nav,
        "standalone_nav": standalone_nav,
        "standalone_cagr": _cagr(standalone_nav, len(rows)),
        "standalone_sharpe": sharpe,
        "max_drawdown_pct": max_drawdown_pct(standalone_curve),
        "total_turnover": turnover,
        "average_gross": statistics.mean(float(row["gross"]) for row in rows) if rows else 0.0,
        "active_bar_count": sum(float(row["gross"]) > 0.0 for row in rows),
        "order_count": sum(int(row["orders"]) for row in rows),
        "trading_cost_return_sum": sum(float(row["trading_cost_return"]) for row in rows),
        "funding_return_sum": sum(float(row["funding_return"]) for row in rows),
        "break_even_execution_cost_bps_per_turnover": break_even,
        "independent_nav_reconciliation_difference": abs(
            standalone_nav - (float(rows[-1]["equity"]) / MULTI_SPEED_TREND_PROTOCOL.capital_usdt)
        ) if rows else 0.0,
    }


def _benchmark_returns(
    aligned: Mapping[str, Sequence[Bar]], rows: Sequence[Mapping[str, Any]]
) -> tuple[list[float], list[float]]:
    index_by_date = {
        bar.date: index for index, bar in enumerate(aligned["BTCUSDT"])
    }
    btc: list[float] = []
    top3: list[float] = []
    for row in rows:
        index = index_by_date[str(row["decision_date"])]
        values = [
            aligned[symbol][index + 1].close / aligned[symbol][index].close - 1.0
            for symbol in TOP3
        ]
        btc.append(values[0])
        top3.append(statistics.mean(values))
    return btc, top3


def _beta_summary(strategy: Sequence[float], benchmark: Sequence[float]) -> dict[str, float]:
    x_mean = statistics.mean(benchmark)
    y_mean = statistics.mean(strategy)
    variance = sum((value - x_mean) ** 2 for value in benchmark)
    beta = (
        sum((x - x_mean) * (y - y_mean) for x, y in zip(benchmark, strategy)) / variance
        if variance > 0.0 else 0.0
    )
    alpha_daily = y_mean - beta * x_mean
    residuals = [y - beta * x for x, y in zip(benchmark, strategy)]
    residual_nav = _compound(residuals)
    fitted_variance = sum((beta * (x - x_mean)) ** 2 for x in benchmark)
    total_variance = sum((y - y_mean) ** 2 for y in strategy)
    return {
        "beta": beta,
        "annualized_alpha": alpha_daily * 365.0,
        "residual_nav": residual_nav,
        "residual_cagr": _cagr(residual_nav, len(residuals)),
        "r_squared": fitted_variance / total_variance if total_variance > 0.0 else 0.0,
    }


def _segments(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        segment | _summary([
            row for row in rows
            if segment["start"] <= str(row["outcome_date"]) <= segment["end"]
        ])
        for segment in MULTI_SPEED_TREND_PROTOCOL.segments
    ]


def compact_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    fields = (
        "decision_date", "outcome_date", "equity", "mode", "gross", "turnover",
        "orders", "gross_price_return", "funding_return", "trading_cost_return", "net_return",
    )
    return [{field: row[field] for field in fields} for row in rows]


def build_multi_speed_report(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    funding_by_symbol: Mapping[str, Sequence[Funding]],
    preregistration: Mapping[str, Any],
    *,
    funding_complete: bool,
    observed_at: str,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    validate_multi_speed_preregistration(preregistration)
    protocol = MULTI_SPEED_TREND_PROTOCOL
    aligned = align_bars(bars_by_symbol, TOP3)
    rules = research_rules()
    base_config = frozen_top3_config()
    base = run_variant(
        aligned, funding_by_symbol, rules,
        recovery_enabled=False, base_config=base_config, capital_usdt=protocol.capital_usdt,
        gross_cap_policy="renormalize_active_targets_with_filter_floors",
    )
    candidate = run_variant(
        aligned, funding_by_symbol, rules,
        recovery_enabled=False, base_config=base_config, capital_usdt=protocol.capital_usdt,
        desired_weights_selector=DirectionConsistencySelector(),
        gross_cap_policy="renormalize_active_targets_with_filter_floors",
    )
    base_doubled = run_variant(
        aligned, funding_by_symbol, rules,
        recovery_enabled=False, base_config=base_config, capital_usdt=protocol.capital_usdt,
        transaction_cost_multiplier=protocol.transaction_cost_multiplier_stress,
        gross_cap_policy="renormalize_active_targets_with_filter_floors",
    )
    candidate_doubled = run_variant(
        aligned, funding_by_symbol, rules,
        recovery_enabled=False, base_config=base_config, capital_usdt=protocol.capital_usdt,
        desired_weights_selector=DirectionConsistencySelector(),
        transaction_cost_multiplier=protocol.transaction_cost_multiplier_stress,
        gross_cap_policy="renormalize_active_targets_with_filter_floors",
    )
    candidate_delayed = run_variant(
        aligned, funding_by_symbol, rules,
        recovery_enabled=False, base_config=base_config, capital_usdt=protocol.capital_usdt,
        desired_weights_selector=DirectionConsistencySelector(
            signal_delay_bars=protocol.signal_delay_stress_bars
        ),
        gross_cap_policy="renormalize_active_targets_with_filter_floors",
    )

    summaries = {
        "base": _summary(base.equity),
        "candidate": _summary(candidate.equity),
        "base_doubled_cost": _summary(base_doubled.equity),
        "candidate_doubled_cost": _summary(candidate_doubled.equity),
        "candidate_one_bar_delay": _summary(candidate_delayed.equity),
    }
    candidate_net = [float(row["net_return"]) for row in candidate.equity]
    btc_returns, top3_returns = _benchmark_returns(aligned, candidate.equity)
    beta = {
        "btc": _beta_summary(candidate_net, btc_returns),
        "top3_equal_weight": _beta_summary(candidate_net, top3_returns),
    }
    base_segments = _segments(base.equity)
    candidate_segments = _segments(candidate.equity)
    segment_comparison = [
        {
            "label": candidate_row["label"],
            "base_standalone_cagr": base_row["standalone_cagr"],
            "candidate_standalone_cagr": candidate_row["standalone_cagr"],
            "candidate_minus_base_cagr": (
                candidate_row["standalone_cagr"] - base_row["standalone_cagr"]
            ),
            "base_max_drawdown_pct": base_row["max_drawdown_pct"],
            "candidate_max_drawdown_pct": candidate_row["max_drawdown_pct"],
        }
        for base_row, candidate_row in zip(base_segments, candidate_segments)
    ]
    outperformance_count = sum(row["candidate_minus_base_cagr"] > 0.0 for row in segment_comparison)
    max_gross = max(
        float(row["gross"])
        for rows in (base.equity, candidate.equity, base_doubled.equity, candidate_doubled.equity, candidate_delayed.equity)
        for row in rows
    )
    reconciliation_pass = all(
        summary["independent_nav_reconciliation_difference"] <= 1e-7
        for summary in summaries.values()
    )
    gates = {
        "candidate_standalone_cagr_above_base": (
            summaries["candidate"]["standalone_cagr"] > summaries["base"]["standalone_cagr"]
        ),
        "maximum_drawdown_worsening_within_2pp": (
            summaries["candidate"]["max_drawdown_pct"]
            <= summaries["base"]["max_drawdown_pct"] + protocol.maximum_drawdown_worsening_pp
        ),
        "candidate_top3_beta_residual_cagr_positive": beta["top3_equal_weight"]["residual_cagr"] > 0.0,
        "candidate_outperforms_base_in_at_least_2_segments": (
            outperformance_count >= protocol.minimum_positive_segment_outperformance
        ),
        "candidate_cagr_positive_at_doubled_execution_cost": (
            summaries["candidate_doubled_cost"]["standalone_cagr"] > 0.0
        ),
        "candidate_cagr_positive_with_one_bar_signal_delay": (
            summaries["candidate_one_bar_delay"]["standalone_cagr"] > 0.0
        ),
        "gross_cap_respected": max_gross <= protocol.maximum_effective_gross + 1e-12,
        "independent_nav_reconciliation_pass": reconciliation_pass,
        "funding_history_complete": funding_complete,
    }
    retained = all(gates.values())
    data_basis = {
        "bars": {
            symbol: [[bar.ts_ms, bar.open, bar.high, bar.low, bar.close, bar.volume] for bar in aligned[symbol]]
            for symbol in TOP3
        },
        "funding": {
            symbol: [[row.ts_ms, row.rate] for row in funding_by_symbol[symbol]]
            for symbol in TOP3
        },
    }
    report = {
        "schema_version": MULTI_SPEED_REPORT_VERSION,
        "artifact_type": "crypto_multi_speed_trend_trial",
        "observed_at": observed_at,
        "meta": {
            "research_only": True,
            "data_role": "consumed_historical_discovery_pool",
            "strategy_results_evaluated": True,
            "standalone_executable_nav_evaluated": False,
            "standalone_executable_proxy_evaluated": True,
            "promotion_evidence": False,
            "orders_authorized": False,
        },
        "contract_hash": protocol.contract_hash,
        "protocol_hash": protocol.protocol_hash,
        "data": {
            "first_common_date": aligned["BTCUSDT"][0].date,
            "last_common_date": aligned["BTCUSDT"][-1].date,
            "common_bar_count": len(aligned["BTCUSDT"]),
            "data_hash": canonical_hash(data_basis),
            "funding_complete": funding_complete,
            "rules_role": "estimated_research_proxy_not_venue_certified",
        },
        "summaries": summaries,
        "beta_residual": beta,
        "segments": segment_comparison,
        "diagnostics": {
            "gates": gates,
            "passed_gate_count": sum(gates.values()),
            "gate_count": len(gates),
            "segment_outperformance_count": outperformance_count,
            "maximum_observed_gross": max_gross,
            "verdict": (
                "retain_direction_consistency_for_family_review"
                if retained
                else "reject_direction_consistency_continue_distinct_family_trials"
            ),
            "candidate_pnl_ready": False,
            "promotion_evidence": False,
            "orders_authorized": False,
            "remaining_blockers": [
                "all_history_is_consumed_discovery_data",
                "historical_exchange_rules_are_not_point_in_time_certified",
                "bid_ask_and_fill_costs_are_estimated",
                "eligible_new_time_evidence_missing",
            ],
        },
    }
    trajectories = {
        "base": compact_rows(base.equity),
        "candidate": compact_rows(candidate.equity),
        "base_doubled_cost": compact_rows(base_doubled.equity),
        "candidate_doubled_cost": compact_rows(candidate_doubled.equity),
        "candidate_one_bar_delay": compact_rows(candidate_delayed.equity),
    }
    return report, trajectories
