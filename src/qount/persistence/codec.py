"""Explicit codecs for immutable runtime and governance contract artifacts."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence, TypeVar

from qount.contracts import ArtifactReference
from qount.contracts import DecisionBatchManifest
from qount.contracts import MarketSnapshot
from qount.contracts import OrderPlan
from qount.contracts import PlannedCancellation
from qount.contracts import PlannedOrder
from qount.contracts import PortfolioTarget
from qount.contracts import RiskDecision
from qount.contracts import StrategyIntent
from qount.contracts import is_sha256
from qount.governance.registry import DeploymentManifest
from qount.governance.registry import StrategyRegistration
from qount.governance.registry import StrategyRegistry


ARTIFACT_SCHEMA_VERSION = 1
_ENVELOPE_FIELDS = {
    "artifact_schema_version",
    "artifact_type",
    "object_id",
    "payload",
    "payload_hash",
    "artifact_hash",
}
_TYPE_BY_CLASS = {
    StrategyIntent: "strategy_intent",
    MarketSnapshot: "market_snapshot",
    PortfolioTarget: "portfolio_target",
    RiskDecision: "risk_decision",
    OrderPlan: "order_plan",
    StrategyRegistration: "strategy_registration",
    StrategyRegistry: "strategy_registry",
    DeploymentManifest: "deployment_manifest",
    DecisionBatchManifest: "decision_batch_manifest",
}
_ArtifactObject = TypeVar("_ArtifactObject")


class ArtifactCodecError(ValueError):
    """Raised when an artifact cannot be encoded or verified."""


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise ArtifactCodecError("artifact_not_canonical_json") from exc


def _canonical_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _mapping(value: object, *, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ArtifactCodecError(f"{name}_not_object")
    if any(not isinstance(key, str) for key in value):
        raise ArtifactCodecError(f"{name}_key_not_string")
    return value


def _sequence(value: object, *, name: str) -> Sequence[Any]:
    if not isinstance(value, list):
        raise ArtifactCodecError(f"{name}_not_array")
    return value


def _exact_fields(
    value: Mapping[str, Any],
    fields: set[str],
    *,
    name: str,
) -> None:
    actual = set(value)
    if actual != fields:
        missing = ",".join(sorted(fields - actual)) or "none"
        unexpected = ",".join(sorted(actual - fields)) or "none"
        raise ArtifactCodecError(
            f"{name}_fields_invalid:missing={missing}:unexpected={unexpected}"
        )


def artifact_type_for(value: object) -> str:
    artifact_type = _TYPE_BY_CLASS.get(type(value))
    if artifact_type is None:
        raise ArtifactCodecError(
            f"artifact_type_unsupported:{type(value).__name__}"
        )
    return artifact_type


def _object_id(value: object) -> str:
    fields = {
        StrategyIntent: "decision_id",
        MarketSnapshot: "snapshot_id",
        PortfolioTarget: "portfolio_target_id",
        RiskDecision: "risk_decision_id",
        OrderPlan: "order_plan_id",
        StrategyRegistration: "registry_entry_id",
        StrategyRegistry: "strategy_registry_id",
        DeploymentManifest: "deployment_manifest_id",
        DecisionBatchManifest: "decision_batch_manifest_id",
    }
    object_id = getattr(value, fields[type(value)])
    if not is_sha256(object_id):
        raise ArtifactCodecError("artifact_object_id_invalid")
    return object_id


def _registration_payload(value: StrategyRegistration) -> dict[str, Any]:
    return {
        "schema_version": value.schema_version,
        "registry_entry_id": value.registry_entry_id,
        "strategy_id": value.strategy_id,
        "strategy_version": value.strategy_version,
        "strategy_kind": value.strategy_kind,
        "promotion_status": value.promotion_status,
        "strategy_contract_hash": value.strategy_contract_hash,
        "code_hash": value.code_hash,
        "config_hash": value.config_hash,
        "promotion_artifact_hash": value.promotion_artifact_hash,
        "owner_authorization_hash": value.owner_authorization_hash,
        "maximum_stress_loss_fraction": value.maximum_stress_loss_fraction,
        "maximum_gross": value.maximum_gross,
        "registered_at": value.registered_at,
        "supersedes_entry_id": value.supersedes_entry_id,
        "halted_from_status": value.halted_from_status,
        "recovery_evidence_hash": value.recovery_evidence_hash,
        "entry_hash": value.entry_hash,
    }


def _planned_order_payload(value: PlannedOrder) -> dict[str, Any]:
    return {
        "client_order_id": value.client_order_id,
        "symbol": value.symbol,
        "side": value.side,
        "quantity": value.quantity,
        "reduce_only": value.reduce_only,
        "phase": value.phase,
        "sequence": value.sequence,
        "decision_ids": list(value.decision_ids),
        "order_type": value.order_type,
        "close_position": value.close_position,
        "limit_price": value.limit_price,
        "stop_price": value.stop_price,
    }


def _planned_cancellation_payload(
    value: PlannedCancellation,
) -> dict[str, Any]:
    return {
        "cancellation_id": value.cancellation_id,
        "symbol": value.symbol,
        "target_exchange_order_id": value.target_exchange_order_id,
        "target_client_order_id": value.target_client_order_id,
        "decision_ids": list(value.decision_ids),
        "sequence": value.sequence,
        "reason": value.reason,
    }


def _artifact_reference_payload(value: ArtifactReference) -> dict[str, str]:
    return value.as_dict()


def _payload(value: object) -> dict[str, Any]:
    if isinstance(value, PlannedOrder):
        return _planned_order_payload(value)
    if isinstance(value, PlannedCancellation):
        return _planned_cancellation_payload(value)
    if isinstance(value, DecisionBatchManifest):
        return {
            "schema_version": value.schema_version,
            "decision_batch_manifest_id": value.decision_batch_manifest_id,
            "batch_id": value.batch_id,
            "created_at": value.created_at,
            "market_snapshot": _artifact_reference_payload(
                value.market_snapshot
            ),
            "strategy_intents": [
                _artifact_reference_payload(reference)
                for reference in value.strategy_intents
            ],
            "portfolio_target": _artifact_reference_payload(
                value.portfolio_target
            ),
            "risk_decision": _artifact_reference_payload(value.risk_decision),
            "order_plan": _artifact_reference_payload(value.order_plan),
            "orders_authorized": value.orders_authorized,
            "manifest_hash": value.manifest_hash,
        }
    if isinstance(value, StrategyIntent):
        return {
            "schema_version": value.schema_version,
            "strategy_id": value.strategy_id,
            "strategy_version": value.strategy_version,
            "decision_id": value.decision_id,
            "snapshot_id": value.snapshot_id,
            "decision_time": value.decision_time,
            "data_cutoff": value.data_cutoff,
            "target_weights": dict(value.target_weights),
            "expected_holding_bars": value.expected_holding_bars,
            "target_stress_loss_fraction": value.target_stress_loss_fraction,
            "reason_codes": list(value.reason_codes),
            "evidence_hash": value.evidence_hash,
            "state_hash": value.state_hash,
            "intent_hash": value.intent_hash,
        }
    if isinstance(value, MarketSnapshot):
        return {
            "schema_version": value.schema_version,
            "snapshot_id": value.snapshot_id,
            "decision_time": value.decision_time,
            "data_cutoff": value.data_cutoff,
            "prices": dict(value.prices),
            "funding": dict(value.funding),
            "features": dict(value.features),
            "exchange_rules_hash": value.exchange_rules_hash,
            "account_snapshot_hash": value.account_snapshot_hash,
            "data_quality": dict(value.data_quality),
            "source_hashes": dict(value.source_hashes),
            "snapshot_hash": value.snapshot_hash,
        }
    if isinstance(value, PortfolioTarget):
        return {
            "schema_version": value.schema_version,
            "portfolio_target_id": value.portfolio_target_id,
            "snapshot_id": value.snapshot_id,
            "decision_ids": list(value.decision_ids),
            "decision_time": value.decision_time,
            "proposed_target_weights": dict(value.proposed_target_weights),
            "target_weights": dict(value.target_weights),
            "sleeve_contributions": {
                strategy_id: dict(weights)
                for strategy_id, weights in value.sleeve_contributions.items()
            },
            "blockers": list(value.blockers),
            "allocatable": value.allocatable,
            "allocation_hash": value.allocation_hash,
            "target_hash": value.target_hash,
        }
    if isinstance(value, RiskDecision):
        return {
            "schema_version": value.schema_version,
            "risk_decision_id": value.risk_decision_id,
            "batch_id": value.batch_id,
            "portfolio_target_id": value.portfolio_target_id,
            "decision_time": value.decision_time,
            "approved": value.approved,
            "input_target": dict(value.input_target),
            "approved_target": dict(value.approved_target),
            "adjustments": list(value.adjustments),
            "violations": list(value.violations),
            "risk_state_hash": value.risk_state_hash,
            "increase_risk_allowed": value.increase_risk_allowed,
            "reduce_risk_allowed": value.reduce_risk_allowed,
            "decision_hash": value.decision_hash,
        }
    if isinstance(value, OrderPlan):
        return {
            "schema_version": value.schema_version,
            "order_plan_id": value.order_plan_id,
            "batch_id": value.batch_id,
            "risk_decision_id": value.risk_decision_id,
            "portfolio_target_id": value.portfolio_target_id,
            "snapshot_id": value.snapshot_id,
            "decision_ids": list(value.decision_ids),
            "created_at": value.created_at,
            "current_position_hash": value.current_position_hash,
            "approved_target": dict(value.approved_target),
            "orders": [_planned_order_payload(order) for order in value.orders],
            "cancellations": [
                _planned_cancellation_payload(cancellation)
                for cancellation in value.cancellations
            ],
            "retained_order_ids": list(value.retained_order_ids),
            "expected_positions": dict(value.expected_positions),
            "reconciliation_tolerance": dict(value.reconciliation_tolerance),
            "blockers": list(value.blockers),
            "executable": value.executable,
            "plan_hash": value.plan_hash,
        }
    if isinstance(value, StrategyRegistration):
        return _registration_payload(value)
    if isinstance(value, StrategyRegistry):
        return {
            "schema_version": value.schema_version,
            "strategy_registry_id": value.strategy_registry_id,
            "created_at": value.created_at,
            "entries": [_registration_payload(entry) for entry in value.entries],
            "registry_hash": value.registry_hash,
        }
    if isinstance(value, DeploymentManifest):
        return {
            "schema_version": value.schema_version,
            "deployment_manifest_id": value.deployment_manifest_id,
            "environment": value.environment,
            "git_commit": value.git_commit,
            "dirty": value.dirty,
            "code_tree_hash": value.code_tree_hash,
            "dependency_lock_hash": value.dependency_lock_hash,
            "config_hash": value.config_hash,
            "strategy_registry_id": value.strategy_registry_id,
            "strategy_registry_hash": value.strategy_registry_hash,
            "strategy_entry_ids": list(value.strategy_entry_ids),
            "promotion_artifact_hash": value.promotion_artifact_hash,
            "owner_authorization_hash": value.owner_authorization_hash,
            "deployed_at": value.deployed_at,
            "deployed_by": value.deployed_by,
            "rollback_target": value.rollback_target,
            "orders_authorized": value.orders_authorized,
            "manifest_hash": value.manifest_hash,
        }
    raise ArtifactCodecError(f"artifact_type_unsupported:{type(value).__name__}")


def _validate_for_encoding(value: object) -> None:
    validate = getattr(value, "validate", None)
    if not callable(validate):
        raise ArtifactCodecError("artifact_object_validation_missing")
    errors = tuple(validate())
    if errors:
        raise ArtifactCodecError(
            f"artifact_object_invalid:{','.join(errors)}"
        )
    if isinstance(value, StrategyIntent) and not value.traced:
        raise ArtifactCodecError("legacy_strategy_intent_not_persistable")


def artifact_envelope(value: object) -> dict[str, Any]:
    """Return a fully hashed envelope for one verified standard object."""

    artifact_type = artifact_type_for(value)
    _validate_for_encoding(value)
    payload = _payload(value)
    core = {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "artifact_type": artifact_type,
        "object_id": _object_id(value),
        "payload": payload,
        "payload_hash": _canonical_hash(payload),
    }
    return core | {"artifact_hash": _canonical_hash(core)}


def dump_artifact(value: object) -> bytes:
    """Serialize one object into deterministic ASCII JSON bytes."""

    return _canonical_bytes(artifact_envelope(value)) + b"\n"


def _verify_reconstruction(
    payload: Mapping[str, Any],
    value: _ArtifactObject,
    *,
    artifact_type: str,
) -> _ArtifactObject:
    try:
        expected = _canonical_bytes(_payload(value))
        actual = _canonical_bytes(payload)
    except ArtifactCodecError:
        raise
    if actual != expected:
        raise ArtifactCodecError(f"{artifact_type}_identity_or_hash_mismatch")
    return value


def _decode_registration(payload: Mapping[str, Any]) -> StrategyRegistration:
    expected = {
        "schema_version",
        "registry_entry_id",
        "strategy_id",
        "strategy_version",
        "strategy_kind",
        "promotion_status",
        "strategy_contract_hash",
        "code_hash",
        "config_hash",
        "promotion_artifact_hash",
        "owner_authorization_hash",
        "maximum_stress_loss_fraction",
        "maximum_gross",
        "registered_at",
        "supersedes_entry_id",
        "halted_from_status",
        "recovery_evidence_hash",
        "entry_hash",
    }
    _exact_fields(payload, expected, name="strategy_registration_payload")
    value = StrategyRegistration.create(
        strategy_id=payload["strategy_id"],
        strategy_version=payload["strategy_version"],
        strategy_kind=payload["strategy_kind"],
        promotion_status=payload["promotion_status"],
        strategy_contract_hash=payload["strategy_contract_hash"],
        code_hash=payload["code_hash"],
        config_hash=payload["config_hash"],
        promotion_artifact_hash=payload["promotion_artifact_hash"],
        owner_authorization_hash=payload["owner_authorization_hash"],
        maximum_stress_loss_fraction=payload["maximum_stress_loss_fraction"],
        maximum_gross=payload["maximum_gross"],
        registered_at=payload["registered_at"],
        supersedes_entry_id=payload["supersedes_entry_id"],
        halted_from_status=payload["halted_from_status"],
        recovery_evidence_hash=payload["recovery_evidence_hash"],
    )
    return _verify_reconstruction(
        payload,
        value,
        artifact_type="strategy_registration",
    )


def _decode_planned_order(
    payload: Mapping[str, Any],
    *,
    batch_id: str,
) -> PlannedOrder:
    expected = {
        "client_order_id",
        "symbol",
        "side",
        "quantity",
        "reduce_only",
        "phase",
        "sequence",
        "decision_ids",
        "order_type",
        "close_position",
        "limit_price",
        "stop_price",
    }
    _exact_fields(payload, expected, name="planned_order_payload")
    value = PlannedOrder.create(
        batch_id=batch_id,
        decision_ids=_sequence(
            payload["decision_ids"], name="planned_order_decision_ids"
        ),
        symbol=payload["symbol"],
        side=payload["side"],
        quantity=payload["quantity"],
        reduce_only=payload["reduce_only"],
        phase=payload["phase"],
        sequence=payload["sequence"],
        order_type=payload["order_type"],
        close_position=payload["close_position"],
        limit_price=payload["limit_price"],
        stop_price=payload["stop_price"],
    )
    _verify_reconstruction(payload, value, artifact_type="planned_order")
    return value


def _decode_planned_cancellation(
    payload: Mapping[str, Any],
    *,
    batch_id: str,
) -> PlannedCancellation:
    expected = {
        "cancellation_id",
        "symbol",
        "target_exchange_order_id",
        "target_client_order_id",
        "decision_ids",
        "sequence",
        "reason",
    }
    _exact_fields(payload, expected, name="planned_cancellation_payload")
    value = PlannedCancellation.create(
        batch_id=batch_id,
        decision_ids=_sequence(
            payload["decision_ids"], name="planned_cancellation_decision_ids"
        ),
        symbol=payload["symbol"],
        target_exchange_order_id=payload["target_exchange_order_id"],
        target_client_order_id=payload["target_client_order_id"],
        sequence=payload["sequence"],
        reason=payload["reason"],
    )
    _verify_reconstruction(
        payload,
        value,
        artifact_type="planned_cancellation",
    )
    return value


def _decode_artifact_reference(
    payload: Mapping[str, Any],
    *,
    name: str,
) -> ArtifactReference:
    expected = {
        "artifact_type",
        "object_id",
        "payload_hash",
        "artifact_hash",
        "file_name",
    }
    _exact_fields(payload, expected, name=name)
    return ArtifactReference.create(
        artifact_type=payload["artifact_type"],
        object_id=payload["object_id"],
        payload_hash=payload["payload_hash"],
        artifact_hash=payload["artifact_hash"],
        file_name=payload["file_name"],
    )


def _decode_payload(artifact_type: str, payload: Mapping[str, Any]) -> object:
    if artifact_type == "decision_batch_manifest":
        expected = {
            "schema_version",
            "decision_batch_manifest_id",
            "batch_id",
            "created_at",
            "market_snapshot",
            "strategy_intents",
            "portfolio_target",
            "risk_decision",
            "order_plan",
            "orders_authorized",
            "manifest_hash",
        }
        _exact_fields(payload, expected, name="decision_batch_manifest_payload")
        intent_references = tuple(
            _decode_artifact_reference(
                _mapping(item, name=f"decision_batch_intent:{index}"),
                name=f"decision_batch_intent:{index}",
            )
            for index, item in enumerate(
                _sequence(
                    payload["strategy_intents"],
                    name="decision_batch_strategy_intents",
                )
            )
        )
        value = DecisionBatchManifest.create(
            batch_id=payload["batch_id"],
            created_at=payload["created_at"],
            market_snapshot=_decode_artifact_reference(
                _mapping(
                    payload["market_snapshot"],
                    name="decision_batch_market_snapshot",
                ),
                name="decision_batch_market_snapshot",
            ),
            strategy_intents=intent_references,
            portfolio_target=_decode_artifact_reference(
                _mapping(
                    payload["portfolio_target"],
                    name="decision_batch_portfolio_target",
                ),
                name="decision_batch_portfolio_target",
            ),
            risk_decision=_decode_artifact_reference(
                _mapping(
                    payload["risk_decision"],
                    name="decision_batch_risk_decision",
                ),
                name="decision_batch_risk_decision",
            ),
            order_plan=_decode_artifact_reference(
                _mapping(
                    payload["order_plan"],
                    name="decision_batch_order_plan",
                ),
                name="decision_batch_order_plan",
            ),
        )
    elif artifact_type == "strategy_intent":
        expected = {
            "schema_version",
            "strategy_id",
            "strategy_version",
            "decision_id",
            "snapshot_id",
            "decision_time",
            "data_cutoff",
            "target_weights",
            "expected_holding_bars",
            "target_stress_loss_fraction",
            "reason_codes",
            "evidence_hash",
            "state_hash",
            "intent_hash",
        }
        _exact_fields(payload, expected, name="strategy_intent_payload")
        value = StrategyIntent.create(
            strategy_id=payload["strategy_id"],
            strategy_version=payload["strategy_version"],
            decision_id=payload["decision_id"],
            snapshot_id=payload["snapshot_id"],
            decision_time=payload["decision_time"],
            data_cutoff=payload["data_cutoff"],
            target_weights=_mapping(
                payload["target_weights"], name="strategy_intent_target_weights"
            ),
            expected_holding_bars=payload["expected_holding_bars"],
            target_stress_loss_fraction=payload["target_stress_loss_fraction"],
            reason_codes=_sequence(
                payload["reason_codes"], name="strategy_intent_reason_codes"
            ),
            evidence_hash=payload["evidence_hash"],
            state_hash=payload["state_hash"],
        )
    elif artifact_type == "market_snapshot":
        expected = {
            "schema_version",
            "snapshot_id",
            "decision_time",
            "data_cutoff",
            "prices",
            "funding",
            "features",
            "exchange_rules_hash",
            "account_snapshot_hash",
            "data_quality",
            "source_hashes",
            "snapshot_hash",
        }
        _exact_fields(payload, expected, name="market_snapshot_payload")
        value = MarketSnapshot.create(
            decision_time=payload["decision_time"],
            data_cutoff=payload["data_cutoff"],
            prices=_mapping(payload["prices"], name="snapshot_prices"),
            funding=_mapping(payload["funding"], name="snapshot_funding"),
            features=_mapping(payload["features"], name="snapshot_features"),
            exchange_rules_hash=payload["exchange_rules_hash"],
            account_snapshot_hash=payload["account_snapshot_hash"],
            data_quality=_mapping(
                payload["data_quality"], name="snapshot_data_quality"
            ),
            source_hashes=_mapping(
                payload["source_hashes"], name="snapshot_source_hashes"
            ),
        )
    elif artifact_type == "portfolio_target":
        expected = {
            "schema_version",
            "portfolio_target_id",
            "snapshot_id",
            "decision_ids",
            "decision_time",
            "proposed_target_weights",
            "target_weights",
            "sleeve_contributions",
            "blockers",
            "allocatable",
            "allocation_hash",
            "target_hash",
        }
        _exact_fields(payload, expected, name="portfolio_target_payload")
        sleeves = _mapping(
            payload["sleeve_contributions"], name="portfolio_target_sleeves"
        )
        value = PortfolioTarget.create(
            snapshot_id=payload["snapshot_id"],
            decision_ids=_sequence(
                payload["decision_ids"], name="portfolio_target_decision_ids"
            ),
            decision_time=payload["decision_time"],
            proposed_target_weights=_mapping(
                payload["proposed_target_weights"],
                name="portfolio_target_proposed_weights",
            ),
            target_weights=_mapping(
                payload["target_weights"], name="portfolio_target_weights"
            ),
            sleeve_contributions={
                strategy_id: _mapping(
                    weights,
                    name=f"portfolio_target_sleeve:{strategy_id}",
                )
                for strategy_id, weights in sleeves.items()
            },
            blockers=_sequence(
                payload["blockers"], name="portfolio_target_blockers"
            ),
            allocatable=payload["allocatable"],
            allocation_hash=payload["allocation_hash"],
        )
    elif artifact_type == "risk_decision":
        expected = {
            "schema_version",
            "risk_decision_id",
            "batch_id",
            "portfolio_target_id",
            "decision_time",
            "approved",
            "input_target",
            "approved_target",
            "adjustments",
            "violations",
            "risk_state_hash",
            "increase_risk_allowed",
            "reduce_risk_allowed",
            "decision_hash",
        }
        _exact_fields(payload, expected, name="risk_decision_payload")
        value = RiskDecision.create(
            batch_id=payload["batch_id"],
            portfolio_target_id=payload["portfolio_target_id"],
            decision_time=payload["decision_time"],
            approved=payload["approved"],
            input_target=_mapping(
                payload["input_target"], name="risk_decision_input_target"
            ),
            approved_target=_mapping(
                payload["approved_target"], name="risk_decision_approved_target"
            ),
            adjustments=_sequence(
                payload["adjustments"], name="risk_decision_adjustments"
            ),
            violations=_sequence(
                payload["violations"], name="risk_decision_violations"
            ),
            risk_state_hash=payload["risk_state_hash"],
            increase_risk_allowed=payload["increase_risk_allowed"],
            reduce_risk_allowed=payload["reduce_risk_allowed"],
        )
    elif artifact_type == "order_plan":
        expected = {
            "schema_version",
            "order_plan_id",
            "batch_id",
            "risk_decision_id",
            "portfolio_target_id",
            "snapshot_id",
            "decision_ids",
            "created_at",
            "current_position_hash",
            "approved_target",
            "orders",
            "cancellations",
            "retained_order_ids",
            "expected_positions",
            "reconciliation_tolerance",
            "blockers",
            "executable",
            "plan_hash",
        }
        _exact_fields(payload, expected, name="order_plan_payload")
        orders = tuple(
            _decode_planned_order(
                _mapping(item, name=f"order_plan_order:{index}"),
                batch_id=payload["batch_id"],
            )
            for index, item in enumerate(
                _sequence(payload["orders"], name="order_plan_orders")
            )
        )
        cancellations = tuple(
            _decode_planned_cancellation(
                _mapping(item, name=f"order_plan_cancellation:{index}"),
                batch_id=payload["batch_id"],
            )
            for index, item in enumerate(
                _sequence(
                    payload["cancellations"], name="order_plan_cancellations"
                )
            )
        )
        value = OrderPlan.create(
            batch_id=payload["batch_id"],
            risk_decision_id=payload["risk_decision_id"],
            portfolio_target_id=payload["portfolio_target_id"],
            snapshot_id=payload["snapshot_id"],
            decision_ids=_sequence(
                payload["decision_ids"], name="order_plan_decision_ids"
            ),
            created_at=payload["created_at"],
            current_position_hash=payload["current_position_hash"],
            approved_target=_mapping(
                payload["approved_target"], name="order_plan_approved_target"
            ),
            orders=orders,
            cancellations=cancellations,
            retained_order_ids=_sequence(
                payload["retained_order_ids"],
                name="order_plan_retained_order_ids",
            ),
            expected_positions=_mapping(
                payload["expected_positions"], name="order_plan_expected_positions"
            ),
            reconciliation_tolerance=_mapping(
                payload["reconciliation_tolerance"],
                name="order_plan_reconciliation_tolerance",
            ),
            blockers=_sequence(payload["blockers"], name="order_plan_blockers"),
            executable=payload["executable"],
        )
    elif artifact_type == "strategy_registration":
        return _decode_registration(payload)
    elif artifact_type == "strategy_registry":
        expected = {
            "schema_version",
            "strategy_registry_id",
            "created_at",
            "entries",
            "registry_hash",
        }
        _exact_fields(payload, expected, name="strategy_registry_payload")
        entries = tuple(
            _decode_registration(
                _mapping(item, name=f"strategy_registry_entry:{index}")
            )
            for index, item in enumerate(
                _sequence(payload["entries"], name="strategy_registry_entries")
            )
        )
        value = StrategyRegistry.create(entries, created_at=payload["created_at"])
    elif artifact_type == "deployment_manifest":
        expected = {
            "schema_version",
            "deployment_manifest_id",
            "environment",
            "git_commit",
            "dirty",
            "code_tree_hash",
            "dependency_lock_hash",
            "config_hash",
            "strategy_registry_id",
            "strategy_registry_hash",
            "strategy_entry_ids",
            "promotion_artifact_hash",
            "owner_authorization_hash",
            "deployed_at",
            "deployed_by",
            "rollback_target",
            "orders_authorized",
            "manifest_hash",
        }
        _exact_fields(payload, expected, name="deployment_manifest_payload")
        value = DeploymentManifest(
            schema_version=payload["schema_version"],
            deployment_manifest_id=payload["deployment_manifest_id"],
            environment=payload["environment"],
            git_commit=payload["git_commit"],
            dirty=payload["dirty"],
            code_tree_hash=payload["code_tree_hash"],
            dependency_lock_hash=payload["dependency_lock_hash"],
            config_hash=payload["config_hash"],
            strategy_registry_id=payload["strategy_registry_id"],
            strategy_registry_hash=payload["strategy_registry_hash"],
            strategy_entry_ids=tuple(
                _sequence(
                    payload["strategy_entry_ids"],
                    name="deployment_manifest_strategy_entry_ids",
                )
            ),
            promotion_artifact_hash=payload["promotion_artifact_hash"],
            owner_authorization_hash=payload["owner_authorization_hash"],
            deployed_at=payload["deployed_at"],
            deployed_by=payload["deployed_by"],
            rollback_target=payload["rollback_target"],
            orders_authorized=payload["orders_authorized"],
            manifest_hash=payload["manifest_hash"],
        )
        errors = value.validate()
        if errors:
            raise ArtifactCodecError(
                f"deployment_manifest_invalid:{','.join(errors)}"
            )
    else:
        raise ArtifactCodecError(f"artifact_type_unknown:{artifact_type}")
    return _verify_reconstruction(payload, value, artifact_type=artifact_type)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ArtifactCodecError(f"artifact_json_duplicate_key:{key}")
        value[key] = item
    return value


def load_artifact(
    raw: bytes | str,
    *,
    expected_artifact_type: str | None = None,
) -> object:
    """Parse, verify, and reconstruct one immutable artifact."""

    try:
        value = json.loads(raw, object_pairs_hook=_strict_object)
    except ArtifactCodecError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise ArtifactCodecError("artifact_json_invalid") from exc
    envelope = _mapping(value, name="artifact_envelope")
    _exact_fields(envelope, _ENVELOPE_FIELDS, name="artifact_envelope")
    if (
        type(envelope["artifact_schema_version"]) is not int
        or envelope["artifact_schema_version"] != ARTIFACT_SCHEMA_VERSION
    ):
        raise ArtifactCodecError("artifact_schema_version_unsupported")
    artifact_type = envelope["artifact_type"]
    if not isinstance(artifact_type, str):
        raise ArtifactCodecError("artifact_type_invalid")
    if artifact_type not in set(_TYPE_BY_CLASS.values()):
        raise ArtifactCodecError(f"artifact_type_unknown:{artifact_type}")
    if expected_artifact_type is not None and artifact_type != expected_artifact_type:
        raise ArtifactCodecError(
            "artifact_type_mismatch:"
            f"expected={expected_artifact_type}:actual={artifact_type}"
        )
    payload = _mapping(envelope["payload"], name="artifact_payload")
    if envelope["payload_hash"] != _canonical_hash(payload):
        raise ArtifactCodecError("artifact_payload_hash_mismatch")
    core = {key: envelope[key] for key in _ENVELOPE_FIELDS - {"artifact_hash"}}
    if envelope["artifact_hash"] != _canonical_hash(core):
        raise ArtifactCodecError("artifact_hash_mismatch")
    object_id = envelope["object_id"]
    if not is_sha256(object_id):
        raise ArtifactCodecError("artifact_object_id_invalid")
    try:
        reconstructed = _decode_payload(artifact_type, payload)
    except ArtifactCodecError:
        raise
    except (AttributeError, TypeError, ValueError) as exc:
        raise ArtifactCodecError(
            f"artifact_payload_invalid:{artifact_type}"
        ) from exc
    if _object_id(reconstructed) != object_id:
        raise ArtifactCodecError("artifact_object_id_mismatch")
    return reconstructed
