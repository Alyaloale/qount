"""Historical report for the preregistered stop-latched UM regime overlay."""

from __future__ import annotations

import statistics
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.grid.data import Bar, Funding
from qount.mini_trend.backtest import align_bars
from qount.mini_trend.forward import TOP3, frozen_top3_config
from qount.mini_trend.futures_recovery import canonical_hash, selected_um_rules
from qount.mini_trend.futures_recovery_backtest import VariantResult, run_variant
from qount.mini_trend.futures_regime_overlay import control_regime_config_selector
from qount.mini_trend.futures_regime_overlay_report import summarize_risk_stages
from qount.mini_trend.futures_regime_stop_latch import FUTURES_REGIME_STOP_LATCH_PROTOCOL
from qount.mini_trend.futures_regime_stop_latch import STRONG_BULL_BOOSTED
from qount.mini_trend.futures_regime_stop_latch import STRONG_BULL_LATCHED_BASE
from qount.mini_trend.futures_regime_stop_latch import StopLatchedRegimeSelector
from qount.mini_trend.futures_regime_stop_latch import validate_regime_stop_latch_registration
from qount.models import utc_now
from qount.rv.stats import returns_from_curve, sharpe
from qount.settings import Settings


REGIME_STOP_LATCH_REPORT_VERSION = "mini_trend_um_regime_stop_latch_historical_v0.3"


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


def summarize_latch_activity(result: VariantResult) -> dict[str, int]:
    entries = 0
    prior_stage = None
    for row in result.equity:
        stage = str(row["risk_stage"])
        entries += int(stage == STRONG_BULL_LATCHED_BASE and prior_stage != stage)
        prior_stage = stage
    return {
        "stop_trigger_count": sum(
            len(row["stopped"])
            for row in result.equity
            if row["risk_stage"] in {STRONG_BULL_BOOSTED, STRONG_BULL_LATCHED_BASE}
        ),
        "latch_entry_count": entries,
        "boosted_bar_count": sum(
            1 for row in result.equity if row["risk_stage"] == STRONG_BULL_BOOSTED
        ),
        "latched_bar_count": sum(
            1 for row in result.equity if row["risk_stage"] == STRONG_BULL_LATCHED_BASE
        ),
    }


def max_drawdown_interval(result: VariantResult, capital_usdt: float) -> dict[str, Any]:
    peak = capital_usdt
    peak_date = result.equity[0]["decision_date"]
    worst = 0.0
    worst_peak_date = peak_date
    trough_date = peak_date
    for row in result.equity:
        equity = float(row["equity"])
        if equity > peak:
            peak = equity
            peak_date = row["outcome_date"]
        drawdown = (peak - equity) / peak * 100.0
        if drawdown > worst:
            worst = drawdown
            worst_peak_date = peak_date
            trough_date = row["outcome_date"]
    return {
        "peak_date": worst_peak_date,
        "trough_date": trough_date,
        "drawdown_pct": round(worst, 8),
    }


def _metrics(result: VariantResult) -> dict[str, Any]:
    capital = FUTURES_REGIME_STOP_LATCH_PROTOCOL.capital_usdt
    curve = [capital] + [float(row["equity"]) for row in result.equity]
    gross = [float(row["gross"]) for row in result.equity]
    return dict(result.metrics) | {
        "sharpe": round(sharpe(returns_from_curve(curve), periods_per_year=365.0), 8),
        "average_effective_gross": round(statistics.mean(gross), 8),
        "maximum_effective_gross": round(max(gross), 8),
        "risk_stage_summary": summarize_risk_stages(result, capital),
        "latch_activity": summarize_latch_activity(result),
        "max_drawdown_interval": max_drawdown_interval(result, capital),
    }


def _run_pair(
    bars: Mapping[str, Sequence[Bar]],
    funding: Mapping[str, Sequence[Funding]],
    rules: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    protocol = FUTURES_REGIME_STOP_LATCH_PROTOCOL
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
    selector = StopLatchedRegimeSelector()
    candidate = run_variant(
        bars,
        funding,
        rules,
        base_config=frozen_top3_config(),
        base_config_selector=selector,
        base_config_feedback=selector.observe_stops,
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


def build_regime_stop_latch_historical_report(
    inputs: Mapping[str, Mapping[str, Any]],
    rules_artifact: Mapping[str, Any],
    preregistration: Mapping[str, Any],
    live_lessons_path: str,
    base_preregistration_path: str,
    prior_regime_overlay_path: str,
) -> dict[str, Any]:
    protocol = FUTURES_REGIME_STOP_LATCH_PROTOCOL
    validate_regime_stop_latch_registration(
        preregistration,
        rules_artifact,
        live_lessons_path,
        base_preregistration_path,
        prior_regime_overlay_path,
    )
    rules, rules_hash = selected_um_rules(rules_artifact)
    segments = [
        _window_report(inputs[spec["label"]], spec, rules)
        for spec in protocol.historical_windows
    ]
    full = _window_report(inputs[protocol.full_window["label"]], protocol.full_window, rules)
    thresholds = protocol.protocol_basis["historical_pass_gates"]
    weak = next(row for row in segments if row["label"] == thresholds["weak_segment_label"])
    activity = full["candidate"]["latch_activity"]
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
        "latch_exercised": activity["latch_entry_count"]
        >= thresholds["minimum_latch_activation_count"]
        and activity["latched_bar_count"] >= thresholds["minimum_latched_bar_count"],
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
        "schema_version": REGIME_STOP_LATCH_REPORT_VERSION,
        "artifact_type": "mini_trend_um_regime_stop_latch_historical_diagnostic",
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
        "diagnostics": {
            "gates": gates,
            "historical_gate_passed": passed,
            "verdict": (
                "retain_historical_stop_latch_candidate"
                if passed
                else "reject_historical_regime_stop_latch"
            ),
            "interpretation": "Consumed historical mechanism test only; never an OOS or live claim.",
            "paper_or_live_allowed": False,
        },
    }


def write_regime_stop_latch_historical_artifact(
    settings: Settings, payload: dict[str, Any], *, explicit_path: str | None = None
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-um-regime-stop-latch-historical",
        path_key="artifact_path",
        default_filename="mini_trend_um_regime_stop_latch_historical.json",
        explicit_path=explicit_path,
    )
