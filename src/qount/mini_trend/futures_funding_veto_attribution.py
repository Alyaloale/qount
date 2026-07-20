"""Exact realized-return attribution for the fixed UM funding-veto candidate."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.grid.data import Bar, Funding
from qount.mini_trend.backtest import align_bars
from qount.mini_trend.forward import TOP3
from qount.mini_trend.futures_funding_veto import FUTURES_FUNDING_VETO_PROTOCOL
from qount.mini_trend.futures_funding_veto_report import FUNDING_VETO_REPORT_VERSION
from qount.mini_trend.futures_funding_veto_report import _data_hash, _metrics, _run_variants
from qount.mini_trend.futures_funding_veto_robustness import (
    FUNDING_VETO_ROBUSTNESS_REPORT_VERSION,
)
from qount.mini_trend.futures_funding_veto_robustness import (
    FUNDING_VETO_ROBUSTNESS_PROTOCOL,
)
from qount.mini_trend.futures_recovery import canonical_hash, selected_um_rules
from qount.mini_trend.futures_recovery_backtest import VariantResult
from qount.mini_trend.futures_risk_tier import file_sha256
from qount.models import utc_now
from qount.settings import Settings


FUNDING_VETO_ATTRIBUTION_PREREG_VERSION = (
    "mini_trend_um_funding_veto_attribution_preregistration_v0.1"
)
FUNDING_VETO_ATTRIBUTION_REPORT_VERSION = (
    "mini_trend_um_funding_veto_attribution_historical_v0.1"
)

ATTRIBUTION_GROUPS = (
    "event_price_exposure",
    "event_funding",
    "event_trading_cost",
    "downstream_price_exposure",
    "downstream_funding",
    "downstream_trading_cost",
)
_RETURN_COMPONENT_FIELDS = (
    "gross_price_return",
    "funding_return",
    "trading_cost_return",
)


@dataclass(frozen=True)
class FundingVetoAttributionProtocol:
    strategy: str = "MiniTrend-UM-FundingVeto-v0.1"
    reference: str = "MiniTrend-UM-RegimeStopLatch-v0.1"
    daily_identity_tolerance: float = 1e-12
    historical_replay_tolerance: float = 1e-8
    shapley_closure_tolerance_percentage_points: float = 1e-8

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
            "source": {
                "same fixed historical replay as the retained funding-veto report": True,
                "same bars_funding_filters_costs_and_state": True,
                "veto_event_dates_fixed_from_source_artifact": True,
            },
            "daily_return_identity": {
                "formula": "net = gross_price + funding + trading_cost_return",
                "trading_cost_return_is_non_positive": True,
                "tolerance": self.daily_identity_tolerance,
            },
            "attribution": {
                "method": "exact_six_group_shapley_over_terminal_compounded_return",
                "groups": list(ATTRIBUTION_GROUPS),
                "event_definition": "candidate funding-veto decision dates in the bound source artifact",
                "downstream_definition": "all other realized daily return observations",
                "coalitions_evaluated": 2 ** len(ATTRIBUTION_GROUPS),
                "ordering_search_allowed": False,
                "group_search_allowed": False,
                "component_sign_convention": {
                    "price_exposure": "candidate gross price return minus reference",
                    "funding": "candidate funding return minus reference; positive means saved funding cost",
                    "trading_cost": (
                        "candidate negative trading-cost return minus reference; positive means saved cost"
                    ),
                },
            },
            "limitations": {
                "holdout_role": "consumed_historical_discovery_only",
                "realized_path_accounting_not_counterfactual_execution": True,
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
            "mechanism_gates": {
                "exact_historical_replay_required": True,
                "daily_component_identity_required": True,
                "daily_group_delta_closure_required": True,
                "shapley_terminal_return_closure_required": True,
                "all_registered_veto_events_required": True,
                "positive_event_funding_contribution_required": True,
                "positive_total_funding_contribution_required": True,
            },
            "trial_count": 1,
            "parameter_search_allowed": False,
            "attribution_group_search_allowed": False,
            "ordering_search_allowed": False,
            "paper_or_live_allowed": False,
            "promotion_rule": (
                "Attribution may support or reject the historical cost-veto mechanism story; "
                "it cannot promote the strategy or create independent evidence."
            ),
        }

    @property
    def protocol_hash(self) -> str:
        return canonical_hash(self.protocol_basis)


FUNDING_VETO_ATTRIBUTION_PROTOCOL = FundingVetoAttributionProtocol()


def _load_object(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object at {path}")
    return payload


def _load_source_historical(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser()
    payload = _load_object(source)
    if payload.get("schema_version") != FUNDING_VETO_REPORT_VERSION:
        raise ValueError("unexpected funding-veto historical schema")
    if payload.get("artifact_type") != "mini_trend_um_funding_veto_historical_diagnostic":
        raise ValueError("unexpected funding-veto historical artifact")
    if payload.get("contract_hash") != FUTURES_FUNDING_VETO_PROTOCOL.contract_hash:
        raise ValueError("funding-veto historical contract hash mismatch")
    if payload.get("protocol_hash") != FUTURES_FUNDING_VETO_PROTOCOL.protocol_hash:
        raise ValueError("funding-veto historical protocol hash mismatch")
    if payload.get("diagnostics", {}).get("verdict") != (
        "retain_historical_funding_veto_candidate"
    ):
        raise ValueError("attribution requires the retained funding-veto candidate")
    meta = payload.get("meta", {})
    if meta.get("holdout_role") != "discovery_pool" or meta.get("network_download_used") is not False:
        raise ValueError("source historical artifact has an invalid data boundary")
    full = payload["full_window"]
    events = full["candidate"]["funding_veto_activity"]["events"]
    event_dates = [str(row["decision_date"]) for row in events]
    if len(set(event_dates)) != len(event_dates):
        raise ValueError("source historical artifact has duplicate funding-veto dates")
    metric_fields = ("return_pct", "sharpe", "max_drawdown_pct")
    return {
        "artifact_path": str(source),
        "artifact_sha256": file_sha256(source),
        "exchange_rules_hash": payload["exchange_rules_hash"],
        "full_window_data_hash": full["data_hash"],
        "reference_metrics": {
            key: full["reference_stop_latch"][key] for key in metric_fields
        },
        "candidate_metrics": {key: full["candidate"][key] for key in metric_fields},
        "event_dates": event_dates,
        "event_count": len(event_dates),
    }


def _load_robustness_historical(
    path: str | Path, source_historical_sha256: str
) -> dict[str, Any]:
    source = Path(path).expanduser()
    payload = _load_object(source)
    if payload.get("schema_version") != FUNDING_VETO_ROBUSTNESS_REPORT_VERSION:
        raise ValueError("unexpected funding-veto robustness schema")
    if payload.get("artifact_type") != (
        "mini_trend_um_funding_veto_robustness_historical_diagnostic"
    ):
        raise ValueError("unexpected funding-veto robustness artifact")
    if payload.get("contract_hash") != FUNDING_VETO_ROBUSTNESS_PROTOCOL.contract_hash:
        raise ValueError("funding-veto robustness contract hash mismatch")
    if payload.get("protocol_hash") != FUNDING_VETO_ROBUSTNESS_PROTOCOL.protocol_hash:
        raise ValueError("funding-veto robustness protocol hash mismatch")
    if payload.get("source_historical_sha256") != source_historical_sha256:
        raise ValueError("robustness artifact is not bound to the source historical report")
    if payload.get("diagnostics", {}).get("verdict") != (
        "retain_historical_candidate_after_conditional_bootstrap"
    ):
        raise ValueError("attribution requires the retained robustness result")
    return {
        "artifact_path": str(source),
        "artifact_sha256": file_sha256(source),
        "verdict": payload["diagnostics"]["verdict"],
        "win_probabilities": payload["bootstrap"]["win_probabilities"],
    }


def build_funding_veto_attribution_preregistration(
    rules_artifact: Mapping[str, Any],
    funding_veto_historical_path: str | Path,
    robustness_historical_path: str | Path,
) -> dict[str, Any]:
    _, rules_hash = selected_um_rules(rules_artifact)
    historical = _load_source_historical(funding_veto_historical_path)
    if historical["exchange_rules_hash"] != rules_hash:
        raise ValueError("source historical exchange-rules hash mismatch")
    robustness = _load_robustness_historical(
        robustness_historical_path, historical["artifact_sha256"]
    )
    protocol = FUNDING_VETO_ATTRIBUTION_PROTOCOL
    return {
        "schema_version": FUNDING_VETO_ATTRIBUTION_PREREG_VERSION,
        "artifact_type": "mini_trend_um_funding_veto_attribution_preregistration",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "attribution_results_evaluated": False,
            "source_historical_results_consumed": True,
            "source_robustness_results_consumed": True,
            "existing_cache_only": True,
            "network_download_allowed": False,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "decision_contract": protocol.contract_basis | {"contract_hash": protocol.contract_hash},
        "protocol": protocol.protocol_basis | {"protocol_hash": protocol.protocol_hash},
        "exchange_rules": {"selected_rules_hash": rules_hash, "symbols": sorted(TOP3)},
        "source_historical": historical,
        "source_robustness": robustness,
    }


def validate_funding_veto_attribution_registration(
    preregistration: Mapping[str, Any],
    rules_artifact: Mapping[str, Any],
    funding_veto_historical_path: str | Path,
    robustness_historical_path: str | Path,
) -> None:
    protocol = FUNDING_VETO_ATTRIBUTION_PROTOCOL
    if preregistration.get("schema_version") != FUNDING_VETO_ATTRIBUTION_PREREG_VERSION:
        raise ValueError("unexpected funding-veto attribution preregistration schema")
    if preregistration.get("decision_contract", {}).get("contract_hash") != protocol.contract_hash:
        raise ValueError("funding-veto attribution contract hash mismatch")
    if preregistration.get("protocol", {}).get("protocol_hash") != protocol.protocol_hash:
        raise ValueError("funding-veto attribution protocol hash mismatch")
    _, rules_hash = selected_um_rules(rules_artifact)
    if preregistration.get("exchange_rules", {}).get("selected_rules_hash") != rules_hash:
        raise ValueError("funding-veto attribution exchange-rules hash mismatch")
    historical = _load_source_historical(funding_veto_historical_path)
    if preregistration.get("source_historical", {}).get("artifact_sha256") != historical[
        "artifact_sha256"
    ]:
        raise ValueError("funding-veto attribution source historical hash mismatch")
    robustness = _load_robustness_historical(
        robustness_historical_path, historical["artifact_sha256"]
    )
    if preregistration.get("source_robustness", {}).get("artifact_sha256") != robustness[
        "artifact_sha256"
    ]:
        raise ValueError("funding-veto attribution robustness hash mismatch")


def terminal_return_pct(returns: Sequence[float]) -> float:
    equity = 1.0
    for value in returns:
        equity *= 1.0 + float(value)
        if equity <= 0.0:
            raise ValueError("attribution path equity became non-positive")
    return (equity - 1.0) * 100.0


def exact_shapley_terminal_attribution(
    reference_returns: Sequence[float],
    component_deltas: Mapping[str, Sequence[float]],
) -> dict[str, Any]:
    names = list(component_deltas)
    if not names:
        raise ValueError("attribution requires at least one component")
    observations = len(reference_returns)
    if observations == 0:
        raise ValueError("attribution requires realized returns")
    if any(len(component_deltas[name]) != observations for name in names):
        raise ValueError("all attribution components must align with the reference")
    coalition_values: dict[int, float] = {}
    for mask in range(1 << len(names)):
        path = [float(value) for value in reference_returns]
        for component_index, name in enumerate(names):
            if mask & (1 << component_index):
                path = [
                    value + float(delta)
                    for value, delta in zip(path, component_deltas[name])
                ]
        coalition_values[mask] = terminal_return_pct(path)
    factorial = math.factorial
    denominator = factorial(len(names))
    contributions: dict[str, float] = {}
    for component_index, name in enumerate(names):
        contribution = 0.0
        bit = 1 << component_index
        for mask in range(1 << len(names)):
            if mask & bit:
                continue
            subset_size = mask.bit_count()
            weight = (
                factorial(subset_size)
                * factorial(len(names) - subset_size - 1)
                / denominator
            )
            contribution += weight * (coalition_values[mask | bit] - coalition_values[mask])
        contributions[name] = contribution
    full_mask = (1 << len(names)) - 1
    total_delta = coalition_values[full_mask] - coalition_values[0]
    return {
        "reference_terminal_return_pct": coalition_values[0],
        "candidate_terminal_return_pct": coalition_values[full_mask],
        "candidate_minus_reference_percentage_points": total_delta,
        "group_contributions_percentage_points": contributions,
        "closure_error_percentage_points": sum(contributions.values()) - total_delta,
        "coalitions_evaluated": len(coalition_values),
    }


def _component_rows(
    reference: VariantResult,
    candidate: VariantResult,
    event_dates: Sequence[str],
) -> dict[str, Any]:
    if len(reference.equity) != len(candidate.equity):
        raise ValueError("reference and candidate return paths have different lengths")
    event_set = set(event_dates)
    matched_events: set[str] = set()
    reference_returns: list[float] = []
    candidate_returns: list[float] = []
    groups = {name: [] for name in ATTRIBUTION_GROUPS}
    maximum_identity_error = 0.0
    maximum_group_closure_error = 0.0
    divergent_bar_count = 0
    downstream_divergent_bar_count = 0
    for reference_row, candidate_row in zip(reference.equity, candidate.equity):
        identity = (reference_row["decision_date"], reference_row["outcome_date"])
        if identity != (candidate_row["decision_date"], candidate_row["outcome_date"]):
            raise ValueError("reference and candidate return paths are not date aligned")
        for row in (reference_row, candidate_row):
            recomposed = sum(float(row[field]) for field in _RETURN_COMPONENT_FIELDS)
            maximum_identity_error = max(
                maximum_identity_error, abs(float(row["net_return"]) - recomposed)
            )
        decision_date = str(candidate_row["decision_date"])
        timing = "event" if decision_date in event_set else "downstream"
        if timing == "event":
            matched_events.add(decision_date)
        deltas = {
            f"{timing}_price_exposure": float(candidate_row["gross_price_return"])
            - float(reference_row["gross_price_return"]),
            f"{timing}_funding": float(candidate_row["funding_return"])
            - float(reference_row["funding_return"]),
            f"{timing}_trading_cost": float(candidate_row["trading_cost_return"])
            - float(reference_row["trading_cost_return"]),
        }
        row_delta = float(candidate_row["net_return"]) - float(reference_row["net_return"])
        maximum_group_closure_error = max(
            maximum_group_closure_error, abs(row_delta - sum(deltas.values()))
        )
        divergent = abs(row_delta) > FUNDING_VETO_ATTRIBUTION_PROTOCOL.daily_identity_tolerance
        divergent_bar_count += int(divergent)
        downstream_divergent_bar_count += int(divergent and timing == "downstream")
        for name in ATTRIBUTION_GROUPS:
            groups[name].append(deltas.get(name, 0.0))
        reference_returns.append(float(reference_row["net_return"]))
        candidate_returns.append(float(candidate_row["net_return"]))
    missing_events = sorted(event_set - matched_events)
    return {
        "reference_returns": reference_returns,
        "candidate_returns": candidate_returns,
        "groups": groups,
        "observation_count": len(reference_returns),
        "matched_event_count": len(matched_events),
        "missing_event_dates": missing_events,
        "divergent_bar_count": divergent_bar_count,
        "downstream_divergent_bar_count": downstream_divergent_bar_count,
        "maximum_daily_component_identity_error": maximum_identity_error,
        "maximum_daily_group_delta_closure_error": maximum_group_closure_error,
    }


def _metric_deltas(actual: Mapping[str, Any], expected: Mapping[str, Any]) -> dict[str, float]:
    return {
        key: round(float(actual[key]) - float(expected[key]), 10)
        for key in ("return_pct", "sharpe", "max_drawdown_pct")
    }


def _group_report(
    groups: Mapping[str, Sequence[float]], shapley: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    contributions = shapley["group_contributions_percentage_points"]
    return {
        name: {
            "shapley_terminal_return_contribution_percentage_points": round(
                float(contributions[name]), 8
            ),
            "arithmetic_daily_return_delta_sum_percentage_points": round(
                sum(float(value) for value in groups[name]) * 100.0, 8
            ),
            "nonzero_bar_count": sum(
                abs(float(value)) > FUNDING_VETO_ATTRIBUTION_PROTOCOL.daily_identity_tolerance
                for value in groups[name]
            ),
        }
        for name in ATTRIBUTION_GROUPS
    }


def build_funding_veto_attribution_report(
    source: Mapping[str, Any],
    rules_artifact: Mapping[str, Any],
    preregistration: Mapping[str, Any],
    funding_veto_historical_path: str | Path,
    robustness_historical_path: str | Path,
) -> dict[str, Any]:
    validate_funding_veto_attribution_registration(
        preregistration,
        rules_artifact,
        funding_veto_historical_path,
        robustness_historical_path,
    )
    rules, rules_hash = selected_um_rules(rules_artifact)
    bars = align_bars(source["bars"], TOP3)
    data_hash = _data_hash(bars, source["funding"])
    registered_source = preregistration["source_historical"]
    if data_hash != registered_source["full_window_data_hash"]:
        raise ValueError("funding-veto attribution data hash mismatch")
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
    protocol = FUNDING_VETO_ATTRIBUTION_PROTOCOL
    replay_exact = all(
        abs(value) <= protocol.historical_replay_tolerance
        for value in list(reference_replay_delta.values()) + list(candidate_replay_delta.values())
    )
    components = _component_rows(
        reference, candidate, registered_source["event_dates"]
    )
    shapley = exact_shapley_terminal_attribution(
        components["reference_returns"], components["groups"]
    )
    group_report = _group_report(components["groups"], shapley)
    aggregate_contributions = {
        "event_total": sum(
            group_report[name]["shapley_terminal_return_contribution_percentage_points"]
            for name in ATTRIBUTION_GROUPS
            if name.startswith("event_")
        ),
        "downstream_total": sum(
            group_report[name]["shapley_terminal_return_contribution_percentage_points"]
            for name in ATTRIBUTION_GROUPS
            if name.startswith("downstream_")
        ),
        "price_exposure_total": sum(
            group_report[name]["shapley_terminal_return_contribution_percentage_points"]
            for name in ATTRIBUTION_GROUPS
            if name.endswith("price_exposure")
        ),
        "funding_total": sum(
            group_report[name]["shapley_terminal_return_contribution_percentage_points"]
            for name in ATTRIBUTION_GROUPS
            if name.endswith("funding")
        ),
        "trading_cost_total": sum(
            group_report[name]["shapley_terminal_return_contribution_percentage_points"]
            for name in ATTRIBUTION_GROUPS
            if name.endswith("trading_cost")
        ),
    }
    aggregate_contributions = {
        key: round(value, 8) for key, value in aggregate_contributions.items()
    }
    observed_delta = float(shapley["candidate_minus_reference_percentage_points"])
    contribution_shares = {
        key: round(value / observed_delta, 8) if abs(observed_delta) > 1e-15 else None
        for key, value in aggregate_contributions.items()
    }
    gates = {
        "exact_historical_replay": replay_exact,
        "daily_component_identity": components["maximum_daily_component_identity_error"]
        <= protocol.daily_identity_tolerance,
        "daily_group_delta_closure": components[
            "maximum_daily_group_delta_closure_error"
        ]
        <= protocol.daily_identity_tolerance,
        "shapley_terminal_return_closure": abs(
            float(shapley["closure_error_percentage_points"])
        )
        <= protocol.shapley_closure_tolerance_percentage_points,
        "all_registered_veto_events": components["matched_event_count"]
        == registered_source["event_count"]
        and not components["missing_event_dates"],
        "positive_event_funding_contribution": group_report["event_funding"][
            "shapley_terminal_return_contribution_percentage_points"
        ]
        > 0.0,
        "positive_total_funding_contribution": aggregate_contributions["funding_total"]
        > 0.0,
    }
    passed = all(gates.values())
    return {
        "schema_version": FUNDING_VETO_ATTRIBUTION_REPORT_VERSION,
        "artifact_type": "mini_trend_um_funding_veto_attribution_historical_diagnostic",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "discovery_pool",
            "existing_cache_only": True,
            "network_download_used": False,
            "realized_path_accounting": True,
            "counterfactual_execution_simulation": False,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "contract_hash": protocol.contract_hash,
        "protocol_hash": protocol.protocol_hash,
        "exchange_rules_hash": rules_hash,
        "source_historical_sha256": registered_source["artifact_sha256"],
        "source_robustness_sha256": preregistration["source_robustness"]["artifact_sha256"],
        "data_hash": data_hash,
        "historical_replay": {
            "exact": replay_exact,
            "tolerance": protocol.historical_replay_tolerance,
            "reference_metric_deltas": reference_replay_delta,
            "candidate_metric_deltas": candidate_replay_delta,
        },
        "accounting": {
            "observation_count": components["observation_count"],
            "registered_event_count": registered_source["event_count"],
            "matched_event_count": components["matched_event_count"],
            "missing_event_dates": components["missing_event_dates"],
            "divergent_bar_count": components["divergent_bar_count"],
            "downstream_divergent_bar_count": components[
                "downstream_divergent_bar_count"
            ],
            "maximum_daily_component_identity_error": components[
                "maximum_daily_component_identity_error"
            ],
            "maximum_daily_group_delta_closure_error": components[
                "maximum_daily_group_delta_closure_error"
            ],
            "shapley_coalitions_evaluated": shapley["coalitions_evaluated"],
            "shapley_closure_error_percentage_points": round(
                float(shapley["closure_error_percentage_points"]), 12
            ),
        },
        "terminal_return_attribution": {
            "reference_return_pct": round(
                float(shapley["reference_terminal_return_pct"]), 8
            ),
            "candidate_return_pct": round(
                float(shapley["candidate_terminal_return_pct"]), 8
            ),
            "candidate_minus_reference_percentage_points": round(observed_delta, 8),
            "groups": group_report,
            "aggregates": aggregate_contributions,
            "aggregate_contribution_shares": contribution_shares,
        },
        "diagnostics": {
            "gates": gates,
            "mechanism_gate_passed": passed,
            "verdict": (
                "historical_cost_veto_mechanism_supported"
                if passed
                else "historical_cost_veto_mechanism_not_supported"
            ),
            "interpretation": (
                "Shapley allocates realized compounded-return differences, including interactions; "
                "it does not simulate executable counterfactual paths or create OOS evidence."
            ),
            "paper_or_live_allowed": False,
        },
    }


def write_funding_veto_attribution_preregistration_artifact(
    settings: Settings, payload: dict[str, Any], *, explicit_path: str | None = None
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-um-funding-veto-attribution-preregistration",
        path_key="artifact_path",
        default_filename="mini_trend_um_funding_veto_attribution_preregistration.json",
        explicit_path=explicit_path,
    )


def write_funding_veto_attribution_report_artifact(
    settings: Settings, payload: dict[str, Any], *, explicit_path: str | None = None
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-um-funding-veto-attribution-historical",
        path_key="artifact_path",
        default_filename="mini_trend_um_funding_veto_attribution_historical.json",
        explicit_path=explicit_path,
    )
