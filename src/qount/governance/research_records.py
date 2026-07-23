"""Immutable research-governance records for the R0 evidence plane.

These records are deliberately data-only contracts.  They make lineage,
point-in-time membership, NAV definitions, costs, and candidate gates
machine-readable without implying promotion or live authority.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from dataclasses import fields
from typing import Any, Mapping, Sequence

from qount.contracts.hashing import canonical_hash
from qount.contracts.trace import aware_datetime
from qount.contracts.trace import is_sha256


RESEARCH_RECORD_SCHEMA_VERSION = 1
RESEARCH_DECISIONS = (
    "planned",
    "active_research",
    "retain",
    "reject",
    "blocked",
)
RESEARCH_DATA_ROLES = (
    "discovery_pool",
    "promotion_pool",
    "consumed_historical_discovery_pool",
    "point_in_time_collection",
    "point_in_time_forward_collection",
)
LIFECYCLE_STATES = ("active", "delisted", "suspended", "unknown")
RESEARCH_EVIDENCE_STATUSES = ("available", "partial", "unavailable")
RESEARCH_EVIDENCE_TYPES = (
    "historical_family_mapping",
    "point_in_time_lifecycle",
    "cost_model",
    "standalone_nav_readiness",
)


def _record_hash(core: Mapping[str, Any]) -> str:
    return canonical_hash(dict(core))


def _as_dict(record: object) -> dict[str, Any]:
    return {
        field.name: getattr(record, field.name)
        for field in fields(record)
    }


def _hash_error(
    value: Mapping[str, Any],
    hash_field: str,
    error: str,
) -> tuple[str, ...]:
    if value.get(hash_field) != _record_hash(
        {key: item for key, item in value.items() if key != hash_field}
    ):
        return (error,)
    return ()


def _datetime_error(value: str, name: str) -> tuple[str, ...]:
    try:
        aware_datetime(value)
    except (AttributeError, TypeError, ValueError):
        return (f"{name}_invalid",)
    return ()


@dataclass(frozen=True)
class HistoricalFamilyMapping:
    """Maps old strategy/family labels without inheriting their verdicts."""

    current_family: str
    historical_family_ids: tuple[str, ...]
    mapping_reason: str
    mapping_status: str = "review_required"
    mapping_hash: str = ""

    @classmethod
    def create(
        cls,
        *,
        current_family: str,
        historical_family_ids: Sequence[str],
        mapping_reason: str,
        mapping_status: str = "review_required",
    ) -> "HistoricalFamilyMapping":
        core = {
            "current_family": current_family,
            "historical_family_ids": tuple(sorted(historical_family_ids)),
            "mapping_reason": mapping_reason,
            "mapping_status": mapping_status,
        }
        return cls(**core, mapping_hash=_record_hash(core))

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not self.current_family:
            errors.append("family_mapping_current_family_empty")
        if not self.historical_family_ids:
            errors.append("family_mapping_historical_ids_empty")
        if not self.mapping_reason.strip():
            errors.append("family_mapping_reason_empty")
        if self.mapping_status not in {"review_required", "confirmed", "rejected"}:
            errors.append("family_mapping_status_invalid")
        errors.extend(
            _hash_error(_as_dict(self), "mapping_hash", "family_mapping_hash_invalid")
        )
        return tuple(errors)


@dataclass(frozen=True)
class ResearchEvidenceReadinessRecord:
    """Hash-bound statement of which R0 evidence is and is not available."""

    record_id: str
    evidence_type: str
    scope: str
    status: str
    available_evidence: Mapping[str, Any]
    missing_evidence: Mapping[str, str]
    source_hashes: Mapping[str, str]
    supports_research: bool
    supports_candidate_pnl: bool
    supports_promotion: bool
    orders_allowed: bool
    record_hash: str

    @classmethod
    def create(
        cls,
        *,
        evidence_type: str,
        scope: str,
        status: str,
        available_evidence: Mapping[str, Any],
        missing_evidence: Mapping[str, str],
        source_hashes: Mapping[str, str],
        supports_research: bool,
        supports_candidate_pnl: bool,
        supports_promotion: bool = False,
        orders_allowed: bool = False,
    ) -> "ResearchEvidenceReadinessRecord":
        core = {
            "evidence_type": evidence_type,
            "scope": scope,
            "status": status,
            "available_evidence": dict(available_evidence),
            "missing_evidence": dict(sorted(missing_evidence.items())),
            "source_hashes": dict(sorted(source_hashes.items())),
            "supports_research": supports_research,
            "supports_candidate_pnl": supports_candidate_pnl,
            "supports_promotion": supports_promotion,
            "orders_allowed": orders_allowed,
        }
        record_hash = _record_hash(core)
        return cls(record_id=record_hash, **core, record_hash=record_hash)

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.evidence_type not in RESEARCH_EVIDENCE_TYPES:
            errors.append("research_evidence_type_invalid")
        if not self.scope.strip():
            errors.append("research_evidence_scope_empty")
        if self.status not in RESEARCH_EVIDENCE_STATUSES:
            errors.append("research_evidence_status_invalid")
        if self.status == "available" and self.missing_evidence:
            errors.append("research_evidence_available_has_missing_fields")
        if self.status in {"partial", "unavailable"} and not self.missing_evidence:
            errors.append("research_evidence_missing_reasons_required")
        if not self.source_hashes:
            errors.append("research_evidence_source_hashes_empty")
        for source_name, source_hash in self.source_hashes.items():
            if not source_name or not is_sha256(source_hash):
                errors.append(f"research_evidence_source_hash_invalid:{source_name}")
        for field_name, reason in self.missing_evidence.items():
            if not field_name or not reason.strip():
                errors.append(f"research_evidence_missing_reason_invalid:{field_name}")
        if self.supports_candidate_pnl and not self.supports_research:
            errors.append("research_evidence_candidate_pnl_without_research")
        if self.supports_promotion and not self.supports_candidate_pnl:
            errors.append("research_evidence_promotion_without_candidate_pnl")
        if self.orders_allowed:
            errors.append("research_evidence_order_authority_forbidden")
        value = _as_dict(self)
        value.pop("record_id", None)
        errors.extend(
            _hash_error(
                value,
                "record_hash",
                "research_evidence_record_hash_invalid",
            )
        )
        if self.record_id != self.record_hash:
            errors.append("research_evidence_record_id_invalid")
        return tuple(errors)


@dataclass(frozen=True)
class GlobalExperimentRecord:
    """Cross-line trial index entry required before result interpretation."""

    schema_version: int
    experiment_id: str
    hypothesis_family: str
    trial_number_within_family: int
    research_question: str
    economic_mechanism: str
    baseline_ids: tuple[str, ...]
    preregistered_primary_metric: str
    preregistered_failure_conditions: tuple[str, ...]
    allowed_sensitivity_range: Mapping[str, Any]
    dataset_ids: tuple[str, ...]
    data_role: str
    untouched_data_ids: tuple[str, ...]
    code_hash: str
    config_hash: str
    source_hashes: Mapping[str, str]
    first_result_observed_at: str | None
    reviewer_observations: tuple[Mapping[str, Any], ...]
    result_artifact_hash: str | None
    decision: str
    contamination_notes: tuple[str, ...]
    record_hash: str

    @classmethod
    def create(
        cls,
        *,
        hypothesis_family: str,
        trial_number_within_family: int,
        research_question: str,
        economic_mechanism: str,
        baseline_ids: Sequence[str] = (),
        preregistered_primary_metric: str,
        preregistered_failure_conditions: Sequence[str],
        allowed_sensitivity_range: Mapping[str, Any],
        dataset_ids: Sequence[str] = (),
        data_role: str = "discovery_pool",
        untouched_data_ids: Sequence[str] = (),
        code_hash: str,
        config_hash: str,
        source_hashes: Mapping[str, str] | None = None,
        first_result_observed_at: str | None = None,
        reviewer_observations: Sequence[Mapping[str, Any]] = (),
        result_artifact_hash: str | None = None,
        decision: str = "planned",
        contamination_notes: Sequence[str] = (),
    ) -> "GlobalExperimentRecord":
        core = {
            "schema_version": RESEARCH_RECORD_SCHEMA_VERSION,
            "hypothesis_family": hypothesis_family,
            "trial_number_within_family": trial_number_within_family,
            "research_question": research_question,
            "economic_mechanism": economic_mechanism,
            "baseline_ids": tuple(sorted(baseline_ids)),
            "preregistered_primary_metric": preregistered_primary_metric,
            "preregistered_failure_conditions": tuple(preregistered_failure_conditions),
            "allowed_sensitivity_range": dict(allowed_sensitivity_range),
            "dataset_ids": tuple(sorted(dataset_ids)),
            "data_role": data_role,
            "untouched_data_ids": tuple(sorted(untouched_data_ids)),
            "code_hash": code_hash,
            "config_hash": config_hash,
            "source_hashes": dict(sorted((source_hashes or {}).items())),
            "first_result_observed_at": first_result_observed_at,
            "reviewer_observations": tuple(dict(item) for item in reviewer_observations),
            "result_artifact_hash": result_artifact_hash,
            "decision": decision,
            "contamination_notes": tuple(contamination_notes),
        }
        record_hash = _record_hash(core)
        return cls(
            schema_version=RESEARCH_RECORD_SCHEMA_VERSION,
            experiment_id=record_hash,
            **{key: value for key, value in core.items() if key != "schema_version"},
            record_hash=record_hash,
        )

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not self.experiment_id:
            errors.append("global_experiment_id_empty")
        if not self.hypothesis_family:
            errors.append("global_experiment_family_empty")
        if self.trial_number_within_family < 1:
            errors.append("global_experiment_trial_number_invalid")
        for name, value in (
            ("research_question", self.research_question),
            ("economic_mechanism", self.economic_mechanism),
            ("preregistered_primary_metric", self.preregistered_primary_metric),
        ):
            if not value.strip():
                errors.append(f"global_experiment_{name}_empty")
        if not self.preregistered_failure_conditions:
            errors.append("global_experiment_failure_conditions_empty")
        if self.data_role not in RESEARCH_DATA_ROLES:
            errors.append("global_experiment_data_role_invalid")
        if self.decision not in RESEARCH_DECISIONS:
            errors.append("global_experiment_decision_invalid")
        if not is_sha256(self.code_hash):
            errors.append("global_experiment_code_hash_invalid")
        if not is_sha256(self.config_hash):
            errors.append("global_experiment_config_hash_invalid")
        for source_name, source_hash in self.source_hashes.items():
            if not source_name or not is_sha256(source_hash):
                errors.append(f"global_experiment_source_hash_invalid:{source_name}")
        if self.first_result_observed_at is not None:
            errors.extend(
                _datetime_error(
                    self.first_result_observed_at,
                    "global_experiment_first_result_observed_at",
                )
            )
        if self.result_artifact_hash is None and self.decision in {"retain", "reject"}:
            errors.append("global_experiment_result_hash_required")
        core = _as_dict(self)
        core.pop("experiment_id", None)
        core.pop("record_hash", None)
        errors.extend(
            _hash_error(
                {**core, "record_hash": self.record_hash},
                "record_hash",
                "global_experiment_record_hash_invalid",
            )
        )
        return tuple(errors)


@dataclass(frozen=True)
class PointInTimeSymbolLifecycle:
    symbol: str
    venue: str
    valid_from: str
    valid_to: str | None
    state: str
    rules_hash: str | None
    source_hash: str
    lifecycle_hash: str

    @classmethod
    def create(
        cls,
        *,
        symbol: str,
        venue: str,
        valid_from: str,
        valid_to: str | None,
        state: str,
        rules_hash: str | None,
        source_hash: str,
    ) -> "PointInTimeSymbolLifecycle":
        core = {
            "symbol": symbol,
            "venue": venue,
            "valid_from": valid_from,
            "valid_to": valid_to,
            "state": state,
            "rules_hash": rules_hash,
            "source_hash": source_hash,
        }
        return cls(**core, lifecycle_hash=_record_hash(core))

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not self.symbol or not self.venue:
            errors.append("symbol_lifecycle_identity_empty")
        errors.extend(_datetime_error(self.valid_from, "symbol_lifecycle_valid_from"))
        if self.valid_to is not None:
            errors.extend(_datetime_error(self.valid_to, "symbol_lifecycle_valid_to"))
            try:
                if aware_datetime(self.valid_to) <= aware_datetime(self.valid_from):
                    errors.append("symbol_lifecycle_interval_invalid")
            except (AttributeError, TypeError, ValueError):
                pass
        if self.state not in LIFECYCLE_STATES:
            errors.append("symbol_lifecycle_state_invalid")
        if not is_sha256(self.source_hash):
            errors.append("symbol_lifecycle_source_hash_invalid")
        errors.extend(
            _hash_error(
                _as_dict(self),
                "lifecycle_hash",
                "symbol_lifecycle_hash_invalid",
            )
        )
        return tuple(errors)


@dataclass(frozen=True)
class PointInTimeUniverseRevision:
    revision_id: str
    as_of: str
    venue: str
    included_symbols: tuple[str, ...]
    exclusion_reasons: Mapping[str, str]
    lifecycle_hashes: tuple[str, ...]
    source_hashes: Mapping[str, str]
    dataset_role: str
    revision_hash: str

    @classmethod
    def create(
        cls,
        *,
        as_of: str,
        venue: str,
        included_symbols: Sequence[str],
        exclusion_reasons: Mapping[str, str],
        lifecycle_hashes: Sequence[str],
        source_hashes: Mapping[str, str],
        dataset_role: str = "point_in_time_collection",
    ) -> "PointInTimeUniverseRevision":
        core = {
            "as_of": as_of,
            "venue": venue,
            "included_symbols": tuple(sorted(set(included_symbols))),
            "exclusion_reasons": dict(sorted(exclusion_reasons.items())),
            "lifecycle_hashes": tuple(sorted(lifecycle_hashes)),
            "source_hashes": dict(sorted(source_hashes.items())),
            "dataset_role": dataset_role,
        }
        revision_hash = _record_hash(core)
        return cls(revision_id=revision_hash, **core, revision_hash=revision_hash)

    def validate(self) -> tuple[str, ...]:
        errors = list(_datetime_error(self.as_of, "universe_revision_as_of"))
        if not self.venue:
            errors.append("universe_revision_venue_empty")
        if self.dataset_role not in {
            "point_in_time_collection",
            "point_in_time_forward_collection",
            "synthetic_fixture",
        }:
            errors.append("universe_revision_dataset_role_invalid")
        if len(self.included_symbols) != len(set(self.included_symbols)):
            errors.append("universe_revision_symbol_duplicate")
        if set(self.exclusion_reasons) & set(self.included_symbols):
            errors.append("universe_revision_included_symbol_has_exclusion_reason")
        value = _as_dict(self)
        value.pop("revision_id", None)
        errors.extend(
            _hash_error(value, "revision_hash", "universe_revision_hash_invalid")
        )
        return tuple(errors)


def build_point_in_time_universe(
    lifecycles: Sequence[PointInTimeSymbolLifecycle],
    *,
    as_of: str,
    venue: str,
    source_hashes: Mapping[str, str],
    exclusion_reasons: Mapping[str, str] | None = None,
    dataset_role: str = "point_in_time_collection",
) -> PointInTimeUniverseRevision:
    """Select membership using only lifecycle intervals known at ``as_of``."""

    cutoff = aware_datetime(as_of)
    selected: dict[str, PointInTimeSymbolLifecycle] = {}
    for lifecycle in lifecycles:
        errors = lifecycle.validate()
        if errors:
            raise ValueError(",".join(errors))
        if lifecycle.venue != venue:
            continue
        start = aware_datetime(lifecycle.valid_from)
        end = aware_datetime(lifecycle.valid_to) if lifecycle.valid_to else None
        if start <= cutoff and (end is None or cutoff < end):
            previous = selected.get(lifecycle.symbol)
            if previous is None or aware_datetime(previous.valid_from) < start:
                selected[lifecycle.symbol] = lifecycle
    active = {
        symbol: lifecycle
        for symbol, lifecycle in selected.items()
        if lifecycle.state == "active"
    }
    reasons = dict(exclusion_reasons or {})
    for lifecycle in lifecycles:
        if lifecycle.venue != venue or lifecycle.symbol in active:
            continue
        try:
            starts_after_cutoff = aware_datetime(lifecycle.valid_from) > cutoff
        except (AttributeError, TypeError, ValueError):
            starts_after_cutoff = False
        reasons.setdefault(
            lifecycle.symbol,
            "not_yet_listed" if starts_after_cutoff else lifecycle.state,
        )
    return PointInTimeUniverseRevision.create(
        as_of=as_of,
        venue=venue,
        included_symbols=sorted(active),
        exclusion_reasons=reasons,
        lifecycle_hashes=[item.lifecycle_hash for item in selected.values()],
        source_hashes=source_hashes,
        dataset_role=dataset_role,
    )


@dataclass(frozen=True)
class UnifiedNavScorecard:
    """One scorecard vocabulary for signal, executable, and account NAV."""

    candidate_id: str
    signal_nav: float
    standalone_executable_nav: float
    portfolio_realized_nav: float
    beta_residual_return: float
    total_cost: float
    cost_model_hash: str
    trial_count: int
    fold_metrics: tuple[Mapping[str, Any], ...]
    data_hash: str
    scorecard_hash: str

    @classmethod
    def create(
        cls,
        *,
        candidate_id: str,
        signal_nav: float,
        standalone_executable_nav: float,
        portfolio_realized_nav: float,
        beta_residual_return: float,
        total_cost: float,
        cost_model_hash: str,
        trial_count: int,
        fold_metrics: Sequence[Mapping[str, Any]],
        data_hash: str,
    ) -> "UnifiedNavScorecard":
        core = {
            "candidate_id": candidate_id,
            "signal_nav": signal_nav,
            "standalone_executable_nav": standalone_executable_nav,
            "portfolio_realized_nav": portfolio_realized_nav,
            "beta_residual_return": beta_residual_return,
            "total_cost": total_cost,
            "cost_model_hash": cost_model_hash,
            "trial_count": trial_count,
            "fold_metrics": tuple(dict(item) for item in fold_metrics),
            "data_hash": data_hash,
        }
        return cls(**core, scorecard_hash=_record_hash(core))

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not self.candidate_id:
            errors.append("nav_scorecard_candidate_id_empty")
        for name in (
            "signal_nav",
            "standalone_executable_nav",
            "portfolio_realized_nav",
            "beta_residual_return",
            "total_cost",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value):
                errors.append(f"nav_scorecard_{name}_non_finite")
        if self.signal_nav <= 0 or self.standalone_executable_nav <= 0 or self.portfolio_realized_nav <= 0:
            errors.append("nav_scorecard_nav_non_positive")
        if self.total_cost < 0:
            errors.append("nav_scorecard_cost_negative")
        if self.trial_count < 0:
            errors.append("nav_scorecard_trial_count_negative")
        errors.extend(
            _hash_error(_as_dict(self), "scorecard_hash", "nav_scorecard_hash_invalid")
        )
        if not is_sha256(self.cost_model_hash):
            errors.append("nav_scorecard_cost_model_hash_invalid")
        if not is_sha256(self.data_hash):
            errors.append("nav_scorecard_data_hash_invalid")
        return tuple(errors)


@dataclass(frozen=True)
class CandidateRevalidationRecord:
    """Frozen revalidation contract before any combination PnL is run."""

    candidate_id: str
    hypothesis_family: str
    historical_evidence_ids: tuple[str, ...]
    current_data_ids: tuple[str, ...]
    untouched_data_ids: tuple[str, ...]
    venue_and_account_scope: str
    baseline_ids: tuple[str, ...]
    frozen_cost_model: Mapping[str, Any]
    execution_contract: Mapping[str, Any]
    standalone_nav_artifacts: tuple[str, ...]
    factor_and_beta_plan: Mapping[str, Any]
    tail_scenarios: tuple[str, ...]
    primary_metric: str
    kill_tests: tuple[str, ...]
    trial_budget: int
    owner_authorization_state: str
    decision: str
    record_hash: str

    @classmethod
    def create(
        cls,
        *,
        candidate_id: str,
        hypothesis_family: str,
        historical_evidence_ids: Sequence[str],
        current_data_ids: Sequence[str],
        untouched_data_ids: Sequence[str],
        venue_and_account_scope: str,
        baseline_ids: Sequence[str],
        frozen_cost_model: Mapping[str, Any],
        execution_contract: Mapping[str, Any],
        standalone_nav_artifacts: Sequence[str],
        factor_and_beta_plan: Mapping[str, Any],
        tail_scenarios: Sequence[str],
        primary_metric: str,
        kill_tests: Sequence[str],
        trial_budget: int,
        owner_authorization_state: str,
        decision: str,
    ) -> "CandidateRevalidationRecord":
        core = {
            "candidate_id": candidate_id,
            "hypothesis_family": hypothesis_family,
            "historical_evidence_ids": tuple(historical_evidence_ids),
            "current_data_ids": tuple(current_data_ids),
            "untouched_data_ids": tuple(untouched_data_ids),
            "venue_and_account_scope": venue_and_account_scope,
            "baseline_ids": tuple(baseline_ids),
            "frozen_cost_model": dict(frozen_cost_model),
            "execution_contract": dict(execution_contract),
            "standalone_nav_artifacts": tuple(standalone_nav_artifacts),
            "factor_and_beta_plan": dict(factor_and_beta_plan),
            "tail_scenarios": tuple(tail_scenarios),
            "primary_metric": primary_metric,
            "kill_tests": tuple(kill_tests),
            "trial_budget": trial_budget,
            "owner_authorization_state": owner_authorization_state,
            "decision": decision,
        }
        return cls(**core, record_hash=_record_hash(core))

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        for name in (
            "candidate_id",
            "hypothesis_family",
            "venue_and_account_scope",
            "primary_metric",
        ):
            if not str(getattr(self, name)).strip():
                errors.append(f"candidate_revalidation_{name}_empty")
        if not self.historical_evidence_ids:
            errors.append("candidate_revalidation_historical_evidence_empty")
        if not self.current_data_ids:
            errors.append("candidate_revalidation_current_data_empty")
        if not self.baseline_ids:
            errors.append("candidate_revalidation_baseline_empty")
        if not self.kill_tests:
            errors.append("candidate_revalidation_kill_tests_empty")
        if self.trial_budget <= 0:
            errors.append("candidate_revalidation_trial_budget_invalid")
        if self.decision not in RESEARCH_DECISIONS:
            errors.append("candidate_revalidation_decision_invalid")
        if not self.owner_authorization_state:
            errors.append("candidate_revalidation_authorization_state_empty")
        orders_allowed = self.execution_contract.get("orders_allowed")
        if not isinstance(orders_allowed, bool):
            errors.append("candidate_revalidation_orders_allowed_invalid")
        if self.decision == "active_research" and not bool(
            self.execution_contract.get("research_execution_allowed")
        ):
            errors.append("candidate_revalidation_research_execution_not_allowed")
        if (
            "carry" in self.hypothesis_family.lower()
            and orders_allowed is True
            and self.owner_authorization_state != "authorized"
        ):
            errors.append("candidate_revalidation_carry_order_authorization_required")
        errors.extend(
            _hash_error(
                _as_dict(self),
                "record_hash",
                "candidate_revalidation_hash_invalid",
            )
        )
        return tuple(errors)


def build_r0_candidate_records(
    evidence_records: Mapping[str, ResearchEvidenceReadinessRecord],
) -> tuple[CandidateRevalidationRecord, ...]:
    """Build v4 candidates from explicit evidence records, never placeholders."""

    required = {
        "cxd_family": "historical_family_mapping",
        "cxd_lifecycle": "point_in_time_lifecycle",
        "cxd_cost": "cost_model",
        "cxd_nav": "standalone_nav_readiness",
        "cta_r_family": "historical_family_mapping",
        "cta_r_lifecycle": "point_in_time_lifecycle",
        "cta_r_cost": "cost_model",
        "cta_r_nav": "standalone_nav_readiness",
    }
    missing = sorted(set(required) - set(evidence_records))
    if missing:
        raise ValueError("r0_evidence_records_missing:" + ",".join(missing))
    for name, expected_type in required.items():
        record = evidence_records[name]
        errors = record.validate()
        if errors:
            raise ValueError(f"r0_evidence_record_invalid:{name}:" + ",".join(errors))
        if record.evidence_type != expected_type:
            raise ValueError(f"r0_evidence_record_type_mismatch:{name}")

    common = {
        "untouched_data_ids": (),
        "baseline_ids": ("base_v0.2_frozen_control",),
        "factor_and_beta_plan": {
            "market": "crypto_market",
            "momentum": "required",
            "carry": "required_if_applicable",
        },
        "tail_scenarios": ("basis_tail", "cost_shock", "gap_and_missing_data"),
        "primary_metric": "cost_adjusted_standalone_executable_nav",
        "kill_tests": (
            "standalone_nav_non_positive_after_tail",
            "independent_nav_reconciliation_failure",
            "point_in_time_data_gap",
        ),
        "trial_budget": 3,
    }
    cxd_family = evidence_records["cxd_family"]
    cxd_lifecycle = evidence_records["cxd_lifecycle"]
    cxd_cost = evidence_records["cxd_cost"]
    cxd_nav = evidence_records["cxd_nav"]
    cxd = CandidateRevalidationRecord.create(
        candidate_id="cxd-trend-carry-revalidation-v4",
        hypothesis_family="cxd_trend_carry",
        historical_evidence_ids=(cxd_family.record_id,),
        current_data_ids=(cxd_lifecycle.record_id,),
        frozen_cost_model={
            "status": cxd_cost.status,
            "evidence_id": cxd_cost.record_id,
            "evidence_hash": cxd_cost.record_hash,
            "candidate_pnl_ready": cxd_cost.supports_candidate_pnl,
        },
        standalone_nav_artifacts=(cxd_nav.record_id,),
        venue_and_account_scope="historical_discovery_shadow_virtual; no carry order permission",
        execution_contract={
            "mode": "research_virtual",
            "carry": "observation_shadow_virtual",
            "research_execution_allowed": True,
            "orders_allowed": False,
            "blocks_local_progress": False,
            "trial_budget_blocks_research": False,
            "candidate_pnl_ready": all(
                record.supports_candidate_pnl
                for record in (cxd_lifecycle, cxd_cost, cxd_nav)
            ),
        },
        owner_authorization_state="owner_authorized_research",
        decision="active_research",
        **common,
    )
    cta_family = evidence_records["cta_r_family"]
    cta_lifecycle = evidence_records["cta_r_lifecycle"]
    cta_cost = evidence_records["cta_r_cost"]
    cta_nav = evidence_records["cta_r_nav"]
    cta_r = CandidateRevalidationRecord.create(
        candidate_id="cta-r-cross-asset-revalidation-v4",
        hypothesis_family="cta_r_cross_asset",
        historical_evidence_ids=(cta_family.record_id,),
        current_data_ids=(cta_lifecycle.record_id,),
        frozen_cost_model={
            "status": cta_cost.status,
            "evidence_id": cta_cost.record_id,
            "evidence_hash": cta_cost.record_hash,
            "candidate_pnl_ready": cta_cost.supports_candidate_pnl,
        },
        standalone_nav_artifacts=(cta_nav.record_id,),
        venue_and_account_scope="research_cross_asset_only; no Binance wallet order permission",
        execution_contract={
            "mode": "research_virtual",
            "research_execution_allowed": True,
            "orders_allowed": False,
            "blocks_local_progress": False,
            "trial_budget_blocks_research": False,
            "candidate_pnl_ready": all(
                record.supports_candidate_pnl
                for record in (cta_lifecycle, cta_cost, cta_nav)
            ),
        },
        owner_authorization_state="owner_authorized_research",
        decision="active_research",
        **common,
    )
    return (cxd, cta_r)
