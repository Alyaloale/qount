"""Immutable runtime contracts linking data, portfolio, risk, and execution."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from qount.contracts.hashing import canonical_hash
from qount.contracts.trace import aware_datetime
from qount.contracts.trace import is_sha256
from qount.contracts.trace import timestamp_errors
from qount.contracts.trace import trace_id
from qount.contracts.trace import weight_errors


RUNTIME_CONTRACT_SCHEMA_VERSION = 1
_CLIENT_ORDER_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,36}$")


def planned_client_order_id(
    *,
    batch_id: str,
    decision_ids: Sequence[str],
    symbol: str,
    phase: str,
    sequence: int,
) -> str:
    """Return a Binance-safe deterministic ID for one planned order."""

    digest = trace_id(
        "planned_order",
        {
            "batch_id": batch_id,
            "decision_ids": sorted(decision_ids),
            "symbol": symbol,
            "phase": phase,
            "sequence": sequence,
        },
    )
    phase_code = {"reduce": "r", "increase": "i", "protective": "p"}.get(
        phase,
        "x",
    )
    return f"q-{phase_code}-{digest[:28]}"


def planned_cancellation_id(
    *,
    batch_id: str,
    decision_ids: Sequence[str],
    symbol: str,
    target_exchange_order_id: str | None,
    target_client_order_id: str | None,
    sequence: int,
) -> str:
    """Return a deterministic internal ID for one protective cancellation."""

    return trace_id(
        "planned_cancellation",
        {
            "batch_id": batch_id,
            "decision_ids": sorted(decision_ids),
            "symbol": symbol,
            "target_exchange_order_id": target_exchange_order_id,
            "target_client_order_id": target_client_order_id,
            "sequence": sequence,
        },
    )


@dataclass(frozen=True)
class MarketSnapshot:
    schema_version: int
    snapshot_id: str
    decision_time: str
    data_cutoff: str
    prices: Mapping[str, float]
    funding: Mapping[str, float]
    features: Mapping[str, Any]
    exchange_rules_hash: str
    account_snapshot_hash: str | None
    data_quality: Mapping[str, Any]
    source_hashes: Mapping[str, str]
    snapshot_hash: str

    @classmethod
    def create(
        cls,
        *,
        decision_time: str,
        data_cutoff: str,
        prices: Mapping[str, float],
        funding: Mapping[str, float] | None,
        features: Mapping[str, Any] | None,
        exchange_rules_hash: str,
        account_snapshot_hash: str | None,
        data_quality: Mapping[str, Any],
        source_hashes: Mapping[str, str],
    ) -> MarketSnapshot:
        core = {
            "schema_version": RUNTIME_CONTRACT_SCHEMA_VERSION,
            "decision_time": decision_time,
            "data_cutoff": data_cutoff,
            "prices": dict(prices),
            "funding": dict(funding or {}),
            "features": dict(features or {}),
            "exchange_rules_hash": exchange_rules_hash,
            "account_snapshot_hash": account_snapshot_hash,
            "data_quality": dict(data_quality),
            "source_hashes": dict(source_hashes),
        }
        snapshot_hash = canonical_hash(core)
        snapshot = cls(
            **core,
            snapshot_id=trace_id(
                "market_snapshot",
                {
                    "decision_time": decision_time,
                    "snapshot_hash": snapshot_hash,
                },
            ),
            snapshot_hash=snapshot_hash,
        )
        errors = snapshot.validate()
        if errors:
            raise ValueError(f"market_snapshot_invalid:{','.join(errors)}")
        return snapshot

    def _core(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "decision_time": self.decision_time,
            "data_cutoff": self.data_cutoff,
            "prices": dict(self.prices),
            "funding": dict(self.funding),
            "features": dict(self.features),
            "exchange_rules_hash": self.exchange_rules_hash,
            "account_snapshot_hash": self.account_snapshot_hash,
            "data_quality": dict(self.data_quality),
            "source_hashes": dict(self.source_hashes),
        }

    def validate(self) -> tuple[str, ...]:
        errors = list(
            timestamp_errors(
                self.decision_time,
                self.data_cutoff,
                prefix="snapshot",
            )
        )
        if self.schema_version != RUNTIME_CONTRACT_SCHEMA_VERSION:
            errors.append("snapshot_schema_version_invalid")
        if not self.prices:
            errors.append("snapshot_prices_empty")
        for symbol, raw_price in self.prices.items():
            try:
                price = float(raw_price)
            except (TypeError, ValueError):
                price = math.nan
            if not symbol or not math.isfinite(price) or price <= 0.0:
                errors.append(f"snapshot_price_invalid:{symbol}")
        for symbol, raw_rate in self.funding.items():
            try:
                rate = float(raw_rate)
            except (TypeError, ValueError):
                rate = math.nan
            if not symbol or not math.isfinite(rate):
                errors.append(f"snapshot_funding_invalid:{symbol}")
        if not is_sha256(self.exchange_rules_hash):
            errors.append("snapshot_exchange_rules_hash_invalid")
        if self.account_snapshot_hash is not None and not is_sha256(
            self.account_snapshot_hash
        ):
            errors.append("snapshot_account_hash_invalid")
        if not self.source_hashes:
            errors.append("snapshot_source_hashes_empty")
        for source, value in self.source_hashes.items():
            if not source or not is_sha256(value):
                errors.append(f"snapshot_source_hash_invalid:{source}")
        complete = self.data_quality.get("complete")
        blockers = self.data_quality.get("blockers")
        if not isinstance(complete, bool):
            errors.append("snapshot_data_quality_complete_invalid")
        if not isinstance(blockers, (list, tuple)):
            errors.append("snapshot_data_quality_blockers_invalid")
        elif complete and blockers:
            errors.append("snapshot_complete_with_blockers")
        elif complete is False and not blockers:
            errors.append("snapshot_incomplete_without_blockers")
        account_linked = self.data_quality.get("account_snapshot_linked")
        if account_linked is not None:
            if not isinstance(account_linked, bool):
                errors.append("snapshot_account_linked_flag_invalid")
            elif account_linked != (self.account_snapshot_hash is not None):
                errors.append("snapshot_account_link_mismatch")

        expected_hash = canonical_hash(self._core())
        if self.snapshot_hash != expected_hash:
            errors.append("snapshot_hash_invalid")
        expected_id = trace_id(
            "market_snapshot",
            {
                "decision_time": self.decision_time,
                "snapshot_hash": expected_hash,
            },
        )
        if self.snapshot_id != expected_id:
            errors.append("snapshot_id_invalid")
        return tuple(errors)


@dataclass(frozen=True)
class PortfolioTarget:
    schema_version: int
    portfolio_target_id: str
    snapshot_id: str
    decision_ids: tuple[str, ...]
    decision_time: str
    proposed_target_weights: Mapping[str, float]
    target_weights: Mapping[str, float]
    sleeve_contributions: Mapping[str, Mapping[str, float]]
    blockers: tuple[str, ...]
    allocatable: bool
    allocation_hash: str
    target_hash: str

    @classmethod
    def create(
        cls,
        *,
        snapshot_id: str,
        decision_ids: Sequence[str],
        decision_time: str,
        proposed_target_weights: Mapping[str, float],
        target_weights: Mapping[str, float],
        sleeve_contributions: Mapping[str, Mapping[str, float]],
        blockers: Sequence[str],
        allocatable: bool,
        allocation_hash: str,
    ) -> PortfolioTarget:
        normalized_decision_ids = tuple(decision_ids)
        core = {
            "schema_version": RUNTIME_CONTRACT_SCHEMA_VERSION,
            "snapshot_id": snapshot_id,
            "decision_ids": normalized_decision_ids,
            "decision_time": decision_time,
            "proposed_target_weights": dict(proposed_target_weights),
            "target_weights": dict(target_weights),
            "sleeve_contributions": {
                strategy_id: dict(weights)
                for strategy_id, weights in sleeve_contributions.items()
            },
            "blockers": tuple(blockers),
            "allocatable": allocatable,
            "allocation_hash": allocation_hash,
        }
        target_hash = canonical_hash(core)
        target = cls(
            **core,
            portfolio_target_id=trace_id(
                "portfolio_target",
                {
                    "snapshot_id": snapshot_id,
                    "decision_ids": sorted(normalized_decision_ids),
                    "target_hash": target_hash,
                },
            ),
            target_hash=target_hash,
        )
        errors = target.validate()
        if errors:
            raise ValueError(f"portfolio_target_invalid:{','.join(errors)}")
        return target

    def _core(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "decision_ids": tuple(self.decision_ids),
            "decision_time": self.decision_time,
            "proposed_target_weights": dict(self.proposed_target_weights),
            "target_weights": dict(self.target_weights),
            "sleeve_contributions": {
                strategy_id: dict(weights)
                for strategy_id, weights in self.sleeve_contributions.items()
            },
            "blockers": tuple(self.blockers),
            "allocatable": self.allocatable,
            "allocation_hash": self.allocation_hash,
        }

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.schema_version != RUNTIME_CONTRACT_SCHEMA_VERSION:
            errors.append("portfolio_target_schema_version_invalid")
        if not is_sha256(self.snapshot_id):
            errors.append("portfolio_target_snapshot_id_invalid")
        if not self.decision_ids:
            errors.append("portfolio_target_decision_ids_empty")
        elif len(self.decision_ids) != len(set(self.decision_ids)):
            errors.append("portfolio_target_decision_ids_duplicate")
        for decision_id in self.decision_ids:
            if not is_sha256(decision_id):
                errors.append("portfolio_target_decision_id_invalid")
        try:
            aware_datetime(self.decision_time)
        except (AttributeError, TypeError, ValueError):
            errors.append("portfolio_target_decision_time_invalid")
        errors.extend(
            weight_errors(
                self.proposed_target_weights,
                prefix="proposed_target",
                maximum_gross=None,
                allow_short=True,
            )
        )
        errors.extend(
            weight_errors(
                self.target_weights,
                prefix="portfolio_target",
                allow_short=True,
            )
        )
        for strategy_id, weights in self.sleeve_contributions.items():
            if not strategy_id:
                errors.append("portfolio_target_sleeve_id_empty")
            errors.extend(
                weight_errors(
                    weights,
                    prefix=f"sleeve:{strategy_id}",
                    maximum_gross=None,
                    allow_short=True,
                )
            )
        if not self.sleeve_contributions:
            errors.append("portfolio_target_sleeve_contributions_empty")
        if not isinstance(self.allocatable, bool):
            errors.append("portfolio_target_allocatable_invalid")
        elif self.allocatable != (not self.blockers):
            errors.append("portfolio_target_allocatable_blocker_mismatch")
        if self.blockers:
            for weight in self.target_weights.values():
                try:
                    nonzero = abs(float(weight)) > 1e-12
                except (TypeError, ValueError):
                    nonzero = True
                if nonzero:
                    errors.append("portfolio_target_not_fail_closed")
                    break
        if not is_sha256(self.allocation_hash):
            errors.append("portfolio_target_allocation_hash_invalid")

        expected_hash = canonical_hash(self._core())
        if self.target_hash != expected_hash:
            errors.append("portfolio_target_hash_invalid")
        expected_id = trace_id(
            "portfolio_target",
            {
                "snapshot_id": self.snapshot_id,
                "decision_ids": sorted(self.decision_ids),
                "target_hash": expected_hash,
            },
        )
        if self.portfolio_target_id != expected_id:
            errors.append("portfolio_target_id_invalid")
        return tuple(errors)


@dataclass(frozen=True)
class RiskDecision:
    schema_version: int
    risk_decision_id: str
    batch_id: str
    portfolio_target_id: str
    decision_time: str
    approved: bool
    input_target: Mapping[str, float]
    approved_target: Mapping[str, float]
    adjustments: tuple[str, ...]
    violations: tuple[str, ...]
    risk_state_hash: str
    increase_risk_allowed: bool
    reduce_risk_allowed: bool
    decision_hash: str

    @classmethod
    def create(
        cls,
        *,
        batch_id: str,
        portfolio_target_id: str,
        decision_time: str,
        approved: bool,
        input_target: Mapping[str, float],
        approved_target: Mapping[str, float],
        adjustments: Sequence[str],
        violations: Sequence[str],
        risk_state_hash: str,
        increase_risk_allowed: bool,
        reduce_risk_allowed: bool,
    ) -> RiskDecision:
        core = {
            "schema_version": RUNTIME_CONTRACT_SCHEMA_VERSION,
            "batch_id": batch_id,
            "portfolio_target_id": portfolio_target_id,
            "decision_time": decision_time,
            "approved": approved,
            "input_target": dict(input_target),
            "approved_target": dict(approved_target),
            "adjustments": tuple(adjustments),
            "violations": tuple(violations),
            "risk_state_hash": risk_state_hash,
            "increase_risk_allowed": increase_risk_allowed,
            "reduce_risk_allowed": reduce_risk_allowed,
        }
        decision_hash = canonical_hash(core)
        decision = cls(
            **core,
            risk_decision_id=trace_id(
                "risk_decision",
                {
                    "batch_id": batch_id,
                    "decision_hash": decision_hash,
                },
            ),
            decision_hash=decision_hash,
        )
        errors = decision.validate()
        if errors:
            raise ValueError(f"risk_decision_invalid:{','.join(errors)}")
        return decision

    def _core(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "batch_id": self.batch_id,
            "portfolio_target_id": self.portfolio_target_id,
            "decision_time": self.decision_time,
            "approved": self.approved,
            "input_target": dict(self.input_target),
            "approved_target": dict(self.approved_target),
            "adjustments": tuple(self.adjustments),
            "violations": tuple(self.violations),
            "risk_state_hash": self.risk_state_hash,
            "increase_risk_allowed": self.increase_risk_allowed,
            "reduce_risk_allowed": self.reduce_risk_allowed,
        }

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.schema_version != RUNTIME_CONTRACT_SCHEMA_VERSION:
            errors.append("risk_decision_schema_version_invalid")
        for name in ("batch_id", "portfolio_target_id", "risk_state_hash"):
            if not is_sha256(getattr(self, name)):
                errors.append(f"risk_decision_{name}_invalid")
        try:
            aware_datetime(self.decision_time)
        except (AttributeError, TypeError, ValueError):
            errors.append("risk_decision_time_invalid")
        errors.extend(
            weight_errors(
                self.input_target,
                prefix="risk_input_target",
                allow_short=True,
            )
        )
        errors.extend(
            weight_errors(
                self.approved_target,
                prefix="risk_approved_target",
                allow_short=True,
            )
        )
        if self.approved and self.violations:
            errors.append("risk_approved_with_violations")
        for name in (
            "approved",
            "increase_risk_allowed",
            "reduce_risk_allowed",
        ):
            if not isinstance(getattr(self, name), bool):
                errors.append(f"risk_{name}_invalid")
        if len(self.adjustments) != len(set(self.adjustments)):
            errors.append("risk_adjustments_duplicate")
        if len(self.violations) != len(set(self.violations)):
            errors.append("risk_violations_duplicate")
        if any(not value for value in (*self.adjustments, *self.violations)):
            errors.append("risk_reason_empty")
        if self.increase_risk_allowed and (not self.approved or self.violations):
            errors.append("risk_increase_not_fail_closed")
        expected_hash = canonical_hash(self._core())
        if self.decision_hash != expected_hash:
            errors.append("risk_decision_hash_invalid")
        expected_id = trace_id(
            "risk_decision",
            {
                "batch_id": self.batch_id,
                "decision_hash": expected_hash,
            },
        )
        if self.risk_decision_id != expected_id:
            errors.append("risk_decision_id_invalid")
        return tuple(errors)


@dataclass(frozen=True)
class PlannedOrder:
    client_order_id: str
    symbol: str
    side: str
    quantity: float | None
    reduce_only: bool
    phase: str
    sequence: int
    decision_ids: tuple[str, ...]
    order_type: str = "market"
    close_position: bool = False
    limit_price: float | None = None
    stop_price: float | None = None

    @classmethod
    def create(
        cls,
        *,
        batch_id: str,
        decision_ids: Sequence[str],
        symbol: str,
        side: str,
        quantity: float | None,
        reduce_only: bool,
        phase: str,
        sequence: int,
        order_type: str = "market",
        close_position: bool = False,
        limit_price: float | None = None,
        stop_price: float | None = None,
    ) -> PlannedOrder:
        if not is_sha256(batch_id):
            raise ValueError("planned_order_invalid:planned_order_batch_id_invalid")
        normalized_decision_ids = tuple(decision_ids)
        order = cls(
            client_order_id=planned_client_order_id(
                batch_id=batch_id,
                decision_ids=normalized_decision_ids,
                symbol=symbol,
                phase=phase,
                sequence=sequence,
            ),
            symbol=symbol,
            side=side,
            quantity=quantity,
            reduce_only=reduce_only,
            phase=phase,
            sequence=sequence,
            decision_ids=normalized_decision_ids,
            order_type=order_type,
            close_position=close_position,
            limit_price=limit_price,
            stop_price=stop_price,
        )
        errors = order.validate()
        if errors:
            raise ValueError(f"planned_order_invalid:{','.join(errors)}")
        return order

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not _CLIENT_ORDER_ID_RE.fullmatch(self.client_order_id):
            errors.append("planned_order_client_id_invalid")
        if not self.symbol:
            errors.append("planned_order_symbol_empty")
        if self.side not in {"buy", "sell"}:
            errors.append("planned_order_side_invalid")
        if self.phase not in {"reduce", "increase", "protective"}:
            errors.append("planned_order_phase_invalid")
        if not self.order_type:
            errors.append("planned_order_type_empty")
        if not isinstance(self.sequence, int) or self.sequence < 1:
            errors.append("planned_order_sequence_invalid")
        if not self.decision_ids or any(
            not is_sha256(value) for value in self.decision_ids
        ):
            errors.append("planned_order_decision_ids_invalid")
        if len(self.decision_ids) != len(set(self.decision_ids)):
            errors.append("planned_order_decision_ids_duplicate")
        if self.close_position:
            if self.quantity is not None:
                errors.append("planned_order_close_position_quantity_present")
        else:
            try:
                quantity = float(self.quantity)
            except (TypeError, ValueError):
                quantity = math.nan
            if not math.isfinite(quantity) or quantity <= 0.0:
                errors.append("planned_order_quantity_invalid")
        if self.phase == "reduce" and not self.reduce_only:
            errors.append("planned_order_reduction_not_reduce_only")
        if self.phase == "increase" and self.reduce_only:
            errors.append("planned_order_increase_reduce_only")
        if self.phase == "protective" and not (self.reduce_only or self.close_position):
            errors.append("planned_order_protection_not_reduce_only")
        for name in ("limit_price", "stop_price"):
            value = getattr(self, name)
            if value is not None:
                try:
                    price = float(value)
                except (TypeError, ValueError):
                    price = math.nan
                if not math.isfinite(price) or price <= 0.0:
                    errors.append(f"planned_order_{name}_invalid")
        return tuple(errors)

    def as_dict(self) -> dict[str, Any]:
        return {
            "client_order_id": self.client_order_id,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "reduce_only": self.reduce_only,
            "phase": self.phase,
            "sequence": self.sequence,
            "decision_ids": tuple(self.decision_ids),
            "order_type": self.order_type,
            "close_position": self.close_position,
            "limit_price": self.limit_price,
            "stop_price": self.stop_price,
        }


@dataclass(frozen=True)
class PlannedCancellation:
    cancellation_id: str
    symbol: str
    target_exchange_order_id: str | None
    target_client_order_id: str | None
    decision_ids: tuple[str, ...]
    sequence: int
    reason: str

    @classmethod
    def create(
        cls,
        *,
        batch_id: str,
        decision_ids: Sequence[str],
        symbol: str,
        target_exchange_order_id: str | None,
        target_client_order_id: str | None,
        sequence: int,
        reason: str,
    ) -> PlannedCancellation:
        if not is_sha256(batch_id):
            raise ValueError(
                "planned_cancellation_invalid:planned_cancellation_batch_id_invalid"
            )
        normalized_decision_ids = tuple(decision_ids)
        normalized_exchange_id = (
            str(target_exchange_order_id) if target_exchange_order_id else None
        )
        normalized_client_id = (
            str(target_client_order_id) if target_client_order_id else None
        )
        cancellation = cls(
            cancellation_id=planned_cancellation_id(
                batch_id=batch_id,
                decision_ids=normalized_decision_ids,
                symbol=symbol,
                target_exchange_order_id=normalized_exchange_id,
                target_client_order_id=normalized_client_id,
                sequence=sequence,
            ),
            symbol=symbol,
            target_exchange_order_id=normalized_exchange_id,
            target_client_order_id=normalized_client_id,
            decision_ids=normalized_decision_ids,
            sequence=sequence,
            reason=reason,
        )
        errors = cancellation.validate()
        if errors:
            raise ValueError(f"planned_cancellation_invalid:{','.join(errors)}")
        return cancellation

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not is_sha256(self.cancellation_id):
            errors.append("planned_cancellation_id_invalid")
        if not self.symbol:
            errors.append("planned_cancellation_symbol_empty")
        if not self.target_exchange_order_id and not self.target_client_order_id:
            errors.append("planned_cancellation_target_missing")
        if not self.decision_ids or any(
            not is_sha256(value) for value in self.decision_ids
        ):
            errors.append("planned_cancellation_decision_ids_invalid")
        if len(self.decision_ids) != len(set(self.decision_ids)):
            errors.append("planned_cancellation_decision_ids_duplicate")
        if not isinstance(self.sequence, int) or self.sequence < 1:
            errors.append("planned_cancellation_sequence_invalid")
        if not self.reason:
            errors.append("planned_cancellation_reason_empty")
        return tuple(errors)

    def as_dict(self) -> dict[str, Any]:
        return {
            "cancellation_id": self.cancellation_id,
            "symbol": self.symbol,
            "target_exchange_order_id": self.target_exchange_order_id,
            "target_client_order_id": self.target_client_order_id,
            "decision_ids": tuple(self.decision_ids),
            "sequence": self.sequence,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class OrderPlan:
    schema_version: int
    order_plan_id: str
    batch_id: str
    risk_decision_id: str
    portfolio_target_id: str
    snapshot_id: str
    decision_ids: tuple[str, ...]
    created_at: str
    current_position_hash: str
    approved_target: Mapping[str, float]
    orders: tuple[PlannedOrder, ...]
    cancellations: tuple[PlannedCancellation, ...]
    retained_order_ids: tuple[str, ...]
    expected_positions: Mapping[str, float]
    reconciliation_tolerance: Mapping[str, float]
    blockers: tuple[str, ...]
    executable: bool
    plan_hash: str

    @classmethod
    def create(
        cls,
        *,
        batch_id: str,
        risk_decision_id: str,
        portfolio_target_id: str,
        snapshot_id: str,
        decision_ids: Sequence[str],
        created_at: str,
        current_position_hash: str,
        approved_target: Mapping[str, float],
        orders: Sequence[PlannedOrder],
        blockers: Sequence[str],
        executable: bool,
        cancellations: Sequence[PlannedCancellation] = (),
        retained_order_ids: Sequence[str] = (),
        expected_positions: Mapping[str, float] | None = None,
        reconciliation_tolerance: Mapping[str, float] | None = None,
    ) -> OrderPlan:
        normalized_decision_ids = tuple(decision_ids)
        normalized_orders = tuple(orders)
        normalized_cancellations = tuple(cancellations)
        normalized_retained_order_ids = tuple(retained_order_ids)
        normalized_blockers = tuple(blockers)
        core = {
            "schema_version": RUNTIME_CONTRACT_SCHEMA_VERSION,
            "batch_id": batch_id,
            "risk_decision_id": risk_decision_id,
            "portfolio_target_id": portfolio_target_id,
            "snapshot_id": snapshot_id,
            "decision_ids": normalized_decision_ids,
            "created_at": created_at,
            "current_position_hash": current_position_hash,
            "approved_target": dict(approved_target),
            "orders": normalized_orders,
            "cancellations": normalized_cancellations,
            "retained_order_ids": normalized_retained_order_ids,
            "expected_positions": dict(expected_positions or {}),
            "reconciliation_tolerance": dict(reconciliation_tolerance or {}),
            "blockers": normalized_blockers,
            "executable": executable,
        }
        hash_core = core | {
            "orders": [order.as_dict() for order in normalized_orders],
            "cancellations": [
                cancellation.as_dict()
                for cancellation in normalized_cancellations
            ],
        }
        plan_hash = canonical_hash(hash_core)
        plan = cls(
            **core,
            order_plan_id=trace_id(
                "order_plan",
                {
                    "batch_id": batch_id,
                    "plan_hash": plan_hash,
                },
            ),
            plan_hash=plan_hash,
        )
        errors = plan.validate()
        if errors:
            raise ValueError(f"order_plan_invalid:{','.join(errors)}")
        return plan

    def _hash_core(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "batch_id": self.batch_id,
            "risk_decision_id": self.risk_decision_id,
            "portfolio_target_id": self.portfolio_target_id,
            "snapshot_id": self.snapshot_id,
            "decision_ids": tuple(self.decision_ids),
            "created_at": self.created_at,
            "current_position_hash": self.current_position_hash,
            "approved_target": dict(self.approved_target),
            "orders": [order.as_dict() for order in self.orders],
            "cancellations": [
                cancellation.as_dict() for cancellation in self.cancellations
            ],
            "retained_order_ids": tuple(self.retained_order_ids),
            "expected_positions": dict(self.expected_positions),
            "reconciliation_tolerance": dict(self.reconciliation_tolerance),
            "blockers": tuple(self.blockers),
            "executable": self.executable,
        }

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.schema_version != RUNTIME_CONTRACT_SCHEMA_VERSION:
            errors.append("order_plan_schema_version_invalid")
        for name in (
            "batch_id",
            "risk_decision_id",
            "portfolio_target_id",
            "snapshot_id",
            "current_position_hash",
        ):
            if not is_sha256(getattr(self, name)):
                errors.append(f"order_plan_{name}_invalid")
        if not self.decision_ids or any(
            not is_sha256(value) for value in self.decision_ids
        ):
            errors.append("order_plan_decision_ids_invalid")
        if len(self.decision_ids) != len(set(self.decision_ids)):
            errors.append("order_plan_decision_ids_duplicate")
        try:
            aware_datetime(self.created_at)
        except (AttributeError, TypeError, ValueError):
            errors.append("order_plan_created_at_invalid")
        errors.extend(
            weight_errors(
                self.approved_target,
                prefix="order_plan_target",
                allow_short=True,
            )
        )
        client_ids = [order.client_order_id for order in self.orders]
        if len(client_ids) != len(set(client_ids)):
            errors.append("order_plan_client_order_id_duplicate")
        sequences = [order.sequence for order in self.orders]
        sequences.extend(
            cancellation.sequence for cancellation in self.cancellations
        )
        if len(sequences) != len(set(sequences)):
            errors.append("order_plan_sequence_duplicate")
        phase_order = {"reduce": 0, "increase": 1, "protective": 2}
        phases = [phase_order.get(order.phase, 99) for order in self.orders]
        if phases != sorted(phases):
            errors.append("order_plan_reduction_increase_order_invalid")
        for index, order in enumerate(self.orders):
            errors.extend(f"order:{index}:{error}" for error in order.validate())
            if not set(order.decision_ids).issubset(self.decision_ids):
                errors.append(f"order:{index}:decision_ids_not_in_plan")
            expected_client_id = planned_client_order_id(
                batch_id=self.batch_id,
                decision_ids=order.decision_ids,
                symbol=order.symbol,
                phase=order.phase,
                sequence=order.sequence,
            )
            if order.client_order_id != expected_client_id:
                errors.append(f"order:{index}:client_order_id_not_deterministic")
        for index, cancellation in enumerate(self.cancellations):
            errors.extend(
                f"cancellation:{index}:{error}"
                for error in cancellation.validate()
            )
            if not set(cancellation.decision_ids).issubset(self.decision_ids):
                errors.append(f"cancellation:{index}:decision_ids_not_in_plan")
            expected_cancellation_id = planned_cancellation_id(
                batch_id=self.batch_id,
                decision_ids=cancellation.decision_ids,
                symbol=cancellation.symbol,
                target_exchange_order_id=cancellation.target_exchange_order_id,
                target_client_order_id=cancellation.target_client_order_id,
                sequence=cancellation.sequence,
            )
            if cancellation.cancellation_id != expected_cancellation_id:
                errors.append(f"cancellation:{index}:id_not_deterministic")
        action_order = [
            (order.sequence, {"reduce": 0, "increase": 1, "protective": 3}.get(order.phase, 99))
            for order in self.orders
        ]
        action_order.extend(
            (cancellation.sequence, 2) for cancellation in self.cancellations
        )
        ordered_phases = [phase for _, phase in sorted(action_order)]
        if ordered_phases != sorted(ordered_phases):
            errors.append("order_plan_global_action_order_invalid")
        if len(self.retained_order_ids) != len(set(self.retained_order_ids)):
            errors.append("order_plan_retained_order_ids_duplicate")
        if any(not value for value in self.retained_order_ids):
            errors.append("order_plan_retained_order_id_empty")
        for name, values in (
            ("expected_position", self.expected_positions),
            ("reconciliation_tolerance", self.reconciliation_tolerance),
        ):
            for symbol, raw_value in values.items():
                try:
                    value = float(raw_value)
                except (TypeError, ValueError):
                    value = math.nan
                if (
                    not symbol
                    or not math.isfinite(value)
                    or (name == "reconciliation_tolerance" and value < 0.0)
                ):
                    errors.append(f"order_plan_{name}_invalid:{symbol}")
        if not isinstance(self.executable, bool):
            errors.append("order_plan_executable_invalid")
        if self.blockers and self.executable:
            errors.append("order_plan_executable_with_blockers")
        expected_hash = canonical_hash(self._hash_core())
        if self.plan_hash != expected_hash:
            errors.append("order_plan_hash_invalid")
        expected_id = trace_id(
            "order_plan",
            {
                "batch_id": self.batch_id,
                "plan_hash": expected_hash,
            },
        )
        if self.order_plan_id != expected_id:
            errors.append("order_plan_id_invalid")
        return tuple(errors)
