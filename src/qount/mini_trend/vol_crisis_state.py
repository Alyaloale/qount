"""Trial 148: crypto_vol_crisis_state_v1 -- crisis RiskMultiplier overlay.

Outputs ``RiskMultiplier in [0, 1]`` from a three-signal composite:
downside semi-variance, BTC-alt correlation surge and funding extremes.
Each signal is z-scored against a past-only 252-day window; the composite
maps linearly to [0, 1] where 0 = full de-risk, 1 = full risk.

The RiskMultiplier is applied as an overlay to three baselines (Base,
multi-speed direction consistency, fixed vol-target) and the trial reports
``drawdown_saved / return_sacrificed`` plus tail residual for each.

Distinction from prior evidence (frozen in contract):
- vs price-only vol/HMM/GRU: adds funding extremes and BTC-alt correlation,
  not price-only volatility.
- vs Trial 147 fast de-risk: multi-signal continuous RiskMultiplier, not a
  binary 20-day return sign; applied as risk overlay, not standalone signal.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from qount.contracts import canonical_hash
from qount.research_data.market_data import Bar, Funding
from qount.mini_trend.backtest import align_bars
from qount.mini_trend.forward import TOP3, frozen_top3_config
from qount.mini_trend.futures_recovery import FUTURES_RECOVERY_PROTOCOL
from qount.mini_trend.futures_recovery_backtest import (
    allocate_with_filters,
    desired_weights,
    run_variant,
)
from qount.mini_trend.multi_speed_trend import (
    DirectionConsistencySelector,
    _atr_pct,
    _beta_summary,
    _compound,
    _cagr,
    _correlation,
    _daily_returns,
    compact_rows,
)
from qount.mini_trend.scorecard import max_drawdown_pct
from qount.research_data.indicators import ATR  # noqa: F401


CRISIS_STATE_PREREG_VERSION = "crypto_vol_crisis_state_preregistration_v0.1"
CRISIS_STATE_REPORT_VERSION = "crypto_vol_crisis_state_trial_v0.1"
_DAY_MS = 86_400_000


@dataclass(frozen=True)
class VolCrisisStateProtocol:
    hypothesis_family: str = "crypto_vol_crisis_state_v1"
    candidate_id: str = "crypto_vol_crisis_risk_multiplier_v1"
    global_trial_number: int = 148
    trial_number_within_family: int = 1
    family_trial_budget: int = 3
    market: str = "um"
    interval: str = "1d"
    universe: tuple[str, ...] = TOP3
    start_month: str = "2020-02"
    end_month: str = "2026-06"
    downside_semi_var_lookback: int = 20
    correlation_lookback: int = 60
    funding_lookback: int = 30
    zscore_standardization_window: int = 252
    crisis_threshold: float = 2.0
    return_sacrifice_budget_pct: float = 5.0
    minimum_improvement_segments: int = 2
    vol_lookback: int = 20
    atr_lookback: int = 14
    vol_target: float = 0.015
    corr_floor: float = 0.2
    maximum_effective_gross: float = 1.0
    capital_usdt: float = 400.0
    estimated_min_notional_usdt: float = 5.0

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
                "architecture": "three_signal_crisis_risk_multiplier",
                "decision_timing": (
                    "decision_after_aligned_bar_close; target weights apply from bar i close "
                    "through bar i+1 close"
                ),
                "feature_visibility": (
                    "price features include returns ending at decision bar i; funding features "
                    "include only settlements in the completed interval before bar i"
                ),
                "funding_interval_semantics": "(bar_open_i, bar_open_i+1]",
                "downside_semi_variance": {
                    "lookback": self.downside_semi_var_lookback,
                    "zscore_window": self.zscore_standardization_window,
                },
                "btc_alt_correlation_surge": {
                    "lookback": self.correlation_lookback,
                    "zscore_window": self.zscore_standardization_window,
                    "pairs": ["BTC-ETH", "BTC-BNB"],
                },
                "funding_extremes": {
                    "lookback": self.funding_lookback,
                    "zscore_window": self.zscore_standardization_window,
                    "symbol": "BTCUSDT",
                },
                "composite": "equal_weight_z_score_mean",
                "risk_multiplier_mapping": f"clip(1 - max(0, crisis_z) / {self.crisis_threshold}, 0, 1)",
                "distinction_from_price_only_vol": "adds funding extremes and btc-alt correlation; not price-only volatility",
                "distinction_from_trial_147_fast_derisk": "multi-signal continuous risk multiplier; not binary 20-day return sign",
                "parameter_search_allowed": False,
            },
            "baselines": ["MiniTrend-UM-Base-v0.2", "multi_speed_direction_consistency_v1", "fixed_vol_target"],
            "kill_tests": {
                "return_sacrifice_exceeds_budget": f"return_sacrificed > {self.return_sacrifice_budget_pct}% CAGR for all baselines",
                "tail_residual_no_improvement": "crisis-scaled tail residual not better for any baseline",
                "single_crash_fit": f"drawdown improvement in fewer than {self.minimum_improvement_segments} segments for all baselines",
            },
            "output_role": "risk_multiplier_overlay_not_direction",
            "candidate_pnl_ready": False,
            "promotion_evidence": False,
            "orders_authorized": False,
        }

    @property
    def contract_hash(self) -> str:
        return canonical_hash(self.contract_basis)

    @property
    def protocol_basis(self) -> dict[str, Any]:
        return {
            "contract_hash": self.contract_hash,
            "primary_metric": "drawdown_saved_per_return_sacrificed",
            "failure_conditions": [
                "return_sacrifice_exceeds_budget_for_all_baselines",
                "tail_residual_no_improvement_for_any_baseline",
                "single_crash_fit_for_all_baselines",
                "gross_cap_or_nav_reconciliation_failure",
                "funding_history_has_zero_settlement_holding_interval",
            ],
            "allowed_sensitivity_range": {},
            "segments": list(self.segments),
            "interpretation": (
                "Formal discovery trial 148. Tests whether a three-signal crisis "
                "RiskMultiplier improves drawdown without excessive return sacrifice. "
                "A rejection does not rescue Trials 145/146/147."
            ),
            "candidate_pnl_ready": False,
            "promotion_evidence": False,
            "orders_authorized": False,
        }

    @property
    def protocol_hash(self) -> str:
        return canonical_hash(self.protocol_basis)


CRISIS_STATE_PROTOCOL = VolCrisisStateProtocol()


def build_crisis_state_preregistration(created_at: str) -> dict[str, Any]:
    protocol = CRISIS_STATE_PROTOCOL
    return {
        "schema_version": CRISIS_STATE_PREREG_VERSION,
        "artifact_type": "crypto_vol_crisis_state_preregistration",
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


def validate_crisis_state_preregistration(payload: Mapping[str, Any]) -> None:
    protocol = CRISIS_STATE_PROTOCOL
    if payload.get("schema_version") != CRISIS_STATE_PREREG_VERSION:
        raise ValueError("unexpected crisis-state preregistration schema")
    decision_contract = dict(payload.get("decision_contract", {}))
    declared_contract_hash = decision_contract.pop("contract_hash", None)
    if declared_contract_hash != protocol.contract_hash or canonical_hash(decision_contract) != protocol.contract_hash:
        raise ValueError("crisis-state contract hash mismatch")
    protocol_payload = dict(payload.get("protocol", {}))
    declared_protocol_hash = protocol_payload.pop("protocol_hash", None)
    if declared_protocol_hash != protocol.protocol_hash or canonical_hash(protocol_payload) != protocol.protocol_hash:
        raise ValueError("crisis-state protocol hash mismatch")
    if payload.get("meta", {}).get("strategy_results_evaluated") is not False:
        raise ValueError("crisis-state preregistration contains evaluated results")


def research_rules() -> dict[str, dict[str, float]]:
    floor = CRISIS_STATE_PROTOCOL.estimated_min_notional_usdt
    return {symbol: {"min_notional": floor, "min_qty": 0.0} for symbol in TOP3}


# --- Signal pre-computation --------------------------------------------------


def _zscore_last(values: Sequence[float], window: int) -> float:
    if len(values) < window + 1:
        return 0.0
    current = values[-1]
    past = list(values[-(window + 1):-1])
    if len(past) < 2:
        return 0.0
    mean = statistics.mean(past)
    std = statistics.pstdev(past)
    return (current - mean) / std if std > 0.0 else 0.0


def _downside_semi_var_series(closes: Sequence[float], lookback: int) -> list[float]:
    returns = [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes))]
    series: list[float] = []
    for i in range(lookback, len(returns) + 1):
        window = returns[i - lookback:i]
        negative = [r for r in window if r < 0.0]
        series.append(sum(r * r for r in negative) / lookback if negative else 0.0)
    return series


def _correlation_series(closes_a: Sequence[float], closes_b: Sequence[float], lookback: int) -> list[float]:
    n = min(len(closes_a), len(closes_b))
    rets_a = [closes_a[i] / closes_a[i - 1] - 1.0 for i in range(1, n)]
    rets_b = [closes_b[i] / closes_b[i - 1] - 1.0 for i in range(1, n)]
    series: list[float] = []
    for i in range(lookback, len(rets_a) + 1):
        series.append(_correlation(rets_a[i - lookback:i], rets_b[i - lookback:i]) or 0.0)
    return series


def _daily_avg_funding(bars: Sequence[Bar], funding: Sequence[Funding]) -> list[float]:
    sorted_funding = sorted(funding, key=lambda r: r.ts_ms)
    result: list[float] = []
    fi = 0
    for i in range(len(bars) - 1):
        start_ms = bars[i].ts_ms
        end_ms = bars[i + 1].ts_ms
        rates: list[float] = []
        while fi < len(sorted_funding) and sorted_funding[fi].ts_ms <= end_ms:
            if sorted_funding[fi].ts_ms > start_ms:
                rates.append(abs(sorted_funding[fi].rate))
            fi += 1
        result.append(statistics.mean(rates) if rates else 0.0)
    return result


def _rolling_mean(values: Sequence[float], window: int) -> list[float]:
    series: list[float] = []
    for i in range(window, len(values) + 1):
        series.append(statistics.mean(values[i - window:i]))
    return series


def _feature_prefix_through_decision(
    series: Sequence[float], decision_index: int, lookback: int
) -> list[float]:
    """Return feature observations whose last one ends at the decision bar.

    A lookback-derived series starts at ``lookback`` because its first value uses
    returns ending at that bar. Therefore decision bar ``i`` maps to index
    ``i - lookback`` and must be included in the prefix for a close-time decision.
    """

    feature_index = decision_index - lookback
    if feature_index < 0:
        return []
    return list(series[: feature_index + 1])


def compute_risk_multiplier_series(
    aligned: Mapping[str, Sequence[Bar]],
    funding_by_symbol: Mapping[str, Sequence[Funding]],
) -> dict[str, float]:
    """Pre-compute RiskMultiplier for each close-time decision date.

    Funding observations are built as left-open/right-closed completed intervals;
    the decision at bar ``i`` can see the interval ending at bar ``i`` but never
    the interval from bar ``i`` to bar ``i+1``.
    """
    protocol = CRISIS_STATE_PROTOCOL
    btc_bars = aligned["BTCUSDT"]
    btc_closes = [bar.close for bar in btc_bars]
    eth_closes = [bar.close for bar in aligned["ETHUSDT"]]
    bnb_closes = [bar.close for bar in aligned["BNBUSDT"]]

    dsv = _downside_semi_var_series(btc_closes, protocol.downside_semi_var_lookback)
    corr_eth = _correlation_series(btc_closes, eth_closes, protocol.correlation_lookback)
    corr_bnb = _correlation_series(btc_closes, bnb_closes, protocol.correlation_lookback)
    corr_avg = [(a + b) / 2.0 for a, b in zip(corr_eth, corr_bnb)]
    daily_fund = _daily_avg_funding(btc_bars, funding_by_symbol.get("BTCUSDT", []))
    fund_rolling = _rolling_mean(daily_fund, protocol.funding_lookback)

    z_window = protocol.zscore_standardization_window
    rm_by_date: dict[str, float] = {}
    n_bars = len(btc_bars)
    for i in range(1, n_bars):
        z_dsv = _zscore_last(
            _feature_prefix_through_decision(
                dsv, i, protocol.downside_semi_var_lookback
            ),
            z_window,
        )
        z_corr = _zscore_last(
            _feature_prefix_through_decision(
                corr_avg, i, protocol.correlation_lookback
            ),
            z_window,
        )
        z_fund = _zscore_last(
            _feature_prefix_through_decision(
                fund_rolling, i, protocol.funding_lookback
            ),
            z_window,
        )
        crisis_z = (z_dsv + z_corr + z_fund) / 3.0
        rm = max(0.0, min(1.0, 1.0 - max(0.0, crisis_z) / protocol.crisis_threshold))
        rm_by_date[btc_bars[i].date] = rm
    return rm_by_date


# --- Selectors ---------------------------------------------------------------


class CrisisStateSelector:
    """Wraps a base selector (or Base when None) and scales weights by RiskMultiplier."""

    def __init__(
        self,
        base_selector: Callable | None,
        risk_multiplier_by_date: Mapping[str, float],
        *,
        signal_delay_bars: int = 0,
    ) -> None:
        self.base_selector = base_selector
        self._rm = dict(risk_multiplier_by_date)
        self.signal_delay_bars = signal_delay_bars

    def __call__(
        self,
        bars: Mapping[str, Sequence[Bar]],
        rules: Mapping[str, Mapping[str, Any]],
        equity: float,
        base_config: Any,
    ) -> tuple[Mapping[str, float], str, bool]:
        signal_bars = {
            symbol: list(rows[:-self.signal_delay_bars]) if self.signal_delay_bars else list(rows)
            for symbol, rows in bars.items()
        }
        if self.base_selector is None:
            weights, mode, feasible = desired_weights(
                signal_bars, rules, equity, recovery_enabled=False, base_config=base_config,
            )
        else:
            weights, mode, feasible = self.base_selector(signal_bars, rules, equity, base_config)
        decision_date = signal_bars["BTCUSDT"][-1].date
        rm = self._rm.get(decision_date, 1.0)
        scaled = {symbol: float(weight) * rm for symbol, weight in weights.items()}
        return scaled, f"{mode}_crisis_scaled", feasible


class FixedVolTargetSelector:
    """Simple always-hold vol-target baseline (no trend filter)."""

    def __init__(self, *, signal_delay_bars: int = 0) -> None:
        self.signal_delay_bars = signal_delay_bars

    def __call__(
        self,
        bars: Mapping[str, Sequence[Bar]],
        rules: Mapping[str, Mapping[str, Any]],
        equity: float,
        _base_config: Any,
    ) -> tuple[Mapping[str, float], str, bool]:
        protocol = CRISIS_STATE_PROTOCOL
        signal_bars = {
            symbol: list(rows[:-self.signal_delay_bars]) if self.signal_delay_bars else list(rows)
            for symbol, rows in bars.items()
        }
        required = max(protocol.vol_lookback, protocol.atr_lookback) + 1
        if any(len(signal_bars[symbol]) < required for symbol in TOP3):
            return {symbol: 0.0 for symbol in TOP3}, "cash_warmup", True
        raw: dict[str, float] = {}
        scales: dict[str, float] = {}
        for symbol in TOP3:
            returns = _daily_returns(signal_bars[symbol], protocol.vol_lookback)
            volatility = statistics.stdev(returns)
            atr_pct = _atr_pct(signal_bars[symbol], protocol.atr_lookback)
            if volatility <= 0.0 or atr_pct is None or atr_pct <= 0.0:
                continue
            raw[symbol] = 1.0 / volatility / max(0.2, protocol.corr_floor)
            scales[symbol] = min(1.0, protocol.vol_target / atr_pct)
        if not raw:
            return {symbol: 0.0 for symbol in TOP3}, "cash_no_vol_data", True
        raw_total = sum(raw.values())
        proposed = {symbol: raw[symbol] / raw_total * scales[symbol] for symbol in raw}
        gross = min(sum(proposed.values()), protocol.maximum_effective_gross)
        prices = {symbol: bars[symbol][-1].close for symbol in TOP3}
        allocated, feasible = allocate_with_filters(proposed, gross, equity, prices, rules)
        return allocated, "fixed_vol_target", feasible


# --- Report ------------------------------------------------------------------


def _summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    net = [float(row["net_return"]) for row in rows]
    gross_price = [float(row["gross_price_return"]) for row in rows]
    standalone_nav = _compound(net)
    std = statistics.stdev(net) if len(net) > 1 else 0.0
    sharpe = statistics.mean(net) / std * math.sqrt(365.0) if std > 0.0 else 0.0
    curve = [1.0]
    for value in net:
        curve.append(curve[-1] * (1.0 + value))
    return {
        "bars": len(rows),
        "standalone_nav": standalone_nav,
        "standalone_cagr": _cagr(standalone_nav, len(rows)),
        "standalone_sharpe": sharpe,
        "max_drawdown_pct": max_drawdown_pct(curve),
        "total_turnover": sum(float(row["turnover"]) for row in rows),
        "average_gross": statistics.mean(float(row["gross"]) for row in rows) if rows else 0.0,
        "independent_nav_reconciliation_difference": abs(
            standalone_nav - (float(rows[-1]["equity"]) / CRISIS_STATE_PROTOCOL.capital_usdt)
        ) if rows else 0.0,
    }


def _segments(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        segment | _summary([
            row for row in rows
            if segment["start"] <= str(row["outcome_date"]) <= segment["end"]
        ])
        for segment in CRISIS_STATE_PROTOCOL.segments
    ]


def _max_dd_from_rows(rows: Sequence[Mapping[str, Any]]) -> float:
    net = [float(row["net_return"]) for row in rows]
    curve = [1.0]
    for value in net:
        curve.append(curve[-1] * (1.0 + value))
    return max_drawdown_pct(curve)


def build_crisis_state_report(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    funding_by_symbol: Mapping[str, Sequence[Funding]],
    preregistration: Mapping[str, Any],
    *,
    funding_complete: bool,
    observed_at: str,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    validate_crisis_state_preregistration(preregistration)
    protocol = CRISIS_STATE_PROTOCOL
    aligned = align_bars(bars_by_symbol, TOP3)
    rules = research_rules()
    base_config = frozen_top3_config()
    rm_series = compute_risk_multiplier_series(aligned, funding_by_symbol)

    common = dict(
        recovery_enabled=False, base_config=base_config, capital_usdt=protocol.capital_usdt,
        gross_cap_policy="renormalize_active_targets_with_filter_floors",
    )

    variants = {
        "base": run_variant(aligned, funding_by_symbol, rules, desired_weights_selector=None, **common),
        "base_crisis": run_variant(
            aligned, funding_by_symbol, rules,
            desired_weights_selector=CrisisStateSelector(None, rm_series), **common,
        ),
        "multi": run_variant(
            aligned, funding_by_symbol, rules,
            desired_weights_selector=DirectionConsistencySelector(), **common,
        ),
        "multi_crisis": run_variant(
            aligned, funding_by_symbol, rules,
            desired_weights_selector=CrisisStateSelector(DirectionConsistencySelector(), rm_series), **common,
        ),
        "voltarget": run_variant(
            aligned, funding_by_symbol, rules,
            desired_weights_selector=FixedVolTargetSelector(), **common,
        ),
        "voltarget_crisis": run_variant(
            aligned, funding_by_symbol, rules,
            desired_weights_selector=CrisisStateSelector(FixedVolTargetSelector(), rm_series), **common,
        ),
    }

    summaries = {key: _summary(variant.equity) for key, variant in variants.items()}

    baseline_pairs = [("base", "base_crisis"), ("multi", "multi_crisis"), ("voltarget", "voltarget_crisis")]
    crisis_comparison = []
    for base_key, crisis_key in baseline_pairs:
        base_sum = summaries[base_key]
        crisis_sum = summaries[crisis_key]
        dd_saved = base_sum["max_drawdown_pct"] - crisis_sum["max_drawdown_pct"]
        ret_sacrificed = base_sum["standalone_cagr"] - crisis_sum["standalone_cagr"]
        ratio = dd_saved / ret_sacrificed if abs(ret_sacrificed) > 1e-12 else float("inf") if dd_saved > 0 else 0.0
        base_net = [float(r["net_return"]) for r in variants[base_key].equity]
        crisis_net = [float(r["net_return"]) for r in variants[crisis_key].equity]
        btc_returns = [
            aligned["BTCUSDT"][i + 1].close / aligned["BTCUSDT"][i].close - 1.0
            for i in range(len(variants[crisis_key].equity))
        ]
        top3_returns = [
            statistics.mean([
                aligned[s][i + 1].close / aligned[s][i].close - 1.0 for s in TOP3
            ])
            for i in range(len(variants[crisis_key].equity))
        ]
        crisis_comparison.append({
            "baseline": base_key,
            "baseline_cagr": base_sum["standalone_cagr"],
            "crisis_cagr": crisis_sum["standalone_cagr"],
            "baseline_maxdd": base_sum["max_drawdown_pct"],
            "crisis_maxdd": crisis_sum["max_drawdown_pct"],
            "drawdown_saved": dd_saved,
            "return_sacrificed": ret_sacrificed,
            "drawdown_saved_per_return_sacrificed": ratio,
            "crisis_top3_beta_residual": _beta_summary(crisis_net, top3_returns),
            "baseline_top3_beta_residual": _beta_summary(base_net, top3_returns),
        })

    max_gross = max(float(row["gross"]) for variant in variants.values() for row in variant.equity)
    reconciliation_pass = all(
        summary["independent_nav_reconciliation_difference"] <= 1e-7 for summary in summaries.values()
    )

    any_sacrifice_within_budget = any(
        cmp["return_sacrificed"] <= protocol.return_sacrifice_budget_pct / 100.0
        for cmp in crisis_comparison
    )
    any_tail_improvement = any(
        cmp["crisis_top3_beta_residual"]["residual_cagr"]
        >= cmp["baseline_top3_beta_residual"]["residual_cagr"]
        for cmp in crisis_comparison
    )
    segment_improvements = []
    for base_key, crisis_key in baseline_pairs:
        base_segs = _segments(variants[base_key].equity)
        crisis_segs = _segments(variants[crisis_key].equity)
        improved = sum(
            1 for b, c in zip(base_segs, crisis_segs)
            if c.get("max_drawdown_pct", 0) < b.get("max_drawdown_pct", 0)
        )
        segment_improvements.append({"baseline": base_key, "segments_improved": improved})
    any_multi_segment = any(
        si["segments_improved"] >= protocol.minimum_improvement_segments
        for si in segment_improvements
    )

    gates = {
        "return_sacrifice_within_budget_for_at_least_one_baseline": any_sacrifice_within_budget,
        "tail_residual_improvement_for_at_least_one_baseline": any_tail_improvement,
        "multi_segment_improvement_for_at_least_one_baseline": any_multi_segment,
        "gross_cap_respected": max_gross <= protocol.maximum_effective_gross + 1e-12,
        "independent_nav_reconciliation_pass": reconciliation_pass,
        "funding_history_complete": funding_complete,
    }
    retained = all(gates.values())

    data_basis = {
        "bars": {
            symbol: [[bar.ts_ms, bar.close] for bar in aligned[symbol]]
            for symbol in TOP3
        },
        "funding": {
            symbol: [[row.ts_ms, row.rate] for row in funding_by_symbol[symbol]]
            for symbol in TOP3
        },
    }
    report = {
        "schema_version": CRISIS_STATE_REPORT_VERSION,
        "artifact_type": "crypto_vol_crisis_state_trial",
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
        },
        "summaries": summaries,
        "crisis_comparison": crisis_comparison,
        "segment_improvements": segment_improvements,
        "diagnostics": {
            "gates": gates,
            "passed_gate_count": sum(gates.values()),
            "gate_count": len(gates),
            "verdict": (
                "retain_crisis_state_for_next_evidence"
                if retained
                else "reject_crisis_state_mechanism_not_sufficient"
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
    trajectories = {key: compact_rows(variant.equity) for key, variant in variants.items()}
    return report, trajectories
