"""Execution-state divergence decay audit for the fixed UM funding veto."""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.research_data.market_data import Bar, Funding
from qount.mini_trend.backtest import align_bars
from qount.mini_trend.forward import TOP3
from qount.mini_trend.futures_funding_veto import FUTURES_FUNDING_VETO_PROTOCOL
from qount.mini_trend.futures_funding_veto_attribution import (
    FUNDING_VETO_ATTRIBUTION_REPORT_VERSION,
)
from qount.mini_trend.futures_funding_veto_attribution import (
    FUNDING_VETO_ATTRIBUTION_PROTOCOL,
)
from qount.mini_trend.futures_funding_veto_attribution import _load_source_historical
from qount.mini_trend.futures_funding_veto_report import _data_hash, _metrics, _run_variants
from qount.mini_trend.futures_recovery import canonical_hash, selected_um_rules
from qount.mini_trend.futures_recovery_backtest import VariantResult
from qount.mini_trend.futures_risk_tier import file_sha256
from qount.models import utc_now
from qount.settings import Settings


FUNDING_VETO_STATE_DECAY_PREREG_VERSION = (
    "mini_trend_um_funding_veto_state_decay_preregistration_v0.1"
)
FUNDING_VETO_STATE_DECAY_REPORT_VERSION = (
    "mini_trend_um_funding_veto_state_decay_historical_v0.1"
)
STATE_FIELDS = (
    "decision_risk_stage",
    "active_vol_target",
    "target_weights",
    "trail_high",
    "cooldown_remaining",
    "selector_state",
)


@dataclass(frozen=True)
class FundingVetoStateDecayProtocol:
    strategy: str = "MiniTrend-UM-FundingVeto-v0.1"
    reference: str = "MiniTrend-UM-RegimeStopLatch-v0.1"
    numeric_state_tolerance: float = 1e-12
    return_divergence_tolerance: float = 1e-12
    historical_replay_tolerance: float = 1e-8

    @property
    def full_window(self) -> dict[str, str]:
        return FUTURES_FUNDING_VETO_PROTOCOL.full_window

    @property
    def contract_basis(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "candidate_contract_hash": FUTURES_FUNDING_VETO_PROTOCOL.contract_hash,
            "reference": self.reference,
            "reference_contract_hash": FUTURES_FUNDING_VETO_PROTOCOL.contract_basis[
                "inherited_stop_latch_contract_hash"
            ],
            "execution_state_snapshot": {
                "fields": list(STATE_FIELDS),
                "numeric_tolerance": self.numeric_state_tolerance,
                "captured_after_decision_stop_cooldown_and_target_update": True,
                "account_equity_included": False,
                "equity_exclusion_reason": (
                    "realized PnL differences persist permanently; return divergence is audited separately"
                ),
            },
            "decay_audit": {
                "state_spell": "maximal contiguous completed-day run with divergent execution state",
                "return_spell": "maximal contiguous completed-day run with divergent net simple return",
                "first_resynchronization": (
                    "first later completed day with equal execution state; later re-divergence remains possible"
                ),
                "stable_resynchronization_before_next_veto": (
                    "first equal-state day followed only by equal states until the next veto date"
                ),
                "event_dates_fixed_from_source_historical": True,
                "duration_parameter_search_allowed": False,
                "state_field_search_allowed": False,
            },
            "limitations": {
                "holdout_role": "consumed_historical_discovery_only",
                "execution_state_sync_not_equity_sync": True,
                "not_causal_counterfactual_isolation": True,
                "not_oos": True,
                "not_paper_or_live_evidence": True,
            },
        }

    @property
    def contract_hash(self) -> str:
        return canonical_hash(self.contract_basis)

    @property
    def protocol_basis(self) -> dict[str, Any]:
        return {
            "contract_hash": self.contract_hash,
            "full_window": self.full_window,
            "diagnostic_gates": {
                "exact_historical_replay_required": True,
                "execution_state_coverage_required": 1.0,
                "all_registered_veto_events_required": True,
                "return_divergence_counts_must_match_attribution": True,
                "all_veto_events_must_start_in_divergent_state": True,
                "all_veto_events_must_eventually_first_resynchronize": True,
                "final_veto_must_stably_resynchronize_by_window_end": True,
            },
            "trial_count": 1,
            "parameter_search_allowed": False,
            "state_field_search_allowed": False,
            "duration_threshold_search_allowed": False,
            "paper_or_live_allowed": False,
            "promotion_rule": (
                "State-decay diagnostics may characterize path persistence only; they cannot "
                "promote, tune, or authorize the strategy."
            ),
        }

    @property
    def protocol_hash(self) -> str:
        return canonical_hash(self.protocol_basis)


FUNDING_VETO_STATE_DECAY_PROTOCOL = FundingVetoStateDecayProtocol()


def _load_object(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object at {path}")
    return payload


def _load_attribution_historical(
    path: str | Path, source_historical_sha256: str
) -> dict[str, Any]:
    source = Path(path).expanduser()
    payload = _load_object(source)
    if payload.get("schema_version") != FUNDING_VETO_ATTRIBUTION_REPORT_VERSION:
        raise ValueError("unexpected funding-veto attribution schema")
    if payload.get("artifact_type") != (
        "mini_trend_um_funding_veto_attribution_historical_diagnostic"
    ):
        raise ValueError("unexpected funding-veto attribution artifact")
    if payload.get("contract_hash") != FUNDING_VETO_ATTRIBUTION_PROTOCOL.contract_hash:
        raise ValueError("funding-veto attribution contract hash mismatch")
    if payload.get("protocol_hash") != FUNDING_VETO_ATTRIBUTION_PROTOCOL.protocol_hash:
        raise ValueError("funding-veto attribution protocol hash mismatch")
    if payload.get("source_historical_sha256") != source_historical_sha256:
        raise ValueError("attribution artifact is not bound to the source historical report")
    if payload.get("diagnostics", {}).get("verdict") != (
        "historical_cost_veto_mechanism_supported"
    ):
        raise ValueError("state-decay audit requires the supported attribution result")
    accounting = payload["accounting"]
    return {
        "artifact_path": str(source),
        "artifact_sha256": file_sha256(source),
        "verdict": payload["diagnostics"]["verdict"],
        "observation_count": accounting["observation_count"],
        "divergent_bar_count": accounting["divergent_bar_count"],
        "downstream_divergent_bar_count": accounting["downstream_divergent_bar_count"],
    }


def build_funding_veto_state_decay_preregistration(
    rules_artifact: Mapping[str, Any],
    funding_veto_historical_path: str | Path,
    attribution_historical_path: str | Path,
) -> dict[str, Any]:
    _, rules_hash = selected_um_rules(rules_artifact)
    historical = _load_source_historical(funding_veto_historical_path)
    if historical["exchange_rules_hash"] != rules_hash:
        raise ValueError("source historical exchange-rules hash mismatch")
    attribution = _load_attribution_historical(
        attribution_historical_path, historical["artifact_sha256"]
    )
    protocol = FUNDING_VETO_STATE_DECAY_PROTOCOL
    return {
        "schema_version": FUNDING_VETO_STATE_DECAY_PREREG_VERSION,
        "artifact_type": "mini_trend_um_funding_veto_state_decay_preregistration",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "state_decay_results_evaluated": False,
            "source_historical_results_consumed": True,
            "source_attribution_results_consumed": True,
            "existing_cache_only": True,
            "network_download_allowed": False,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "decision_contract": protocol.contract_basis | {"contract_hash": protocol.contract_hash},
        "protocol": protocol.protocol_basis | {"protocol_hash": protocol.protocol_hash},
        "exchange_rules": {"selected_rules_hash": rules_hash, "symbols": sorted(TOP3)},
        "source_historical": historical,
        "source_attribution": attribution,
    }


def validate_funding_veto_state_decay_registration(
    preregistration: Mapping[str, Any],
    rules_artifact: Mapping[str, Any],
    funding_veto_historical_path: str | Path,
    attribution_historical_path: str | Path,
) -> None:
    protocol = FUNDING_VETO_STATE_DECAY_PROTOCOL
    if preregistration.get("schema_version") != FUNDING_VETO_STATE_DECAY_PREREG_VERSION:
        raise ValueError("unexpected funding-veto state-decay preregistration schema")
    if preregistration.get("decision_contract", {}).get("contract_hash") != protocol.contract_hash:
        raise ValueError("funding-veto state-decay contract hash mismatch")
    if preregistration.get("protocol", {}).get("protocol_hash") != protocol.protocol_hash:
        raise ValueError("funding-veto state-decay protocol hash mismatch")
    _, rules_hash = selected_um_rules(rules_artifact)
    if preregistration.get("exchange_rules", {}).get("selected_rules_hash") != rules_hash:
        raise ValueError("funding-veto state-decay exchange-rules hash mismatch")
    historical = _load_source_historical(funding_veto_historical_path)
    if preregistration.get("source_historical", {}).get("artifact_sha256") != historical[
        "artifact_sha256"
    ]:
        raise ValueError("funding-veto state-decay source historical hash mismatch")
    attribution = _load_attribution_historical(
        attribution_historical_path, historical["artifact_sha256"]
    )
    if preregistration.get("source_attribution", {}).get("artifact_sha256") != attribution[
        "artifact_sha256"
    ]:
        raise ValueError("funding-veto state-decay attribution hash mismatch")


def _numeric_mapping_delta(
    reference: Mapping[str, Any], candidate: Mapping[str, Any]
) -> tuple[bool, float]:
    if set(reference) != set(candidate):
        return True, float("inf")
    maximum = 0.0
    for key in reference:
        maximum = max(maximum, abs(float(candidate[key]) - float(reference[key])))
    return maximum > FUNDING_VETO_STATE_DECAY_PROTOCOL.numeric_state_tolerance, maximum


def compare_execution_states(
    reference: Mapping[str, Any], candidate: Mapping[str, Any]
) -> dict[str, Any]:
    missing_reference = sorted(set(STATE_FIELDS) - set(reference))
    missing_candidate = sorted(set(STATE_FIELDS) - set(candidate))
    if missing_reference or missing_candidate:
        raise ValueError(
            "execution state missing fields: "
            f"reference={missing_reference}, candidate={missing_candidate}"
        )
    weight_diff, maximum_weight_delta = _numeric_mapping_delta(
        reference["target_weights"], candidate["target_weights"]
    )
    trail_diff, maximum_trail_delta = _numeric_mapping_delta(
        reference["trail_high"], candidate["trail_high"]
    )
    cooldown_diff = reference["cooldown_remaining"] != candidate["cooldown_remaining"]
    selector_diff = reference["selector_state"] != candidate["selector_state"]
    stage_diff = reference["decision_risk_stage"] != candidate["decision_risk_stage"]
    vol_target_delta = abs(
        float(candidate["active_vol_target"]) - float(reference["active_vol_target"])
    )
    vol_target_diff = (
        vol_target_delta > FUNDING_VETO_STATE_DECAY_PROTOCOL.numeric_state_tolerance
    )
    facets = {
        "risk_stage": stage_diff,
        "vol_target": vol_target_diff,
        "target_weights": weight_diff,
        "trail_high": trail_diff,
        "cooldown": cooldown_diff,
        "selector_state": selector_diff,
    }
    return {
        "divergent": any(facets.values()),
        "facets": facets,
        "maximum_target_weight_delta": maximum_weight_delta,
        "maximum_trail_high_delta": maximum_trail_delta,
        "vol_target_delta": vol_target_delta,
    }


def _spell_rows(
    flags: Sequence[bool],
    rows: Sequence[Mapping[str, Any]],
    event_dates: set[str],
    comparisons: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    spells: list[dict[str, Any]] = []
    start = 0
    while start < len(flags):
        if not flags[start]:
            start += 1
            continue
        end = start
        while end + 1 < len(flags) and flags[end + 1]:
            end += 1
        spell: dict[str, Any] = {
            "spell_index": len(spells),
            "start_decision_date": rows[start]["decision_date"],
            "end_decision_date": rows[end]["decision_date"],
            "end_outcome_date": rows[end]["outcome_date"],
            "bar_count": end - start + 1,
            "event_dates": [
                rows[index]["decision_date"]
                for index in range(start, end + 1)
                if rows[index]["decision_date"] in event_dates
            ],
        }
        if comparisons is not None:
            spell["maximum_target_weight_delta"] = max(
                float(comparisons[index]["maximum_target_weight_delta"])
                for index in range(start, end + 1)
            )
            spell["facet_bar_counts"] = {
                facet: sum(
                    bool(comparisons[index]["facets"][facet])
                    for index in range(start, end + 1)
                )
                for facet in comparisons[start]["facets"]
            }
        spells.append(spell)
        start = end + 1
    return spells


def _event_decay_rows(
    rows: Sequence[Mapping[str, Any]],
    flags: Sequence[bool],
    event_dates: Sequence[str],
    state_spells: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    index_by_date = {str(row["decision_date"]): index for index, row in enumerate(rows)}
    event_indices = [index_by_date[date] for date in event_dates if date in index_by_date]
    spell_by_event = {
        date: spell["spell_index"]
        for spell in state_spells
        for date in spell["event_dates"]
    }
    output = []
    for event_position, event_date in enumerate(event_dates):
        index = index_by_date.get(event_date)
        if index is None:
            output.append({"event_date": event_date, "missing": True})
            continue
        next_event_index = (
            event_indices[event_position + 1]
            if event_position + 1 < len(event_indices)
            else len(rows)
        )
        first_sync_index = next(
            (candidate for candidate in range(index + 1, len(rows)) if not flags[candidate]),
            None,
        )
        stable_sync_index = next(
            (
                candidate
                for candidate in range(index + 1, next_event_index)
                if not any(flags[candidate:next_event_index])
            ),
            None,
        )
        output.append(
            {
                "event_date": event_date,
                "missing": False,
                "state_divergent_on_event": bool(flags[index]),
                "state_spell_index": spell_by_event.get(event_date),
                "first_sync_date": (
                    rows[first_sync_index]["decision_date"] if first_sync_index is not None else None
                ),
                "bars_to_first_sync": (
                    first_sync_index - index if first_sync_index is not None else None
                ),
                "later_veto_before_first_sync": (
                    first_sync_index is None or next_event_index < first_sync_index
                ),
                "stable_sync_before_next_veto_date": (
                    rows[stable_sync_index]["decision_date"]
                    if stable_sync_index is not None
                    else None
                ),
                "bars_to_stable_sync_before_next_veto": (
                    stable_sync_index - index if stable_sync_index is not None else None
                ),
            }
        )
    return output


def build_state_decay_diagnostic(
    reference: VariantResult,
    candidate: VariantResult,
    event_dates: Sequence[str],
) -> dict[str, Any]:
    if len(reference.equity) != len(candidate.equity):
        raise ValueError("reference and candidate state paths have different lengths")
    comparisons = []
    state_flags = []
    return_flags = []
    coverage = 0
    for reference_row, candidate_row in zip(reference.equity, candidate.equity):
        if (reference_row["decision_date"], reference_row["outcome_date"]) != (
            candidate_row["decision_date"],
            candidate_row["outcome_date"],
        ):
            raise ValueError("reference and candidate state paths are not date aligned")
        if "execution_state" in reference_row and "execution_state" in candidate_row:
            coverage += 1
        comparison = compare_execution_states(
            reference_row["execution_state"], candidate_row["execution_state"]
        )
        comparisons.append(comparison)
        state_flags.append(bool(comparison["divergent"]))
        return_flags.append(
            abs(float(candidate_row["net_return"]) - float(reference_row["net_return"]))
            > FUNDING_VETO_STATE_DECAY_PROTOCOL.return_divergence_tolerance
        )
    event_set = set(event_dates)
    state_spells = _spell_rows(
        state_flags, candidate.equity, event_set, comparisons
    )
    return_spells = _spell_rows(return_flags, candidate.equity, event_set)
    events = _event_decay_rows(candidate.equity, state_flags, event_dates, state_spells)
    first_sync_durations = [
        int(row["bars_to_first_sync"])
        for row in events
        if row.get("bars_to_first_sync") is not None
    ]
    stable_sync_durations = [
        int(row["bars_to_stable_sync_before_next_veto"])
        for row in events
        if row.get("bars_to_stable_sync_before_next_veto") is not None
    ]
    state_spell_lengths = [int(row["bar_count"]) for row in state_spells]
    return_spell_lengths = [int(row["bar_count"]) for row in return_spells]
    return {
        "observation_count": len(candidate.equity),
        "execution_state_coverage": coverage / len(candidate.equity),
        "state_divergent_bar_count": sum(state_flags),
        "return_divergent_bar_count": sum(return_flags),
        "downstream_return_divergent_bar_count": sum(
            flag and candidate.equity[index]["decision_date"] not in event_set
            for index, flag in enumerate(return_flags)
        ),
        "state_spell_count": len(state_spells),
        "return_spell_count": len(return_spells),
        "state_spell_length_summary": {
            "minimum": min(state_spell_lengths) if state_spell_lengths else 0,
            "median": statistics.median(state_spell_lengths) if state_spell_lengths else 0.0,
            "maximum": max(state_spell_lengths) if state_spell_lengths else 0,
        },
        "return_spell_length_summary": {
            "minimum": min(return_spell_lengths) if return_spell_lengths else 0,
            "median": statistics.median(return_spell_lengths) if return_spell_lengths else 0.0,
            "maximum": max(return_spell_lengths) if return_spell_lengths else 0,
        },
        "first_sync_duration_summary": {
            "resolved_event_count": len(first_sync_durations),
            "minimum": min(first_sync_durations) if first_sync_durations else None,
            "median": statistics.median(first_sync_durations) if first_sync_durations else None,
            "maximum": max(first_sync_durations) if first_sync_durations else None,
        },
        "stable_sync_before_next_veto_summary": {
            "resolved_event_count": len(stable_sync_durations),
            "minimum": min(stable_sync_durations) if stable_sync_durations else None,
            "median": statistics.median(stable_sync_durations) if stable_sync_durations else None,
            "maximum": max(stable_sync_durations) if stable_sync_durations else None,
        },
        "events_with_later_veto_before_first_sync": sum(
            bool(row.get("later_veto_before_first_sync")) for row in events
        ),
        "state_spells": state_spells,
        "return_spells": return_spells,
        "events": events,
    }


def _metric_deltas(actual: Mapping[str, Any], expected: Mapping[str, Any]) -> dict[str, float]:
    return {
        key: round(float(actual[key]) - float(expected[key]), 10)
        for key in ("return_pct", "sharpe", "max_drawdown_pct")
    }


def build_funding_veto_state_decay_report(
    source: Mapping[str, Any],
    rules_artifact: Mapping[str, Any],
    preregistration: Mapping[str, Any],
    funding_veto_historical_path: str | Path,
    attribution_historical_path: str | Path,
) -> dict[str, Any]:
    validate_funding_veto_state_decay_registration(
        preregistration,
        rules_artifact,
        funding_veto_historical_path,
        attribution_historical_path,
    )
    rules, rules_hash = selected_um_rules(rules_artifact)
    bars = align_bars(source["bars"], TOP3)
    data_hash = _data_hash(bars, source["funding"])
    registered_source = preregistration["source_historical"]
    if data_hash != registered_source["full_window_data_hash"]:
        raise ValueError("funding-veto state-decay data hash mismatch")
    _, reference, candidate, funding_activity = _run_variants(
        bars, source["funding"], rules
    )
    reference_metrics = _metrics(reference)
    candidate_metrics = _metrics(candidate, funding_activity)
    reference_replay_delta = _metric_deltas(
        reference_metrics, registered_source["reference_metrics"]
    )
    candidate_replay_delta = _metric_deltas(
        candidate_metrics, registered_source["candidate_metrics"]
    )
    protocol = FUNDING_VETO_STATE_DECAY_PROTOCOL
    replay_exact = all(
        abs(value) <= protocol.historical_replay_tolerance
        for value in list(reference_replay_delta.values()) + list(candidate_replay_delta.values())
    )
    decay = build_state_decay_diagnostic(
        reference, candidate, registered_source["event_dates"]
    )
    expected = preregistration["source_attribution"]
    events = decay["events"]
    final_event = events[-1]
    gates = {
        "exact_historical_replay": replay_exact,
        "execution_state_coverage": decay["execution_state_coverage"] == 1.0,
        "all_registered_veto_events": len(events) == registered_source["event_count"]
        and not any(row["missing"] for row in events),
        "return_divergence_counts_match_attribution": decay["return_divergent_bar_count"]
        == expected["divergent_bar_count"]
        and decay["downstream_return_divergent_bar_count"]
        == expected["downstream_divergent_bar_count"],
        "all_veto_events_start_in_divergent_state": all(
            row.get("state_divergent_on_event") is True for row in events
        ),
        "all_veto_events_eventually_first_resynchronize": all(
            row.get("first_sync_date") is not None for row in events
        ),
        "final_veto_stably_resynchronizes_by_window_end": final_event.get(
            "stable_sync_before_next_veto_date"
        )
        is not None,
    }
    passed = all(gates.values())
    return {
        "schema_version": FUNDING_VETO_STATE_DECAY_REPORT_VERSION,
        "artifact_type": "mini_trend_um_funding_veto_state_decay_historical_diagnostic",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "discovery_pool",
            "existing_cache_only": True,
            "network_download_used": False,
            "execution_state_sync_excludes_equity": True,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "contract_hash": protocol.contract_hash,
        "protocol_hash": protocol.protocol_hash,
        "exchange_rules_hash": rules_hash,
        "source_historical_sha256": registered_source["artifact_sha256"],
        "source_attribution_sha256": expected["artifact_sha256"],
        "data_hash": data_hash,
        "historical_replay": {
            "exact": replay_exact,
            "tolerance": protocol.historical_replay_tolerance,
            "reference_metric_deltas": reference_replay_delta,
            "candidate_metric_deltas": candidate_replay_delta,
        },
        "state_decay": decay,
        "diagnostics": {
            "gates": gates,
            "diagnostic_gate_passed": passed,
            "verdict": (
                "historical_execution_state_decay_resolved"
                if passed
                else "historical_execution_state_decay_unresolved"
            ),
            "interpretation": (
                "Execution-state synchronization excludes persistent account-equity differences; "
                "first synchronization does not imply permanent path equivalence."
            ),
            "paper_or_live_allowed": False,
        },
    }


def write_funding_veto_state_decay_preregistration_artifact(
    settings: Settings, payload: dict[str, Any], *, explicit_path: str | None = None
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-um-funding-veto-state-decay-preregistration",
        path_key="artifact_path",
        default_filename="mini_trend_um_funding_veto_state_decay_preregistration.json",
        explicit_path=explicit_path,
    )


def write_funding_veto_state_decay_report_artifact(
    settings: Settings, payload: dict[str, Any], *, explicit_path: str | None = None
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-um-funding-veto-state-decay-historical",
        path_key="artifact_path",
        default_filename="mini_trend_um_funding_veto_state_decay_historical.json",
        explicit_path=explicit_path,
    )
