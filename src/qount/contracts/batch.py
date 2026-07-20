"""Pure contracts for one complete, replayable decision batch."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Sequence

from qount.contracts.hashing import canonical_hash
from qount.contracts.runtime import MarketSnapshot
from qount.contracts.runtime import OrderPlan
from qount.contracts.runtime import PortfolioTarget
from qount.contracts.runtime import RiskDecision
from qount.contracts.strategy import StrategyIntent
from qount.contracts.trace import aware_datetime
from qount.contracts.trace import is_sha256
from qount.contracts.trace import trace_id


DECISION_BATCH_SCHEMA_VERSION = 1
_ARTIFACT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_FILE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,159}$")


@dataclass(frozen=True)
class ArtifactReference:
    artifact_type: str
    object_id: str
    payload_hash: str
    artifact_hash: str
    file_name: str

    @classmethod
    def create(
        cls,
        *,
        artifact_type: str,
        object_id: str,
        payload_hash: str,
        artifact_hash: str,
        file_name: str,
    ) -> ArtifactReference:
        reference = cls(
            artifact_type=artifact_type,
            object_id=object_id,
            payload_hash=payload_hash,
            artifact_hash=artifact_hash,
            file_name=file_name,
        )
        errors = reference.validate()
        if errors:
            raise ValueError(f"artifact_reference_invalid:{','.join(errors)}")
        return reference

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not isinstance(self.artifact_type, str) or not _ARTIFACT_TYPE_RE.fullmatch(
            self.artifact_type
        ):
            errors.append("artifact_reference_type_invalid")
        for name in ("object_id", "payload_hash", "artifact_hash"):
            if not is_sha256(getattr(self, name)):
                errors.append(f"artifact_reference_{name}_invalid")
        if (
            not isinstance(self.file_name, str)
            or not _FILE_NAME_RE.fullmatch(self.file_name)
            or ".." in self.file_name
            or "/" in self.file_name
            or "\\" in self.file_name
        ):
            errors.append("artifact_reference_file_name_invalid")
        return tuple(errors)

    def as_dict(self) -> dict[str, str]:
        return {
            "artifact_type": self.artifact_type,
            "object_id": self.object_id,
            "payload_hash": self.payload_hash,
            "artifact_hash": self.artifact_hash,
            "file_name": self.file_name,
        }


@dataclass(frozen=True)
class DecisionBatchManifest:
    schema_version: int
    decision_batch_manifest_id: str
    batch_id: str
    created_at: str
    market_snapshot: ArtifactReference
    strategy_intents: tuple[ArtifactReference, ...]
    portfolio_target: ArtifactReference
    risk_decision: ArtifactReference
    order_plan: ArtifactReference
    orders_authorized: bool
    manifest_hash: str

    @classmethod
    def create(
        cls,
        *,
        batch_id: str,
        created_at: str,
        market_snapshot: ArtifactReference,
        strategy_intents: Sequence[ArtifactReference],
        portfolio_target: ArtifactReference,
        risk_decision: ArtifactReference,
        order_plan: ArtifactReference,
    ) -> DecisionBatchManifest:
        normalized_intents = tuple(
            sorted(strategy_intents, key=lambda reference: reference.object_id)
        )
        core = {
            "schema_version": DECISION_BATCH_SCHEMA_VERSION,
            "batch_id": batch_id,
            "created_at": created_at,
            "market_snapshot": market_snapshot.as_dict(),
            "strategy_intents": [
                reference.as_dict() for reference in normalized_intents
            ],
            "portfolio_target": portfolio_target.as_dict(),
            "risk_decision": risk_decision.as_dict(),
            "order_plan": order_plan.as_dict(),
            "orders_authorized": False,
        }
        manifest_hash = canonical_hash(core)
        manifest = cls(
            schema_version=DECISION_BATCH_SCHEMA_VERSION,
            decision_batch_manifest_id=trace_id(
                "decision_batch_manifest",
                {"batch_id": batch_id, "manifest_hash": manifest_hash},
            ),
            batch_id=batch_id,
            created_at=created_at,
            market_snapshot=market_snapshot,
            strategy_intents=normalized_intents,
            portfolio_target=portfolio_target,
            risk_decision=risk_decision,
            order_plan=order_plan,
            orders_authorized=False,
            manifest_hash=manifest_hash,
        )
        errors = manifest.validate()
        if errors:
            raise ValueError(f"decision_batch_manifest_invalid:{','.join(errors)}")
        return manifest

    def _core(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "batch_id": self.batch_id,
            "created_at": self.created_at,
            "market_snapshot": self.market_snapshot.as_dict(),
            "strategy_intents": [
                reference.as_dict() for reference in self.strategy_intents
            ],
            "portfolio_target": self.portfolio_target.as_dict(),
            "risk_decision": self.risk_decision.as_dict(),
            "order_plan": self.order_plan.as_dict(),
            "orders_authorized": self.orders_authorized,
        }

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.schema_version != DECISION_BATCH_SCHEMA_VERSION:
            errors.append("decision_batch_manifest_schema_version_invalid")
        if not is_sha256(self.batch_id):
            errors.append("decision_batch_manifest_batch_id_invalid")
        try:
            aware_datetime(self.created_at)
        except (AttributeError, TypeError, ValueError):
            errors.append("decision_batch_manifest_created_at_invalid")
        expected_types = (
            ("market_snapshot", self.market_snapshot, "market_snapshot"),
            ("portfolio_target", self.portfolio_target, "portfolio_target"),
            ("risk_decision", self.risk_decision, "risk_decision"),
            ("order_plan", self.order_plan, "order_plan"),
        )
        for name, reference, expected_type in expected_types:
            errors.extend(
                f"{name}:{error}" for error in reference.validate()
            )
            if reference.artifact_type != expected_type:
                errors.append(f"decision_batch_manifest_{name}_type_invalid")
            expected_file_name = f"{expected_type}.json"
            if reference.file_name != expected_file_name:
                errors.append(f"decision_batch_manifest_{name}_file_name_invalid")
        if not self.strategy_intents:
            errors.append("decision_batch_manifest_strategy_intents_empty")
        intent_ids = [reference.object_id for reference in self.strategy_intents]
        if intent_ids != sorted(intent_ids):
            errors.append("decision_batch_manifest_strategy_intents_not_sorted")
        if len(intent_ids) != len(set(intent_ids)):
            errors.append("decision_batch_manifest_strategy_intent_duplicate")
        for index, reference in enumerate(self.strategy_intents):
            errors.extend(
                f"strategy_intent:{index}:{error}"
                for error in reference.validate()
            )
            if reference.artifact_type != "strategy_intent":
                errors.append(
                    f"decision_batch_manifest_strategy_intent_type_invalid:{index}"
                )
            expected_file_name = f"strategy_intent.{reference.object_id}.json"
            if reference.file_name != expected_file_name:
                errors.append(
                    "decision_batch_manifest_strategy_intent_file_name_invalid:"
                    f"{index}"
                )
        references = (
            self.market_snapshot,
            *self.strategy_intents,
            self.portfolio_target,
            self.risk_decision,
            self.order_plan,
        )
        file_names = [reference.file_name for reference in references]
        if len(file_names) != len(set(file_names)):
            errors.append("decision_batch_manifest_file_name_duplicate")
        if self.orders_authorized is not False:
            errors.append("decision_batch_manifest_cannot_authorize_orders")
        expected_hash = canonical_hash(self._core())
        if self.manifest_hash != expected_hash:
            errors.append("decision_batch_manifest_hash_invalid")
        expected_id = trace_id(
            "decision_batch_manifest",
            {"batch_id": self.batch_id, "manifest_hash": expected_hash},
        )
        if self.decision_batch_manifest_id != expected_id:
            errors.append("decision_batch_manifest_id_invalid")
        return tuple(errors)

    def artifact_references(self) -> tuple[ArtifactReference, ...]:
        return (
            self.market_snapshot,
            *self.strategy_intents,
            self.portfolio_target,
            self.risk_decision,
            self.order_plan,
        )


def validate_decision_batch(
    snapshot: MarketSnapshot,
    intents: Sequence[StrategyIntent],
    target: PortfolioTarget,
    risk: RiskDecision,
    plan: OrderPlan,
) -> tuple[str, ...]:
    """Validate the full in-memory lineage before a batch may be committed."""

    errors: list[str] = []
    errors.extend(f"snapshot:{error}" for error in snapshot.validate())
    normalized_intents = tuple(intents)
    if not normalized_intents:
        errors.append("decision_batch_strategy_intents_empty")
    strategy_ids = [intent.strategy_id for intent in normalized_intents]
    decision_ids = [intent.decision_id for intent in normalized_intents]
    if len(strategy_ids) != len(set(strategy_ids)):
        errors.append("decision_batch_strategy_id_duplicate")
    if len(decision_ids) != len(set(decision_ids)):
        errors.append("decision_batch_decision_id_duplicate")
    for index, intent in enumerate(normalized_intents):
        errors.extend(
            f"intent:{index}:{error}" for error in intent.validate()
        )
        if not intent.traced:
            errors.append(f"intent:{index}:trace_required")
        if intent.snapshot_id != snapshot.snapshot_id:
            errors.append(f"intent:{index}:snapshot_id_mismatch")
        if intent.decision_time != snapshot.decision_time:
            errors.append(f"intent:{index}:decision_time_mismatch")
        if intent.data_cutoff != snapshot.data_cutoff:
            errors.append(f"intent:{index}:data_cutoff_mismatch")

    errors.extend(f"target:{error}" for error in target.validate())
    if target.snapshot_id != snapshot.snapshot_id:
        errors.append("decision_batch_target_snapshot_id_mismatch")
    if target.decision_time != snapshot.decision_time:
        errors.append("decision_batch_target_decision_time_mismatch")
    if set(target.decision_ids) != set(decision_ids):
        errors.append("decision_batch_target_decision_ids_mismatch")
    if set(target.sleeve_contributions) != set(strategy_ids):
        errors.append("decision_batch_target_sleeves_mismatch")
    aggregated: dict[str, float] = {}
    try:
        for weights in target.sleeve_contributions.values():
            for symbol, weight in weights.items():
                aggregated[symbol] = aggregated.get(symbol, 0.0) + float(weight)
        symbols = set(aggregated) | set(target.proposed_target_weights)
        sleeve_sum_mismatch = any(
            not math.isclose(
                aggregated.get(symbol, 0.0),
                float(target.proposed_target_weights.get(symbol, 0.0)),
                abs_tol=1e-12,
                rel_tol=0.0,
            )
            for symbol in symbols
        )
    except (AttributeError, TypeError, ValueError):
        sleeve_sum_mismatch = True
    if sleeve_sum_mismatch:
        errors.append("decision_batch_target_sleeve_sum_mismatch")

    errors.extend(f"risk:{error}" for error in risk.validate())
    if risk.portfolio_target_id != target.portfolio_target_id:
        errors.append("decision_batch_risk_portfolio_target_mismatch")
    if risk.decision_time != target.decision_time:
        errors.append("decision_batch_risk_decision_time_mismatch")
    if dict(risk.input_target) != dict(target.target_weights):
        errors.append("decision_batch_risk_input_target_mismatch")

    errors.extend(f"plan:{error}" for error in plan.validate())
    if plan.batch_id != risk.batch_id:
        errors.append("decision_batch_plan_batch_id_mismatch")
    if plan.risk_decision_id != risk.risk_decision_id:
        errors.append("decision_batch_plan_risk_decision_id_mismatch")
    if plan.portfolio_target_id != target.portfolio_target_id:
        errors.append("decision_batch_plan_portfolio_target_id_mismatch")
    if plan.snapshot_id != snapshot.snapshot_id:
        errors.append("decision_batch_plan_snapshot_id_mismatch")
    if set(plan.decision_ids) != set(decision_ids):
        errors.append("decision_batch_plan_decision_ids_mismatch")
    if dict(plan.approved_target) != dict(risk.approved_target):
        errors.append("decision_batch_plan_approved_target_mismatch")
    try:
        if aware_datetime(plan.created_at) < aware_datetime(risk.decision_time):
            errors.append("decision_batch_plan_created_before_risk_decision")
    except (AttributeError, TypeError, ValueError):
        pass
    if not risk.increase_risk_allowed and any(
        order.phase == "increase" for order in plan.orders
    ):
        errors.append("decision_batch_increase_order_not_allowed")
    reduction_actions = any(
        order.phase in {"reduce", "protective"} for order in plan.orders
    ) or bool(plan.cancellations)
    if reduction_actions and not risk.reduce_risk_allowed:
        errors.append("decision_batch_reduction_action_not_allowed")
    return tuple(dict.fromkeys(errors))
