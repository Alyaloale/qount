"""Frozen, transaction-consistent runtime ledger snapshots for reporting."""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Any, Mapping

from qount.contracts import canonical_hash
from qount.contracts import is_sha256
from qount.contracts import trace_id
from qount.contracts.trace import aware_datetime
from qount.execution.state_machine import RECOVERABLE_ORDER_STATUSES
from qount.execution.state_machine import OrderRecoveryReport
from qount.ledger.audit import audit_journal_lock
from qount.ledger.audit import verify_audit_journal
from qount.ledger.reconciliation import ThreeWayReconciliation
from qount.ledger.store import AccountObservation
from qount.ledger.store import NavMark
from qount.ledger.store import RuntimeLedger
from qount.ledger.store import RuntimeLedgerError
from qount.ledger.store import _json_object
from qount.ledger.store import _validate_verified_batch
from qount.persistence import VerifiedDecisionBatch


RUNTIME_LEDGER_SNAPSHOT_SCHEMA_VERSION = 3

_ORDER_STATUSES = {
    "PLANNED",
    "SUBMITTING",
    "ACKNOWLEDGED",
    "PARTIALLY_FILLED",
    "FILLED",
    "REJECTED",
    "CANCELED",
    "EXPIRED",
    "UNKNOWN",
}
_POSITION_FIELDS = {
    "symbol",
    "quantity",
    "average_cost",
    "realized_trading_pnl",
    "updated_at",
    "source_hash",
    "position_hash",
}
_ORDER_FIELDS = {
    "client_order_id",
    "batch_id",
    "symbol",
    "side",
    "planned_quantity",
    "reduce_only",
    "phase",
    "sequence",
    "order_type",
    "close_position",
    "limit_price",
    "stop_price",
    "plan_spec_hash",
    "status",
    "exchange_order_id",
    "executed_quantity",
    "average_price",
    "last_transition_at",
    "last_observation_hash",
    "latest_reason",
}
_ORDER_EVENT_FIELDS = {
    "event_id",
    "client_order_id",
    "from_status",
    "to_status",
    "event_at",
    "exchange_order_id",
    "executed_quantity",
    "average_price",
    "source_hash",
    "reason",
    "transition_hash",
}
_FILL_FIELDS = {
    "fill_id",
    "client_order_id",
    "exchange_trade_id",
    "quantity",
    "price",
    "fee",
    "fee_asset",
    "occurred_at",
    "source_hash",
    "fill_hash",
}
_CASH_EVENT_FIELDS = {
    "cash_event_id",
    "event_key",
    "event_type",
    "amount",
    "asset",
    "symbol",
    "occurred_at",
    "source_hash",
    "event_hash",
}
_RECOVERY_FIELDS = {
    "recovery_id",
    "started_at",
    "completed_at",
    "attempted_client_order_ids",
    "resolved_client_order_ids",
    "unresolved_client_order_ids",
    "errors",
    "risk_increase_allowed",
    "halt_required",
    "report_hash",
}
_ACCOUNT_OBSERVATION_FIELDS = set(AccountObservation.__dataclass_fields__)
_ACCOUNT_FIELDS = _ACCOUNT_OBSERVATION_FIELDS | {
    "actual_gross_fraction",
    "margin_fraction",
    "peak_equity",
    "current_drawdown_fraction",
    "peak_drawdown_fraction",
    "peak_drawdown_at",
}


class RuntimeLedgerSnapshotError(RuntimeLedgerError):
    """Raised when a reporting snapshot cannot be proven authoritative."""


def _utc_time(value: str, *, name: str) -> str:
    try:
        parsed = aware_datetime(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise RuntimeLedgerSnapshotError(f"{name}_invalid") from exc
    return parsed.astimezone(dt.timezone.utc).isoformat()


def _finite(value: object, *, name: str, minimum: float | None = None) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeLedgerSnapshotError(f"{name}_invalid") from exc
    if not math.isfinite(number) or (
        minimum is not None and number < minimum
    ):
        raise RuntimeLedgerSnapshotError(f"{name}_invalid")
    return number


def _exact_fields(
    value: Mapping[str, Any], expected: set[str], *, name: str
) -> None:
    if set(value) != expected:
        raise RuntimeLedgerSnapshotError(f"{name}_fields_invalid")


def _optional_finite(
    value: object, *, name: str, minimum: float | None = None
) -> float | None:
    if value is None:
        return None
    return _finite(value, name=name, minimum=minimum)


def _nonempty_text(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeLedgerSnapshotError(f"{name}_invalid")
    return value


def _validate_position_fact(value: Mapping[str, Any]) -> None:
    _exact_fields(value, _POSITION_FIELDS, name="runtime_snapshot_position_fact")
    symbol = _nonempty_text(value["symbol"], name="runtime_snapshot_position_symbol")
    quantity = _finite(
        value["quantity"], name=f"runtime_snapshot_position_quantity:{symbol}"
    )
    average_cost = _finite(
        value["average_cost"],
        name=f"runtime_snapshot_position_average_cost:{symbol}",
        minimum=0.0,
    )
    _finite(
        value["realized_trading_pnl"],
        name=f"runtime_snapshot_position_realized_pnl:{symbol}",
    )
    if (abs(quantity) > 0.0 and average_cost <= 0.0) or (
        quantity == 0.0 and average_cost != 0.0
    ):
        raise RuntimeLedgerSnapshotError("runtime_snapshot_position_cost_invalid")
    _utc_time(str(value["updated_at"]), name="runtime_snapshot_position_time")
    for field in ("source_hash", "position_hash"):
        if not is_sha256(value[field]):
            raise RuntimeLedgerSnapshotError(
                f"runtime_snapshot_position_{field}_invalid"
            )
    core = {field: value[field] for field in _POSITION_FIELDS - {"position_hash"}}
    if value["position_hash"] != canonical_hash(core):
        raise RuntimeLedgerSnapshotError("runtime_snapshot_position_hash_invalid")


def _validate_order_fact(value: Mapping[str, Any]) -> None:
    _exact_fields(value, _ORDER_FIELDS, name="runtime_snapshot_order")
    client_order_id = _nonempty_text(
        value["client_order_id"], name="runtime_snapshot_order_id"
    )
    for field in ("batch_id", "plan_spec_hash", "last_observation_hash"):
        if not is_sha256(value[field]):
            raise RuntimeLedgerSnapshotError(f"runtime_snapshot_order_{field}_invalid")
    _nonempty_text(value["symbol"], name="runtime_snapshot_order_symbol")
    if value["side"] not in {"buy", "sell"}:
        raise RuntimeLedgerSnapshotError("runtime_snapshot_order_side_invalid")
    if value["phase"] not in {"reduce", "increase", "protective"}:
        raise RuntimeLedgerSnapshotError("runtime_snapshot_order_phase_invalid")
    if value["status"] not in _ORDER_STATUSES:
        raise RuntimeLedgerSnapshotError("runtime_snapshot_order_status_invalid")
    for field in ("reduce_only", "close_position"):
        if not isinstance(value[field], bool):
            raise RuntimeLedgerSnapshotError(
                f"runtime_snapshot_order_{field}_invalid"
            )
    if (
        not isinstance(value["sequence"], int)
        or isinstance(value["sequence"], bool)
        or value["sequence"] < 0
    ):
        raise RuntimeLedgerSnapshotError("runtime_snapshot_order_sequence_invalid")
    _nonempty_text(value["order_type"], name="runtime_snapshot_order_type")
    planned = _optional_finite(
        value["planned_quantity"],
        name="runtime_snapshot_order_planned_quantity",
        minimum=0.0,
    )
    if planned is not None and planned <= 0.0:
        raise RuntimeLedgerSnapshotError("runtime_snapshot_order_planned_quantity_invalid")
    executed = _finite(
        value["executed_quantity"],
        name="runtime_snapshot_order_executed_quantity",
        minimum=0.0,
    )
    if planned is not None and executed > planned + 1e-12:
        raise RuntimeLedgerSnapshotError("runtime_snapshot_order_executed_quantity_invalid")
    if value["status"] == "FILLED" and (
        planned is None or abs(executed - planned) > 1e-12
    ):
        raise RuntimeLedgerSnapshotError("runtime_snapshot_order_fill_state_invalid")
    if value["status"] == "PARTIALLY_FILLED" and (
        executed <= 0.0 or (planned is not None and executed >= planned - 1e-12)
    ):
        raise RuntimeLedgerSnapshotError("runtime_snapshot_order_partial_state_invalid")
    for field in ("limit_price", "stop_price", "average_price"):
        number = _optional_finite(
            value[field], name=f"runtime_snapshot_order_{field}", minimum=0.0
        )
        if number is not None and number <= 0.0:
            raise RuntimeLedgerSnapshotError(f"runtime_snapshot_order_{field}_invalid")
    for field in ("exchange_order_id", "latest_reason"):
        if value[field] is not None:
            _nonempty_text(value[field], name=f"runtime_snapshot_order_{field}")
    _utc_time(
        str(value["last_transition_at"]), name="runtime_snapshot_order_transition_time"
    )
    if not client_order_id:
        raise RuntimeLedgerSnapshotError("runtime_snapshot_order_id_invalid")


def _validate_order_event(value: Mapping[str, Any]) -> None:
    _exact_fields(value, _ORDER_EVENT_FIELDS, name="runtime_snapshot_order_event")
    for field in ("event_id", "source_hash", "transition_hash"):
        if not is_sha256(value[field]):
            raise RuntimeLedgerSnapshotError(
                f"runtime_snapshot_order_event_{field}_invalid"
            )
    _nonempty_text(value["client_order_id"], name="runtime_snapshot_order_event_order")
    if value["from_status"] not in _ORDER_STATUSES or value["to_status"] not in _ORDER_STATUSES:
        raise RuntimeLedgerSnapshotError("runtime_snapshot_order_event_status_invalid")
    _utc_time(str(value["event_at"]), name="runtime_snapshot_order_event_time")
    _finite(
        value["executed_quantity"],
        name="runtime_snapshot_order_event_quantity",
        minimum=0.0,
    )
    _optional_finite(
        value["average_price"],
        name="runtime_snapshot_order_event_average_price",
        minimum=0.0,
    )
    for field in ("exchange_order_id", "reason"):
        if value[field] is not None:
            _nonempty_text(value[field], name=f"runtime_snapshot_order_event_{field}")
    core = {
        field: value[field]
        for field in _ORDER_EVENT_FIELDS - {"event_id", "transition_hash"}
    }
    expected_hash = canonical_hash(core)
    if value["transition_hash"] != expected_hash or value["event_id"] != trace_id(
        "order_event", {"transition_hash": expected_hash}
    ):
        raise RuntimeLedgerSnapshotError("runtime_snapshot_order_event_hash_invalid")


def _validate_fill(value: Mapping[str, Any]) -> None:
    _exact_fields(value, _FILL_FIELDS, name="runtime_snapshot_fill")
    for field in ("fill_id", "source_hash", "fill_hash"):
        if not is_sha256(value[field]):
            raise RuntimeLedgerSnapshotError(f"runtime_snapshot_fill_{field}_invalid")
    client_order_id = _nonempty_text(
        value["client_order_id"], name="runtime_snapshot_fill_order"
    )
    exchange_trade_id = _nonempty_text(
        value["exchange_trade_id"], name="runtime_snapshot_fill_trade"
    )
    _nonempty_text(value["fee_asset"], name="runtime_snapshot_fill_fee_asset")
    for field in ("quantity", "price"):
        if _finite(value[field], name=f"runtime_snapshot_fill_{field}", minimum=0.0) <= 0.0:
            raise RuntimeLedgerSnapshotError(f"runtime_snapshot_fill_{field}_invalid")
    _finite(value["fee"], name="runtime_snapshot_fill_fee", minimum=0.0)
    _utc_time(str(value["occurred_at"]), name="runtime_snapshot_fill_time")
    core = {field: value[field] for field in _FILL_FIELDS - {"fill_id", "fill_hash"}}
    if value["fill_hash"] != canonical_hash(core) or value["fill_id"] != trace_id(
        "fill",
        {
            "client_order_id": client_order_id,
            "exchange_trade_id": exchange_trade_id,
        },
    ):
        raise RuntimeLedgerSnapshotError("runtime_snapshot_fill_hash_invalid")


def _validate_cash_event(value: Mapping[str, Any]) -> None:
    _exact_fields(value, _CASH_EVENT_FIELDS, name="runtime_snapshot_cash_event")
    for field in ("cash_event_id", "source_hash", "event_hash"):
        if not is_sha256(value[field]):
            raise RuntimeLedgerSnapshotError(
                f"runtime_snapshot_cash_event_{field}_invalid"
            )
    event_key = _nonempty_text(
        value["event_key"], name="runtime_snapshot_cash_event_key"
    )
    if value["event_type"] not in {"funding", "fee", "transfer", "adjustment"}:
        raise RuntimeLedgerSnapshotError("runtime_snapshot_cash_event_type_invalid")
    amount = _finite(value["amount"], name="runtime_snapshot_cash_event_amount")
    if value["event_type"] == "fee" and amount < 0.0:
        raise RuntimeLedgerSnapshotError("runtime_snapshot_cash_event_fee_invalid")
    _nonempty_text(value["asset"], name="runtime_snapshot_cash_event_asset")
    if value["symbol"] is not None:
        _nonempty_text(value["symbol"], name="runtime_snapshot_cash_event_symbol")
    _utc_time(str(value["occurred_at"]), name="runtime_snapshot_cash_event_time")
    core = {field: value[field] for field in _CASH_EVENT_FIELDS - {"event_hash"}}
    if value["event_hash"] != canonical_hash(core) or value["cash_event_id"] != trace_id(
        "cash_event", {"event_key": event_key}
    ):
        raise RuntimeLedgerSnapshotError("runtime_snapshot_cash_event_hash_invalid")


def _recovery_from_mapping(value: Mapping[str, Any]) -> OrderRecoveryReport:
    _exact_fields(value, _RECOVERY_FIELDS, name="runtime_snapshot_recovery")
    try:
        report = OrderRecoveryReport(
            recovery_id=str(value["recovery_id"]),
            started_at=str(value["started_at"]),
            completed_at=str(value["completed_at"]),
            attempted_client_order_ids=tuple(value["attempted_client_order_ids"]),
            resolved_client_order_ids=tuple(value["resolved_client_order_ids"]),
            unresolved_client_order_ids=tuple(value["unresolved_client_order_ids"]),
            errors=dict(value["errors"]),
            risk_increase_allowed=value["risk_increase_allowed"],
            halt_required=value["halt_required"],
            report_hash=str(value["report_hash"]),
        )
        report.validate()
    except (AttributeError, TypeError, ValueError) as exc:
        raise RuntimeLedgerSnapshotError("runtime_snapshot_recovery_invalid") from exc
    return report


def _nav_mark_from_mapping(value: Mapping[str, Any]) -> NavMark:
    expected = set(NavMark.__dataclass_fields__)
    if set(value) != expected:
        raise RuntimeLedgerSnapshotError("runtime_snapshot_nav_fields_invalid")
    try:
        mark = NavMark(
            nav_mark_id=str(value["nav_mark_id"]),
            marked_at=str(value["marked_at"]),
            previous_equity=_finite(value["previous_equity"], name="nav_previous_equity", minimum=0.0),
            equity=_finite(value["equity"], name="nav_equity", minimum=0.0),
            equity_change=_finite(value["equity_change"], name="nav_equity_change"),
            trading_pnl=_finite(value["trading_pnl"], name="nav_trading_pnl"),
            funding=_finite(value["funding"], name="nav_funding"),
            fees=_finite(value["fees"], name="nav_fees", minimum=0.0),
            transfers=_finite(value["transfers"], name="nav_transfers"),
            residual=_finite(value["residual"], name="nav_residual"),
            residual_tolerance=_finite(
                value["residual_tolerance"],
                name="nav_residual_tolerance",
                minimum=0.0,
            ),
            passed=value["passed"],
            trading_pnl_cumulative=_finite(
                value["trading_pnl_cumulative"],
                name="nav_trading_pnl_cumulative",
            ),
            funding_cumulative=_finite(
                value["funding_cumulative"], name="nav_funding_cumulative"
            ),
            fees_cumulative=_finite(
                value["fees_cumulative"], name="nav_fees_cumulative", minimum=0.0
            ),
            transfers_cumulative=_finite(
                value["transfers_cumulative"], name="nav_transfers_cumulative"
            ),
            signal_nav=(
                None
                if value["signal_nav"] is None
                else _finite(value["signal_nav"], name="nav_signal_nav", minimum=0.0)
            ),
            standalone_executable_nav=(
                None
                if value["standalone_executable_nav"] is None
                else _finite(
                    value["standalone_executable_nav"],
                    name="nav_standalone_executable_nav",
                    minimum=0.0,
                )
            ),
            source_hash=str(value["source_hash"]),
            mark_hash=str(value["mark_hash"]),
        )
    except KeyError as exc:
        raise RuntimeLedgerSnapshotError("runtime_snapshot_nav_fields_invalid") from exc
    if not isinstance(mark.passed, bool):
        raise RuntimeLedgerSnapshotError("runtime_snapshot_nav_passed_invalid")
    if not is_sha256(mark.source_hash) or not is_sha256(mark.mark_hash):
        raise RuntimeLedgerSnapshotError("runtime_snapshot_nav_hash_invalid")
    _utc_time(mark.marked_at, name="runtime_snapshot_nav_time")
    core = {
        name: getattr(mark, name)
        for name in NavMark.__dataclass_fields__
        if name not in {"nav_mark_id", "mark_hash"}
    }
    expected_hash = canonical_hash(core)
    if mark.mark_hash != expected_hash:
        raise RuntimeLedgerSnapshotError("runtime_snapshot_nav_mark_hash_invalid")
    if mark.nav_mark_id != trace_id(
        "nav_mark", {"marked_at": mark.marked_at, "mark_hash": expected_hash}
    ):
        raise RuntimeLedgerSnapshotError("runtime_snapshot_nav_mark_id_invalid")
    return mark


def _account_observation_from_mapping(
    value: Mapping[str, Any],
) -> AccountObservation:
    fields = set(value)
    if fields != _ACCOUNT_OBSERVATION_FIELDS and fields != _ACCOUNT_FIELDS:
        raise RuntimeLedgerSnapshotError("runtime_snapshot_account_fields_invalid")
    try:
        observation = AccountObservation(
            account_observation_id=str(value["account_observation_id"]),
            batch_id=str(value["batch_id"]),
            observed_at=str(value["observed_at"]),
            quote_asset=str(value["quote_asset"]),
            wallet_balance=_finite(
                value["wallet_balance"], name="account_wallet_balance", minimum=0.0
            ),
            available_balance=_finite(
                value["available_balance"],
                name="account_available_balance",
                minimum=0.0,
            ),
            actual_gross_notional=_finite(
                value["actual_gross_notional"],
                name="account_actual_gross_notional",
                minimum=0.0,
            ),
            margin_used=_finite(
                value["margin_used"], name="account_margin_used", minimum=0.0
            ),
            source_id=str(value["source_id"]),
            source_hash=str(value["source_hash"]),
            observation_hash=str(value["observation_hash"]),
        )
    except KeyError as exc:
        raise RuntimeLedgerSnapshotError(
            "runtime_snapshot_account_fields_invalid"
        ) from exc
    if not observation.quote_asset or not observation.quote_asset.isalnum():
        raise RuntimeLedgerSnapshotError("runtime_snapshot_account_asset_invalid")
    _utc_time(observation.observed_at, name="runtime_snapshot_account_time")
    for name in (
        "account_observation_id",
        "batch_id",
        "source_id",
        "source_hash",
        "observation_hash",
    ):
        if not is_sha256(getattr(observation, name)):
            raise RuntimeLedgerSnapshotError(
                f"runtime_snapshot_account_{name}_invalid"
            )
    core = {
        name: getattr(observation, name)
        for name in AccountObservation.__dataclass_fields__
        if name not in {"account_observation_id", "observation_hash"}
    }
    expected_hash = canonical_hash(core)
    if observation.observation_hash != expected_hash:
        raise RuntimeLedgerSnapshotError("runtime_snapshot_account_hash_invalid")
    expected_id = trace_id(
        "account_observation",
        {
            "observed_at": observation.observed_at,
            "observation_hash": expected_hash,
        },
    )
    if observation.account_observation_id != expected_id:
        raise RuntimeLedgerSnapshotError("runtime_snapshot_account_id_invalid")
    return observation


def _drawdown_facts(
    marks: tuple[NavMark, ...],
) -> dict[str, float | str]:
    if not marks:
        raise RuntimeLedgerSnapshotError("runtime_snapshot_nav_history_empty")
    peak_equity = marks[0].previous_equity
    peak_drawdown = 0.0
    peak_drawdown_at = marks[0].marked_at
    current_drawdown = 0.0
    for mark in marks:
        peak_equity = max(peak_equity, mark.equity)
        if peak_equity == 0.0:
            if mark.equity != 0.0:
                raise RuntimeLedgerSnapshotError(
                    "runtime_snapshot_drawdown_equity_invalid"
                )
            current_drawdown = 0.0
        else:
            current_drawdown = (peak_equity - mark.equity) / peak_equity
        if current_drawdown > peak_drawdown:
            peak_drawdown = current_drawdown
            peak_drawdown_at = mark.marked_at
    return {
        "peak_equity": peak_equity,
        "current_drawdown_fraction": current_drawdown,
        "peak_drawdown_fraction": peak_drawdown,
        "peak_drawdown_at": peak_drawdown_at,
    }


def _fraction(numerator: float, denominator: float, *, name: str) -> float:
    if denominator == 0.0:
        if numerator != 0.0:
            raise RuntimeLedgerSnapshotError(f"runtime_snapshot_{name}_undefined")
        return 0.0
    return numerator / denominator


def _same_number(left: object, right: object) -> bool:
    return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=1e-12)


def _reconciliation_from_mapping(
    value: Mapping[str, Any],
) -> ThreeWayReconciliation:
    expected = set(ThreeWayReconciliation.__dataclass_fields__)
    if set(value) != expected:
        raise RuntimeLedgerSnapshotError(
            "runtime_snapshot_reconciliation_fields_invalid"
        )
    try:
        report = ThreeWayReconciliation(
            reconciliation_id=str(value["reconciliation_id"]),
            batch_id=str(value["batch_id"]),
            reconciled_at=str(value["reconciled_at"]),
            phase=str(value["phase"]),
            target_positions=dict(value["target_positions"]),
            ledger_positions=dict(value["ledger_positions"]),
            exchange_positions=dict(value["exchange_positions"]),
            position_tolerances=dict(value["position_tolerances"]),
            position_differences={
                str(symbol): dict(differences)
                for symbol, differences in value["position_differences"].items()
            },
            ledger_open_order_ids=tuple(value["ledger_open_order_ids"]),
            exchange_open_order_ids=tuple(value["exchange_open_order_ids"]),
            missing_exchange_order_ids=tuple(value["missing_exchange_order_ids"]),
            unmanaged_exchange_order_ids=tuple(value["unmanaged_exchange_order_ids"]),
            equity_residual=_finite(
                value["equity_residual"], name="reconciliation_equity_residual"
            ),
            equity_residual_tolerance=_finite(
                value["equity_residual_tolerance"],
                name="reconciliation_equity_residual_tolerance",
                minimum=0.0,
            ),
            passed=value["passed"],
            risk_increase_allowed=value["risk_increase_allowed"],
            halt_required=value["halt_required"],
            blockers=tuple(value["blockers"]),
            report_hash=str(value["report_hash"]),
        )
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise RuntimeLedgerSnapshotError(
            "runtime_snapshot_reconciliation_invalid"
        ) from exc
    try:
        report.validate()
    except ValueError as exc:
        raise RuntimeLedgerSnapshotError(
            "runtime_snapshot_reconciliation_invalid"
        ) from exc
    return report


@dataclass(frozen=True)
class RuntimeLedgerSnapshot:
    schema_version: int
    batch_id: str
    manifest_hash: str
    order_plan_id: str
    plan_hash: str
    captured_at: str
    source_updated_at: str
    positions: Mapping[str, float]
    position_details: tuple[Mapping[str, Any], ...]
    orders: tuple[Mapping[str, Any], ...]
    order_events: tuple[Mapping[str, Any], ...]
    fills: tuple[Mapping[str, Any], ...]
    cash_events: tuple[Mapping[str, Any], ...]
    recoveries: tuple[Mapping[str, Any], ...]
    open_order_ids: tuple[str, ...]
    unresolved_order_ids: tuple[str, ...]
    account: Mapping[str, Any]
    nav_history: tuple[Mapping[str, Any], ...]
    nav: Mapping[str, Any]
    reconciliation: Mapping[str, Any]
    audit_last_hash: str
    audit_row_count: int
    snapshot_hash: str

    def _core(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "batch_id": self.batch_id,
            "manifest_hash": self.manifest_hash,
            "order_plan_id": self.order_plan_id,
            "plan_hash": self.plan_hash,
            "captured_at": self.captured_at,
            "source_updated_at": self.source_updated_at,
            "positions": dict(self.positions),
            "position_details": tuple(dict(row) for row in self.position_details),
            "orders": tuple(dict(row) for row in self.orders),
            "order_events": tuple(dict(row) for row in self.order_events),
            "fills": tuple(dict(row) for row in self.fills),
            "cash_events": tuple(dict(row) for row in self.cash_events),
            "recoveries": tuple(dict(row) for row in self.recoveries),
            "open_order_ids": self.open_order_ids,
            "unresolved_order_ids": self.unresolved_order_ids,
            "account": dict(self.account),
            "nav_history": tuple(dict(row) for row in self.nav_history),
            "nav": dict(self.nav),
            "reconciliation": dict(self.reconciliation),
            "audit_last_hash": self.audit_last_hash,
            "audit_row_count": self.audit_row_count,
        }

    def validate(self) -> None:
        if self.schema_version != RUNTIME_LEDGER_SNAPSHOT_SCHEMA_VERSION:
            raise RuntimeLedgerSnapshotError("runtime_snapshot_schema_invalid")
        for name in (
            "batch_id",
            "manifest_hash",
            "order_plan_id",
            "plan_hash",
            "audit_last_hash",
            "snapshot_hash",
        ):
            if not is_sha256(getattr(self, name)):
                raise RuntimeLedgerSnapshotError(f"runtime_snapshot_{name}_invalid")
        captured = aware_datetime(
            _utc_time(self.captured_at, name="runtime_snapshot_captured_at")
        )
        source_updated = aware_datetime(
            _utc_time(
                self.source_updated_at,
                name="runtime_snapshot_source_updated_at",
            )
        )
        if source_updated > captured:
            raise RuntimeLedgerSnapshotError(
                "runtime_snapshot_source_updated_after_capture"
            )
        if (
            not isinstance(self.audit_row_count, int)
            or isinstance(self.audit_row_count, bool)
            or self.audit_row_count < 1
        ):
            raise RuntimeLedgerSnapshotError("runtime_snapshot_audit_row_count_invalid")
        positions: dict[str, float] = {}
        for symbol, raw in self.positions.items():
            if not isinstance(symbol, str) or not symbol:
                raise RuntimeLedgerSnapshotError("runtime_snapshot_position_symbol_invalid")
            positions[symbol] = _finite(
                raw, name=f"runtime_snapshot_position:{symbol}"
            )
        if list(self.positions) != sorted(self.positions):
            raise RuntimeLedgerSnapshotError("runtime_snapshot_positions_order_invalid")
        if not isinstance(self.position_details, tuple):
            raise RuntimeLedgerSnapshotError(
                "runtime_snapshot_position_details_invalid"
            )
        position_symbols: list[str] = []
        for row in self.position_details:
            _validate_position_fact(row)
            position_symbols.append(str(row["symbol"]))
        if (
            position_symbols != sorted(position_symbols)
            or len(position_symbols) != len(set(position_symbols))
            or positions
            != {
                str(row["symbol"]): float(row["quantity"])
                for row in self.position_details
            }
        ):
            raise RuntimeLedgerSnapshotError(
                "runtime_snapshot_position_details_mismatch"
            )
        if not isinstance(self.orders, tuple):
            raise RuntimeLedgerSnapshotError("runtime_snapshot_orders_invalid")
        order_ids: list[str] = []
        orders_by_id: dict[str, Mapping[str, Any]] = {}
        for row in self.orders:
            _validate_order_fact(row)
            order_id = str(row["client_order_id"])
            order_ids.append(order_id)
            orders_by_id[order_id] = row
        if order_ids != sorted(order_ids) or len(order_ids) != len(set(order_ids)):
            raise RuntimeLedgerSnapshotError(
                "runtime_snapshot_order_identity_or_order_invalid"
            )
        if not isinstance(self.order_events, tuple):
            raise RuntimeLedgerSnapshotError("runtime_snapshot_order_events_invalid")
        event_keys: list[tuple[str, str]] = []
        latest_event_by_order: dict[str, Mapping[str, Any]] = {}
        for row in self.order_events:
            _validate_order_event(row)
            order_id = str(row["client_order_id"])
            if order_id not in orders_by_id:
                raise RuntimeLedgerSnapshotError(
                    "runtime_snapshot_order_event_order_missing"
                )
            event_keys.append((str(row["event_at"]), str(row["event_id"])))
            latest_event_by_order[order_id] = row
        if event_keys != sorted(event_keys) or len(event_keys) != len(set(event_keys)):
            raise RuntimeLedgerSnapshotError(
                "runtime_snapshot_order_event_order_invalid"
            )
        for order_id, event in latest_event_by_order.items():
            order = orders_by_id[order_id]
            if (
                event["to_status"] != order["status"]
                or event["event_at"] != order["last_transition_at"]
                or event["source_hash"] != order["last_observation_hash"]
                or event["reason"] != order["latest_reason"]
                or float(event["executed_quantity"])
                != float(order["executed_quantity"])
            ):
                raise RuntimeLedgerSnapshotError(
                    "runtime_snapshot_order_latest_event_mismatch"
                )
        if not isinstance(self.fills, tuple):
            raise RuntimeLedgerSnapshotError("runtime_snapshot_fills_invalid")
        fill_keys: list[tuple[str, str]] = []
        fill_ids: set[str] = set()
        fill_quantity_by_order: dict[str, float] = {}
        for row in self.fills:
            _validate_fill(row)
            order_id = str(row["client_order_id"])
            if order_id not in orders_by_id:
                raise RuntimeLedgerSnapshotError("runtime_snapshot_fill_order_missing")
            fill_id = str(row["fill_id"])
            fill_keys.append((str(row["occurred_at"]), fill_id))
            fill_ids.add(fill_id)
            fill_quantity_by_order[order_id] = fill_quantity_by_order.get(
                order_id, 0.0
            ) + float(row["quantity"])
        if fill_keys != sorted(fill_keys) or len(fill_ids) != len(self.fills):
            raise RuntimeLedgerSnapshotError("runtime_snapshot_fill_order_invalid")
        if any(
            quantity > float(orders_by_id[order_id]["executed_quantity"]) + 1e-12
            for order_id, quantity in fill_quantity_by_order.items()
        ):
            raise RuntimeLedgerSnapshotError(
                "runtime_snapshot_fill_quantity_exceeds_order"
            )
        if not isinstance(self.cash_events, tuple):
            raise RuntimeLedgerSnapshotError("runtime_snapshot_cash_events_invalid")
        cash_keys: list[tuple[str, str]] = []
        for row in self.cash_events:
            _validate_cash_event(row)
            cash_keys.append((str(row["occurred_at"]), str(row["cash_event_id"])))
        if cash_keys != sorted(cash_keys) or len(cash_keys) != len(set(cash_keys)):
            raise RuntimeLedgerSnapshotError(
                "runtime_snapshot_cash_event_order_invalid"
            )
        if not isinstance(self.recoveries, tuple):
            raise RuntimeLedgerSnapshotError("runtime_snapshot_recoveries_invalid")
        recovery_keys: list[tuple[str, str]] = []
        for row in self.recoveries:
            report = _recovery_from_mapping(row)
            if any(order_id not in orders_by_id for order_id in report.attempted_client_order_ids):
                raise RuntimeLedgerSnapshotError(
                    "runtime_snapshot_recovery_order_missing"
                )
            recovery_keys.append((report.completed_at, report.recovery_id))
        if recovery_keys != sorted(recovery_keys) or len(recovery_keys) != len(
            set(recovery_keys)
        ):
            raise RuntimeLedgerSnapshotError(
                "runtime_snapshot_recovery_order_invalid"
            )
        for name, values in (
            ("open_order_ids", self.open_order_ids),
            ("unresolved_order_ids", self.unresolved_order_ids),
        ):
            if (
                not isinstance(values, tuple)
                or any(not isinstance(value, str) or not value for value in values)
                or tuple(sorted(values)) != values
                or len(values) != len(set(values))
            ):
                raise RuntimeLedgerSnapshotError(f"runtime_snapshot_{name}_invalid")
        if not set(self.unresolved_order_ids).issubset(self.open_order_ids):
            raise RuntimeLedgerSnapshotError(
                "runtime_snapshot_unresolved_orders_not_open"
            )
        expected_open_ids = tuple(
            sorted(
                order_id
                for order_id, row in orders_by_id.items()
                if row["status"] in RECOVERABLE_ORDER_STATUSES
                or row["status"] == "ACKNOWLEDGED"
            )
        )
        expected_unresolved_ids = tuple(
            sorted(
                order_id
                for order_id, row in orders_by_id.items()
                if row["status"] in RECOVERABLE_ORDER_STATUSES
            )
        )
        if (
            self.open_order_ids != expected_open_ids
            or self.unresolved_order_ids != expected_unresolved_ids
        ):
            raise RuntimeLedgerSnapshotError(
                "runtime_snapshot_open_order_state_mismatch"
            )
        if not isinstance(self.nav_history, tuple) or not self.nav_history:
            raise RuntimeLedgerSnapshotError("runtime_snapshot_nav_history_invalid")
        nav_marks = tuple(_nav_mark_from_mapping(row) for row in self.nav_history)
        nav_keys = tuple((mark.marked_at, mark.nav_mark_id) for mark in nav_marks)
        if nav_keys != tuple(sorted(nav_keys)) or len(nav_keys) != len(set(nav_keys)):
            raise RuntimeLedgerSnapshotError(
                "runtime_snapshot_nav_history_order_invalid"
            )
        for previous, current in zip(nav_marks, nav_marks[1:]):
            if (
                not _same_number(current.previous_equity, previous.equity)
                or not _same_number(
                    current.trading_pnl_cumulative,
                    previous.trading_pnl_cumulative + current.trading_pnl,
                )
                or not _same_number(
                    current.funding_cumulative,
                    previous.funding_cumulative + current.funding,
                )
                or not _same_number(
                    current.fees_cumulative,
                    previous.fees_cumulative + current.fees,
                )
                or not _same_number(
                    current.transfers_cumulative,
                    previous.transfers_cumulative + current.transfers,
                )
            ):
                raise RuntimeLedgerSnapshotError(
                    "runtime_snapshot_nav_history_continuity_invalid"
                )
        nav = _nav_mark_from_mapping(self.nav)
        if dict(self.nav_history[-1]) != dict(self.nav):
            raise RuntimeLedgerSnapshotError("runtime_snapshot_nav_latest_mismatch")
        account = _account_observation_from_mapping(self.account)
        if account.batch_id != self.batch_id:
            raise RuntimeLedgerSnapshotError(
                "runtime_snapshot_account_batch_mismatch"
            )
        if account.observed_at != nav.marked_at:
            raise RuntimeLedgerSnapshotError(
                "runtime_snapshot_account_nav_time_mismatch"
            )
        if account.available_balance > account.wallet_balance + 1e-12:
            raise RuntimeLedgerSnapshotError(
                "runtime_snapshot_available_balance_exceeds_wallet"
            )
        expected_account_facts = {
            "actual_gross_fraction": _fraction(
                account.actual_gross_notional,
                nav.equity,
                name="actual_gross_fraction",
            ),
            "margin_fraction": _fraction(
                account.margin_used,
                nav.equity,
                name="margin_fraction",
            ),
            **_drawdown_facts(nav_marks),
        }
        for name in (
            "actual_gross_fraction",
            "margin_fraction",
            "peak_equity",
            "current_drawdown_fraction",
            "peak_drawdown_fraction",
        ):
            _finite(self.account[name], name=f"runtime_snapshot_account_{name}", minimum=0.0)
            if not _same_number(self.account[name], expected_account_facts[name]):
                raise RuntimeLedgerSnapshotError(
                    f"runtime_snapshot_account_{name}_mismatch"
                )
        if self.account["peak_drawdown_at"] != expected_account_facts[
            "peak_drawdown_at"
        ]:
            raise RuntimeLedgerSnapshotError(
                "runtime_snapshot_account_peak_drawdown_at_mismatch"
            )
        reconciliation = _reconciliation_from_mapping(self.reconciliation)
        if reconciliation.batch_id != self.batch_id:
            raise RuntimeLedgerSnapshotError(
                "runtime_snapshot_reconciliation_batch_mismatch"
            )
        if dict(reconciliation.ledger_positions) != positions:
            raise RuntimeLedgerSnapshotError(
                "runtime_snapshot_reconciliation_positions_mismatch"
            )
        if reconciliation.ledger_open_order_ids != self.open_order_ids:
            raise RuntimeLedgerSnapshotError(
                "runtime_snapshot_reconciliation_orders_mismatch"
            )
        if (
            reconciliation.equity_residual != nav.residual
            or reconciliation.equity_residual_tolerance != nav.residual_tolerance
        ):
            raise RuntimeLedgerSnapshotError(
                "runtime_snapshot_reconciliation_nav_mismatch"
            )
        if aware_datetime(nav.marked_at) > aware_datetime(
            reconciliation.reconciled_at
        ) or aware_datetime(reconciliation.reconciled_at) > captured:
            raise RuntimeLedgerSnapshotError(
                "runtime_snapshot_accounting_time_order_invalid"
            )
        if self.snapshot_hash != canonical_hash(self._core()):
            raise RuntimeLedgerSnapshotError("runtime_snapshot_hash_invalid")

    def as_dict(self) -> dict[str, Any]:
        return self._core() | {"snapshot_hash": self.snapshot_hash}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> RuntimeLedgerSnapshot:
        """Rehydrate a published snapshot and replay all integrity checks."""

        expected = set(cls.__dataclass_fields__)
        if not isinstance(value, Mapping) or set(value) != expected:
            raise RuntimeLedgerSnapshotError("runtime_snapshot_fields_invalid")
        try:
            snapshot = cls(
                schema_version=value["schema_version"],
                batch_id=value["batch_id"],
                manifest_hash=value["manifest_hash"],
                order_plan_id=value["order_plan_id"],
                plan_hash=value["plan_hash"],
                captured_at=value["captured_at"],
                source_updated_at=value["source_updated_at"],
                positions=dict(value["positions"]),
                position_details=tuple(
                    dict(row) for row in value["position_details"]
                ),
                orders=tuple(dict(row) for row in value["orders"]),
                order_events=tuple(dict(row) for row in value["order_events"]),
                fills=tuple(dict(row) for row in value["fills"]),
                cash_events=tuple(dict(row) for row in value["cash_events"]),
                recoveries=tuple(dict(row) for row in value["recoveries"]),
                open_order_ids=tuple(value["open_order_ids"]),
                unresolved_order_ids=tuple(value["unresolved_order_ids"]),
                account=dict(value["account"]),
                nav_history=tuple(dict(row) for row in value["nav_history"]),
                nav=dict(value["nav"]),
                reconciliation=dict(value["reconciliation"]),
                audit_last_hash=value["audit_last_hash"],
                audit_row_count=value["audit_row_count"],
                snapshot_hash=value["snapshot_hash"],
            )
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise RuntimeLedgerSnapshotError(
                "runtime_snapshot_fields_invalid"
            ) from exc
        snapshot.validate()
        return snapshot


def build_runtime_ledger_snapshot(
    ledger: RuntimeLedger,
    batch: VerifiedDecisionBatch,
    *,
    captured_at: str,
) -> RuntimeLedgerSnapshot:
    """Read one frozen reporting snapshot without exchange or order interfaces."""

    if not isinstance(ledger, RuntimeLedger):
        raise TypeError("runtime_snapshot_requires_runtime_ledger")
    _validate_verified_batch(batch)
    captured_at = _utc_time(captured_at, name="runtime_snapshot_captured_at")
    ledger.flush_audit_outbox()
    with audit_journal_lock(ledger.audit_path):
        with ledger._connection() as connection:
            connection.execute("BEGIN")
            try:
                integrity = tuple(
                    str(row[0])
                    for row in connection.execute("PRAGMA integrity_check")
                )
                foreign_keys = tuple(connection.execute("PRAGMA foreign_key_check"))
                if integrity != ("ok",):
                    raise RuntimeLedgerSnapshotError(
                        "runtime_snapshot_ledger_integrity_failed"
                    )
                if foreign_keys:
                    raise RuntimeLedgerSnapshotError(
                        "runtime_snapshot_foreign_key_check_failed"
                    )
                stored_batch = connection.execute(
                    "SELECT * FROM batches WHERE batch_id = ?",
                    (batch.manifest.batch_id,),
                ).fetchone()
                if stored_batch is None:
                    raise RuntimeLedgerSnapshotError(
                        "runtime_snapshot_batch_missing"
                    )
                latest_batch = connection.execute(
                    "SELECT batch_id FROM batches ORDER BY recorded_at DESC,rowid DESC LIMIT 1"
                ).fetchone()
                if latest_batch is None or latest_batch["batch_id"] != batch.manifest.batch_id:
                    raise RuntimeLedgerSnapshotError(
                        "runtime_snapshot_batch_not_latest"
                    )
                expected_batch_fields = {
                    "manifest_hash": batch.manifest.manifest_hash,
                    "snapshot_id": batch.snapshot.snapshot_id,
                    "portfolio_target_id": batch.target.portfolio_target_id,
                    "risk_decision_id": batch.risk.risk_decision_id,
                    "order_plan_id": batch.plan.order_plan_id,
                    "plan_hash": batch.plan.plan_hash,
                }
                if any(
                    stored_batch[name] != expected
                    for name, expected in expected_batch_fields.items()
                ):
                    raise RuntimeLedgerSnapshotError(
                        "runtime_snapshot_batch_identity_mismatch"
                    )
                position_rows = connection.execute(
                    "SELECT * FROM positions ORDER BY symbol"
                ).fetchall()
                position_details = tuple(
                    {
                        "symbol": str(row["symbol"]),
                        "quantity": float(row["quantity"]),
                        "average_cost": float(row["average_cost"]),
                        "realized_trading_pnl": float(
                            row["realized_trading_pnl"]
                        ),
                        "updated_at": str(row["updated_at"]),
                        "source_hash": str(row["source_hash"]),
                        "position_hash": str(row["position_hash"]),
                    }
                    for row in position_rows
                )
                positions = {
                    str(row["symbol"]): float(row["quantity"])
                    for row in position_details
                }
                order_rows = connection.execute(
                    "SELECT orders.*,(SELECT reason FROM order_events "
                    "WHERE order_events.client_order_id=orders.client_order_id "
                    "ORDER BY rowid DESC LIMIT 1) latest_reason "
                    "FROM orders ORDER BY client_order_id"
                ).fetchall()
                orders = tuple(
                    {
                        "client_order_id": str(row["client_order_id"]),
                        "batch_id": str(row["batch_id"]),
                        "symbol": str(row["symbol"]),
                        "side": str(row["side"]),
                        "planned_quantity": (
                            None
                            if row["planned_quantity"] is None
                            else float(row["planned_quantity"])
                        ),
                        "reduce_only": bool(row["reduce_only"]),
                        "phase": str(row["phase"]),
                        "sequence": int(row["sequence"]),
                        "order_type": str(row["order_type"]),
                        "close_position": bool(row["close_position"]),
                        "limit_price": (
                            None
                            if row["limit_price"] is None
                            else float(row["limit_price"])
                        ),
                        "stop_price": (
                            None
                            if row["stop_price"] is None
                            else float(row["stop_price"])
                        ),
                        "plan_spec_hash": str(row["plan_spec_hash"]),
                        "status": str(row["status"]),
                        "exchange_order_id": (
                            None
                            if row["exchange_order_id"] is None
                            else str(row["exchange_order_id"])
                        ),
                        "executed_quantity": float(row["executed_quantity"]),
                        "average_price": (
                            None
                            if row["average_price"] is None
                            else float(row["average_price"])
                        ),
                        "last_transition_at": str(row["last_transition_at"]),
                        "last_observation_hash": str(
                            row["last_observation_hash"]
                        ),
                        "latest_reason": (
                            None
                            if row["latest_reason"] is None
                            else str(row["latest_reason"])
                        ),
                    }
                    for row in order_rows
                )
                expected_current_orders = {
                    order.client_order_id: canonical_hash(order.as_dict())
                    for order in batch.plan.orders
                }
                observed_current_orders = {
                    str(row["client_order_id"]): str(row["plan_spec_hash"])
                    for row in orders
                    if row["batch_id"] == batch.manifest.batch_id
                }
                if observed_current_orders != expected_current_orders:
                    raise RuntimeLedgerSnapshotError(
                        "runtime_snapshot_current_batch_orders_mismatch"
                    )
                order_events = tuple(
                    {
                        "event_id": str(row["event_id"]),
                        "client_order_id": str(row["client_order_id"]),
                        "from_status": str(row["from_status"]),
                        "to_status": str(row["to_status"]),
                        "event_at": str(row["event_at"]),
                        "exchange_order_id": (
                            None
                            if row["exchange_order_id"] is None
                            else str(row["exchange_order_id"])
                        ),
                        "executed_quantity": float(row["executed_quantity"]),
                        "average_price": (
                            None
                            if row["average_price"] is None
                            else float(row["average_price"])
                        ),
                        "source_hash": str(row["source_hash"]),
                        "reason": (
                            None if row["reason"] is None else str(row["reason"])
                        ),
                        "transition_hash": str(row["transition_hash"]),
                    }
                    for row in connection.execute(
                        "SELECT * FROM order_events ORDER BY event_at,event_id"
                    )
                )
                fills = tuple(
                    {
                        "fill_id": str(row["fill_id"]),
                        "client_order_id": str(row["client_order_id"]),
                        "exchange_trade_id": str(row["exchange_trade_id"]),
                        "quantity": float(row["quantity"]),
                        "price": float(row["price"]),
                        "fee": float(row["fee"]),
                        "fee_asset": str(row["fee_asset"]),
                        "occurred_at": str(row["occurred_at"]),
                        "source_hash": str(row["source_hash"]),
                        "fill_hash": str(row["fill_hash"]),
                    }
                    for row in connection.execute(
                        "SELECT * FROM fills ORDER BY occurred_at,fill_id"
                    )
                )
                cash_events = tuple(
                    {
                        "cash_event_id": str(row["cash_event_id"]),
                        "event_key": str(row["event_key"]),
                        "event_type": str(row["event_type"]),
                        "amount": float(row["amount"]),
                        "asset": str(row["asset"]),
                        "symbol": (
                            None if row["symbol"] is None else str(row["symbol"])
                        ),
                        "occurred_at": str(row["occurred_at"]),
                        "source_hash": str(row["source_hash"]),
                        "event_hash": str(row["event_hash"]),
                    }
                    for row in connection.execute(
                        "SELECT * FROM cash_events ORDER BY occurred_at,cash_event_id"
                    )
                )
                recovery_rows = connection.execute(
                    "SELECT * FROM order_recoveries ORDER BY completed_at,recovery_id"
                ).fetchall()
                recovery_values: list[Mapping[str, Any]] = []
                for row in recovery_rows:
                    recovery = _json_object(
                        str(row["payload_json"]), name="runtime_snapshot_recovery"
                    )
                    report = _recovery_from_mapping(recovery)
                    if (
                        row["recovery_id"] != report.recovery_id
                        or row["report_hash"] != report.report_hash
                        or bool(row["risk_increase_allowed"])
                        is not report.risk_increase_allowed
                        or bool(row["halt_required"]) is not report.halt_required
                    ):
                        raise RuntimeLedgerSnapshotError(
                            "runtime_snapshot_recovery_row_mismatch"
                        )
                    recovery_values.append(recovery)
                recoveries = tuple(recovery_values)
                open_statuses = tuple(sorted((*RECOVERABLE_ORDER_STATUSES, "ACKNOWLEDGED")))
                placeholders = ",".join("?" for _ in open_statuses)
                open_order_ids = tuple(
                    str(row["client_order_id"])
                    for row in connection.execute(
                        f"SELECT client_order_id FROM orders WHERE status IN ({placeholders}) "
                        "ORDER BY client_order_id",
                        open_statuses,
                    )
                )
                recoverable_placeholders = ",".join(
                    "?" for _ in RECOVERABLE_ORDER_STATUSES
                )
                unresolved_order_ids = tuple(
                    str(row["client_order_id"])
                    for row in connection.execute(
                        f"SELECT client_order_id FROM orders WHERE status IN ({recoverable_placeholders}) "
                        "ORDER BY client_order_id",
                        tuple(sorted(RECOVERABLE_ORDER_STATUSES)),
                    )
                )
                nav_rows = connection.execute(
                    "SELECT * FROM nav_marks ORDER BY marked_at,nav_mark_id"
                ).fetchall()
                if not nav_rows:
                    raise RuntimeLedgerSnapshotError(
                        "runtime_snapshot_nav_mark_missing"
                    )
                nav_marks = tuple(
                    _nav_mark_from_mapping(ledger._nav_mark_from_row(row).as_dict())
                    for row in nav_rows
                )
                nav_history = tuple(mark.as_dict() for mark in nav_marks)
                nav = nav_marks[-1]
                account_row = connection.execute(
                    "SELECT * FROM account_observations "
                    "ORDER BY observed_at DESC,account_observation_id DESC LIMIT 1"
                ).fetchone()
                if account_row is None:
                    raise RuntimeLedgerSnapshotError(
                        "runtime_snapshot_account_observation_missing"
                    )
                account_observation = _account_observation_from_mapping(
                    ledger._account_observation_from_row(account_row).as_dict()
                )
                if account_observation.batch_id != batch.manifest.batch_id:
                    raise RuntimeLedgerSnapshotError(
                        "runtime_snapshot_account_batch_mismatch"
                    )
                if account_observation.observed_at != nav.marked_at:
                    raise RuntimeLedgerSnapshotError(
                        "runtime_snapshot_account_nav_time_mismatch"
                    )
                account = account_observation.as_dict() | {
                    "actual_gross_fraction": _fraction(
                        account_observation.actual_gross_notional,
                        nav.equity,
                        name="actual_gross_fraction",
                    ),
                    "margin_fraction": _fraction(
                        account_observation.margin_used,
                        nav.equity,
                        name="margin_fraction",
                    ),
                    **_drawdown_facts(nav_marks),
                }
                reconciliation_row = connection.execute(
                    "SELECT * FROM reconciliations ORDER BY rowid DESC LIMIT 1"
                ).fetchone()
                if reconciliation_row is None:
                    raise RuntimeLedgerSnapshotError(
                        "runtime_snapshot_reconciliation_missing"
                    )
                if reconciliation_row["batch_id"] != batch.manifest.batch_id:
                    raise RuntimeLedgerSnapshotError(
                        "runtime_snapshot_reconciliation_batch_mismatch"
                    )
                reconciliation = _json_object(
                    str(reconciliation_row["payload_json"]),
                    name="runtime_snapshot_reconciliation",
                )
                report = _reconciliation_from_mapping(reconciliation)
                if (
                    reconciliation_row["reconciliation_id"]
                    != report.reconciliation_id
                    or reconciliation_row["report_hash"] != report.report_hash
                    or bool(reconciliation_row["passed"]) is not report.passed
                    or bool(reconciliation_row["risk_increase_allowed"])
                    is not report.risk_increase_allowed
                    or bool(reconciliation_row["halt_required"])
                    is not report.halt_required
                ):
                    raise RuntimeLedgerSnapshotError(
                        "runtime_snapshot_reconciliation_row_mismatch"
                    )
                outbox = connection.execute(
                    "SELECT * FROM audit_outbox ORDER BY sequence"
                ).fetchall()
                if not outbox or any(row["published_at"] is None for row in outbox):
                    raise RuntimeLedgerSnapshotError(
                        "runtime_snapshot_audit_outbox_unpublished"
                    )
                audit_rows = tuple(
                    ledger._audit_row_from_outbox(row) for row in outbox
                )
                if (
                    audit_rows[-1]["event_type"] != "reconciliation_recorded"
                    or audit_rows[-1]["entity_id"] != report.reconciliation_id
                ):
                    raise RuntimeLedgerSnapshotError(
                        "runtime_snapshot_reconciliation_not_latest"
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        journal = verify_audit_journal(ledger.audit_path)
        if journal.row_count < len(audit_rows):
            raise RuntimeLedgerSnapshotError(
                "runtime_snapshot_audit_journal_incomplete"
            )
        for sequence, expected in enumerate(audit_rows, 1):
            if journal.rows_by_sequence.get(sequence) != expected:
                raise RuntimeLedgerSnapshotError(
                    f"runtime_snapshot_audit_journal_mismatch:{sequence}"
                )
    source_updated_at = str(audit_rows[-1]["occurred_at"])
    if aware_datetime(source_updated_at) > aware_datetime(captured_at):
        raise RuntimeLedgerSnapshotError(
            "runtime_snapshot_capture_before_source_update"
        )
    core = {
        "schema_version": RUNTIME_LEDGER_SNAPSHOT_SCHEMA_VERSION,
        "batch_id": batch.manifest.batch_id,
        "manifest_hash": batch.manifest.manifest_hash,
        "order_plan_id": batch.plan.order_plan_id,
        "plan_hash": batch.plan.plan_hash,
        "captured_at": captured_at,
        "source_updated_at": source_updated_at,
        "positions": positions,
        "position_details": position_details,
        "orders": orders,
        "order_events": order_events,
        "fills": fills,
        "cash_events": cash_events,
        "recoveries": recoveries,
        "open_order_ids": open_order_ids,
        "unresolved_order_ids": unresolved_order_ids,
        "account": account,
        "nav_history": nav_history,
        "nav": nav.as_dict(),
        "reconciliation": report.as_dict(),
        "audit_last_hash": str(audit_rows[-1]["row_hash"]),
        "audit_row_count": len(audit_rows),
    }
    snapshot = RuntimeLedgerSnapshot(
        **core,
        snapshot_hash=canonical_hash(core),
    )
    snapshot.validate()
    return snapshot
