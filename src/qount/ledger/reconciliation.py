"""Deterministic target, ledger, and exchange reconciliation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from qount.contracts import canonical_hash
from qount.contracts import trace_id
from qount.contracts.trace import aware_datetime
from qount.contracts.trace import is_sha256


@dataclass(frozen=True)
class ThreeWayReconciliation:
    reconciliation_id: str
    batch_id: str
    reconciled_at: str
    phase: str
    target_positions: Mapping[str, float]
    ledger_positions: Mapping[str, float]
    exchange_positions: Mapping[str, float]
    position_tolerances: Mapping[str, float]
    position_differences: Mapping[str, Mapping[str, float | bool]]
    ledger_open_order_ids: tuple[str, ...]
    exchange_open_order_ids: tuple[str, ...]
    missing_exchange_order_ids: tuple[str, ...]
    unmanaged_exchange_order_ids: tuple[str, ...]
    equity_residual: float
    equity_residual_tolerance: float
    passed: bool
    risk_increase_allowed: bool
    halt_required: bool
    blockers: tuple[str, ...]
    report_hash: str

    def _core(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "reconciled_at": self.reconciled_at,
            "phase": self.phase,
            "target_positions": dict(self.target_positions),
            "ledger_positions": dict(self.ledger_positions),
            "exchange_positions": dict(self.exchange_positions),
            "position_tolerances": dict(self.position_tolerances),
            "position_differences": {
                symbol: dict(values)
                for symbol, values in self.position_differences.items()
            },
            "ledger_open_order_ids": self.ledger_open_order_ids,
            "exchange_open_order_ids": self.exchange_open_order_ids,
            "missing_exchange_order_ids": self.missing_exchange_order_ids,
            "unmanaged_exchange_order_ids": self.unmanaged_exchange_order_ids,
            "equity_residual": self.equity_residual,
            "equity_residual_tolerance": self.equity_residual_tolerance,
            "passed": self.passed,
            "risk_increase_allowed": self.risk_increase_allowed,
            "halt_required": self.halt_required,
            "blockers": self.blockers,
        }

    def validate(self) -> None:
        if not is_sha256(self.batch_id):
            raise ValueError("reconciliation_batch_id_invalid")
        try:
            aware_datetime(self.reconciled_at)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("reconciliation_time_invalid") from exc
        if self.phase not in {"pre_dispatch", "post_dispatch"}:
            raise ValueError("reconciliation_phase_invalid")
        if len(self.blockers) != len(set(self.blockers)):
            raise ValueError("reconciliation_blockers_duplicate")
        expected_passed = not self.blockers
        if self.passed is not expected_passed:
            raise ValueError("reconciliation_passed_flag_invalid")
        if self.risk_increase_allowed is not expected_passed:
            raise ValueError("reconciliation_risk_flag_invalid")
        expected_halt = bool(
            self.missing_exchange_order_ids
            or self.unmanaged_exchange_order_ids
            or any(
                bool(values["ledger_exchange_mismatch"])
                for values in self.position_differences.values()
            )
            or abs(self.equity_residual) > self.equity_residual_tolerance
        )
        if self.halt_required is not expected_halt:
            raise ValueError("reconciliation_halt_flag_invalid")
        expected_hash = canonical_hash(self._core())
        if self.report_hash != expected_hash:
            raise ValueError("reconciliation_hash_invalid")
        expected_id = trace_id(
            "three_way_reconciliation",
            {"batch_id": self.batch_id, "report_hash": expected_hash},
        )
        if self.reconciliation_id != expected_id:
            raise ValueError("reconciliation_id_invalid")

    def as_dict(self) -> dict[str, Any]:
        return self._core() | {
            "reconciliation_id": self.reconciliation_id,
            "report_hash": self.report_hash,
        }


def _finite_map(values: Mapping[str, float], *, name: str) -> dict[str, float]:
    result: dict[str, float] = {}
    for symbol, raw in values.items():
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name}_value_invalid:{symbol}") from exc
        if not symbol or not math.isfinite(value):
            raise ValueError(f"{name}_value_invalid:{symbol}")
        result[str(symbol)] = value
    return result


def reconcile_three_way(
    *,
    batch_id: str,
    reconciled_at: str,
    target_positions: Mapping[str, float],
    ledger_positions: Mapping[str, float],
    exchange_positions: Mapping[str, float],
    position_tolerances: Mapping[str, float],
    ledger_open_order_ids: Sequence[str],
    exchange_open_order_ids: Sequence[str],
    equity_residual: float,
    equity_residual_tolerance: float,
    phase: str = "post_dispatch",
) -> ThreeWayReconciliation:
    if phase not in {"pre_dispatch", "post_dispatch"}:
        raise ValueError("reconciliation_phase_invalid")
    target = _finite_map(target_positions, name="target_positions")
    ledger = _finite_map(ledger_positions, name="ledger_positions")
    exchange = _finite_map(exchange_positions, name="exchange_positions")
    tolerances = _finite_map(position_tolerances, name="position_tolerances")
    if any(value < 0.0 for value in tolerances.values()):
        raise ValueError("position_tolerance_negative")
    try:
        residual = float(equity_residual)
        residual_tolerance = float(equity_residual_tolerance)
    except (TypeError, ValueError) as exc:
        raise ValueError("equity_residual_invalid") from exc
    if (
        not math.isfinite(residual)
        or not math.isfinite(residual_tolerance)
        or residual_tolerance < 0.0
    ):
        raise ValueError("equity_residual_invalid")
    symbols = sorted(set(target) | set(ledger) | set(exchange))
    differences: dict[str, dict[str, float | bool]] = {}
    blockers: list[str] = []
    for symbol in symbols:
        tolerance = tolerances.get(symbol)
        if tolerance is None:
            blockers.append(f"position_tolerance_missing:{symbol}")
            tolerance = 0.0
        target_ledger = ledger.get(symbol, 0.0) - target.get(symbol, 0.0)
        ledger_exchange = exchange.get(symbol, 0.0) - ledger.get(symbol, 0.0)
        target_mismatch = abs(target_ledger) > tolerance
        exchange_mismatch = abs(ledger_exchange) > tolerance
        differences[symbol] = {
            "target_ledger_difference": target_ledger,
            "ledger_exchange_difference": ledger_exchange,
            "tolerance": tolerance,
            "target_ledger_mismatch": target_mismatch,
            "ledger_exchange_mismatch": exchange_mismatch,
        }
        if target_mismatch:
            blockers.append(f"target_ledger_position_mismatch:{symbol}")
        if exchange_mismatch:
            blockers.append(f"ledger_exchange_position_mismatch:{symbol}")
    ledger_orders = tuple(sorted(str(value) for value in ledger_open_order_ids))
    exchange_orders = tuple(sorted(str(value) for value in exchange_open_order_ids))
    if len(ledger_orders) != len(set(ledger_orders)) or len(exchange_orders) != len(
        set(exchange_orders)
    ):
        raise ValueError("reconciliation_order_id_duplicate")
    missing_orders = tuple(sorted(set(ledger_orders) - set(exchange_orders)))
    unmanaged_orders = tuple(sorted(set(exchange_orders) - set(ledger_orders)))
    blockers.extend(f"ledger_order_missing_on_exchange:{value}" for value in missing_orders)
    blockers.extend(f"unmanaged_exchange_order:{value}" for value in unmanaged_orders)
    if abs(residual) > residual_tolerance:
        blockers.append("equity_residual_exceeds_tolerance")
    normalized_blockers = tuple(dict.fromkeys(blockers))
    core = {
        "batch_id": batch_id,
        "reconciled_at": reconciled_at,
        "phase": phase,
        "target_positions": target,
        "ledger_positions": ledger,
        "exchange_positions": exchange,
        "position_tolerances": tolerances,
        "position_differences": differences,
        "ledger_open_order_ids": ledger_orders,
        "exchange_open_order_ids": exchange_orders,
        "missing_exchange_order_ids": missing_orders,
        "unmanaged_exchange_order_ids": unmanaged_orders,
        "equity_residual": residual,
        "equity_residual_tolerance": residual_tolerance,
        "passed": not normalized_blockers,
        "risk_increase_allowed": not normalized_blockers,
        "halt_required": bool(
            missing_orders
            or unmanaged_orders
            or any(
                bool(values["ledger_exchange_mismatch"])
                for values in differences.values()
            )
            or abs(residual) > residual_tolerance
        ),
        "blockers": normalized_blockers,
    }
    report_hash = canonical_hash(core)
    report = ThreeWayReconciliation(
        **core,
        reconciliation_id=trace_id(
            "three_way_reconciliation",
            {"batch_id": batch_id, "report_hash": report_hash},
        ),
        report_hash=report_hash,
    )
    report.validate()
    return report
