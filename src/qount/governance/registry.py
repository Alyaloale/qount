"""Immutable strategy registry and deployment lineage contracts."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from qount.contracts import canonical_hash
from qount.contracts import is_sha256
from qount.contracts import StrategyIntent
from qount.contracts import trace_id
from qount.contracts.trace import aware_datetime


GOVERNANCE_SCHEMA_VERSION = 1
PROMOTION_STATUSES = (
    "draft",
    "research",
    "frozen_candidate",
    "shadow",
    "paper",
    "minimal_live",
    "scaled_live",
    "halted",
)
_STATUS_RANK = {
    status: index for index, status in enumerate(PROMOTION_STATUSES[:-1])
}
_NEXT_STATUS = {
    "draft": "research",
    "research": "frozen_candidate",
    "frozen_candidate": "shadow",
    "shadow": "paper",
    "paper": "minimal_live",
    "minimal_live": "scaled_live",
}
_STRATEGY_KINDS = {"continuous", "event", "filter"}
_LIVE_STATUSES = {"minimal_live", "scaled_live"}
_SEMVER_RE = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
_GIT_COMMIT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


def _optional_hash_error(value: str | None, name: str) -> str | None:
    if value is not None and not is_sha256(value):
        return f"{name}_invalid"
    return None


def _number(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


@dataclass(frozen=True)
class StrategyRegistration:
    schema_version: int
    registry_entry_id: str
    strategy_id: str
    strategy_version: str
    strategy_kind: str
    promotion_status: str
    strategy_contract_hash: str
    code_hash: str
    config_hash: str
    promotion_artifact_hash: str | None
    owner_authorization_hash: str | None
    maximum_stress_loss_fraction: float
    maximum_gross: float
    registered_at: str
    supersedes_entry_id: str | None
    halted_from_status: str | None
    recovery_evidence_hash: str | None
    entry_hash: str

    @classmethod
    def create(
        cls,
        *,
        strategy_id: str,
        strategy_version: str,
        strategy_kind: str,
        promotion_status: str,
        strategy_contract_hash: str,
        code_hash: str,
        config_hash: str,
        promotion_artifact_hash: str | None,
        owner_authorization_hash: str | None,
        maximum_stress_loss_fraction: float,
        maximum_gross: float,
        registered_at: str,
        supersedes_entry_id: str | None = None,
        halted_from_status: str | None = None,
        recovery_evidence_hash: str | None = None,
    ) -> StrategyRegistration:
        core = {
            "schema_version": GOVERNANCE_SCHEMA_VERSION,
            "strategy_id": strategy_id,
            "strategy_version": strategy_version,
            "strategy_kind": strategy_kind,
            "promotion_status": promotion_status,
            "strategy_contract_hash": strategy_contract_hash,
            "code_hash": code_hash,
            "config_hash": config_hash,
            "promotion_artifact_hash": promotion_artifact_hash,
            "owner_authorization_hash": owner_authorization_hash,
            "maximum_stress_loss_fraction": maximum_stress_loss_fraction,
            "maximum_gross": maximum_gross,
            "registered_at": registered_at,
            "supersedes_entry_id": supersedes_entry_id,
            "halted_from_status": halted_from_status,
            "recovery_evidence_hash": recovery_evidence_hash,
        }
        entry_hash = canonical_hash(core)
        registration = cls(
            **core,
            registry_entry_id=trace_id(
                "strategy_registration",
                {
                    "strategy_id": strategy_id,
                    "strategy_version": strategy_version,
                    "entry_hash": entry_hash,
                },
            ),
            entry_hash=entry_hash,
        )
        errors = registration.validate()
        if errors:
            raise ValueError(f"strategy_registration_invalid:{','.join(errors)}")
        return registration

    def _core(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "strategy_kind": self.strategy_kind,
            "promotion_status": self.promotion_status,
            "strategy_contract_hash": self.strategy_contract_hash,
            "code_hash": self.code_hash,
            "config_hash": self.config_hash,
            "promotion_artifact_hash": self.promotion_artifact_hash,
            "owner_authorization_hash": self.owner_authorization_hash,
            "maximum_stress_loss_fraction": self.maximum_stress_loss_fraction,
            "maximum_gross": self.maximum_gross,
            "registered_at": self.registered_at,
            "supersedes_entry_id": self.supersedes_entry_id,
            "halted_from_status": self.halted_from_status,
            "recovery_evidence_hash": self.recovery_evidence_hash,
        }

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.schema_version != GOVERNANCE_SCHEMA_VERSION:
            errors.append("strategy_registration_schema_version_invalid")
        if not self.strategy_id:
            errors.append("strategy_registration_strategy_id_empty")
        if not _SEMVER_RE.fullmatch(self.strategy_version):
            errors.append("strategy_registration_version_invalid")
        if self.strategy_kind not in _STRATEGY_KINDS:
            errors.append("strategy_registration_kind_invalid")
        if self.promotion_status not in PROMOTION_STATUSES:
            errors.append("strategy_registration_status_invalid")
        for name in ("strategy_contract_hash", "code_hash", "config_hash"):
            if not is_sha256(getattr(self, name)):
                errors.append(f"strategy_registration_{name}_invalid")
        for value, name in (
            (self.promotion_artifact_hash, "strategy_registration_promotion_hash"),
            (self.owner_authorization_hash, "strategy_registration_owner_hash"),
            (self.supersedes_entry_id, "strategy_registration_supersedes_id"),
            (self.recovery_evidence_hash, "strategy_registration_recovery_hash"),
        ):
            error = _optional_hash_error(value, name)
            if error:
                errors.append(error)
        try:
            aware_datetime(self.registered_at)
        except (AttributeError, TypeError, ValueError):
            errors.append("strategy_registration_time_invalid")
        risk_values = {
            name: _number(getattr(self, name))
            for name in ("maximum_stress_loss_fraction", "maximum_gross")
        }
        for name, value in risk_values.items():
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                errors.append(f"strategy_registration_{name}_invalid")

        status = self.promotion_status
        evidence_status = self.halted_from_status if status == "halted" else status
        if evidence_status in _STATUS_RANK:
            requires_promotion = _STATUS_RANK[evidence_status] >= _STATUS_RANK[
                "frozen_candidate"
            ]
            if requires_promotion and not is_sha256(self.promotion_artifact_hash):
                errors.append("strategy_registration_promotion_evidence_missing")
            if not requires_promotion and self.promotion_artifact_hash is not None:
                errors.append("strategy_registration_promotion_evidence_too_early")
        if status in _LIVE_STATUSES:
            if not is_sha256(self.owner_authorization_hash):
                errors.append("strategy_registration_owner_authorization_missing")
            if (
                risk_values["maximum_stress_loss_fraction"] <= 0.0
                or risk_values["maximum_gross"] <= 0.0
            ):
                errors.append("strategy_registration_live_risk_budget_empty")
            if self.strategy_kind == "filter":
                errors.append("strategy_registration_filter_cannot_be_live")
        if status == "halted":
            if self.halted_from_status not in _STATUS_RANK:
                errors.append("strategy_registration_halted_origin_invalid")
            if any(
                not math.isfinite(value) or abs(value) > 1e-12
                for value in risk_values.values()
            ):
                errors.append("strategy_registration_halted_risk_not_zero")
        elif self.halted_from_status is not None:
            errors.append("strategy_registration_halted_origin_unexpected")
        if self.recovery_evidence_hash is not None and not is_sha256(
            self.owner_authorization_hash
        ):
            errors.append("strategy_registration_recovery_owner_authorization_missing")

        expected_hash = canonical_hash(self._core())
        if self.entry_hash != expected_hash:
            errors.append("strategy_registration_hash_invalid")
        expected_id = trace_id(
            "strategy_registration",
            {
                "strategy_id": self.strategy_id,
                "strategy_version": self.strategy_version,
                "entry_hash": expected_hash,
            },
        )
        if self.registry_entry_id != expected_id:
            errors.append("strategy_registration_id_invalid")
        return tuple(errors)

    def as_dict(self) -> dict[str, Any]:
        return self._core() | {
            "registry_entry_id": self.registry_entry_id,
            "entry_hash": self.entry_hash,
        }


def validate_strategy_transition(
    previous: StrategyRegistration,
    current: StrategyRegistration,
) -> tuple[str, ...]:
    """Validate one immutable registry state transition."""

    errors: list[str] = []
    errors.extend(f"previous:{error}" for error in previous.validate())
    errors.extend(f"current:{error}" for error in current.validate())
    if previous.strategy_id != current.strategy_id:
        errors.append("strategy_transition_identity_mismatch")
    if current.supersedes_entry_id != previous.registry_entry_id:
        errors.append("strategy_transition_supersedes_mismatch")
    same_version = previous.strategy_version == current.strategy_version
    if same_version:
        immutable_fields = (
            "strategy_kind",
            "strategy_contract_hash",
            "code_hash",
            "config_hash",
        )
        for name in immutable_fields:
            if getattr(previous, name) != getattr(current, name):
                errors.append(f"strategy_transition_immutable_field_changed:{name}")
    elif current.promotion_status != "research":
        errors.append("strategy_transition_new_version_must_restart_research")
    risk_increased = (
        _number(current.maximum_stress_loss_fraction)
        > _number(previous.maximum_stress_loss_fraction) + 1e-12
        or _number(current.maximum_gross) > _number(previous.maximum_gross) + 1e-12
    )
    if risk_increased and not is_sha256(current.owner_authorization_hash):
        errors.append("strategy_transition_risk_increase_authorization_missing")
    try:
        if aware_datetime(current.registered_at) <= aware_datetime(
            previous.registered_at
        ):
            errors.append("strategy_transition_time_not_forward")
    except (AttributeError, TypeError, ValueError):
        pass

    if same_version:
        before = previous.promotion_status
        after = current.promotion_status
        if before == "halted":
            origin = previous.halted_from_status
            if after == "halted" or origin not in _STATUS_RANK:
                errors.append("strategy_transition_halted_recovery_status_invalid")
            elif after not in _STATUS_RANK or _STATUS_RANK[after] > _STATUS_RANK[origin]:
                errors.append("strategy_transition_halted_recovery_above_origin")
            if not is_sha256(current.recovery_evidence_hash):
                errors.append("strategy_transition_reconciliation_evidence_missing")
            if not is_sha256(current.owner_authorization_hash):
                errors.append("strategy_transition_recovery_authorization_missing")
        elif after == "halted":
            if current.halted_from_status != before:
                errors.append("strategy_transition_halted_origin_mismatch")
        elif _NEXT_STATUS.get(before) != after:
            errors.append("strategy_transition_skip_or_reverse_forbidden")
    return tuple(dict.fromkeys(errors))


@dataclass(frozen=True)
class StrategyRegistry:
    schema_version: int
    strategy_registry_id: str
    created_at: str
    entries: tuple[StrategyRegistration, ...]
    registry_hash: str

    @classmethod
    def create(
        cls,
        entries: Sequence[StrategyRegistration],
        *,
        created_at: str,
    ) -> StrategyRegistry:
        normalized_entries = tuple(
            sorted(entries, key=lambda row: (row.strategy_id, row.strategy_version))
        )
        core = {
            "schema_version": GOVERNANCE_SCHEMA_VERSION,
            "created_at": created_at,
            "entries": [entry.as_dict() for entry in normalized_entries],
        }
        registry_hash = canonical_hash(core)
        registry = cls(
            schema_version=GOVERNANCE_SCHEMA_VERSION,
            strategy_registry_id=trace_id(
                "strategy_registry",
                {"created_at": created_at, "registry_hash": registry_hash},
            ),
            created_at=created_at,
            entries=normalized_entries,
            registry_hash=registry_hash,
        )
        errors = registry.validate()
        if errors:
            raise ValueError(f"strategy_registry_invalid:{','.join(errors)}")
        return registry

    def _core(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "entries": [entry.as_dict() for entry in self.entries],
        }

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.schema_version != GOVERNANCE_SCHEMA_VERSION:
            errors.append("strategy_registry_schema_version_invalid")
        try:
            created_at = aware_datetime(self.created_at)
        except (AttributeError, TypeError, ValueError):
            created_at = None
            errors.append("strategy_registry_time_invalid")
        if not self.entries:
            errors.append("strategy_registry_entries_empty")
        strategy_ids = [entry.strategy_id for entry in self.entries]
        if len(strategy_ids) != len(set(strategy_ids)):
            errors.append("strategy_registry_strategy_id_duplicate")
        entry_ids = [entry.registry_entry_id for entry in self.entries]
        if len(entry_ids) != len(set(entry_ids)):
            errors.append("strategy_registry_entry_id_duplicate")
        identities = [
            (entry.strategy_id, entry.strategy_version) for entry in self.entries
        ]
        if list(identities) != sorted(identities):
            errors.append("strategy_registry_entries_not_sorted")
        for index, entry in enumerate(self.entries):
            errors.extend(f"entry:{index}:{error}" for error in entry.validate())
            if created_at is not None:
                try:
                    if aware_datetime(entry.registered_at) > created_at:
                        errors.append(f"entry:{index}:registered_after_registry")
                except (AttributeError, TypeError, ValueError):
                    pass
        expected_hash = canonical_hash(self._core())
        if self.registry_hash != expected_hash:
            errors.append("strategy_registry_hash_invalid")
        expected_id = trace_id(
            "strategy_registry",
            {"created_at": self.created_at, "registry_hash": expected_hash},
        )
        if self.strategy_registry_id != expected_id:
            errors.append("strategy_registry_id_invalid")
        return tuple(errors)

    def entry_by_id(self) -> Mapping[str, StrategyRegistration]:
        return {entry.registry_entry_id: entry for entry in self.entries}

    def entry_by_strategy_id(self) -> Mapping[str, StrategyRegistration]:
        return {entry.strategy_id: entry for entry in self.entries}

    def as_dict(self) -> dict[str, Any]:
        return self._core() | {
            "strategy_registry_id": self.strategy_registry_id,
            "registry_hash": self.registry_hash,
        }


def validate_registry_transition(
    previous: StrategyRegistry,
    current: StrategyRegistry,
) -> tuple[str, ...]:
    """Validate replacement of one current-strategy allowlist snapshot."""

    errors: list[str] = []
    errors.extend(f"previous:{error}" for error in previous.validate())
    errors.extend(f"current:{error}" for error in current.validate())
    try:
        if aware_datetime(current.created_at) <= aware_datetime(previous.created_at):
            errors.append("strategy_registry_transition_time_not_forward")
    except (AttributeError, TypeError, ValueError):
        pass
    previous_by_strategy = previous.entry_by_strategy_id()
    current_by_strategy = current.entry_by_strategy_id()
    for strategy_id, entry in current_by_strategy.items():
        prior = previous_by_strategy.get(strategy_id)
        if prior is None:
            if entry.promotion_status not in {"draft", "research"}:
                errors.append(
                    f"strategy_registry_new_strategy_not_research:{strategy_id}"
                )
            if entry.supersedes_entry_id is not None:
                errors.append(
                    f"strategy_registry_new_strategy_has_supersedes:{strategy_id}"
                )
            continue
        errors.extend(
            f"strategy:{strategy_id}:{error}"
            for error in validate_strategy_transition(prior, entry)
        )
    for strategy_id, entry in previous_by_strategy.items():
        if strategy_id not in current_by_strategy and entry.promotion_status != "halted":
            errors.append(f"strategy_registry_removed_without_halt:{strategy_id}")
    return tuple(dict.fromkeys(errors))


_DEPLOYMENT_STATUS = {
    "research": set(PROMOTION_STATUSES),
    "shadow": {"shadow", "paper", "minimal_live", "scaled_live"},
    "paper": {"paper", "minimal_live", "scaled_live"},
    "production": _LIVE_STATUSES,
}


def validate_registered_intents(
    registry: StrategyRegistry,
    intents: Sequence[StrategyIntent],
    *,
    environment: str,
) -> tuple[str, ...]:
    """Verify traced intents against the current strategy allowlist."""

    errors: list[str] = []
    errors.extend(f"registry:{error}" for error in registry.validate())
    allowed = _DEPLOYMENT_STATUS.get(environment)
    if allowed is None:
        errors.append("registered_intent_environment_invalid")
        allowed = set()
    strategy_ids = [intent.strategy_id for intent in intents]
    if not intents:
        errors.append("registered_intents_empty")
    if len(strategy_ids) != len(set(strategy_ids)):
        errors.append("registered_intent_strategy_duplicate")
    entries = registry.entry_by_strategy_id()
    for index, intent in enumerate(intents):
        errors.extend(
            f"intent:{index}:{error}" for error in intent.validate()
        )
        if not intent.traced:
            errors.append(f"intent:{index}:legacy_intent_not_registered")
        entry = entries.get(intent.strategy_id)
        if entry is None:
            errors.append(f"intent:{index}:strategy_not_registered")
            continue
        if intent.strategy_version != entry.strategy_version:
            errors.append(f"intent:{index}:strategy_version_registry_mismatch")
        if entry.promotion_status not in allowed:
            errors.append(
                f"intent:{index}:strategy_status_not_allowed:{entry.promotion_status}"
            )
        if entry.promotion_status == "halted":
            continue
        gross = sum(abs(_number(weight)) for weight in intent.target_weights.values())
        if gross > entry.maximum_gross + 1e-12:
            errors.append(f"intent:{index}:registered_maximum_gross_exceeded")
        if (
            _number(intent.target_stress_loss_fraction)
            > entry.maximum_stress_loss_fraction + 1e-12
        ):
            errors.append(
                f"intent:{index}:registered_stress_loss_budget_exceeded"
            )
    return tuple(dict.fromkeys(errors))


@dataclass(frozen=True)
class DeploymentManifest:
    schema_version: int
    deployment_manifest_id: str
    environment: str
    git_commit: str
    dirty: bool
    code_tree_hash: str
    dependency_lock_hash: str
    config_hash: str
    strategy_registry_id: str
    strategy_registry_hash: str
    strategy_entry_ids: tuple[str, ...]
    promotion_artifact_hash: str
    owner_authorization_hash: str
    deployed_at: str
    deployed_by: str
    rollback_target: str | None
    orders_authorized: bool
    manifest_hash: str

    @classmethod
    def create(
        cls,
        registry: StrategyRegistry,
        *,
        strategy_entry_ids: Sequence[str],
        environment: str,
        git_commit: str,
        dirty: bool,
        code_tree_hash: str,
        dependency_lock_hash: str,
        config_hash: str,
        deployed_at: str,
        deployed_by: str,
        rollback_target: str | None,
    ) -> DeploymentManifest:
        selected_ids = tuple(sorted(strategy_entry_ids))
        entries_by_id = registry.entry_by_id()
        selected = [
            entries_by_id[value]
            for value in selected_ids
            if value in entries_by_id
        ]
        promotion_hash = canonical_hash(
            {
                "strategy_promotion_artifacts": {
                    entry.registry_entry_id: entry.promotion_artifact_hash
                    for entry in selected
                }
            }
        )
        owner_hash = canonical_hash(
            {
                "strategy_owner_authorizations": {
                    entry.registry_entry_id: entry.owner_authorization_hash
                    for entry in selected
                }
            }
        )
        core = {
            "schema_version": GOVERNANCE_SCHEMA_VERSION,
            "environment": environment,
            "git_commit": git_commit,
            "dirty": dirty,
            "code_tree_hash": code_tree_hash,
            "dependency_lock_hash": dependency_lock_hash,
            "config_hash": config_hash,
            "strategy_registry_id": registry.strategy_registry_id,
            "strategy_registry_hash": registry.registry_hash,
            "strategy_entry_ids": selected_ids,
            "promotion_artifact_hash": promotion_hash,
            "owner_authorization_hash": owner_hash,
            "deployed_at": deployed_at,
            "deployed_by": deployed_by,
            "rollback_target": rollback_target,
            "orders_authorized": False,
        }
        manifest_hash = canonical_hash(core)
        manifest = cls(
            **core,
            deployment_manifest_id=trace_id(
                "deployment_manifest",
                {"environment": environment, "manifest_hash": manifest_hash},
            ),
            manifest_hash=manifest_hash,
        )
        errors = (*manifest.validate(), *manifest.validate_against_registry(registry))
        if errors:
            raise ValueError(f"deployment_manifest_invalid:{','.join(errors)}")
        return manifest

    def _core(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "environment": self.environment,
            "git_commit": self.git_commit,
            "dirty": self.dirty,
            "code_tree_hash": self.code_tree_hash,
            "dependency_lock_hash": self.dependency_lock_hash,
            "config_hash": self.config_hash,
            "strategy_registry_id": self.strategy_registry_id,
            "strategy_registry_hash": self.strategy_registry_hash,
            "strategy_entry_ids": tuple(self.strategy_entry_ids),
            "promotion_artifact_hash": self.promotion_artifact_hash,
            "owner_authorization_hash": self.owner_authorization_hash,
            "deployed_at": self.deployed_at,
            "deployed_by": self.deployed_by,
            "rollback_target": self.rollback_target,
            "orders_authorized": self.orders_authorized,
        }

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.schema_version != GOVERNANCE_SCHEMA_VERSION:
            errors.append("deployment_manifest_schema_version_invalid")
        if self.environment not in _DEPLOYMENT_STATUS:
            errors.append("deployment_manifest_environment_invalid")
        if not _GIT_COMMIT_RE.fullmatch(self.git_commit):
            errors.append("deployment_manifest_git_commit_invalid")
        if not isinstance(self.dirty, bool):
            errors.append("deployment_manifest_dirty_flag_invalid")
        elif self.environment == "production" and self.dirty:
            errors.append("deployment_manifest_production_dirty")
        for name in (
            "code_tree_hash",
            "dependency_lock_hash",
            "config_hash",
            "strategy_registry_id",
            "strategy_registry_hash",
            "promotion_artifact_hash",
            "owner_authorization_hash",
        ):
            if not is_sha256(getattr(self, name)):
                errors.append(f"deployment_manifest_{name}_invalid")
        if not self.strategy_entry_ids:
            errors.append("deployment_manifest_strategy_entries_empty")
        elif any(not is_sha256(value) for value in self.strategy_entry_ids):
            errors.append("deployment_manifest_strategy_entry_id_invalid")
        if len(self.strategy_entry_ids) != len(set(self.strategy_entry_ids)):
            errors.append("deployment_manifest_strategy_entry_id_duplicate")
        if tuple(sorted(self.strategy_entry_ids)) != self.strategy_entry_ids:
            errors.append("deployment_manifest_strategy_entries_not_sorted")
        try:
            aware_datetime(self.deployed_at)
        except (AttributeError, TypeError, ValueError):
            errors.append("deployment_manifest_time_invalid")
        if not self.deployed_by:
            errors.append("deployment_manifest_deployed_by_empty")
        if self.environment == "production" and not is_sha256(self.rollback_target):
            errors.append("deployment_manifest_rollback_target_invalid")
        elif self.rollback_target is not None and not is_sha256(self.rollback_target):
            errors.append("deployment_manifest_rollback_target_invalid")
        if self.orders_authorized is not False:
            errors.append("deployment_manifest_cannot_authorize_orders")
        expected_hash = canonical_hash(self._core())
        if self.manifest_hash != expected_hash:
            errors.append("deployment_manifest_hash_invalid")
        expected_id = trace_id(
            "deployment_manifest",
            {"environment": self.environment, "manifest_hash": expected_hash},
        )
        if self.deployment_manifest_id != expected_id:
            errors.append("deployment_manifest_id_invalid")
        return tuple(errors)

    def validate_against_registry(
        self,
        registry: StrategyRegistry,
    ) -> tuple[str, ...]:
        errors: list[str] = []
        errors.extend(f"registry:{error}" for error in registry.validate())
        if self.strategy_registry_id != registry.strategy_registry_id:
            errors.append("deployment_manifest_registry_id_mismatch")
        if self.strategy_registry_hash != registry.registry_hash:
            errors.append("deployment_manifest_registry_hash_mismatch")
        entries_by_id = registry.entry_by_id()
        missing = [
            value for value in self.strategy_entry_ids if value not in entries_by_id
        ]
        if missing:
            errors.append("deployment_manifest_registry_entry_missing")
        selected = [
            entries_by_id[value]
            for value in self.strategy_entry_ids
            if value in entries_by_id
        ]
        allowed = _DEPLOYMENT_STATUS.get(self.environment, set())
        for entry in selected:
            if entry.promotion_status not in allowed:
                errors.append(
                    "deployment_manifest_strategy_status_not_allowed:"
                    f"{entry.strategy_id}:{entry.promotion_status}"
                )
        promotion_hash = canonical_hash(
            {
                "strategy_promotion_artifacts": {
                    entry.registry_entry_id: entry.promotion_artifact_hash
                    for entry in selected
                }
            }
        )
        if self.promotion_artifact_hash != promotion_hash:
            errors.append("deployment_manifest_promotion_bundle_mismatch")
        owner_hash = canonical_hash(
            {
                "strategy_owner_authorizations": {
                    entry.registry_entry_id: entry.owner_authorization_hash
                    for entry in selected
                }
            }
        )
        if self.owner_authorization_hash != owner_hash:
            errors.append("deployment_manifest_owner_bundle_mismatch")
        return tuple(dict.fromkeys(errors))

    def as_dict(self) -> dict[str, Any]:
        return self._core() | {
            "deployment_manifest_id": self.deployment_manifest_id,
            "manifest_hash": self.manifest_hash,
        }
