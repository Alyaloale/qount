"""Historical control/candidate report for the preregistered UM risk tier."""

from __future__ import annotations

import statistics
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.grid.data import Bar, Funding
from qount.mini_trend.backtest import align_bars
from qount.mini_trend.forward import TOP3, frozen_top3_config
from qount.mini_trend.futures_risk_tier import FUTURES_RISK_TIER_PROTOCOL
from qount.mini_trend.futures_risk_tier import risk_tier_config
from qount.mini_trend.futures_risk_tier import validate_risk_tier_registration
from qount.mini_trend.futures_recovery import canonical_hash, selected_um_rules
from qount.mini_trend.futures_recovery_backtest import VariantResult, run_variant
from qount.models import utc_now
from qount.rv.stats import returns_from_curve, sharpe
from qount.settings import Settings


RISK_TIER_REPORT_VERSION = "mini_trend_um_risk_tier_historical_v0.2"


def _data_hash(bars: Mapping[str, Sequence[Bar]], funding: Mapping[str, Sequence[Funding]]) -> str:
    return canonical_hash(
        {
            "bars": {
                symbol: [[bar.ts_ms, bar.open, bar.high, bar.low, bar.close, bar.volume] for bar in bars[symbol]]
                for symbol in TOP3
            },
            "funding": {
                symbol: [[row.ts_ms, row.rate] for row in funding[symbol]] for symbol in TOP3
            },
        }
    )


def _metrics(result: VariantResult) -> dict[str, Any]:
    curve = [FUTURES_RISK_TIER_PROTOCOL.capital_usdt] + [
        float(row["equity"]) for row in result.equity
    ]
    gross = [float(row["gross"]) for row in result.equity]
    return dict(result.metrics) | {
        "sharpe": round(sharpe(returns_from_curve(curve), periods_per_year=365.0), 8),
        "average_effective_gross": round(statistics.mean(gross), 8),
        "maximum_effective_gross": round(max(gross), 8),
    }


def _run_pair(
    bars: Mapping[str, Sequence[Bar]],
    funding: Mapping[str, Sequence[Funding]],
    rules: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    protocol = FUTURES_RISK_TIER_PROTOCOL
    common = {
        "recovery_enabled": False,
        "daily_chandelier_atr_multiple": protocol.daily_chandelier_atr_multiple,
        "stop_cooldown_completed_bars": protocol.stop_cooldown_completed_bars,
        "gross_cap_policy": protocol.gross_cap_policy,
    }
    control = run_variant(bars, funding, rules, base_config=frozen_top3_config(), **common)
    candidate = run_variant(bars, funding, rules, base_config=risk_tier_config(), **common)
    return _metrics(control), _metrics(candidate)


def build_risk_tier_historical_report(
    inputs: Mapping[str, Mapping[str, Any]],
    rules_artifact: Mapping[str, Any],
    preregistration: Mapping[str, Any],
    live_lessons_path: str,
    base_preregistration_path: str,
) -> dict[str, Any]:
    protocol = FUTURES_RISK_TIER_PROTOCOL
    validate_risk_tier_registration(
        preregistration,
        rules_artifact,
        live_lessons_path,
        base_preregistration_path,
    )
    rules, rules_hash = selected_um_rules(rules_artifact)
    segments = []
    for spec in protocol.historical_windows:
        source = inputs[spec["label"]]
        bars = align_bars(source["bars"], TOP3)
        control, candidate = _run_pair(bars, source["funding"], rules)
        segments.append(
            {
                "label": spec["label"],
                "expected_window": {"start": spec["start"], "end": spec["end"]},
                "data_hash": _data_hash(bars, source["funding"]),
                "control": control,
                "candidate": candidate,
                "incremental_return_pct": round(candidate["return_pct"] - control["return_pct"], 8),
                "drawdown_worsening_percentage_points": round(
                    candidate["max_drawdown_pct"] - control["max_drawdown_pct"], 8
                ),
            }
        )
    full_source = inputs[protocol.full_window["label"]]
    full_bars = align_bars(full_source["bars"], TOP3)
    full_control, full_candidate = _run_pair(full_bars, full_source["funding"], rules)
    full = {
        "label": protocol.full_window["label"],
        "expected_window": {
            "start": protocol.full_window["start"],
            "end": protocol.full_window["end"],
        },
        "data_hash": _data_hash(full_bars, full_source["funding"]),
        "control": full_control,
        "candidate": full_candidate,
        "incremental_return_pct": round(
            full_candidate["return_pct"] - full_control["return_pct"], 8
        ),
        "drawdown_worsening_percentage_points": round(
            full_candidate["max_drawdown_pct"] - full_control["max_drawdown_pct"], 8
        ),
    }
    thresholds = protocol.protocol_basis["historical_pass_gates"]
    gates = {
        "data_complete": all(
            row["control"]["start"] == row["expected_window"]["start"]
            and row["control"]["end"] == row["expected_window"]["end"]
            for row in segments + [full]
        ),
        "minimum_full_window_return_uplift": full["incremental_return_pct"]
        >= thresholds["minimum_full_window_return_uplift_percentage_points"],
        "maximum_sharpe_degradation": full_candidate["sharpe"]
        >= full_control["sharpe"] - thresholds["maximum_sharpe_degradation"],
        "maximum_full_window_drawdown": full_candidate["max_drawdown_pct"]
        <= thresholds["maximum_full_window_drawdown_pct"],
        "maximum_segment_drawdown_worsening": all(
            row["drawdown_worsening_percentage_points"]
            <= thresholds["maximum_segment_drawdown_worsening_percentage_points"]
            for row in segments
        ),
        "minimum_worst_segment_return": min(
            row["candidate"]["return_pct"] for row in segments
        )
        >= thresholds["minimum_worst_segment_return_pct"],
        "maximum_average_effective_gross": full_candidate["average_effective_gross"]
        <= thresholds["maximum_average_effective_gross"],
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
        "schema_version": RISK_TIER_REPORT_VERSION,
        "artifact_type": "mini_trend_um_risk_tier_historical_diagnostic",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "discovery_pool",
            "existing_cache_only": True,
            "network_download_used": False,
            "private_exchange_data": False,
            "historical_window_consumed": True,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "contract_hash": protocol.contract_hash,
        "protocol_hash": protocol.protocol_hash,
        "exchange_rules_hash": rules_hash,
        "segments": segments,
        "full_window": full,
        "diagnostics": {
            "gates": gates,
            "historical_gate_passed": passed,
            "verdict": "collect_new_forward_shadow" if passed else "reject_historical_risk_tier",
            "interpretation": "Risk-budget comparison only; a pass is not an alpha or live-promotion claim.",
            "forward_start_date": protocol.forward_start_date,
            "paper_or_live_allowed": False,
        },
    }


def build_risk_tier_execution_failure_report(
    rules_artifact: Mapping[str, Any],
    preregistration: Mapping[str, Any],
    live_lessons_path: str,
    base_preregistration_path: str,
    error: str,
) -> dict[str, Any]:
    protocol = FUTURES_RISK_TIER_PROTOCOL
    validate_risk_tier_registration(
        preregistration,
        rules_artifact,
        live_lessons_path,
        base_preregistration_path,
    )
    _, rules_hash = selected_um_rules(rules_artifact)
    return {
        "schema_version": RISK_TIER_REPORT_VERSION,
        "artifact_type": "mini_trend_um_risk_tier_historical_diagnostic",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "discovery_pool",
            "existing_cache_only": True,
            "network_download_used": False,
            "strategy_results_evaluated": False,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "contract_hash": protocol.contract_hash,
        "protocol_hash": protocol.protocol_hash,
        "exchange_rules_hash": rules_hash,
        "segments": [],
        "diagnostics": {
            "gates": {"execution_contract_complete": False},
            "historical_gate_passed": False,
            "verdict": "reject_execution_contract_incomplete",
            "blockers": ["effective_gross_exceeded_after_deadband"],
            "error": error,
            "paper_or_live_allowed": False,
        },
    }


def write_risk_tier_historical_artifact(
    settings: Settings, payload: dict[str, Any], *, explicit_path: str | None = None
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-um-risk-tier-historical",
        path_key="artifact_path",
        default_filename="mini_trend_um_risk_tier_historical.json",
        explicit_path=explicit_path,
    )
