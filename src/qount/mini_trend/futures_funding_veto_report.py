"""Historical report for the preregistered UM lagged-funding cost veto."""

from __future__ import annotations

import statistics
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.research_data.market_data import Bar, Funding
from qount.mini_trend.backtest import align_bars
from qount.mini_trend.forward import TOP3, frozen_top3_config
from qount.mini_trend.futures_funding_veto import FUTURES_FUNDING_VETO_PROTOCOL
from qount.mini_trend.futures_funding_veto import FundingVetoRegimeSelector
from qount.mini_trend.futures_funding_veto import validate_funding_veto_registration
from qount.mini_trend.futures_recovery import canonical_hash, selected_um_rules
from qount.mini_trend.futures_recovery_backtest import VariantResult, run_variant
from qount.mini_trend.futures_regime_overlay import control_regime_config_selector
from qount.mini_trend.futures_regime_overlay_report import summarize_risk_stages
from qount.mini_trend.futures_regime_stop_latch import StopLatchedRegimeSelector
from qount.mini_trend.futures_regime_stop_latch_report import max_drawdown_interval
from qount.mini_trend.futures_regime_stop_latch_report import summarize_latch_activity
from qount.mini_trend.regime_adaptation_ablation import _benchmark_returns
from qount.mini_trend.regime_adaptation_ablation import _beta_residual
from qount.models import utc_now
from qount.research_data.metrics import returns_from_curve, sharpe
from qount.settings import Settings


FUNDING_VETO_REPORT_VERSION = "mini_trend_um_funding_veto_historical_v0.2"


def _data_hash(bars: Mapping[str, Sequence[Bar]], funding: Mapping[str, Sequence[Funding]]) -> str:
    return canonical_hash(
        {
            "bars": {
                symbol: [
                    [bar.ts_ms, bar.open, bar.high, bar.low, bar.close, bar.volume]
                    for bar in bars[symbol]
                ]
                for symbol in TOP3
            },
            "funding": {
                symbol: [[row.ts_ms, row.rate] for row in funding[symbol]]
                for symbol in TOP3
            },
        }
    )


def _metrics(
    result: VariantResult, funding_veto_activity: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    capital = FUTURES_FUNDING_VETO_PROTOCOL.capital_usdt
    curve = [capital] + [float(row["equity"]) for row in result.equity]
    gross = [float(row["gross"]) for row in result.equity]
    return dict(result.metrics) | {
        "sharpe": round(sharpe(returns_from_curve(curve), periods_per_year=365.0), 8),
        "average_effective_gross": round(statistics.mean(gross), 8),
        "maximum_effective_gross": round(max(gross), 8),
        "risk_stage_summary": summarize_risk_stages(result, capital),
        "latch_activity": summarize_latch_activity(result),
        "funding_veto_activity": dict(funding_veto_activity or {}),
        "max_drawdown_interval": max_drawdown_interval(result, capital),
    }


def _run_variants(
    bars: Mapping[str, Sequence[Bar]],
    funding: Mapping[str, Sequence[Funding]],
    rules: Mapping[str, Mapping[str, Any]],
) -> tuple[VariantResult, VariantResult, VariantResult, dict[str, Any]]:
    protocol = FUTURES_FUNDING_VETO_PROTOCOL
    common = {
        "recovery_enabled": False,
        "daily_chandelier_atr_multiple": protocol.daily_chandelier_atr_multiple,
        "stop_cooldown_completed_bars": protocol.stop_cooldown_completed_bars,
        "gross_cap_policy": protocol.gross_cap_policy,
    }
    control = run_variant(
        bars,
        funding,
        rules,
        base_config=frozen_top3_config(),
        base_config_selector=control_regime_config_selector,
        **common,
    )
    reference_selector = StopLatchedRegimeSelector()
    reference = run_variant(
        bars,
        funding,
        rules,
        base_config=frozen_top3_config(),
        base_config_selector=reference_selector,
        base_config_feedback=reference_selector.observe_stops,
        **common,
    )
    selector = FundingVetoRegimeSelector(funding)
    candidate = run_variant(
        bars,
        funding,
        rules,
        base_config=frozen_top3_config(),
        base_config_selector=selector,
        base_config_feedback=selector.observe_stops,
        **common,
    )
    return control, reference, candidate, selector.summary()


def _daily_returns(result: VariantResult, capital_usdt: float) -> dict[str, dict[str, Any]]:
    previous = capital_usdt
    rows = {}
    for row in result.equity:
        equity = float(row["equity"])
        rows[row["decision_date"]] = {
            "outcome_date": row["outcome_date"],
            "return_pct": (equity / previous - 1.0) * 100.0,
        }
        previous = equity
    return rows


def _event_audit(
    reference: VariantResult,
    candidate: VariantResult,
    funding_activity: Mapping[str, Any],
) -> dict[str, Any]:
    capital = FUTURES_FUNDING_VETO_PROTOCOL.capital_usdt
    reference_returns = _daily_returns(reference, capital)
    candidate_returns = _daily_returns(candidate, capital)
    events = []
    for event in funding_activity["events"]:
        decision_date = event["decision_date"]
        reference_row = reference_returns[decision_date]
        candidate_row = candidate_returns[decision_date]
        events.append(
            dict(event)
            | {
                "outcome_date": candidate_row["outcome_date"],
                "reference_return_pct": round(reference_row["return_pct"], 8),
                "candidate_return_pct": round(candidate_row["return_pct"], 8),
                "direct_return_delta_percentage_points": round(
                    candidate_row["return_pct"] - reference_row["return_pct"], 8
                ),
            }
        )
    deltas = [row["direct_return_delta_percentage_points"] for row in events]
    positive = [value for value in deltas if value > 0]
    total_positive = sum(positive)
    return {
        "event_count": len(events),
        "positive_direct_delta_count": sum(value > 0 for value in deltas),
        "negative_direct_delta_count": sum(value < 0 for value in deltas),
        "median_direct_delta_percentage_points": round(
            statistics.median(deltas) if deltas else 0.0,
            8,
        ),
        "sum_direct_delta_percentage_points": round(sum(deltas), 8),
        "largest_positive_event_share": round(
            max(positive) / total_positive if total_positive > 0 else 0.0,
            8,
        ),
        "events": events,
        "caveat": "Direct next-day deltas exclude later deadband and path-dependent effects.",
    }


def _window_report(
    source: Mapping[str, Any],
    spec: Mapping[str, str],
    rules: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    bars = align_bars(source["bars"], TOP3)
    control_result, reference_result, candidate_result, funding_activity = _run_variants(
        bars, source["funding"], rules
    )
    control = _metrics(control_result)
    reference = _metrics(reference_result)
    candidate = _metrics(candidate_result, funding_activity)
    benchmark = _benchmark_returns(control_result.equity, bars, source["funding"])
    for metrics, result in (
        (control, control_result),
        (reference, reference_result),
        (candidate, candidate_result),
    ):
        returns = [float(row["net_return"]) for row in result.equity]
        metrics["beta_residual"] = {
            name: _beta_residual(returns, values)
            for name, values in benchmark.items()
        }
    return {
        "label": spec["label"],
        "expected_window": {"start": spec["start"], "end": spec["end"]},
        "data_hash": _data_hash(bars, source["funding"]),
        "control": control,
        "reference_stop_latch": reference,
        "candidate": candidate,
        "incremental_return_pct": round(candidate["return_pct"] - control["return_pct"], 8),
        "sharpe_uplift": round(candidate["sharpe"] - control["sharpe"], 8),
        "drawdown_worsening_percentage_points": round(
            candidate["max_drawdown_pct"] - control["max_drawdown_pct"], 8
        ),
        "funding_veto_event_audit": _event_audit(
            reference_result, candidate_result, funding_activity
        ),
    }


def _prior_comparison(
    preregistration: Mapping[str, Any], full: Mapping[str, Any], segments: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    prior = preregistration["prior_stop_latch"]
    prior_segments = {row["label"]: row["candidate"] for row in prior["segments"]}
    return {
        "full_window": {
            "return_delta_pct": round(
                full["candidate"]["return_pct"] - prior["full_candidate"]["return_pct"], 8
            ),
            "sharpe_delta": round(
                full["candidate"]["sharpe"] - prior["full_candidate"]["sharpe"], 8
            ),
            "drawdown_delta_percentage_points": round(
                full["candidate"]["max_drawdown_pct"]
                - prior["full_candidate"]["max_drawdown_pct"],
                8,
            ),
        },
        "segments": [
            {
                "label": row["label"],
                "return_delta_pct": round(
                    row["candidate"]["return_pct"]
                    - prior_segments[row["label"]]["return_pct"],
                    8,
                ),
                "drawdown_delta_percentage_points": round(
                    row["candidate"]["max_drawdown_pct"]
                    - prior_segments[row["label"]]["max_drawdown_pct"],
                    8,
                ),
            }
            for row in segments
        ],
    }


def build_funding_veto_historical_report(
    inputs: Mapping[str, Mapping[str, Any]],
    rules_artifact: Mapping[str, Any],
    preregistration: Mapping[str, Any],
    live_lessons_path: str,
    base_preregistration_path: str,
    prior_stop_latch_path: str,
) -> dict[str, Any]:
    protocol = FUTURES_FUNDING_VETO_PROTOCOL
    validate_funding_veto_registration(
        preregistration,
        rules_artifact,
        live_lessons_path,
        base_preregistration_path,
        prior_stop_latch_path,
    )
    rules, rules_hash = selected_um_rules(rules_artifact)
    segments = [
        _window_report(inputs[spec["label"]], spec, rules)
        for spec in protocol.historical_windows
    ]
    full = _window_report(inputs[protocol.full_window["label"]], protocol.full_window, rules)
    thresholds = protocol.protocol_basis["historical_pass_gates"]
    weak = next(row for row in segments if row["label"] == thresholds["weak_segment_label"])
    funding_activity = full["candidate"]["funding_veto_activity"]
    latch_activity = full["candidate"]["latch_activity"]
    gates = {
        "data_complete": all(
            row["control"]["start"] == row["expected_window"]["start"]
            and row["control"]["end"] == row["expected_window"]["end"]
            for row in segments + [full]
        ),
        "minimum_full_window_return_uplift": full["incremental_return_pct"]
        >= thresholds["minimum_full_window_return_uplift_percentage_points"],
        "minimum_full_window_sharpe_uplift": full["sharpe_uplift"]
        >= thresholds["minimum_full_window_sharpe_uplift"],
        "maximum_full_window_drawdown_worsening": full[
            "drawdown_worsening_percentage_points"
        ]
        <= thresholds["maximum_full_window_drawdown_worsening_percentage_points"],
        "maximum_segment_drawdown_worsening": all(
            row["drawdown_worsening_percentage_points"]
            <= thresholds["maximum_segment_drawdown_worsening_percentage_points"]
            for row in segments
        ),
        "maximum_weak_segment_return_degradation": weak["candidate"]["return_pct"]
        >= weak["control"]["return_pct"]
        - thresholds["maximum_weak_segment_return_degradation_percentage_points"],
        "maximum_average_effective_gross": full["candidate"]["average_effective_gross"]
        <= thresholds["maximum_average_effective_gross"],
        "maximum_effective_gross": full["candidate"]["maximum_effective_gross"]
        <= thresholds["maximum_effective_gross"],
        "funding_veto_exercised": funding_activity["vetoed_bar_count"]
        >= thresholds["minimum_funding_vetoed_bar_count"],
        "funding_coverage": funding_activity["funding_coverage"]
        == thresholds["required_funding_coverage"],
        "latch_exercised": latch_activity["latch_entry_count"]
        >= thresholds["minimum_latch_entry_count"],
        "runtime_filter_coverage": all(
            row["candidate"]["runtime_filter_coverage"] == thresholds["required_filter_coverage"]
            for row in segments + [full]
        ),
        "no_duplicate_decisions": all(
            row["candidate"]["duplicate_decision_count"]
            <= thresholds["maximum_duplicate_decision_count"]
            for row in segments + [full]
        ),
        "no_same_bar_stop_reentry": all(
            row["candidate"]["same_bar_stop_reentry_count"]
            <= thresholds["maximum_same_bar_stop_reentry_count"]
            for row in segments + [full]
        ),
    }
    passed = all(gates.values())
    return {
        "schema_version": FUNDING_VETO_REPORT_VERSION,
        "artifact_type": "mini_trend_um_funding_veto_historical_diagnostic",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "discovery_pool",
            "existing_cache_only": True,
            "network_download_used": False,
            "historical_window_consumed": True,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "contract_hash": protocol.contract_hash,
        "protocol_hash": protocol.protocol_hash,
        "exchange_rules_hash": rules_hash,
        "segments": segments,
        "full_window": full,
        "prior_stop_latch_comparison": _prior_comparison(preregistration, full, segments),
        "diagnostics": {
            "gates": gates,
            "historical_gate_passed": passed,
            "verdict": (
                "retain_historical_funding_veto_candidate"
                if passed
                else "reject_historical_funding_veto"
            ),
            "interpretation": "Lagged funding is a cost veto, not carry alpha or independent OOS.",
            "paper_or_live_allowed": False,
        },
    }


def write_funding_veto_historical_artifact(
    settings: Settings, payload: dict[str, Any], *, explicit_path: str | None = None
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-um-funding-veto-historical",
        path_key="artifact_path",
        default_filename="mini_trend_um_funding_veto_historical.json",
        explicit_path=explicit_path,
    )
