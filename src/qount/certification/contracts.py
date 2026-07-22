"""Pure contracts for venue certification plans, runs, events, and results.

These contracts implement the execution certification lane (Workstream A)
defined in trading-system-evolution-plan.md sections 3.1-3.4.

Key invariants enforced by every contract:
  * orders_authorized is always False
  * strategy_id is always None (certification is not a strategy)
  * portfolio_nav is always "excluded" (certification cost is operational)
  * batch_type is always "venue_certification"
  * pnl_attribution is always "operational_certification_cost"
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Sequence

from qount.contracts import ArtifactReference
from qount.contracts.hashing import canonical_hash
from qount.contracts.trace import aware_datetime
from qount.contracts.trace import is_sha256
from qount.contracts.trace import trace_id


CERTIFICATION_SCHEMA_VERSION = 1

CERTIFICATION_TYPES = ("local_gateway", "testnet", "real_minimum")

CERTIFICATION_STATUSES = (
    "draft",
    "local_sim",
    "testnet",
    "real_pending_owner",
    "real_authorized",
    "completed",
    "halted",
)

VENUE_SEMANTICS = (
    "client_id_idempotency",
    "ack_loss",
    "partial_fill",
    "stop_algo",
    "rounding_filter",
    "funding_income",
    "crash_recovery",
    "ws_gap_recovery",
    "real_ack_fill",
    "real_rounding",
    "real_fee_maker_taker",
    "real_stop_algo",
    "real_funding_income",
    "real_reconciliation",
)

CERTIFICATION_EVENT_TYPES = (
    "submit",
    "ack",
    "fill",
    "partial_fill",
    "cancel",
    "query",
    "crash",
    "recover",
    "halt",
)

CERTIFICATION_EVENT_SOURCES = ("local_gateway", "testnet", "real")

OBSERVED_ORDER_STATES = (
    "PLANNED",
    "SUBMITTING",
    "ACKNOWLEDGED",
    "PARTIALLY_FILLED",
    "FILLED",
    "CANCELLED",
    "UNKNOWN",
)

RUN_STATUSES = ("running", "completed", "halted")

REQUIRED_RESULT_MEMBERS = (
    "authorization",
    "venue_capability_snapshot",
    "certification_preflight",
    "certification_plan",
    "certification_order_events",
    "exchange_raw",
    "query_coverage",
    "runtime_ledger_snapshot",
    "shadow_accountant_snapshot",
    "reconciliation_diff",
    "operational_cost",
    "zero_position_proof",
)

_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9]{1,19}$")
_ACTION_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


def _finite_float(value: object, *, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return math.nan
    if not math.isfinite(result):
        return math.nan
    return result


@dataclass(frozen=True)
class CertificationPlan:
    """A pre-registered, owner-authorized plan for one certification test.

    Each real certification test validates exactly one venue semantic.
    The build-up and zero-out actions must belong to the same plan and
    share total notional, fee, and maximum exposure time caps.
    """

    schema_version: int
    plan_id: str
    certification_type: str
    venue_semantic: str
    symbol: str
    action: str
    max_notional: float
    max_fee: float
    max_holding_time_seconds: float
    owner_authorization_hash: str
    arm_token_hash: str
    expires_at: str
    preflight_snapshot_hash: str
    venue_capability_snapshot_hash: str
    zero_position_plan: str
    failure_handling_path: str
    certification_status: str
    batch_type: str
    pnl_attribution: str
    strategy_id: str | None
    portfolio_nav: str
    orders_authorized: bool
    plan_hash: str

    @classmethod
    def create(
        cls,
        *,
        certification_type: str,
        venue_semantic: str,
        symbol: str,
        action: str,
        max_notional: float,
        max_fee: float,
        max_holding_time_seconds: float,
        owner_authorization_hash: str,
        arm_token_hash: str,
        expires_at: str,
        preflight_snapshot_hash: str,
        venue_capability_snapshot_hash: str,
        zero_position_plan: str,
        failure_handling_path: str,
        certification_status: str = "draft",
    ) -> CertificationPlan:
        core = {
            "schema_version": CERTIFICATION_SCHEMA_VERSION,
            "certification_type": certification_type,
            "venue_semantic": venue_semantic,
            "symbol": symbol,
            "action": action,
            "max_notional": float(max_notional),
            "max_fee": float(max_fee),
            "max_holding_time_seconds": float(max_holding_time_seconds),
            "owner_authorization_hash": owner_authorization_hash,
            "arm_token_hash": arm_token_hash,
            "expires_at": expires_at,
            "preflight_snapshot_hash": preflight_snapshot_hash,
            "venue_capability_snapshot_hash": venue_capability_snapshot_hash,
            "zero_position_plan": zero_position_plan,
            "failure_handling_path": failure_handling_path,
            "certification_status": certification_status,
            "batch_type": "venue_certification",
            "pnl_attribution": "operational_certification_cost",
            "strategy_id": None,
            "portfolio_nav": "excluded",
            "orders_authorized": False,
        }
        plan_hash = canonical_hash(core)
        plan = cls(
            schema_version=CERTIFICATION_SCHEMA_VERSION,
            plan_id=trace_id(
                "certification_plan", {"plan_hash": plan_hash}
            ),
            certification_type=certification_type,
            venue_semantic=venue_semantic,
            symbol=symbol,
            action=action,
            max_notional=float(max_notional),
            max_fee=float(max_fee),
            max_holding_time_seconds=float(max_holding_time_seconds),
            owner_authorization_hash=owner_authorization_hash,
            arm_token_hash=arm_token_hash,
            expires_at=expires_at,
            preflight_snapshot_hash=preflight_snapshot_hash,
            venue_capability_snapshot_hash=venue_capability_snapshot_hash,
            zero_position_plan=zero_position_plan,
            failure_handling_path=failure_handling_path,
            certification_status=certification_status,
            batch_type="venue_certification",
            pnl_attribution="operational_certification_cost",
            strategy_id=None,
            portfolio_nav="excluded",
            orders_authorized=False,
            plan_hash=plan_hash,
        )
        errors = plan.validate()
        if errors:
            raise ValueError(f"certification_plan_invalid:{','.join(errors)}")
        return plan

    def _core(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "certification_type": self.certification_type,
            "venue_semantic": self.venue_semantic,
            "symbol": self.symbol,
            "action": self.action,
            "max_notional": self.max_notional,
            "max_fee": self.max_fee,
            "max_holding_time_seconds": self.max_holding_time_seconds,
            "owner_authorization_hash": self.owner_authorization_hash,
            "arm_token_hash": self.arm_token_hash,
            "expires_at": self.expires_at,
            "preflight_snapshot_hash": self.preflight_snapshot_hash,
            "venue_capability_snapshot_hash": self.venue_capability_snapshot_hash,
            "zero_position_plan": self.zero_position_plan,
            "failure_handling_path": self.failure_handling_path,
            "certification_status": self.certification_status,
            "batch_type": self.batch_type,
            "pnl_attribution": self.pnl_attribution,
            "strategy_id": self.strategy_id,
            "portfolio_nav": self.portfolio_nav,
            "orders_authorized": self.orders_authorized,
        }

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.schema_version != CERTIFICATION_SCHEMA_VERSION:
            errors.append("certification_plan_schema_version_invalid")
        if self.certification_type not in CERTIFICATION_TYPES:
            errors.append("certification_plan_type_invalid")
        if self.venue_semantic not in VENUE_SEMANTICS:
            errors.append("certification_plan_venue_semantic_invalid")
        if not _SYMBOL_RE.fullmatch(self.symbol):
            errors.append("certification_plan_symbol_invalid")
        if not _ACTION_RE.fullmatch(self.action):
            errors.append("certification_plan_action_invalid")
        nominal = _finite_float(
            self.max_notional, name="max_notional"
        )
        if math.isnan(nominal) or nominal <= 0.0:
            errors.append("certification_plan_max_notional_invalid")
        fee = _finite_float(self.max_fee, name="max_fee")
        if math.isnan(fee) or fee < 0.0:
            errors.append("certification_plan_max_fee_invalid")
        holding = _finite_float(
            self.max_holding_time_seconds, name="max_holding_time_seconds"
        )
        if math.isnan(holding) or holding <= 0.0:
            errors.append("certification_plan_max_holding_time_invalid")
        if self.certification_status not in CERTIFICATION_STATUSES:
            errors.append("certification_plan_status_invalid")
        for name in (
            "owner_authorization_hash",
            "arm_token_hash",
            "preflight_snapshot_hash",
            "venue_capability_snapshot_hash",
        ):
            if not is_sha256(getattr(self, name)):
                errors.append(f"certification_plan_{name}_invalid")
        try:
            aware_datetime(self.expires_at)
        except (AttributeError, TypeError, ValueError):
            errors.append("certification_plan_expires_at_invalid")
        if not self.zero_position_plan:
            errors.append("certification_plan_zero_position_plan_empty")
        if not self.failure_handling_path:
            errors.append("certification_plan_failure_handling_path_empty")
        if self.batch_type != "venue_certification":
            errors.append("certification_plan_batch_type_invalid")
        if self.pnl_attribution != "operational_certification_cost":
            errors.append("certification_plan_pnl_attribution_invalid")
        if self.strategy_id is not None:
            errors.append("certification_plan_strategy_id_must_be_none")
        if self.portfolio_nav != "excluded":
            errors.append("certification_plan_portfolio_nav_invalid")
        if self.orders_authorized is not False:
            errors.append("certification_plan_cannot_authorize_orders")
        expected_hash = canonical_hash(self._core())
        if self.plan_hash != expected_hash:
            errors.append("certification_plan_hash_invalid")
        expected_id = trace_id(
            "certification_plan", {"plan_hash": expected_hash}
        )
        if self.plan_id != expected_id:
            errors.append("certification_plan_id_invalid")
        return tuple(errors)


@dataclass(frozen=True)
class CertificationRun:
    """One execution of a CertificationPlan.

    A run tracks the lifecycle from start to completion or halt.
    orders_authorized is always False; certification never produces
    strategy intents or enters portfolio PnL.
    """

    schema_version: int
    run_id: str
    plan_id: str
    certification_type: str
    started_at: str
    completed_at: str | None
    status: str
    orders_authorized: bool
    run_hash: str

    @classmethod
    def create(
        cls,
        *,
        plan_id: str,
        certification_type: str,
        started_at: str,
        completed_at: str | None = None,
        status: str = "running",
    ) -> CertificationRun:
        core = {
            "schema_version": CERTIFICATION_SCHEMA_VERSION,
            "plan_id": plan_id,
            "certification_type": certification_type,
            "started_at": started_at,
            "completed_at": completed_at,
            "status": status,
            "orders_authorized": False,
        }
        run_hash = canonical_hash(core)
        run = cls(
            schema_version=CERTIFICATION_SCHEMA_VERSION,
            run_id=trace_id(
                "certification_run", {"run_hash": run_hash}
            ),
            plan_id=plan_id,
            certification_type=certification_type,
            started_at=started_at,
            completed_at=completed_at,
            status=status,
            orders_authorized=False,
            run_hash=run_hash,
        )
        errors = run.validate()
        if errors:
            raise ValueError(f"certification_run_invalid:{','.join(errors)}")
        return run

    def _core(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "certification_type": self.certification_type,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "status": self.status,
            "orders_authorized": self.orders_authorized,
        }

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.schema_version != CERTIFICATION_SCHEMA_VERSION:
            errors.append("certification_run_schema_version_invalid")
        if not is_sha256(self.plan_id):
            errors.append("certification_run_plan_id_invalid")
        if self.certification_type not in CERTIFICATION_TYPES:
            errors.append("certification_run_type_invalid")
        try:
            aware_datetime(self.started_at)
        except (AttributeError, TypeError, ValueError):
            errors.append("certification_run_started_at_invalid")
        if self.completed_at is not None:
            try:
                completed = aware_datetime(self.completed_at)
                started = aware_datetime(self.started_at)
                if completed < started:
                    errors.append(
                        "certification_run_completed_before_started"
                    )
            except (AttributeError, TypeError, ValueError):
                errors.append("certification_run_completed_at_invalid")
        if self.status not in RUN_STATUSES:
            errors.append("certification_run_status_invalid")
        if self.orders_authorized is not False:
            errors.append("certification_run_cannot_authorize_orders")
        expected_hash = canonical_hash(self._core())
        if self.run_hash != expected_hash:
            errors.append("certification_run_hash_invalid")
        expected_id = trace_id(
            "certification_run", {"run_hash": expected_hash}
        )
        if self.run_id != expected_id:
            errors.append("certification_run_id_invalid")
        return tuple(errors)


@dataclass(frozen=True)
class CertificationEvent:
    """One observed event during a certification run.

    Events are appended to order_events.jsonl.  Each event captures the
    observed order state, the raw exchange response hash, and the source
    (local gateway, testnet, or real).  UNKNOWN states require resolution
    via query before a replacement order may be considered.
    """

    schema_version: int
    event_id: str
    run_id: str
    event_type: str
    client_order_id: str
    exchange_order_id: str | None
    timestamp: str
    observed_state: str
    raw_response_hash: str
    source: str
    event_hash: str

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        event_type: str,
        client_order_id: str,
        timestamp: str,
        observed_state: str,
        raw_response_hash: str,
        source: str,
        exchange_order_id: str | None = None,
    ) -> CertificationEvent:
        core = {
            "schema_version": CERTIFICATION_SCHEMA_VERSION,
            "run_id": run_id,
            "event_type": event_type,
            "client_order_id": client_order_id,
            "exchange_order_id": exchange_order_id,
            "timestamp": timestamp,
            "observed_state": observed_state,
            "raw_response_hash": raw_response_hash,
            "source": source,
        }
        event_hash = canonical_hash(core)
        event = cls(
            schema_version=CERTIFICATION_SCHEMA_VERSION,
            event_id=trace_id(
                "certification_event", {"event_hash": event_hash}
            ),
            run_id=run_id,
            event_type=event_type,
            client_order_id=client_order_id,
            exchange_order_id=exchange_order_id,
            timestamp=timestamp,
            observed_state=observed_state,
            raw_response_hash=raw_response_hash,
            source=source,
            event_hash=event_hash,
        )
        errors = event.validate()
        if errors:
            raise ValueError(
                f"certification_event_invalid:{','.join(errors)}"
            )
        return event

    def _core(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "event_type": self.event_type,
            "client_order_id": self.client_order_id,
            "exchange_order_id": self.exchange_order_id,
            "timestamp": self.timestamp,
            "observed_state": self.observed_state,
            "raw_response_hash": self.raw_response_hash,
            "source": self.source,
        }

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.schema_version != CERTIFICATION_SCHEMA_VERSION:
            errors.append("certification_event_schema_version_invalid")
        if not is_sha256(self.run_id):
            errors.append("certification_event_run_id_invalid")
        if self.event_type not in CERTIFICATION_EVENT_TYPES:
            errors.append("certification_event_type_invalid")
        if not self.client_order_id:
            errors.append("certification_event_client_order_id_empty")
        try:
            aware_datetime(self.timestamp)
        except (AttributeError, TypeError, ValueError):
            errors.append("certification_event_timestamp_invalid")
        if self.observed_state not in OBSERVED_ORDER_STATES:
            errors.append("certification_event_observed_state_invalid")
        if not is_sha256(self.raw_response_hash):
            errors.append("certification_event_raw_response_hash_invalid")
        if self.source not in CERTIFICATION_EVENT_SOURCES:
            errors.append("certification_event_source_invalid")
        expected_hash = canonical_hash(self._core())
        if self.event_hash != expected_hash:
            errors.append("certification_event_hash_invalid")
        expected_id = trace_id(
            "certification_event", {"event_hash": expected_hash}
        )
        if self.event_id != expected_id:
            errors.append("certification_event_id_invalid")
        return tuple(errors)


@dataclass(frozen=True)
class CertificationResult:
    """The manifest for a completed (or incomplete) certification run.

    This corresponds to manifest.json in the certification artifact set.
    It is written last.  Any missing member, hash mismatch, or non-zero
    final position prevents ``completed`` from being True.

    The ``completed`` flag is computed, not asserted: it is True only when
    all required artifact members are present, all proof hashes are valid,
    and the caller confirms the final position is zero.
    """

    schema_version: int
    result_id: str
    run_id: str
    artifact_members: tuple[ArtifactReference, ...]
    final_zero_position_proof_hash: str
    reconciliation_diff_hash: str
    operational_cost_hash: str
    final_position_is_zero: bool
    completed: bool
    result_hash: str

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        artifact_members: Sequence[ArtifactReference],
        final_zero_position_proof_hash: str,
        reconciliation_diff_hash: str,
        operational_cost_hash: str,
        final_position_is_zero: bool,
    ) -> CertificationResult:
        normalized_members = tuple(
            sorted(artifact_members, key=lambda ref: ref.artifact_type)
        )
        present_types = {
            ref.artifact_type for ref in normalized_members
        }
        all_required_present = all(
            required in present_types
            for required in REQUIRED_RESULT_MEMBERS
        )
        all_proofs_valid = (
            is_sha256(final_zero_position_proof_hash)
            and is_sha256(reconciliation_diff_hash)
            and is_sha256(operational_cost_hash)
        )
        completed = bool(
            all_required_present
            and all_proofs_valid
            and final_position_is_zero
        )
        core = {
            "schema_version": CERTIFICATION_SCHEMA_VERSION,
            "run_id": run_id,
            "artifact_members": [
                ref.as_dict() for ref in normalized_members
            ],
            "final_zero_position_proof_hash": final_zero_position_proof_hash,
            "reconciliation_diff_hash": reconciliation_diff_hash,
            "operational_cost_hash": operational_cost_hash,
            "final_position_is_zero": final_position_is_zero,
            "completed": completed,
        }
        result_hash = canonical_hash(core)
        result = cls(
            schema_version=CERTIFICATION_SCHEMA_VERSION,
            result_id=trace_id(
                "certification_result", {"result_hash": result_hash}
            ),
            run_id=run_id,
            artifact_members=normalized_members,
            final_zero_position_proof_hash=final_zero_position_proof_hash,
            reconciliation_diff_hash=reconciliation_diff_hash,
            operational_cost_hash=operational_cost_hash,
            final_position_is_zero=final_position_is_zero,
            completed=completed,
            result_hash=result_hash,
        )
        errors = result.validate()
        if errors:
            raise ValueError(
                f"certification_result_invalid:{','.join(errors)}"
            )
        return result

    def _core(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "artifact_members": [
                ref.as_dict() for ref in self.artifact_members
            ],
            "final_zero_position_proof_hash": self.final_zero_position_proof_hash,
            "reconciliation_diff_hash": self.reconciliation_diff_hash,
            "operational_cost_hash": self.operational_cost_hash,
            "final_position_is_zero": self.final_position_is_zero,
            "completed": self.completed,
        }

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.schema_version != CERTIFICATION_SCHEMA_VERSION:
            errors.append("certification_result_schema_version_invalid")
        if not is_sha256(self.run_id):
            errors.append("certification_result_run_id_invalid")
        member_types: list[str] = []
        for index, reference in enumerate(self.artifact_members):
            errors.extend(
                f"artifact_member:{index}:{error}"
                for error in reference.validate()
            )
            member_types.append(reference.artifact_type)
        if member_types != sorted(member_types):
            errors.append("certification_result_members_not_sorted")
        if len(member_types) != len(set(member_types)):
            errors.append("certification_result_member_duplicate")
        present = set(member_types)
        missing = [
            required
            for required in REQUIRED_RESULT_MEMBERS
            if required not in present
        ]
        for name in (
            "final_zero_position_proof_hash",
            "reconciliation_diff_hash",
            "operational_cost_hash",
        ):
            if not is_sha256(getattr(self, name)):
                errors.append(f"certification_result_{name}_invalid")
        expected_completed = bool(
            not missing
            and is_sha256(self.final_zero_position_proof_hash)
            and is_sha256(self.reconciliation_diff_hash)
            and is_sha256(self.operational_cost_hash)
            and self.final_position_is_zero
        )
        if self.completed != expected_completed:
            errors.append("certification_result_completed_flag_invalid")
        expected_hash = canonical_hash(self._core())
        if self.result_hash != expected_hash:
            errors.append("certification_result_hash_invalid")
        expected_id = trace_id(
            "certification_result", {"result_hash": expected_hash}
        )
        if self.result_id != expected_id:
            errors.append("certification_result_id_invalid")
        return tuple(errors)
