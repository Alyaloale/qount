"""Local migration replay from one legacy dry plan into the runtime ledger."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

from qount.contracts import canonical_hash
from qount.contracts import is_sha256
from qount.execution import compare_legacy_dispatch_plan
from qount.execution import order_plan_from_legacy_dry_plan
from qount.ledger.store import RuntimeLedger
from qount.persistence import VerifiedDecisionBatch
from qount.persistence import build_decision_batch_manifest
from qount.portfolio import SleeveRiskBudget
from qount.portfolio import allocate_strategy_intents
from qount.portfolio import portfolio_target_from_allocation
from qount.risk import risk_decision_from_legacy_dry_plan
from qount.risk import verify_legacy_dry_dispatch_plan
from qount.strategies import base_intent_from_projection
from qount.strategies import base_snapshot_from_projection


LEGACY_DISPATCH_REPLAY_SCHEMA_VERSION = 1
_EVIDENCE_CLASS = "research_sandbox_local_migration_replay"
_REPLAY_SEMANTICS = "planned_only_not_executed"


class LegacyDispatchReplayError(ValueError):
    """Raised when a legacy dry artifact cannot be replayed without execution."""


def _positive_fraction(value: object, *, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise LegacyDispatchReplayError(f"{name}_invalid") from exc
    if (
        isinstance(value, bool)
        or not math.isfinite(number)
        or not 0.0 < number <= 1.0
    ):
        raise LegacyDispatchReplayError(f"{name}_invalid")
    return number


def _positive_number(value: object, *, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise LegacyDispatchReplayError(f"{name}_invalid") from exc
    if isinstance(value, bool) or not math.isfinite(number) or number <= 0.0:
        raise LegacyDispatchReplayError(f"{name}_invalid")
    return number


def _require_source_link(
    projection: Mapping[str, Any],
    legacy_plan: Mapping[str, Any],
    projection_evidence_hash: str,
) -> None:
    if not is_sha256(projection_evidence_hash):
        raise LegacyDispatchReplayError("projection_evidence_hash_invalid")
    source_hashes = legacy_plan.get("source_hashes")
    if not isinstance(source_hashes, Mapping):
        raise LegacyDispatchReplayError("legacy_plan_source_hashes_invalid")
    if source_hashes.get("projection") != projection_evidence_hash:
        raise LegacyDispatchReplayError("legacy_plan_projection_evidence_mismatch")
    projection_decision = projection.get("decision")
    legacy_decision = legacy_plan.get("decision")
    if not isinstance(projection_decision, Mapping) or not isinstance(
        legacy_decision, Mapping
    ):
        raise LegacyDispatchReplayError("legacy_projection_decision_missing")
    if canonical_hash({"decision": dict(projection_decision)}) != canonical_hash(
        {"decision": dict(legacy_decision)}
    ):
        raise LegacyDispatchReplayError("legacy_projection_decision_mismatch")
    contract = projection.get("contract")
    if not isinstance(contract, Mapping) or legacy_plan.get("contract_hash") != (
        contract.get("live_pilot_contract_hash")
    ):
        raise LegacyDispatchReplayError("legacy_projection_contract_mismatch")


def build_verified_legacy_dispatch_batch(
    projection: Mapping[str, Any],
    legacy_plan: Mapping[str, Any],
    *,
    projection_evidence_hash: str,
    target_stress_loss_fraction: float,
    created_at: str,
) -> VerifiedDecisionBatch:
    """Convert one linked dry artifact into a complete standard decision batch."""

    if not isinstance(projection, Mapping) or not isinstance(legacy_plan, Mapping):
        raise TypeError("legacy_replay_requires_mapping_artifacts")
    try:
        _require_source_link(projection, legacy_plan, projection_evidence_hash)
    except LegacyDispatchReplayError:
        raise
    except (TypeError, ValueError) as exc:
        raise LegacyDispatchReplayError(
            f"legacy_replay_source_link_invalid:{type(exc).__name__}"
        ) from exc
    stress_fraction = _positive_fraction(
        target_stress_loss_fraction,
        name="target_stress_loss_fraction",
    )
    account_equity = _positive_number(
        legacy_plan.get("capital_usdt"),
        name="legacy_plan_capital_usdt",
    )
    try:
        snapshot = base_snapshot_from_projection(
            projection,
            projection_evidence_hash=projection_evidence_hash,
        )
        intent = base_intent_from_projection(
            projection,
            projection_evidence_hash=projection_evidence_hash,
            target_stress_loss_fraction=stress_fraction,
        )
        allocation = allocate_strategy_intents(
            (intent,),
            (
                SleeveRiskBudget(
                    strategy_id=intent.strategy_id,
                    target_stress_loss_fraction=stress_fraction,
                    estimated_standalone_stress_loss_fraction=stress_fraction,
                ),
            ),
            account_equity_usdt=account_equity,
            allowed_strategy_ids=(intent.strategy_id,),
        )
        target = portfolio_target_from_allocation((intent,), allocation)
        if not target.allocatable or target.blockers:
            raise LegacyDispatchReplayError(
                "legacy_replay_portfolio_blocked:"
                + ",".join(target.blockers or ("unknown",))
            )
        risk = risk_decision_from_legacy_dry_plan(legacy_plan, target)
        if not risk.approved or risk.violations:
            raise LegacyDispatchReplayError(
                "legacy_replay_risk_rejected:"
                + ",".join(risk.violations or ("not_approved",))
            )
        plan = order_plan_from_legacy_dry_plan(legacy_plan, target, risk)
        if not plan.executable or plan.blockers:
            raise LegacyDispatchReplayError(
                "legacy_replay_order_plan_blocked:"
                + ",".join(plan.blockers or ("not_executable",))
            )
        parity = compare_legacy_dispatch_plan(legacy_plan, plan)
        if parity["matches"] is not True:
            raise LegacyDispatchReplayError(
                "legacy_replay_parity_mismatch:"
                + ",".join(parity["differences"] or ("unknown",))
            )
        manifest = build_decision_batch_manifest(
            snapshot=snapshot,
            intents=(intent,),
            target=target,
            risk=risk,
            plan=plan,
            created_at=created_at,
        )
    except LegacyDispatchReplayError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise LegacyDispatchReplayError(
            f"legacy_replay_batch_build_failed:{type(exc).__name__}:{exc}"
        ) from exc
    return VerifiedDecisionBatch(
        manifest=manifest,
        snapshot=snapshot,
        intents=(intent,),
        target=target,
        risk=risk,
        plan=plan,
    )


def _table_count(connection: Any, table: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _ledger_state(ledger: RuntimeLedger) -> dict[str, Any]:
    with ledger._connection() as connection:
        connection.execute("BEGIN")
        try:
            batch_ids = tuple(
                str(row["batch_id"])
                for row in connection.execute(
                    "SELECT batch_id FROM batches ORDER BY rowid"
                )
            )
            orders = tuple(
                {
                    "client_order_id": str(row["client_order_id"]),
                    "batch_id": str(row["batch_id"]),
                    "status": str(row["status"]),
                }
                for row in connection.execute(
                    "SELECT client_order_id,batch_id,status FROM orders "
                    "ORDER BY sequence,client_order_id"
                )
            )
            counts = {
                table: _table_count(connection, table)
                for table in (
                    "order_events",
                    "fills",
                    "cash_events",
                    "positions",
                    "nav_marks",
                    "reconciliations",
                    "order_recoveries",
                    "audit_outbox",
                )
            }
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {"batch_ids": batch_ids, "orders": orders, "counts": counts}


def _require_isolated_dry_ledger(
    state: Mapping[str, Any],
    batch: VerifiedDecisionBatch,
    *,
    allow_empty: bool,
) -> None:
    batch_ids = tuple(state["batch_ids"])
    orders = tuple(state["orders"])
    counts = dict(state["counts"])
    if allow_empty and not batch_ids:
        if orders or any(counts.values()):
            raise LegacyDispatchReplayError("legacy_replay_empty_ledger_inconsistent")
        return
    if batch_ids != (batch.manifest.batch_id,):
        raise LegacyDispatchReplayError("legacy_replay_ledger_not_isolated")
    expected_order_ids = tuple(order.client_order_id for order in batch.plan.orders)
    actual_order_ids = tuple(row["client_order_id"] for row in orders)
    if actual_order_ids != expected_order_ids or any(
        row["batch_id"] != batch.manifest.batch_id for row in orders
    ):
        raise LegacyDispatchReplayError("legacy_replay_ledger_orders_mismatch")
    if any(row["status"] != "PLANNED" for row in orders):
        raise LegacyDispatchReplayError("legacy_replay_ledger_order_not_planned")
    forbidden_counts = {
        name: counts[name]
        for name in (
            "order_events",
            "fills",
            "cash_events",
            "positions",
            "nav_marks",
            "reconciliations",
            "order_recoveries",
        )
        if counts[name]
    }
    if forbidden_counts:
        raise LegacyDispatchReplayError("legacy_replay_ledger_contains_execution_state")
    expected_audit_rows = 1 + len(batch.plan.orders)
    if counts["audit_outbox"] != expected_audit_rows:
        raise LegacyDispatchReplayError("legacy_replay_ledger_audit_count_mismatch")


def _parity_summary(
    legacy_plan: Mapping[str, Any],
    batch: VerifiedDecisionBatch,
) -> dict[str, Any]:
    comparison = compare_legacy_dispatch_plan(legacy_plan, batch.plan)
    legacy_state_hash = canonical_hash({"economic_state": comparison["legacy"]})
    standard_state_hash = canonical_hash({"economic_state": comparison["standard"]})
    return {
        "matches": comparison["matches"],
        "differences": tuple(comparison["differences"]),
        "legacy_economic_state_hash": legacy_state_hash,
        "standard_economic_state_hash": standard_state_hash,
        "order_count": len(comparison["standard"]["orders"]),
        "cancellation_count": len(comparison["standard"]["cancellations"]),
        "retained_order_count": len(comparison["standard"]["retained_order_ids"]),
    }


@dataclass(frozen=True)
class LegacyDispatchReplayReport:
    schema_version: int
    evidence_class: str
    replay_semantics: str
    target_stress_loss_fraction: float
    legacy_plan_hash: str
    projection_evidence_hash: str
    batch_id: str
    manifest_hash: str
    snapshot_id: str
    decision_id: str
    intent_hash: str
    portfolio_target_id: str
    risk_decision_id: str
    risk_decision_hash: str
    order_plan_id: str
    standard_plan_hash: str
    parity: Mapping[str, Any]
    expected_positions: Mapping[str, float]
    reconciliation_tolerance: Mapping[str, float]
    ledger: Mapping[str, Any]
    execution_claims: Mapping[str, Any]
    report_hash: str

    def _core(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "evidence_class": self.evidence_class,
            "replay_semantics": self.replay_semantics,
            "target_stress_loss_fraction": self.target_stress_loss_fraction,
            "legacy_plan_hash": self.legacy_plan_hash,
            "projection_evidence_hash": self.projection_evidence_hash,
            "batch_id": self.batch_id,
            "manifest_hash": self.manifest_hash,
            "snapshot_id": self.snapshot_id,
            "decision_id": self.decision_id,
            "intent_hash": self.intent_hash,
            "portfolio_target_id": self.portfolio_target_id,
            "risk_decision_id": self.risk_decision_id,
            "risk_decision_hash": self.risk_decision_hash,
            "order_plan_id": self.order_plan_id,
            "standard_plan_hash": self.standard_plan_hash,
            "parity": dict(self.parity),
            "expected_positions": dict(self.expected_positions),
            "reconciliation_tolerance": dict(self.reconciliation_tolerance),
            "ledger": dict(self.ledger),
            "execution_claims": dict(self.execution_claims),
        }

    def validate(self) -> None:
        if self.schema_version != LEGACY_DISPATCH_REPLAY_SCHEMA_VERSION:
            raise LegacyDispatchReplayError("legacy_replay_report_schema_invalid")
        if self.evidence_class != _EVIDENCE_CLASS:
            raise LegacyDispatchReplayError("legacy_replay_report_evidence_class_invalid")
        if self.replay_semantics != _REPLAY_SEMANTICS:
            raise LegacyDispatchReplayError("legacy_replay_report_semantics_invalid")
        _positive_fraction(
            self.target_stress_loss_fraction,
            name="legacy_replay_report_target_stress_loss_fraction",
        )
        for name in (
            "legacy_plan_hash",
            "projection_evidence_hash",
            "batch_id",
            "manifest_hash",
            "snapshot_id",
            "decision_id",
            "intent_hash",
            "portfolio_target_id",
            "risk_decision_id",
            "risk_decision_hash",
            "order_plan_id",
            "standard_plan_hash",
            "report_hash",
        ):
            if not is_sha256(getattr(self, name)):
                raise LegacyDispatchReplayError(f"legacy_replay_report_{name}_invalid")
        parity = dict(self.parity)
        expected_parity_fields = {
            "matches",
            "differences",
            "legacy_economic_state_hash",
            "standard_economic_state_hash",
            "order_count",
            "cancellation_count",
            "retained_order_count",
        }
        if set(parity) != expected_parity_fields:
            raise LegacyDispatchReplayError(
                "legacy_replay_report_parity_fields_invalid"
            )
        if parity.get("matches") is not True or tuple(
            parity.get("differences") or ()
        ):
            raise LegacyDispatchReplayError("legacy_replay_report_parity_invalid")
        if parity.get("legacy_economic_state_hash") != parity.get(
            "standard_economic_state_hash"
        ) or not is_sha256(parity.get("legacy_economic_state_hash")):
            raise LegacyDispatchReplayError("legacy_replay_report_parity_hash_invalid")
        for name in ("order_count", "cancellation_count", "retained_order_count"):
            if (
                not isinstance(parity.get(name), int)
                or isinstance(parity.get(name), bool)
                or parity[name] < 0
            ):
                raise LegacyDispatchReplayError(
                    f"legacy_replay_report_parity_{name}_invalid"
                )
        for name, values in (
            ("expected_positions", self.expected_positions),
            ("reconciliation_tolerance", self.reconciliation_tolerance),
        ):
            if not isinstance(values, Mapping) or tuple(values) != tuple(
                sorted(values)
            ):
                raise LegacyDispatchReplayError(
                    f"legacy_replay_report_{name}_invalid"
                )
            for symbol, value in values.items():
                try:
                    number = float(value)
                except (TypeError, ValueError) as exc:
                    raise LegacyDispatchReplayError(
                        f"legacy_replay_report_{name}_invalid"
                    ) from exc
                if (
                    not isinstance(symbol, str)
                    or not symbol
                    or isinstance(value, bool)
                    or not math.isfinite(number)
                    or number < 0.0
                ):
                    raise LegacyDispatchReplayError(
                        f"legacy_replay_report_{name}_invalid"
                    )
        ledger = dict(self.ledger)
        expected_ledger_fields = {
            "database_role",
            "batch_count",
            "order_count",
            "planned_order_ids",
            "order_statuses",
            "all_orders_planned",
            "order_event_count",
            "fill_count",
            "cash_event_count",
            "position_count",
            "nav_mark_count",
            "reconciliation_count",
            "order_recovery_count",
            "risk_increase_allowed",
            "journal_mode",
            "foreign_keys",
            "synchronous",
            "audit_row_count",
            "audit_last_hash",
        }
        if (
            set(ledger) != expected_ledger_fields
            or ledger.get("database_role") != "isolated_local_replay"
            or ledger.get("batch_count") != 1
            or isinstance(ledger.get("batch_count"), bool)
            or not isinstance(ledger.get("order_count"), int)
            or isinstance(ledger.get("order_count"), bool)
            or ledger.get("order_count") != parity["order_count"]
            or ledger.get("all_orders_planned") is not True
            or ledger.get("risk_increase_allowed") is not False
            or ledger.get("journal_mode") != "wal"
            or ledger.get("foreign_keys") is not True
            or ledger.get("synchronous") != "full"
        ):
            raise LegacyDispatchReplayError("legacy_replay_report_ledger_invalid")
        planned_ids = tuple(ledger.get("planned_order_ids") or ())
        statuses = ledger.get("order_statuses")
        if (
            len(planned_ids) != parity["order_count"]
            or len(planned_ids) != len(set(planned_ids))
            or any(not isinstance(value, str) or not value for value in planned_ids)
            or not isinstance(statuses, Mapping)
            or set(statuses) != set(planned_ids)
            or any(status != "PLANNED" for status in statuses.values())
        ):
            raise LegacyDispatchReplayError(
                "legacy_replay_report_order_statuses_invalid"
            )
        for name in (
            "order_event_count",
            "fill_count",
            "cash_event_count",
            "position_count",
            "nav_mark_count",
            "reconciliation_count",
            "order_recovery_count",
        ):
            if (
                not isinstance(ledger.get(name), int)
                or isinstance(ledger.get(name), bool)
                or ledger[name] != 0
            ):
                raise LegacyDispatchReplayError(
                    f"legacy_replay_report_{name}_invalid"
                )
        if (
            not isinstance(ledger.get("audit_row_count"), int)
            or isinstance(ledger.get("audit_row_count"), bool)
            or ledger.get("audit_row_count") != 1 + parity["order_count"]
            or not is_sha256(ledger.get("audit_last_hash"))
        ):
            raise LegacyDispatchReplayError("legacy_replay_report_audit_invalid")
        expected_claims = {
            "dry_replay_only": True,
            "order_plan_contract_executable": True,
            "orders_authorized": False,
            "orders_routed": False,
            "acknowledgements_recorded": False,
            "fills_recorded": False,
            "cash_events_recorded": False,
            "nav_marks_recorded": False,
            "reconciliation_recorded": False,
        }
        if dict(self.execution_claims) != expected_claims:
            raise LegacyDispatchReplayError(
                "legacy_replay_report_execution_claims_invalid"
            )
        if self.report_hash != canonical_hash(self._core()):
            raise LegacyDispatchReplayError("legacy_replay_report_hash_invalid")

    def as_dict(self) -> dict[str, Any]:
        return self._core() | {"report_hash": self.report_hash}


@dataclass(frozen=True)
class LegacyDispatchReplay:
    batch: VerifiedDecisionBatch
    report: LegacyDispatchReplayReport


def replay_legacy_dry_dispatch(
    ledger: RuntimeLedger,
    projection: Mapping[str, Any],
    legacy_plan: Mapping[str, Any],
    *,
    projection_evidence_hash: str,
    target_stress_loss_fraction: float,
    created_at: str,
) -> LegacyDispatchReplay:
    """Register a dry batch idempotently and prove that no execution was recorded."""

    if not isinstance(ledger, RuntimeLedger):
        raise TypeError("legacy_replay_requires_runtime_ledger")
    batch = build_verified_legacy_dispatch_batch(
        projection,
        legacy_plan,
        projection_evidence_hash=projection_evidence_hash,
        target_stress_loss_fraction=target_stress_loss_fraction,
        created_at=created_at,
    )
    ledger.flush_audit_outbox()
    ledger.integrity_check()
    _require_isolated_dry_ledger(
        _ledger_state(ledger),
        batch,
        allow_empty=True,
    )
    ledger.record_verified_batch(batch, recorded_at=created_at)
    ledger.flush_audit_outbox()
    integrity = ledger.integrity_check()
    state = _ledger_state(ledger)
    _require_isolated_dry_ledger(state, batch, allow_empty=False)
    verification = verify_legacy_dry_dispatch_plan(legacy_plan, batch.target)
    if not verification.verified:
        raise LegacyDispatchReplayError("legacy_replay_post_registration_invalid")
    parity = _parity_summary(legacy_plan, batch)
    order_statuses = {
        row["client_order_id"]: row["status"]
        for row in sorted(state["orders"], key=lambda value: value["client_order_id"])
    }
    counts = state["counts"]
    ledger_report = {
        "database_role": "isolated_local_replay",
        "batch_count": len(state["batch_ids"]),
        "order_count": len(state["orders"]),
        "planned_order_ids": tuple(
            order.client_order_id for order in batch.plan.orders
        ),
        "order_statuses": order_statuses,
        "all_orders_planned": all(
            status == "PLANNED" for status in order_statuses.values()
        ),
        "order_event_count": counts["order_events"],
        "fill_count": counts["fills"],
        "cash_event_count": counts["cash_events"],
        "position_count": counts["positions"],
        "nav_mark_count": counts["nav_marks"],
        "reconciliation_count": counts["reconciliations"],
        "order_recovery_count": counts["order_recoveries"],
        "risk_increase_allowed": ledger.risk_increase_allowed(),
        "journal_mode": integrity["journal_mode"],
        "foreign_keys": integrity["foreign_keys"],
        "synchronous": integrity["synchronous"],
        "audit_row_count": integrity["audit_rows"],
        "audit_last_hash": integrity["audit_last_hash"],
    }
    execution_claims = {
        "dry_replay_only": True,
        "order_plan_contract_executable": batch.plan.executable,
        "orders_authorized": batch.manifest.orders_authorized,
        "orders_routed": False,
        "acknowledgements_recorded": False,
        "fills_recorded": False,
        "cash_events_recorded": False,
        "nav_marks_recorded": False,
        "reconciliation_recorded": False,
    }
    intent = batch.intents[0]
    core = {
        "schema_version": LEGACY_DISPATCH_REPLAY_SCHEMA_VERSION,
        "evidence_class": _EVIDENCE_CLASS,
        "replay_semantics": _REPLAY_SEMANTICS,
        "target_stress_loss_fraction": float(target_stress_loss_fraction),
        "legacy_plan_hash": verification.legacy_plan_hash,
        "projection_evidence_hash": projection_evidence_hash,
        "batch_id": batch.manifest.batch_id,
        "manifest_hash": batch.manifest.manifest_hash,
        "snapshot_id": batch.snapshot.snapshot_id,
        "decision_id": intent.decision_id,
        "intent_hash": intent.intent_hash,
        "portfolio_target_id": batch.target.portfolio_target_id,
        "risk_decision_id": batch.risk.risk_decision_id,
        "risk_decision_hash": batch.risk.decision_hash,
        "order_plan_id": batch.plan.order_plan_id,
        "standard_plan_hash": batch.plan.plan_hash,
        "parity": parity,
        "expected_positions": dict(sorted(batch.plan.expected_positions.items())),
        "reconciliation_tolerance": dict(
            sorted(batch.plan.reconciliation_tolerance.items())
        ),
        "ledger": ledger_report,
        "execution_claims": execution_claims,
    }
    report = LegacyDispatchReplayReport(
        **core,
        report_hash=canonical_hash(core),
    )
    report.validate()
    return LegacyDispatchReplay(batch=batch, report=report)
