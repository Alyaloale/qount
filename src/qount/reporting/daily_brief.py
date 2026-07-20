"""Deterministic daily brief built only from verified local authority surfaces."""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Any, Mapping

from qount.contracts import canonical_hash
from qount.contracts import trace_id
from qount.contracts import validate_decision_batch
from qount.contracts.trace import aware_datetime
from qount.contracts.trace import is_sha256
from qount.governance import StrategyRegistry
from qount.governance import validate_registered_intents
from qount.ledger import RuntimeLedgerSnapshot
from qount.notifications import ALERT_SEVERITIES
from qount.notifications import DELIVERY_STATES
from qount.notifications import NotificationSnapshot
from qount.persistence import VerifiedDecisionBatch
from qount.persistence import artifact_envelope


DAILY_BRIEF_SCHEMA_VERSION = 1
DAILY_BRIEF_STATUSES = ("clear", "attention_required", "halt_required")
_SOURCE_KEYS = {
    "decision_batch_manifest",
    "strategy_registry",
    "runtime_ledger",
    "notification_store",
}
_OWNER_ACTIONS = {
    "reconcile_before_any_recovery",
    "resolve_recoverable_order_states",
    "review_open_halt_alerts",
    "review_open_critical_alerts",
    "review_open_warning_alerts",
    "review_notification_dead_letters",
}


class DailyBriefError(ValueError):
    """Raised when deterministic report inputs or content are invalid."""


def _utc_time(value: str, *, name: str) -> str:
    try:
        parsed = aware_datetime(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise DailyBriefError(f"{name}_invalid") from exc
    return parsed.astimezone(dt.timezone.utc).isoformat()


def _finite(value: object, *, name: str, minimum: float | None = None) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DailyBriefError(f"{name}_invalid") from exc
    if not math.isfinite(number) or (
        minimum is not None and number < minimum
    ):
        raise DailyBriefError(f"{name}_invalid")
    return number


def _source_errors(
    batch: VerifiedDecisionBatch,
    registry: StrategyRegistry,
    ledger_snapshot: RuntimeLedgerSnapshot,
    notification_snapshot: NotificationSnapshot,
) -> tuple[str, ...]:
    errors: list[str] = []
    if not isinstance(batch, VerifiedDecisionBatch):
        return ("daily_brief_verified_decision_batch_required",)
    if not isinstance(registry, StrategyRegistry):
        return ("daily_brief_strategy_registry_required",)
    if not isinstance(ledger_snapshot, RuntimeLedgerSnapshot):
        return ("daily_brief_runtime_ledger_snapshot_required",)
    if not isinstance(notification_snapshot, NotificationSnapshot):
        return ("daily_brief_notification_snapshot_required",)

    errors.extend(f"manifest:{error}" for error in batch.manifest.validate())
    errors.extend(
        validate_decision_batch(
            batch.snapshot,
            batch.intents,
            batch.target,
            batch.risk,
            batch.plan,
        )
    )
    references = (
        (batch.manifest.market_snapshot, batch.snapshot),
        *zip(batch.manifest.strategy_intents, batch.intents, strict=False),
        (batch.manifest.portfolio_target, batch.target),
        (batch.manifest.risk_decision, batch.risk),
        (batch.manifest.order_plan, batch.plan),
    )
    if len(batch.manifest.strategy_intents) != len(batch.intents):
        errors.append("daily_brief_intent_reference_count_mismatch")
    for reference, value in references:
        try:
            envelope = artifact_envelope(value)
        except (TypeError, ValueError) as exc:
            errors.append(f"daily_brief_artifact_invalid:{type(exc).__name__}")
            continue
        if any(
            getattr(reference, name) != envelope[name]
            for name in ("artifact_type", "object_id", "payload_hash", "artifact_hash")
        ):
            errors.append(f"daily_brief_artifact_reference_mismatch:{reference.file_name}")

    errors.extend(f"registry:{error}" for error in registry.validate())
    errors.extend(
        validate_registered_intents(
            registry,
            batch.intents,
            environment="research",
        )
    )
    try:
        ledger_snapshot.validate()
    except ValueError as exc:
        errors.append(f"daily_brief_runtime_snapshot_invalid:{exc}")
    try:
        notification_snapshot.validate()
    except ValueError as exc:
        errors.append(f"daily_brief_notification_snapshot_invalid:{exc}")
    if (
        ledger_snapshot.batch_id != batch.manifest.batch_id
        or ledger_snapshot.manifest_hash != batch.manifest.manifest_hash
        or ledger_snapshot.order_plan_id != batch.plan.order_plan_id
        or ledger_snapshot.plan_hash != batch.plan.plan_hash
    ):
        errors.append("daily_brief_runtime_snapshot_batch_mismatch")
    try:
        if aware_datetime(registry.created_at) > aware_datetime(
            batch.manifest.created_at
        ):
            errors.append("daily_brief_registry_created_after_batch")
    except (AttributeError, TypeError, ValueError):
        pass
    return tuple(dict.fromkeys(errors))


def _status_and_gates(
    ledger_snapshot: RuntimeLedgerSnapshot,
    notification_snapshot: NotificationSnapshot,
) -> tuple[str, tuple[Mapping[str, str], ...], tuple[str, ...]]:
    open_counts = {
        severity: sum(
            1
            for alert in notification_snapshot.alerts
            if alert["status"] == "OPEN" and alert["severity"] == severity
        )
        for severity in ALERT_SEVERITIES
    }
    reconciliation_ok = bool(
        ledger_snapshot.reconciliation["passed"]
        and not ledger_snapshot.reconciliation["halt_required"]
        and ledger_snapshot.nav["passed"]
    )
    dead_letters = notification_snapshot.delivery_state_counts["DEAD_LETTER"]
    unresolved_orders = bool(ledger_snapshot.unresolved_order_ids)
    halt_required = bool(
        ledger_snapshot.reconciliation["halt_required"]
        or unresolved_orders
        or open_counts["HALT"]
    )
    attention_required = bool(
        not reconciliation_ok
        or open_counts["WARNING"]
        or open_counts["CRITICAL"]
        or dead_letters
    )
    status = (
        "halt_required"
        if halt_required
        else "attention_required"
        if attention_required
        else "clear"
    )
    alert_gate = (
        "block"
        if open_counts["HALT"] or open_counts["CRITICAL"]
        else "warn"
        if open_counts["WARNING"]
        else "pass"
    )
    gates = (
        {
            "gate": "runtime_ledger",
            "status": "pass",
            "detail": "snapshot_and_audit_chain_verified",
        },
        {
            "gate": "order_state_recovery",
            "status": "block" if unresolved_orders else "pass",
            "detail": (
                "recoverable_order_states_present"
                if unresolved_orders
                else "no_recoverable_order_states"
            ),
        },
        {
            "gate": "three_way_reconciliation",
            "status": "pass" if reconciliation_ok else "block",
            "detail": (
                "latest_three_way_reconciliation_passed"
                if reconciliation_ok
                else "latest_three_way_reconciliation_or_nav_failed"
            ),
        },
        {
            "gate": "notification_delivery",
            "status": "block" if dead_letters else "pass",
            "detail": (
                f"dead_letter_count:{dead_letters}"
                if dead_letters
                else "no_dead_letters"
            ),
        },
        {
            "gate": "unresolved_alerts",
            "status": alert_gate,
            "detail": (
                "open_severity_counts:"
                + ",".join(
                    f"{severity}={open_counts[severity]}"
                    for severity in ALERT_SEVERITIES
                )
            ),
        },
        {
            "gate": "live_orders_allowed",
            "status": "block",
            "detail": "daily_brief_never_authorizes_orders",
        },
    )
    actions: set[str] = set()
    if not reconciliation_ok:
        actions.add("reconcile_before_any_recovery")
    if unresolved_orders:
        actions.add("resolve_recoverable_order_states")
    if open_counts["HALT"]:
        actions.add("review_open_halt_alerts")
    if open_counts["CRITICAL"]:
        actions.add("review_open_critical_alerts")
    if open_counts["WARNING"]:
        actions.add("review_open_warning_alerts")
    if dead_letters:
        actions.add("review_notification_dead_letters")
    return status, gates, tuple(sorted(actions))


@dataclass(frozen=True)
class DailyBrief:
    schema_version: int
    brief_id: str
    report_date: str
    generated_at: str
    source_updated_at: str
    source_hashes: Mapping[str, str]
    status: str
    account: Mapping[str, Any]
    positions: tuple[Mapping[str, Any], ...]
    orders: Mapping[str, Any]
    pnl: Mapping[str, Any]
    strategies: tuple[Mapping[str, Any], ...]
    readiness: Mapping[str, Any]
    alerts: Mapping[str, Any]
    llm: Mapping[str, Any]
    owner_actions: tuple[str, ...]
    brief_hash: str

    def _core(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "report_date": self.report_date,
            "generated_at": self.generated_at,
            "source_updated_at": self.source_updated_at,
            "source_hashes": dict(self.source_hashes),
            "status": self.status,
            "account": dict(self.account),
            "positions": [dict(row) for row in self.positions],
            "orders": dict(self.orders),
            "pnl": dict(self.pnl),
            "strategies": [dict(row) for row in self.strategies],
            "readiness": dict(self.readiness),
            "alerts": dict(self.alerts),
            "llm": dict(self.llm),
            "owner_actions": list(self.owner_actions),
        }

    def validate(self) -> None:
        if self.schema_version != DAILY_BRIEF_SCHEMA_VERSION:
            raise DailyBriefError("daily_brief_schema_invalid")
        if not is_sha256(self.brief_id) or not is_sha256(self.brief_hash):
            raise DailyBriefError("daily_brief_identity_invalid")
        if set(self.source_hashes) != _SOURCE_KEYS or any(
            not is_sha256(value) for value in self.source_hashes.values()
        ):
            raise DailyBriefError("daily_brief_source_hashes_invalid")
        generated = aware_datetime(
            _utc_time(self.generated_at, name="daily_brief_generated_at")
        )
        source_updated = aware_datetime(
            _utc_time(
                self.source_updated_at,
                name="daily_brief_source_updated_at",
            )
        )
        if source_updated > generated:
            raise DailyBriefError("daily_brief_source_after_generation")
        try:
            report_date = dt.date.fromisoformat(self.report_date)
        except (TypeError, ValueError) as exc:
            raise DailyBriefError("daily_brief_report_date_invalid") from exc
        if report_date != source_updated.date():
            raise DailyBriefError("daily_brief_report_date_mismatch")
        if self.status not in DAILY_BRIEF_STATUSES:
            raise DailyBriefError("daily_brief_status_invalid")
        if (
            not isinstance(self.positions, tuple)
            or not isinstance(self.strategies, tuple)
            or not isinstance(self.owner_actions, tuple)
        ):
            raise DailyBriefError("daily_brief_sequence_type_invalid")
        symbols = [row.get("symbol") for row in self.positions]
        if symbols != sorted(symbols) or len(symbols) != len(set(symbols)):
            raise DailyBriefError("daily_brief_positions_order_invalid")
        strategy_ids = [row.get("strategy_id") for row in self.strategies]
        if strategy_ids != sorted(strategy_ids) or len(strategy_ids) != len(
            set(strategy_ids)
        ):
            raise DailyBriefError("daily_brief_strategies_order_invalid")
        if any(row.get("live_orders_allowed") is not False for row in self.strategies):
            raise DailyBriefError("daily_brief_strategy_order_authority_invalid")
        if tuple(sorted(self.owner_actions)) != self.owner_actions or not set(
            self.owner_actions
        ).issubset(_OWNER_ACTIONS):
            raise DailyBriefError("daily_brief_owner_actions_invalid")
        if dict(self.llm) != {
            "status": "not_requested_deterministic_only",
            "reports": [],
        }:
            raise DailyBriefError("daily_brief_llm_boundary_invalid")
        readiness = self.readiness
        if readiness.get("status") != self.status:
            raise DailyBriefError("daily_brief_readiness_status_mismatch")
        gates = readiness.get("gates")
        if not isinstance(gates, list) or not any(
            gate.get("gate") == "live_orders_allowed"
            and gate.get("status") == "block"
            for gate in gates
        ):
            raise DailyBriefError("daily_brief_live_gate_missing")
        expected_account_fields = {
            "equity",
            "previous_equity",
            "equity_change",
            "approved_target_gross",
            "actual_position_count",
            "accounting_passed",
            "account_observation_id",
            "observation_hash",
            "quote_asset",
            "wallet_balance",
            "available_balance",
            "actual_gross_notional",
            "actual_gross_fraction",
            "margin_used",
            "margin_fraction",
            "peak_equity",
            "current_drawdown_fraction",
            "peak_drawdown_fraction",
            "peak_drawdown_at",
            "unavailable_fields",
        }
        if set(self.account) != expected_account_fields:
            raise DailyBriefError("daily_brief_account_fields_invalid")
        for name in (
            "equity",
            "previous_equity",
            "equity_change",
            "approved_target_gross",
            "wallet_balance",
            "available_balance",
            "actual_gross_notional",
            "actual_gross_fraction",
            "margin_used",
            "margin_fraction",
            "peak_equity",
            "current_drawdown_fraction",
            "peak_drawdown_fraction",
        ):
            _finite(
                self.account.get(name),
                name=f"daily_brief_account_{name}",
                minimum=0.0 if name != "equity_change" else None,
            )
        if (
            not isinstance(self.account["actual_position_count"], int)
            or isinstance(self.account["actual_position_count"], bool)
            or self.account["actual_position_count"] < 0
            or not isinstance(self.account["accounting_passed"], bool)
            or not is_sha256(self.account["account_observation_id"])
            or not is_sha256(self.account["observation_hash"])
            or not isinstance(self.account["quote_asset"], str)
            or not self.account["quote_asset"]
            or self.account["unavailable_fields"] != []
        ):
            raise DailyBriefError("daily_brief_account_invalid")
        _utc_time(
            self.account["peak_drawdown_at"],
            name="daily_brief_account_peak_drawdown_at",
        )
        expected_pnl_fields = {
            "scope",
            "marked_at",
            "trading_pnl",
            "funding",
            "fees",
            "transfers",
            "residual",
            "residual_tolerance",
            "passed",
            "signal_nav",
            "standalone_executable_nav",
            "realized_equity",
            "peak_equity",
            "current_drawdown_fraction",
            "peak_drawdown_fraction",
            "peak_drawdown_at",
            "unavailable_fields",
        }
        if set(self.pnl) != expected_pnl_fields or self.pnl.get(
            "scope"
        ) != "latest_nav_mark" or self.pnl.get("unavailable_fields") != [
            "slippage"
        ]:
            raise DailyBriefError("daily_brief_pnl_fields_invalid")
        for name in (
            "trading_pnl",
            "funding",
            "fees",
            "transfers",
            "residual",
            "residual_tolerance",
            "realized_equity",
            "peak_equity",
            "current_drawdown_fraction",
            "peak_drawdown_fraction",
        ):
            _finite(
                self.pnl[name],
                name=f"daily_brief_pnl_{name}",
                minimum=(
                    0.0
                    if name
                    in {
                        "fees",
                        "residual_tolerance",
                        "realized_equity",
                        "peak_equity",
                        "current_drawdown_fraction",
                        "peak_drawdown_fraction",
                    }
                    else None
                ),
            )
        for name in ("marked_at", "peak_drawdown_at"):
            _utc_time(self.pnl[name], name=f"daily_brief_pnl_{name}")
        if not isinstance(self.pnl["passed"], bool):
            raise DailyBriefError("daily_brief_pnl_passed_invalid")
        orders = self.orders
        expected_order_fields = {
            "scope",
            "planned_order_count",
            "planned_cancellation_count",
            "runtime_order_count",
            "protective_order_count",
            "protective_order_runtime_statuses",
            "plan_executable",
            "open_order_ids",
            "unresolved_order_ids",
            "status_counts",
            "fill_count",
            "fill_quantity",
            "fill_notional",
            "fill_fees_by_asset",
            "latest_recovery_status",
            "unavailable_fields",
        }
        if set(orders) != expected_order_fields or orders.get(
            "scope"
        ) != "runtime_ledger_orders_and_fills":
            raise DailyBriefError("daily_brief_orders_fields_invalid")
        for name in (
            "planned_order_count",
            "planned_cancellation_count",
            "runtime_order_count",
            "protective_order_count",
            "fill_count",
        ):
            if (
                not isinstance(orders[name], int)
                or isinstance(orders[name], bool)
                or orders[name] < 0
            ):
                raise DailyBriefError(f"daily_brief_orders_{name}_invalid")
        for name in ("fill_quantity", "fill_notional"):
            _finite(
                orders[name], name=f"daily_brief_orders_{name}", minimum=0.0
            )
        if not isinstance(orders["plan_executable"], bool) or orders[
            "latest_recovery_status"
        ] not in {"none", "passed", "blocked"}:
            raise DailyBriefError("daily_brief_orders_state_invalid")
        for name in (
            "open_order_ids",
            "unresolved_order_ids",
            "unavailable_fields",
        ):
            values = orders[name]
            if (
                not isinstance(values, list)
                or any(not isinstance(value, str) or not value for value in values)
                or len(values) != len(set(values))
            ):
                raise DailyBriefError(f"daily_brief_orders_{name}_invalid")
        if orders["unavailable_fields"] != ["order_latency", "slippage"] or not set(
            orders["unresolved_order_ids"]
        ).issubset(orders["open_order_ids"]):
            raise DailyBriefError("daily_brief_orders_availability_invalid")
        for name in (
            "status_counts",
            "protective_order_runtime_statuses",
        ):
            counts = orders[name]
            if not isinstance(counts, Mapping) or any(
                not isinstance(key, str)
                or not key
                or not isinstance(count, int)
                or isinstance(count, bool)
                or count < 0
                for key, count in counts.items()
            ):
                raise DailyBriefError(f"daily_brief_orders_{name}_invalid")
        if sum(orders["status_counts"].values()) != orders["runtime_order_count"] or sum(
            orders["protective_order_runtime_statuses"].values()
        ) > orders["runtime_order_count"]:
            raise DailyBriefError("daily_brief_orders_counts_mismatch")
        fees = orders["fill_fees_by_asset"]
        if not isinstance(fees, Mapping) or any(
            not isinstance(asset, str)
            or not asset
            or _finite(
                amount,
                name=f"daily_brief_orders_fee:{asset}",
                minimum=0.0,
            )
            < 0.0
            for asset, amount in fees.items()
        ):
            raise DailyBriefError("daily_brief_orders_fees_invalid")
        expected_hash = canonical_hash(self._core())
        if self.brief_hash != expected_hash:
            raise DailyBriefError("daily_brief_hash_invalid")
        expected_id = trace_id(
            "daily_brief",
            {"report_date": self.report_date, "brief_hash": expected_hash},
        )
        if self.brief_id != expected_id:
            raise DailyBriefError("daily_brief_id_invalid")

    def as_dict(self) -> dict[str, Any]:
        return self._core() | {
            "brief_id": self.brief_id,
            "brief_hash": self.brief_hash,
        }


def build_daily_brief(
    batch: VerifiedDecisionBatch,
    registry: StrategyRegistry,
    ledger_snapshot: RuntimeLedgerSnapshot,
    notification_snapshot: NotificationSnapshot,
    *,
    generated_at: str,
) -> DailyBrief:
    """Create a deterministic report without querying SQLite, network, or LLMs."""

    errors = _source_errors(
        batch,
        registry,
        ledger_snapshot,
        notification_snapshot,
    )
    if errors:
        raise DailyBriefError(f"daily_brief_sources_invalid:{','.join(errors)}")
    generated_at = _utc_time(generated_at, name="daily_brief_generated_at")
    source_updated_at = max(
        _utc_time(batch.manifest.created_at, name="daily_brief_batch_time"),
        _utc_time(registry.created_at, name="daily_brief_registry_time"),
        _utc_time(
            ledger_snapshot.source_updated_at,
            name="daily_brief_ledger_time",
        ),
        _utc_time(
            notification_snapshot.source_updated_at,
            name="daily_brief_notification_time",
        ),
        key=aware_datetime,
    )
    if any(
        aware_datetime(value) > aware_datetime(generated_at)
        for value in (
            source_updated_at,
            ledger_snapshot.captured_at,
            notification_snapshot.captured_at,
        )
    ):
        raise DailyBriefError("daily_brief_generation_before_source")

    status, gates, owner_actions = _status_and_gates(
        ledger_snapshot,
        notification_snapshot,
    )
    approved_target = batch.risk.approved_target
    position_symbols = sorted(
        set(ledger_snapshot.positions)
        | set(batch.plan.expected_positions)
        | set(approved_target)
    )
    positions = tuple(
        {
            "symbol": symbol,
            "actual_quantity": float(ledger_snapshot.positions.get(symbol, 0.0)),
            "expected_quantity": float(batch.plan.expected_positions.get(symbol, 0.0)),
            "approved_target_weight": float(approved_target.get(symbol, 0.0)),
            "strategy_links": [
                {
                    "strategy_id": intent.strategy_id,
                    "decision_id": intent.decision_id,
                    "reason_codes": list(intent.reason_codes),
                }
                for intent in sorted(batch.intents, key=lambda row: row.strategy_id)
                if float(intent.target_weights.get(symbol, 0.0)) > 0.0
            ],
        }
        for symbol in position_symbols
    )
    nav = ledger_snapshot.nav
    strategies = tuple(
        {
            "strategy_id": entry.strategy_id,
            "strategy_version": entry.strategy_version,
            "promotion_status": entry.promotion_status,
            "maximum_gross": float(entry.maximum_gross),
            "maximum_stress_loss_fraction": float(
                entry.maximum_stress_loss_fraction
            ),
            "decision": (
                None
                if (intent := next(
                    (
                        row
                        for row in batch.intents
                        if row.strategy_id == entry.strategy_id
                    ),
                    None,
                ))
                is None
                else {
                    "decision_id": intent.decision_id,
                    "reason_codes": list(intent.reason_codes),
                    "target_weights": dict(intent.target_weights),
                }
            ),
            "live_orders_allowed": False,
        }
        for entry in sorted(registry.entries, key=lambda row: row.strategy_id)
    )
    open_alerts = tuple(
        alert for alert in notification_snapshot.alerts if alert["status"] == "OPEN"
    )
    open_severity_counts = {
        severity: sum(1 for alert in open_alerts if alert["severity"] == severity)
        for severity in ALERT_SEVERITIES
    }
    order_status_counts: dict[str, int] = {}
    protective_statuses: dict[str, int] = {}
    for order in ledger_snapshot.orders:
        order_status = str(order["status"])
        order_status_counts[order_status] = order_status_counts.get(order_status, 0) + 1
        if order["phase"] == "protective":
            protective_statuses[order_status] = protective_statuses.get(
                order_status, 0
            ) + 1
    fill_fees: dict[str, float] = {}
    for fill in ledger_snapshot.fills:
        asset = str(fill["fee_asset"])
        fill_fees[asset] = fill_fees.get(asset, 0.0) + float(fill["fee"])
    latest_recovery_status = (
        "none"
        if not ledger_snapshot.recoveries
        else "passed"
        if ledger_snapshot.recoveries[-1]["risk_increase_allowed"]
        else "blocked"
    )
    core = {
        "schema_version": DAILY_BRIEF_SCHEMA_VERSION,
        "report_date": aware_datetime(source_updated_at).date().isoformat(),
        "generated_at": generated_at,
        "source_updated_at": source_updated_at,
        "source_hashes": {
            "decision_batch_manifest": batch.manifest.manifest_hash,
            "strategy_registry": registry.registry_hash,
            "runtime_ledger": ledger_snapshot.snapshot_hash,
            "notification_store": notification_snapshot.snapshot_hash,
        },
        "status": status,
        "account": {
            "equity": float(nav["equity"]),
            "previous_equity": float(nav["previous_equity"]),
            "equity_change": float(nav["equity_change"]),
            "approved_target_gross": round(
                sum(float(value) for value in approved_target.values()), 12
            ),
            "actual_position_count": sum(
                1 for value in ledger_snapshot.positions.values() if float(value) > 0.0
            ),
            "accounting_passed": bool(nav["passed"]),
            "account_observation_id": ledger_snapshot.account[
                "account_observation_id"
            ],
            "observation_hash": ledger_snapshot.account["observation_hash"],
            "quote_asset": ledger_snapshot.account["quote_asset"],
            "wallet_balance": float(ledger_snapshot.account["wallet_balance"]),
            "available_balance": float(
                ledger_snapshot.account["available_balance"]
            ),
            "actual_gross_notional": float(
                ledger_snapshot.account["actual_gross_notional"]
            ),
            "actual_gross_fraction": float(
                ledger_snapshot.account["actual_gross_fraction"]
            ),
            "margin_used": float(ledger_snapshot.account["margin_used"]),
            "margin_fraction": float(
                ledger_snapshot.account["margin_fraction"]
            ),
            "peak_equity": float(ledger_snapshot.account["peak_equity"]),
            "current_drawdown_fraction": float(
                ledger_snapshot.account["current_drawdown_fraction"]
            ),
            "peak_drawdown_fraction": float(
                ledger_snapshot.account["peak_drawdown_fraction"]
            ),
            "peak_drawdown_at": ledger_snapshot.account["peak_drawdown_at"],
            "unavailable_fields": [],
        },
        "positions": [dict(row) for row in positions],
        "orders": {
            "scope": "runtime_ledger_orders_and_fills",
            "planned_order_count": len(batch.plan.orders),
            "planned_cancellation_count": len(batch.plan.cancellations),
            "runtime_order_count": len(ledger_snapshot.orders),
            "protective_order_count": sum(
                1 for order in batch.plan.orders if order.phase == "protective"
            ),
            "protective_order_runtime_statuses": dict(
                sorted(protective_statuses.items())
            ),
            "plan_executable": batch.plan.executable,
            "open_order_ids": list(ledger_snapshot.open_order_ids),
            "unresolved_order_ids": list(ledger_snapshot.unresolved_order_ids),
            "status_counts": dict(sorted(order_status_counts.items())),
            "fill_count": len(ledger_snapshot.fills),
            "fill_quantity": sum(
                float(fill["quantity"]) for fill in ledger_snapshot.fills
            ),
            "fill_notional": sum(
                float(fill["quantity"]) * float(fill["price"])
                for fill in ledger_snapshot.fills
            ),
            "fill_fees_by_asset": dict(sorted(fill_fees.items())),
            "latest_recovery_status": latest_recovery_status,
            "unavailable_fields": ["order_latency", "slippage"],
        },
        "pnl": {
            "scope": "latest_nav_mark",
            "marked_at": nav["marked_at"],
            "trading_pnl": float(nav["trading_pnl"]),
            "funding": float(nav["funding"]),
            "fees": float(nav["fees"]),
            "transfers": float(nav["transfers"]),
            "residual": float(nav["residual"]),
            "residual_tolerance": float(nav["residual_tolerance"]),
            "passed": bool(nav["passed"]),
            "signal_nav": nav["signal_nav"],
            "standalone_executable_nav": nav["standalone_executable_nav"],
            "realized_equity": float(nav["equity"]),
            "peak_equity": float(ledger_snapshot.account["peak_equity"]),
            "current_drawdown_fraction": float(
                ledger_snapshot.account["current_drawdown_fraction"]
            ),
            "peak_drawdown_fraction": float(
                ledger_snapshot.account["peak_drawdown_fraction"]
            ),
            "peak_drawdown_at": ledger_snapshot.account["peak_drawdown_at"],
            "unavailable_fields": ["slippage"],
        },
        "strategies": [dict(row) for row in strategies],
        "readiness": {
            "status": status,
            "gates": [dict(gate) for gate in gates],
            "reconciliation_id": ledger_snapshot.reconciliation[
                "reconciliation_id"
            ],
            "reconciliation_hash": ledger_snapshot.reconciliation["report_hash"],
        },
        "alerts": {
            "open_alert_count": len(open_alerts),
            "open_severity_counts": open_severity_counts,
            "delivery_state_counts": dict(
                notification_snapshot.delivery_state_counts
            ),
            "unresolved": [
                {
                    name: alert[name]
                    for name in (
                        "alert_id",
                        "severity",
                        "category",
                        "title",
                        "summary",
                        "occurred_at",
                        "source_type",
                        "source_id",
                        "source_hash",
                        "trace_id",
                        "event_hash",
                    )
                }
                for alert in open_alerts
            ],
            "audit_last_hash": notification_snapshot.audit_last_hash,
            "audit_row_count": notification_snapshot.audit_row_count,
        },
        "llm": {
            "status": "not_requested_deterministic_only",
            "reports": [],
        },
        "owner_actions": list(owner_actions),
    }
    brief_hash = canonical_hash(core)
    brief = DailyBrief(
        schema_version=core["schema_version"],
        brief_id=trace_id(
            "daily_brief",
            {"report_date": core["report_date"], "brief_hash": brief_hash},
        ),
        report_date=core["report_date"],
        generated_at=core["generated_at"],
        source_updated_at=core["source_updated_at"],
        source_hashes=core["source_hashes"],
        status=core["status"],
        account=core["account"],
        positions=positions,
        orders=core["orders"],
        pnl=core["pnl"],
        strategies=strategies,
        readiness=core["readiness"],
        alerts=core["alerts"],
        llm=core["llm"],
        owner_actions=owner_actions,
        brief_hash=brief_hash,
    )
    brief.validate()
    return brief


def validate_daily_brief_sources(
    brief: DailyBrief,
    batch: VerifiedDecisionBatch,
    registry: StrategyRegistry,
    ledger_snapshot: RuntimeLedgerSnapshot,
    notification_snapshot: NotificationSnapshot,
) -> None:
    if not isinstance(brief, DailyBrief):
        raise DailyBriefError("daily_brief_required")
    brief.validate()
    expected = build_daily_brief(
        batch,
        registry,
        ledger_snapshot,
        notification_snapshot,
        generated_at=brief.generated_at,
    )
    if brief != expected:
        raise DailyBriefError("daily_brief_source_mismatch")


def daily_brief_from_dict(value: Mapping[str, Any]) -> DailyBrief:
    expected = {
        "schema_version",
        "brief_id",
        "report_date",
        "generated_at",
        "source_updated_at",
        "source_hashes",
        "status",
        "account",
        "positions",
        "orders",
        "pnl",
        "strategies",
        "readiness",
        "alerts",
        "llm",
        "owner_actions",
        "brief_hash",
    }
    if set(value) != expected:
        raise DailyBriefError("daily_brief_fields_invalid")
    try:
        brief = DailyBrief(
            schema_version=value["schema_version"],
            brief_id=value["brief_id"],
            report_date=value["report_date"],
            generated_at=value["generated_at"],
            source_updated_at=value["source_updated_at"],
            source_hashes=dict(value["source_hashes"]),
            status=value["status"],
            account=dict(value["account"]),
            positions=tuple(dict(row) for row in value["positions"]),
            orders=dict(value["orders"]),
            pnl=dict(value["pnl"]),
            strategies=tuple(dict(row) for row in value["strategies"]),
            readiness=dict(value["readiness"]),
            alerts=dict(value["alerts"]),
            llm=dict(value["llm"]),
            owner_actions=tuple(value["owner_actions"]),
            brief_hash=value["brief_hash"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DailyBriefError("daily_brief_fields_invalid") from exc
    brief.validate()
    return brief
