"""Trial 146: continuous multi-speed z-score forecast for the TOP3 UM research line.

This is the second formal trial of ``multi_speed_trend_v1``. It is a distinct
mechanism from Trial 145's direction-consistency vote: trailing 20/60/120-day
returns are standardized against a past-only 252-day window of the same trailing
return, equally weighted, clipped to [-2, 2], and only positive composites
participate (long/cash). The signal strength modulates relative allocation
through the same vol-inverse / correlation / ATR sizing framework as Trial 145,
so the comparison cleanly isolates the forecast mechanism. Trial 145 parameters
remain frozen and are not rescued here.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from qount.contracts import canonical_hash
from qount.grid.data import Bar, Funding
from qount.mini_trend.backtest import align_bars
from qount.mini_trend.forward import TOP3, frozen_top3_config
from qount.mini_trend.futures_recovery import FUTURES_RECOVERY_PROTOCOL
from qount.mini_trend.futures_recovery_backtest import allocate_with_filters, run_variant
from qount.mini_trend.multi_speed_trend import (
    _atr_pct,
    _benchmark_returns,
    _beta_summary,
    _compound,
    _cagr,
    _correlation,
    _daily_returns,
    compact_rows,
)
from qount.mini_trend.scorecard import max_drawdown_pct
from qount.x4.indicators import ATR  # noqa: F401  (kept for parity with sibling module)


CONTINUOUS_FORECAST_PREREG_VERSION = "crypto_multi_speed_continuous_forecast_preregistration_v0.1"
CONTINUOUS_FORECAST_REPORT_VERSION = "crypto_multi_speed_continuous_forecast_trial_v0.1"


@dataclass(frozen=True)
class MultiSpeedContinuousForecastProtocol:
    hypothesis_family: str = "multi_speed_trend_v1"
    candidate_id: str = "multi_speed_continuous_forecast_v1"
    global_trial_number: int = 146
    trial_number_within_family: int = 2
    family_trial_budget: int = 3
    market: str = "um"
    interval: str = "1d"
    universe: tuple[str, ...] = TOP3
    start_month: str = "2020-02"
    end_month: str = "2026-06"
    direction_lookbacks: tuple[int, ...] = (20, 60, 120)
    forecast_weights: tuple[float, ...] = (1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0)
    zscore_standardization_window: int = 252
    forecast_clip: float = 2.0
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
                "factor": "z-score standardized trailing total return",
                "direction_lookbacks": list(self.direction_lookbacks),
                "forecast_weights": list(self.forecast_weights),
                "zscore_standardization_window": self.zscore_standardization_window,
                "forecast_clip": self.forecast_clip,
                "positive_only_long_cash": True,
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
                "Formal discovery trial 146. A rejection applies to the continuous z-score "
                "forecast, not to Trial 145's direction-consistency baseline or Trial 147's "
                "layered state machine."
            ),
            "candidate_pnl_ready": False,
            "promotion_evidence": False,
            "orders_authorized": False,
        }

    @property
    def protocol_hash(self) -> str:
        return canonical_hash(self.protocol_basis)


CONTINUOUS_FORECAST_PROTOCOL = MultiSpeedContinuousForecastProtocol()


def build_continuous_forecast_preregistration(created_at: str) -> dict[str, Any]:
    protocol = CONTINUOUS_FORECAST_PROTOCOL
    return {
        "schema_version": CONTINUOUS_FORECAST_PREREG_VERSION,
        "artifact_type": "crypto_multi_speed_continuous_forecast_preregistration",
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


def validate_continuous_forecast_preregistration(payload: Mapping[str, Any]) -> None:
    protocol = CONTINUOUS_FORECAST_PROTOCOL
    if payload.get("schema_version") != CONTINUOUS_FORECAST_PREREG_VERSION:
        raise ValueError("unexpected continuous-forecast preregistration schema")
    decision_contract = dict(payload.get("decision_contract", {}))
    declared_contract_hash = decision_contract.pop("contract_hash", None)
    if (
        declared_contract_hash != protocol.contract_hash
        or canonical_hash(decision_contract) != protocol.contract_hash
    ):
        raise ValueError("continuous-forecast contract hash mismatch")
    protocol_payload = dict(payload.get("protocol", {}))
    declared_protocol_hash = protocol_payload.pop("protocol_hash", None)
    if (
        declared_protocol_hash != protocol.protocol_hash
        or canonical_hash(protocol_payload) != protocol.protocol_hash
    ):
        raise ValueError("continuous-forecast protocol hash mismatch")
    if payload.get("meta", {}).get("strategy_results_evaluated") is not False:
        raise ValueError("continuous-forecast preregistration contains evaluated results")


def research_rules() -> dict[str, dict[str, float]]:
    floor = CONTINUOUS_FORECAST_PROTOCOL.estimated_min_notional_usdt
    return {symbol: {"min_notional": floor, "min_qty": 0.0} for symbol in TOP3}


def _zscore(closes: Sequence[float], lookback: int, window: int) -> float:
    if len(closes) < lookback + window + 1:
        return 0.0
    current = closes[-1] / closes[-1 - lookback] - 1.0
    past = [
        closes[-1 - offset] / closes[-1 - offset - lookback] - 1.0
        for offset in range(1, window + 1)
    ]
    if len(past) < 2:
        return 0.0
    mean = statistics.mean(past)
    std = statistics.pstdev(past)
    if std <= 0.0:
        return 0.0
    return (current - mean) / std


def _forecast_composite(bars: Sequence[Bar], protocol: MultiSpeedContinuousForecastProtocol) -> float:
    closes = [bar.close for bar in bars]
    composite = 0.0
    for lookback, weight in zip(protocol.direction_lookbacks, protocol.forecast_weights):
        composite += weight * _zscore(closes, lookback, protocol.zscore_standardization_window)
    return max(min(composite, protocol.forecast_clip), -protocol.forecast_clip)


class ContinuousForecastSelector:
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
        protocol = CONTINUOUS_FORECAST_PROTOCOL
        signal_bars = {
            symbol: list(rows[:-self.signal_delay_bars]) if self.signal_delay_bars else list(rows)
            for symbol, rows in bars.items()
        }
        required = max(
            lb + protocol.zscore_standardization_window + 1 for lb in protocol.direction_lookbacks
        )
        required = max(required, protocol.vol_lookback, protocol.atr_lookback) + 1
        if any(len(signal_bars[symbol]) < required for symbol in TOP3):
            return {symbol: 0.0 for symbol in TOP3}, "cash_warmup", True

        returns_by_symbol = {
            symbol: _daily_returns(signal_bars[symbol], protocol.vol_lookback)
            for symbol in TOP3
        }
        raw: dict[str, float] = {}
        scales: dict[str, float] = {}
        for symbol in TOP3:
            signal = _forecast_composite(signal_bars[symbol], protocol)
            if signal <= 0.0:
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
            raw[symbol] = signal / volatility / max(average_correlation, protocol.corr_floor)
            scales[symbol] = min(1.0, protocol.vol_target / atr_pct)

        if not raw:
            return {symbol: 0.0 for symbol in TOP3}, "cash_no_positive_forecast", True
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
        return allocated, "multi_speed_continuous_forecast", feasible


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
            standalone_nav - (float(rows[-1]["equity"]) / CONTINUOUS_FORECAST_PROTOCOL.capital_usdt)
        ) if rows else 0.0,
    }


def _segments(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        segment | _summary([
            row for row in rows
            if segment["start"] <= str(row["outcome_date"]) <= segment["end"]
        ])
        for segment in CONTINUOUS_FORECAST_PROTOCOL.segments
    ]


def build_continuous_forecast_report(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    funding_by_symbol: Mapping[str, Sequence[Funding]],
    preregistration: Mapping[str, Any],
    *,
    funding_complete: bool,
    observed_at: str,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    validate_continuous_forecast_preregistration(preregistration)
    protocol = CONTINUOUS_FORECAST_PROTOCOL
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
        desired_weights_selector=ContinuousForecastSelector(),
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
        desired_weights_selector=ContinuousForecastSelector(),
        transaction_cost_multiplier=protocol.transaction_cost_multiplier_stress,
        gross_cap_policy="renormalize_active_targets_with_filter_floors",
    )
    candidate_delayed = run_variant(
        aligned, funding_by_symbol, rules,
        recovery_enabled=False, base_config=base_config, capital_usdt=protocol.capital_usdt,
        desired_weights_selector=ContinuousForecastSelector(
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
        "schema_version": CONTINUOUS_FORECAST_REPORT_VERSION,
        "artifact_type": "crypto_multi_speed_continuous_forecast_trial",
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
                "retain_continuous_forecast_for_family_review"
                if retained
                else "reject_continuous_forecast_continue_distinct_family_trials"
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
