"""Historical report for the preregistered UM three-stage regime overlay."""

from __future__ import annotations

import statistics
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.grid.data import Bar, Funding
from qount.mini_trend.backtest import align_bars
from qount.mini_trend.forward import TOP3, frozen_top3_config
from qount.mini_trend.futures_recovery import canonical_hash, selected_um_rules
from qount.mini_trend.futures_recovery_backtest import VariantResult, run_variant
from qount.mini_trend.futures_regime_overlay import FUTURES_REGIME_OVERLAY_PROTOCOL
from qount.mini_trend.futures_regime_overlay import RISK_STAGES
from qount.mini_trend.futures_regime_overlay import control_regime_config_selector
from qount.mini_trend.futures_regime_overlay import regime_config_selector
from qount.mini_trend.futures_regime_overlay import regime_overlay_config
from qount.mini_trend.scorecard import max_drawdown_pct
from qount.mini_trend.futures_regime_overlay import validate_regime_overlay_registration
from qount.models import utc_now
from qount.rv.stats import returns_from_curve, sharpe
from qount.settings import Settings


REGIME_OVERLAY_REPORT_VERSION = "mini_trend_um_regime_overlay_historical_v0.3"


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


def summarize_risk_stages(result: VariantResult, capital_usdt: float) -> dict[str, Any]:
    summaries = {
        stage: {
            "bar_count": 0,
            "active_bar_count": 0,
            "order_count": 0,
            "stop_count": 0,
            "gross_values": [],
            "growth_factor": 1.0,
            "stage_curve": [1.0],
            "daily_returns": [],
        }
        for stage in RISK_STAGES
    }
    previous_equity = capital_usdt
    for row in result.equity:
        stage = str(row["risk_stage"])
        if stage not in summaries:
            summaries[stage] = {
                "bar_count": 0,
                "active_bar_count": 0,
                "order_count": 0,
                "stop_count": 0,
                "gross_values": [],
                "growth_factor": 1.0,
                "stage_curve": [1.0],
                "daily_returns": [],
            }
        summary = summaries[stage]
        equity = float(row["equity"])
        gross = float(row["gross"])
        summary["bar_count"] += 1
        summary["active_bar_count"] += int(gross > 0)
        summary["order_count"] += int(row["orders"])
        summary["stop_count"] += len(row["stopped"])
        summary["gross_values"].append(gross)
        daily_return = equity / previous_equity - 1.0
        summary["growth_factor"] *= 1.0 + daily_return
        summary["stage_curve"].append(summary["stage_curve"][-1] * (1.0 + daily_return))
        summary["daily_returns"].append((daily_return, row["outcome_date"]))
        previous_equity = equity
    return {
        stage: {
            "bar_count": values["bar_count"],
            "active_bar_count": values["active_bar_count"],
            "order_count": values["order_count"],
            "stop_count": values["stop_count"],
            "average_effective_gross": round(
                statistics.mean(values["gross_values"]) if values["gross_values"] else 0.0,
                8,
            ),
            "compounded_return_pct": round((values["growth_factor"] - 1.0) * 100.0, 8),
            "stage_max_drawdown_pct": round(max_drawdown_pct(values["stage_curve"]), 8),
            "worst_daily_observations": [
                {"outcome_date": date, "return_pct": round(value * 100.0, 8)}
                for value, date in sorted(values["daily_returns"])[:3]
            ],
        }
        for stage, values in summaries.items()
    }


def _metrics(result: VariantResult) -> dict[str, Any]:
    capital = FUTURES_REGIME_OVERLAY_PROTOCOL.capital_usdt
    curve = [capital] + [float(row["equity"]) for row in result.equity]
    gross = [float(row["gross"]) for row in result.equity]
    return dict(result.metrics) | {
        "sharpe": round(sharpe(returns_from_curve(curve), periods_per_year=365.0), 8),
        "average_effective_gross": round(statistics.mean(gross), 8),
        "maximum_effective_gross": round(max(gross), 8),
        "risk_stage_summary": summarize_risk_stages(result, capital),
    }


def _run_pair(
    bars: Mapping[str, Sequence[Bar]],
    funding: Mapping[str, Sequence[Funding]],
    rules: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    protocol = FUTURES_REGIME_OVERLAY_PROTOCOL
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
    candidate = run_variant(
        bars,
        funding,
        rules,
        base_config=regime_overlay_config(protocol.transition_range_vol_target),
        base_config_selector=regime_config_selector,
        **common,
    )
    return _metrics(control), _metrics(candidate)


def _window_report(
    source: Mapping[str, Any],
    spec: Mapping[str, str],
    rules: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    bars = align_bars(source["bars"], TOP3)
    control, candidate = _run_pair(bars, source["funding"], rules)
    return {
        "label": spec["label"],
        "expected_window": {"start": spec["start"], "end": spec["end"]},
        "data_hash": _data_hash(bars, source["funding"]),
        "control": control,
        "candidate": candidate,
        "incremental_return_pct": round(candidate["return_pct"] - control["return_pct"], 8),
        "sharpe_uplift": round(candidate["sharpe"] - control["sharpe"], 8),
        "drawdown_worsening_percentage_points": round(
            candidate["max_drawdown_pct"] - control["max_drawdown_pct"], 8
        ),
    }


def build_regime_overlay_historical_report(
    inputs: Mapping[str, Mapping[str, Any]],
    rules_artifact: Mapping[str, Any],
    preregistration: Mapping[str, Any],
    live_lessons_path: str,
    base_preregistration_path: str,
    prior_risk_tier_path: str,
) -> dict[str, Any]:
    protocol = FUTURES_REGIME_OVERLAY_PROTOCOL
    validate_regime_overlay_registration(
        preregistration,
        rules_artifact,
        live_lessons_path,
        base_preregistration_path,
        prior_risk_tier_path,
    )
    rules, rules_hash = selected_um_rules(rules_artifact)
    segments = [
        _window_report(inputs[spec["label"]], spec, rules)
        for spec in protocol.historical_windows
    ]
    full = _window_report(inputs[protocol.full_window["label"]], protocol.full_window, rules)
    thresholds = protocol.protocol_basis["historical_pass_gates"]
    weak = next(row for row in segments if row["label"] == thresholds["weak_segment_label"])
    stage_summary = full["candidate"]["risk_stage_summary"]
    gates = {
        "data_complete": all(
            row["control"]["start"] == row["expected_window"]["start"]
            and row["control"]["end"] == row["expected_window"]["end"]
            for row in segments + [full]
        ),
        "all_risk_stages_observed": all(stage_summary[stage]["bar_count"] > 0 for stage in RISK_STAGES),
        "minimum_full_window_return_uplift": full["incremental_return_pct"]
        >= thresholds["minimum_full_window_return_uplift_percentage_points"],
        "minimum_full_window_sharpe_uplift": full["sharpe_uplift"]
        >= thresholds["minimum_full_window_sharpe_uplift"],
        "maximum_full_window_drawdown": full["candidate"]["max_drawdown_pct"]
        <= thresholds["maximum_full_window_drawdown_pct"],
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
        "schema_version": REGIME_OVERLAY_REPORT_VERSION,
        "artifact_type": "mini_trend_um_regime_overlay_historical_diagnostic",
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
            "verdict": "collect_new_forward_shadow" if passed else "reject_historical_regime_overlay",
            "interpretation": "Stage-aware risk sizing only; a pass is not an alpha or live-promotion claim.",
            "forward_start_date": protocol.forward_start_date,
            "paper_or_live_allowed": False,
        },
    }


def write_regime_overlay_historical_artifact(
    settings: Settings, payload: dict[str, Any], *, explicit_path: str | None = None
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-um-regime-overlay-historical",
        path_key="artifact_path",
        default_filename="mini_trend_um_regime_overlay_historical.json",
        explicit_path=explicit_path,
    )
