"""SQLite WAL runtime ledger with a crash-replayable JSONL audit outbox."""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import re
import sqlite3
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from qount.contracts import canonical_hash
from qount.contracts import is_sha256
from qount.contracts import trace_id
from qount.contracts import validate_decision_batch
from qount.contracts.trace import aware_datetime
from qount.execution.state_machine import ExchangeOrderObservation
from qount.execution.state_machine import OrderRecoveryQuery
from qount.execution.state_machine import OrderRecoveryReport
from qount.execution.state_machine import RECOVERABLE_ORDER_STATUSES
from qount.execution.state_machine import validate_order_transition
from qount.ledger.audit import _append_audit_row_locked
from qount.ledger.audit import audit_journal_lock
from qount.ledger.audit import build_audit_row
from qount.ledger.audit import verify_audit_journal
from qount.ledger.reconciliation import ThreeWayReconciliation
from qount.persistence import VerifiedDecisionBatch
from qount.persistence import artifact_envelope


LEDGER_SCHEMA_VERSION = 3
_ORDER_STATUS_SQL = (
    "'PLANNED','SUBMITTING','ACKNOWLEDGED','PARTIALLY_FILLED',"
    "'FILLED','REJECTED','CANCELED','EXPIRED','UNKNOWN'"
)
_OPEN_ORDER_STATUSES = (
    "SUBMITTING",
    "ACKNOWLEDGED",
    "PARTIALLY_FILLED",
    "UNKNOWN",
)


class RuntimeLedgerError(ValueError):
    """Raised when runtime ledger state or input cannot be trusted."""


class RuntimeLedgerConflictError(RuntimeLedgerError):
    """Raised when an immutable identity is reused with different content."""


class RuntimeLedgerSecurityError(RuntimeLedgerError):
    """Raised when state paths or permissions are unsafe."""


@dataclass(frozen=True)
class NavMark:
    nav_mark_id: str
    marked_at: str
    previous_equity: float
    equity: float
    equity_change: float
    trading_pnl: float
    funding: float
    fees: float
    transfers: float
    residual: float
    residual_tolerance: float
    passed: bool
    trading_pnl_cumulative: float
    funding_cumulative: float
    fees_cumulative: float
    transfers_cumulative: float
    signal_nav: float | None
    standalone_executable_nav: float | None
    source_hash: str
    mark_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
        }


@dataclass(frozen=True)
class AccountObservation:
    account_observation_id: str
    batch_id: str
    observed_at: str
    quote_asset: str
    wallet_balance: float
    available_balance: float
    actual_gross_notional: float
    margin_used: float
    source_id: str
    source_hash: str
    observation_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


def _json_text(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def _json_object(raw: str, *, name: str) -> dict[str, Any]:
    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise RuntimeLedgerError(f"{name}_duplicate_key:{key}")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=reject_duplicate)
    except RuntimeLedgerError:
        raise
    except json.JSONDecodeError as exc:
        raise RuntimeLedgerError(f"{name}_json_invalid") from exc
    if not isinstance(value, dict) or _json_text(value) != raw:
        raise RuntimeLedgerError(f"{name}_not_canonical")
    return value


def _finite(value: object, *, name: str, minimum: float | None = None) -> float:
    try:
        normalized = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeLedgerError(f"{name}_invalid") from exc
    if not math.isfinite(normalized) or (
        minimum is not None and normalized < minimum
    ):
        raise RuntimeLedgerError(f"{name}_invalid")
    return normalized


def _time(value: str, *, name: str) -> str:
    try:
        parsed = aware_datetime(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise RuntimeLedgerError(f"{name}_invalid") from exc
    return parsed.astimezone(dt.timezone.utc).isoformat()


def _source_hash(value: str) -> str:
    if not is_sha256(value):
        raise RuntimeLedgerError("ledger_source_hash_invalid")
    return value


def _apply_signed_fill(
    *,
    old_quantity: float,
    old_cost: float,
    old_realized: float,
    side: str,
    quantity: float,
    price: float,
) -> tuple[float, float, float]:
    """Apply one fill to a signed position with positive average entry cost."""

    signed_fill = quantity if side == "buy" else -quantity
    if abs(old_quantity) <= 1e-15:
        return signed_fill, price, old_realized
    if old_cost <= 0.0:
        raise RuntimeLedgerError("position_average_cost_missing")
    if old_quantity * signed_fill > 0.0:
        new_quantity = old_quantity + signed_fill
        new_cost = (
            abs(old_quantity) * old_cost + abs(signed_fill) * price
        ) / abs(new_quantity)
        return new_quantity, new_cost, old_realized

    closed_quantity = min(abs(old_quantity), abs(signed_fill))
    if old_quantity > 0.0:
        realized_delta = (price - old_cost) * closed_quantity
    else:
        realized_delta = (old_cost - price) * closed_quantity
    new_quantity = old_quantity + signed_fill
    if abs(new_quantity) <= 1e-15:
        return 0.0, 0.0, old_realized + realized_delta
    if old_quantity * new_quantity > 0.0:
        new_cost = old_cost
    else:
        new_cost = price
    return new_quantity, new_cost, old_realized + realized_delta


def _prepare_private_parent(path: Path) -> None:
    parent = path.parent
    if parent.is_symlink():
        raise RuntimeLedgerSecurityError("ledger_state_directory_symlink_forbidden")
    existed = parent.exists()
    parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if not existed:
        os.chmod(parent, 0o700)
    if not parent.is_dir():
        raise RuntimeLedgerSecurityError("ledger_state_directory_invalid")
    mode = stat.S_IMODE(os.stat(parent, follow_symlinks=False).st_mode)
    if mode & 0o077:
        raise RuntimeLedgerSecurityError("ledger_state_directory_mode_invalid")


def _validate_verified_batch(batch: VerifiedDecisionBatch) -> None:
    if not isinstance(batch, VerifiedDecisionBatch):
        raise TypeError("runtime_ledger_requires_verified_decision_batch")
    errors = list(
        validate_decision_batch(
            batch.snapshot,
            batch.intents,
            batch.target,
            batch.risk,
            batch.plan,
        )
    )
    errors.extend(batch.manifest.validate())
    if batch.manifest.batch_id != batch.risk.batch_id:
        errors.append("ledger_manifest_batch_id_mismatch")
    values = (
        batch.snapshot,
        *sorted(batch.intents, key=lambda intent: intent.decision_id),
        batch.target,
        batch.risk,
        batch.plan,
    )
    references = batch.manifest.artifact_references()
    if len(values) != len(references):
        errors.append("ledger_manifest_reference_count_mismatch")
    else:
        for reference, value in zip(references, values, strict=True):
            try:
                envelope = artifact_envelope(value)
            except ValueError:
                errors.append(
                    f"ledger_manifest_reference_object_invalid:{reference.file_name}"
                )
                continue
            for name in (
                "artifact_type",
                "object_id",
                "payload_hash",
                "artifact_hash",
            ):
                if getattr(reference, name) != envelope[name]:
                    errors.append(f"ledger_manifest_reference_{name}_mismatch")
    if errors:
        raise RuntimeLedgerError(
            f"verified_decision_batch_invalid:{','.join(errors)}"
        )


class RuntimeLedger:
    """Single-writer runtime ledger; it never sends or queries exchange orders."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        audit_path: str | Path | None = None,
        busy_timeout_ms: int = 5_000,
        auto_flush: bool = True,
    ) -> None:
        self.database_path = Path(database_path)
        self.audit_path = (
            Path(audit_path)
            if audit_path is not None
            else self.database_path.with_suffix(".audit.jsonl")
        )
        if busy_timeout_ms < 1:
            raise ValueError("ledger_busy_timeout_invalid")
        self.busy_timeout_ms = int(busy_timeout_ms)
        self.auto_flush = bool(auto_flush)
        self._prepare_paths()
        self._initialize()
        self.flush_audit_outbox()

    def _prepare_paths(self) -> None:
        for path, name in (
            (self.database_path, "database"),
            (self.audit_path, "audit"),
        ):
            _prepare_private_parent(path)
            if path.is_symlink():
                raise RuntimeLedgerSecurityError(
                    f"ledger_{name}_symlink_forbidden"
                )
            if path.exists():
                if not path.is_file():
                    raise RuntimeLedgerSecurityError(f"ledger_{name}_path_invalid")
                mode = stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode)
                if mode != 0o600:
                    raise RuntimeLedgerSecurityError(
                        f"ledger_{name}_mode_invalid"
                    )
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{self.database_path}{suffix}")
            if sidecar.is_symlink():
                raise RuntimeLedgerSecurityError("ledger_sidecar_symlink_forbidden")

    def _secure_runtime_files(self) -> None:
        for path in (
            self.database_path,
            Path(f"{self.database_path}-wal"),
            Path(f"{self.database_path}-shm"),
        ):
            if path.exists():
                if path.is_symlink() or not path.is_file():
                    raise RuntimeLedgerSecurityError("ledger_runtime_file_invalid")
                os.chmod(path, 0o600)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        self._prepare_paths()
        connection = sqlite3.connect(
            self.database_path,
            timeout=self.busy_timeout_ms / 1_000.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
            connection.execute("PRAGMA synchronous = FULL")
            yield connection
        finally:
            connection.close()
            self._secure_runtime_files()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()

    def _initialize(self) -> None:
        with self._connection() as connection:
            mode = str(connection.execute("PRAGMA journal_mode = WAL").fetchone()[0])
            if mode.lower() != "wal":
                raise RuntimeLedgerError("ledger_wal_not_enabled")
            connection.executescript(
                f"""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS schema_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS batches (
                    batch_id TEXT PRIMARY KEY,
                    manifest_hash TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    portfolio_target_id TEXT NOT NULL,
                    risk_decision_id TEXT NOT NULL,
                    order_plan_id TEXT NOT NULL,
                    plan_hash TEXT NOT NULL,
                    expected_positions_json TEXT NOT NULL,
                    reconciliation_tolerance_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    record_hash TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS orders (
                    client_order_id TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL REFERENCES batches(batch_id),
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL CHECK(side IN ('buy','sell')),
                    planned_quantity REAL,
                    reduce_only INTEGER NOT NULL CHECK(reduce_only IN (0,1)),
                    phase TEXT NOT NULL CHECK(phase IN ('reduce','increase','protective')),
                    sequence INTEGER NOT NULL,
                    order_type TEXT NOT NULL,
                    close_position INTEGER NOT NULL CHECK(close_position IN (0,1)),
                    limit_price REAL,
                    stop_price REAL,
                    plan_spec_hash TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ({_ORDER_STATUS_SQL})),
                    exchange_order_id TEXT,
                    executed_quantity REAL NOT NULL DEFAULT 0,
                    average_price REAL,
                    last_transition_at TEXT NOT NULL,
                    last_observation_hash TEXT NOT NULL,
                    UNIQUE(batch_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS order_events (
                    event_id TEXT PRIMARY KEY,
                    client_order_id TEXT NOT NULL REFERENCES orders(client_order_id),
                    from_status TEXT NOT NULL CHECK(from_status IN ({_ORDER_STATUS_SQL})),
                    to_status TEXT NOT NULL CHECK(to_status IN ({_ORDER_STATUS_SQL})),
                    event_at TEXT NOT NULL,
                    exchange_order_id TEXT,
                    executed_quantity REAL NOT NULL,
                    average_price REAL,
                    source_hash TEXT NOT NULL,
                    reason TEXT,
                    transition_hash TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS fills (
                    fill_id TEXT PRIMARY KEY,
                    client_order_id TEXT NOT NULL REFERENCES orders(client_order_id),
                    exchange_trade_id TEXT NOT NULL,
                    quantity REAL NOT NULL CHECK(quantity > 0),
                    price REAL NOT NULL CHECK(price > 0),
                    fee REAL NOT NULL CHECK(fee >= 0),
                    fee_asset TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    fill_hash TEXT NOT NULL UNIQUE,
                    UNIQUE(client_order_id, exchange_trade_id)
                );
                CREATE TABLE IF NOT EXISTS cash_events (
                    cash_event_id TEXT PRIMARY KEY,
                    event_key TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL CHECK(
                        event_type IN ('funding','fee','transfer','adjustment')
                    ),
                    amount REAL NOT NULL,
                    asset TEXT NOT NULL,
                    symbol TEXT,
                    occurred_at TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS positions (
                    symbol TEXT PRIMARY KEY,
                    quantity REAL NOT NULL,
                    average_cost REAL NOT NULL CHECK(average_cost >= 0),
                    realized_trading_pnl REAL NOT NULL,
                    updated_at TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    position_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS nav_marks (
                    nav_mark_id TEXT PRIMARY KEY,
                    marked_at TEXT NOT NULL UNIQUE,
                    previous_equity REAL NOT NULL,
                    equity REAL NOT NULL,
                    equity_change REAL NOT NULL,
                    trading_pnl REAL NOT NULL,
                    funding REAL NOT NULL,
                    fees REAL NOT NULL,
                    transfers REAL NOT NULL,
                    residual REAL NOT NULL,
                    residual_tolerance REAL NOT NULL CHECK(residual_tolerance >= 0),
                    passed INTEGER NOT NULL CHECK(passed IN (0,1)),
                    trading_pnl_cumulative REAL NOT NULL,
                    funding_cumulative REAL NOT NULL,
                    fees_cumulative REAL NOT NULL,
                    transfers_cumulative REAL NOT NULL,
                    signal_nav REAL,
                    standalone_executable_nav REAL,
                    source_hash TEXT NOT NULL,
                    mark_hash TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS account_observations (
                    account_observation_id TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL REFERENCES batches(batch_id),
                    observed_at TEXT NOT NULL UNIQUE,
                    quote_asset TEXT NOT NULL,
                    wallet_balance REAL NOT NULL CHECK(wallet_balance >= 0),
                    available_balance REAL NOT NULL CHECK(available_balance >= 0),
                    actual_gross_notional REAL NOT NULL CHECK(actual_gross_notional >= 0),
                    margin_used REAL NOT NULL CHECK(margin_used >= 0),
                    source_id TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    observation_hash TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS reconciliations (
                    reconciliation_id TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL REFERENCES batches(batch_id),
                    reconciled_at TEXT NOT NULL,
                    report_hash TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    passed INTEGER NOT NULL CHECK(passed IN (0,1)),
                    risk_increase_allowed INTEGER NOT NULL CHECK(risk_increase_allowed IN (0,1)),
                    halt_required INTEGER NOT NULL CHECK(halt_required IN (0,1))
                );
                CREATE TABLE IF NOT EXISTS order_recoveries (
                    recovery_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    report_hash TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    risk_increase_allowed INTEGER NOT NULL CHECK(risk_increase_allowed IN (0,1)),
                    halt_required INTEGER NOT NULL CHECK(halt_required IN (0,1))
                );
                CREATE TABLE IF NOT EXISTS audit_outbox (
                    sequence INTEGER PRIMARY KEY,
                    event_id TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    row_hash TEXT NOT NULL UNIQUE,
                    published_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
                CREATE INDEX IF NOT EXISTS idx_fills_occurred_at ON fills(occurred_at);
                CREATE INDEX IF NOT EXISTS idx_cash_events_occurred_at ON cash_events(occurred_at);
                CREATE INDEX IF NOT EXISTS idx_account_observations_batch_time
                    ON account_observations(batch_id, observed_at);
                INSERT INTO schema_metadata(key, value)
                VALUES ('schema_version', '{LEDGER_SCHEMA_VERSION}')
                ON CONFLICT(key) DO NOTHING;
                COMMIT;
                """
            )
            schema_version = connection.execute(
                "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
            ).fetchone()[0]
            if schema_version in {"1", "2"}:
                connection.executescript(
                    f"""
                    BEGIN IMMEDIATE;
                    CREATE TABLE positions_signed_v3 (
                        symbol TEXT PRIMARY KEY,
                        quantity REAL NOT NULL,
                        average_cost REAL NOT NULL CHECK(average_cost >= 0),
                        realized_trading_pnl REAL NOT NULL,
                        updated_at TEXT NOT NULL,
                        source_hash TEXT NOT NULL,
                        position_hash TEXT NOT NULL
                    );
                    INSERT INTO positions_signed_v3(
                        symbol,quantity,average_cost,realized_trading_pnl,
                        updated_at,source_hash,position_hash
                    )
                    SELECT symbol,quantity,average_cost,realized_trading_pnl,
                           updated_at,source_hash,position_hash
                    FROM positions;
                    DROP TABLE positions;
                    ALTER TABLE positions_signed_v3 RENAME TO positions;
                    UPDATE schema_metadata
                    SET value = '{LEDGER_SCHEMA_VERSION}'
                    WHERE key = 'schema_version';
                    COMMIT;
                    """
                )
                schema_version = str(LEDGER_SCHEMA_VERSION)
            if schema_version != str(LEDGER_SCHEMA_VERSION):
                raise RuntimeLedgerError("ledger_schema_version_invalid")

    def _queue_outbox(
        self,
        connection: sqlite3.Connection,
        *,
        event_type: str,
        entity_type: str,
        entity_id: str,
        occurred_at: str,
        payload: Mapping[str, Any],
    ) -> None:
        if not event_type or not entity_type or not entity_id:
            raise RuntimeLedgerError("audit_outbox_identity_invalid")
        occurred_at = _time(occurred_at, name="audit_outbox_occurred_at")
        previous = connection.execute(
            "SELECT sequence, occurred_at, row_hash FROM audit_outbox "
            "ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        sequence = 1 if previous is None else int(previous["sequence"]) + 1
        previous_hash = "0" * 64 if previous is None else str(previous["row_hash"])
        journal_time = occurred_at
        if previous is not None and aware_datetime(journal_time) < aware_datetime(
            str(previous["occurred_at"])
        ):
            journal_time = str(previous["occurred_at"])
        normalized_payload = dict(payload)
        event_id = canonical_hash(
            {
                "sequence": sequence,
                "event_type": event_type,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "occurred_at": journal_time,
                "payload": normalized_payload,
            }
        )
        row = build_audit_row(
            sequence=sequence,
            event_id=event_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            occurred_at=journal_time,
            payload=normalized_payload,
            previous_hash=previous_hash,
        )
        connection.execute(
            "INSERT INTO audit_outbox(sequence,event_id,event_type,entity_type,"
            "entity_id,occurred_at,payload_json,previous_hash,row_hash) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                row["sequence"],
                row["event_id"],
                row["event_type"],
                row["entity_type"],
                row["entity_id"],
                row["occurred_at"],
                _json_text(row["payload"]),
                row["previous_hash"],
                row["row_hash"],
            ),
        )

    def _audit_row_from_outbox(self, row: sqlite3.Row) -> dict[str, Any]:
        audit_row = build_audit_row(
            sequence=int(row["sequence"]),
            event_id=str(row["event_id"]),
            event_type=str(row["event_type"]),
            entity_type=str(row["entity_type"]),
            entity_id=str(row["entity_id"]),
            occurred_at=str(row["occurred_at"]),
            payload=_json_object(str(row["payload_json"]), name="audit_outbox_payload"),
            previous_hash=str(row["previous_hash"]),
        )
        if audit_row["row_hash"] != row["row_hash"]:
            raise RuntimeLedgerError("audit_outbox_row_hash_invalid")
        return audit_row

    def _mark_outbox_published(self, sequence: int, row_hash: str) -> None:
        with self._transaction() as connection:
            cursor = connection.execute(
                "UPDATE audit_outbox SET published_at = occurred_at "
                "WHERE sequence = ? AND row_hash = ? AND published_at IS NULL",
                (sequence, row_hash),
            )
            if cursor.rowcount not in (0, 1):
                raise RuntimeLedgerError("audit_outbox_publish_update_invalid")

    def flush_audit_outbox(self) -> int:
        """Replay committed outbox rows; exact journal rows are never appended twice."""

        with audit_journal_lock(self.audit_path):
            journal = verify_audit_journal(self.audit_path)
            with self._connection() as connection:
                outbox = connection.execute(
                    "SELECT * FROM audit_outbox ORDER BY sequence"
                ).fetchall()
            if journal.last_sequence > len(outbox):
                raise RuntimeLedgerError("audit_journal_ahead_of_outbox")
            expected_rows = [self._audit_row_from_outbox(row) for row in outbox]
            for sequence in range(1, journal.last_sequence + 1):
                if journal.rows_by_sequence[sequence] != expected_rows[sequence - 1]:
                    raise RuntimeLedgerError(
                        f"audit_journal_outbox_mismatch:{sequence}"
                    )
            appended = 0
            for row in expected_rows[journal.last_sequence :]:
                _append_audit_row_locked(self.audit_path, row)
                appended += 1
                self._mark_outbox_published(int(row["sequence"]), str(row["row_hash"]))
            for row in expected_rows[: journal.last_sequence]:
                self._mark_outbox_published(int(row["sequence"]), str(row["row_hash"]))
            return appended

    def _after_commit(self) -> None:
        self._secure_runtime_files()
        if self.auto_flush:
            self.flush_audit_outbox()

    def record_verified_batch(
        self,
        batch: VerifiedDecisionBatch,
        *,
        recorded_at: str | None = None,
    ) -> bool:
        """Atomically register one complete batch and all of its planned orders."""

        _validate_verified_batch(batch)
        recorded_at = recorded_at or batch.manifest.created_at
        recorded_at = _time(recorded_at, name="ledger_batch_recorded_at")
        core = {
            "batch_id": batch.manifest.batch_id,
            "manifest_hash": batch.manifest.manifest_hash,
            "snapshot_id": batch.snapshot.snapshot_id,
            "portfolio_target_id": batch.target.portfolio_target_id,
            "risk_decision_id": batch.risk.risk_decision_id,
            "order_plan_id": batch.plan.order_plan_id,
            "plan_hash": batch.plan.plan_hash,
            "expected_positions": dict(batch.plan.expected_positions),
            "reconciliation_tolerance": dict(batch.plan.reconciliation_tolerance),
            "created_at": batch.manifest.created_at,
        }
        record_hash = canonical_hash(core)
        created = False
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT record_hash FROM batches WHERE batch_id = ?",
                (batch.manifest.batch_id,),
            ).fetchone()
            if existing is not None:
                if existing["record_hash"] != record_hash:
                    raise RuntimeLedgerConflictError("ledger_batch_conflict")
                stored_orders = connection.execute(
                    "SELECT client_order_id, plan_spec_hash FROM orders "
                    "WHERE batch_id = ? ORDER BY sequence",
                    (batch.manifest.batch_id,),
                ).fetchall()
                expected_orders = [
                    (order.client_order_id, canonical_hash(order.as_dict()))
                    for order in batch.plan.orders
                ]
                if [tuple(row) for row in stored_orders] != expected_orders:
                    raise RuntimeLedgerConflictError("ledger_batch_orders_conflict")
            else:
                for order in batch.plan.orders:
                    collision = connection.execute(
                        "SELECT batch_id FROM orders WHERE client_order_id = ?",
                        (order.client_order_id,),
                    ).fetchone()
                    if collision is not None:
                        raise RuntimeLedgerConflictError("ledger_order_identity_conflict")
                connection.execute(
                    "INSERT INTO batches(batch_id,manifest_hash,snapshot_id,"
                    "portfolio_target_id,risk_decision_id,order_plan_id,plan_hash,"
                    "expected_positions_json,reconciliation_tolerance_json,created_at,"
                    "recorded_at,record_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        batch.manifest.batch_id,
                        batch.manifest.manifest_hash,
                        batch.snapshot.snapshot_id,
                        batch.target.portfolio_target_id,
                        batch.risk.risk_decision_id,
                        batch.plan.order_plan_id,
                        batch.plan.plan_hash,
                        _json_text(dict(batch.plan.expected_positions)),
                        _json_text(dict(batch.plan.reconciliation_tolerance)),
                        batch.manifest.created_at,
                        recorded_at,
                        record_hash,
                    ),
                )
                for order in batch.plan.orders:
                    spec = order.as_dict()
                    spec_hash = canonical_hash(spec)
                    connection.execute(
                        "INSERT INTO orders(client_order_id,batch_id,symbol,side,"
                        "planned_quantity,reduce_only,phase,sequence,order_type,"
                        "close_position,limit_price,stop_price,plan_spec_hash,status,"
                        "executed_quantity,last_transition_at,last_observation_hash) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'PLANNED',0,?,?)",
                        (
                            order.client_order_id,
                            batch.plan.batch_id,
                            order.symbol,
                            order.side,
                            order.quantity,
                            int(order.reduce_only),
                            order.phase,
                            order.sequence,
                            order.order_type,
                            int(order.close_position),
                            order.limit_price,
                            order.stop_price,
                            spec_hash,
                            recorded_at,
                            spec_hash,
                        ),
                    )
                self._queue_outbox(
                    connection,
                    event_type="decision_batch_recorded",
                    entity_type="decision_batch",
                    entity_id=batch.manifest.batch_id,
                    occurred_at=recorded_at,
                    payload=core | {
                        "record_hash": record_hash,
                        "client_order_ids": [
                            order.client_order_id for order in batch.plan.orders
                        ],
                    },
                )
                for order in batch.plan.orders:
                    self._queue_outbox(
                        connection,
                        event_type="order_planned",
                        entity_type="order",
                        entity_id=order.client_order_id,
                        occurred_at=recorded_at,
                        payload={
                            "batch_id": batch.plan.batch_id,
                            "plan_spec_hash": canonical_hash(order.as_dict()),
                            "order": order.as_dict(),
                        },
                    )
                created = True
        self._after_commit()
        return created

    def get_order(self, client_order_id: str) -> dict[str, Any]:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM orders WHERE client_order_id = ?",
                (client_order_id,),
            ).fetchone()
        if row is None:
            raise KeyError(client_order_id)
        return dict(row)

    def list_order_events(self, client_order_id: str) -> tuple[dict[str, Any], ...]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM order_events WHERE client_order_id = ? "
                "ORDER BY rowid",
                (client_order_id,),
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def transition_order(
        self,
        client_order_id: str,
        next_status: str,
        *,
        event_at: str,
        source_hash: str,
        exchange_order_id: str | None = None,
        executed_quantity: float | None = None,
        average_price: float | None = None,
        reason: str | None = None,
    ) -> bool:
        """Persist one legal cumulative order observation before further action."""

        event_at = _time(event_at, name="order_transition_time")
        _source_hash(source_hash)
        changed = False
        with self._transaction() as connection:
            order = connection.execute(
                "SELECT * FROM orders WHERE client_order_id = ?",
                (client_order_id,),
            ).fetchone()
            if order is None:
                raise KeyError(client_order_id)
            current_status = str(order["status"])
            current_executed = float(order["executed_quantity"])
            normalized_executed = (
                current_executed
                if executed_quantity is None
                else _finite(
                    executed_quantity,
                    name="order_executed_quantity",
                    minimum=0.0,
                )
            )
            normalized_average = (
                order["average_price"]
                if average_price is None
                else _finite(average_price, name="order_average_price", minimum=0.0)
            )
            normalized_exchange_id = exchange_order_id or order["exchange_order_id"]
            if (
                exchange_order_id
                and order["exchange_order_id"]
                and exchange_order_id != order["exchange_order_id"]
            ):
                raise RuntimeLedgerConflictError("order_exchange_id_conflict")
            if (
                current_status == next_status
                and order["last_observation_hash"] == source_hash
                and normalized_executed == current_executed
                and normalized_average == order["average_price"]
                and normalized_exchange_id == order["exchange_order_id"]
            ):
                return False
            validate_order_transition(current_status, next_status)
            if aware_datetime(event_at) < aware_datetime(str(order["last_transition_at"])):
                raise RuntimeLedgerError("order_transition_time_regression")
            if normalized_executed + 1e-12 < current_executed:
                raise RuntimeLedgerError("order_executed_quantity_regression")
            planned_quantity = order["planned_quantity"]
            if (
                planned_quantity is not None
                and normalized_executed > float(planned_quantity) + 1e-12
            ):
                raise RuntimeLedgerError("order_executed_quantity_exceeds_plan")
            ExchangeOrderObservation.create(
                client_order_id=client_order_id,
                status=next_status,
                observed_at=event_at,
                exchange_order_id=(
                    str(normalized_exchange_id)
                    if normalized_exchange_id is not None
                    else None
                ),
                executed_quantity=normalized_executed,
                average_price=(
                    float(normalized_average)
                    if normalized_average is not None
                    else None
                ),
                source_hash=source_hash,
                reason=reason,
            )
            if next_status == "PARTIALLY_FILLED" and planned_quantity is not None:
                if normalized_executed >= float(planned_quantity) - 1e-12:
                    raise RuntimeLedgerError("partial_fill_reaches_planned_quantity")
            if next_status == "FILLED" and planned_quantity is not None:
                if abs(normalized_executed - float(planned_quantity)) > 1e-12:
                    raise RuntimeLedgerError("filled_quantity_not_complete")
            transition_core = {
                "client_order_id": client_order_id,
                "from_status": current_status,
                "to_status": next_status,
                "event_at": event_at,
                "exchange_order_id": normalized_exchange_id,
                "executed_quantity": normalized_executed,
                "average_price": normalized_average,
                "source_hash": source_hash,
                "reason": reason,
            }
            transition_hash = canonical_hash(transition_core)
            event_id = trace_id("order_event", {"transition_hash": transition_hash})
            connection.execute(
                "INSERT INTO order_events(event_id,client_order_id,from_status,"
                "to_status,event_at,exchange_order_id,executed_quantity,average_price,"
                "source_hash,reason,transition_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    event_id,
                    client_order_id,
                    current_status,
                    next_status,
                    event_at,
                    normalized_exchange_id,
                    normalized_executed,
                    normalized_average,
                    source_hash,
                    reason,
                    transition_hash,
                ),
            )
            connection.execute(
                "UPDATE orders SET status=?,exchange_order_id=?,executed_quantity=?,"
                "average_price=?,last_transition_at=?,last_observation_hash=? "
                "WHERE client_order_id=?",
                (
                    next_status,
                    normalized_exchange_id,
                    normalized_executed,
                    normalized_average,
                    event_at,
                    source_hash,
                    client_order_id,
                ),
            )
            self._queue_outbox(
                connection,
                event_type="order_transitioned",
                entity_type="order",
                entity_id=client_order_id,
                occurred_at=event_at,
                payload=transition_core | {
                    "event_id": event_id,
                    "transition_hash": transition_hash,
                },
            )
            changed = True
        self._after_commit()
        return changed

    def apply_order_observation(self, observation: ExchangeOrderObservation) -> bool:
        errors = observation.validate()
        if errors:
            raise RuntimeLedgerError(
                f"exchange_order_observation_invalid:{','.join(errors)}"
            )
        return self.transition_order(
            observation.client_order_id,
            observation.status,
            event_at=observation.observed_at,
            source_hash=observation.source_hash,
            exchange_order_id=observation.exchange_order_id,
            executed_quantity=observation.executed_quantity,
            average_price=observation.average_price,
            reason=observation.reason,
        )

    def recovery_queries(self) -> tuple[OrderRecoveryQuery, ...]:
        placeholders = ",".join("?" for _ in RECOVERABLE_ORDER_STATUSES)
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT client_order_id,exchange_order_id,symbol,status,last_transition_at "
                f"FROM orders WHERE status IN ({placeholders}) ORDER BY client_order_id",
                tuple(sorted(RECOVERABLE_ORDER_STATUSES)),
            ).fetchall()
        queries = tuple(
            OrderRecoveryQuery(
                client_order_id=str(row["client_order_id"]),
                exchange_order_id=(
                    str(row["exchange_order_id"])
                    if row["exchange_order_id"] is not None
                    else None
                ),
                symbol=str(row["symbol"]),
                current_status=str(row["status"]),
                last_transition_at=str(row["last_transition_at"]),
            )
            for row in rows
        )
        for query in queries:
            query.validate()
        return queries

    def record_order_recovery(self, report: OrderRecoveryReport) -> bool:
        report.validate()
        payload = {
            "recovery_id": report.recovery_id,
            "started_at": report.started_at,
            "completed_at": report.completed_at,
            "attempted_client_order_ids": report.attempted_client_order_ids,
            "resolved_client_order_ids": report.resolved_client_order_ids,
            "unresolved_client_order_ids": report.unresolved_client_order_ids,
            "errors": dict(report.errors),
            "risk_increase_allowed": report.risk_increase_allowed,
            "halt_required": report.halt_required,
            "report_hash": report.report_hash,
        }
        payload_json = _json_text(payload)
        created = False
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT payload_json FROM order_recoveries WHERE recovery_id = ?",
                (report.recovery_id,),
            ).fetchone()
            if existing is not None:
                if existing["payload_json"] != payload_json:
                    raise RuntimeLedgerConflictError("order_recovery_conflict")
            else:
                connection.execute(
                    "INSERT INTO order_recoveries VALUES (?,?,?,?,?,?,?)",
                    (
                        report.recovery_id,
                        report.started_at,
                        report.completed_at,
                        report.report_hash,
                        payload_json,
                        int(report.risk_increase_allowed),
                        int(report.halt_required),
                    ),
                )
                self._queue_outbox(
                    connection,
                    event_type="order_recovery_recorded",
                    entity_type="order_recovery",
                    entity_id=report.recovery_id,
                    occurred_at=report.completed_at,
                    payload=payload,
                )
                created = True
        self._after_commit()
        return created

    def record_position_snapshot(
        self,
        *,
        symbol: str,
        quantity: float,
        average_cost: float,
        realized_trading_pnl: float,
        occurred_at: str,
        source_hash: str,
    ) -> bool:
        if not symbol:
            raise RuntimeLedgerError("position_symbol_invalid")
        quantity = _finite(quantity, name="position_quantity")
        average_cost = _finite(average_cost, name="position_average_cost", minimum=0.0)
        realized = _finite(realized_trading_pnl, name="position_realized_pnl")
        if abs(quantity) > 0.0 and average_cost <= 0.0:
            raise RuntimeLedgerError("position_average_cost_missing")
        if quantity == 0.0 and average_cost != 0.0:
            raise RuntimeLedgerError("flat_position_average_cost_nonzero")
        occurred_at = _time(occurred_at, name="position_time")
        _source_hash(source_hash)
        core = {
            "symbol": symbol,
            "quantity": quantity,
            "average_cost": average_cost,
            "realized_trading_pnl": realized,
            "updated_at": occurred_at,
            "source_hash": source_hash,
        }
        position_hash = canonical_hash(core)
        changed = False
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM positions WHERE symbol = ?", (symbol,)
            ).fetchone()
            if existing is not None:
                if existing["position_hash"] == position_hash:
                    return False
                if aware_datetime(occurred_at) < aware_datetime(str(existing["updated_at"])):
                    raise RuntimeLedgerError("position_time_regression")
            connection.execute(
                "INSERT INTO positions(symbol,quantity,average_cost,realized_trading_pnl,"
                "updated_at,source_hash,position_hash) VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(symbol) DO UPDATE SET quantity=excluded.quantity,"
                "average_cost=excluded.average_cost,"
                "realized_trading_pnl=excluded.realized_trading_pnl,"
                "updated_at=excluded.updated_at,source_hash=excluded.source_hash,"
                "position_hash=excluded.position_hash",
                (
                    symbol,
                    quantity,
                    average_cost,
                    realized,
                    occurred_at,
                    source_hash,
                    position_hash,
                ),
            )
            self._queue_outbox(
                connection,
                event_type="position_snapshot_recorded",
                entity_type="position",
                entity_id=symbol,
                occurred_at=occurred_at,
                payload=core | {"position_hash": position_hash},
            )
            changed = True
        self._after_commit()
        return changed

    def record_fill(
        self,
        *,
        client_order_id: str,
        exchange_trade_id: str,
        quantity: float,
        price: float,
        fee: float,
        fee_asset: str,
        occurred_at: str,
        source_hash: str,
    ) -> bool:
        if not exchange_trade_id or not fee_asset:
            raise RuntimeLedgerError("fill_identity_invalid")
        quantity = _finite(quantity, name="fill_quantity", minimum=0.0)
        price = _finite(price, name="fill_price", minimum=0.0)
        fee = _finite(fee, name="fill_fee", minimum=0.0)
        if quantity <= 0.0 or price <= 0.0:
            raise RuntimeLedgerError("fill_value_invalid")
        occurred_at = _time(occurred_at, name="fill_time")
        _source_hash(source_hash)
        core = {
            "client_order_id": client_order_id,
            "exchange_trade_id": exchange_trade_id,
            "quantity": quantity,
            "price": price,
            "fee": fee,
            "fee_asset": fee_asset,
            "occurred_at": occurred_at,
            "source_hash": source_hash,
        }
        fill_hash = canonical_hash(core)
        fill_id = trace_id(
            "fill",
            {
                "client_order_id": client_order_id,
                "exchange_trade_id": exchange_trade_id,
            },
        )
        created = False
        with self._transaction() as connection:
            order = connection.execute(
                "SELECT * FROM orders WHERE client_order_id = ?", (client_order_id,)
            ).fetchone()
            if order is None:
                raise KeyError(client_order_id)
            existing = connection.execute(
                "SELECT fill_hash FROM fills WHERE fill_id = ?", (fill_id,)
            ).fetchone()
            if existing is not None:
                if existing["fill_hash"] != fill_hash:
                    raise RuntimeLedgerConflictError("fill_conflict")
                return False
            if order["status"] not in {
                "PARTIALLY_FILLED",
                "FILLED",
                "CANCELED",
                "EXPIRED",
                "UNKNOWN",
            }:
                raise RuntimeLedgerError("fill_order_status_invalid")
            latest_nav = connection.execute(
                "SELECT marked_at FROM nav_marks ORDER BY marked_at DESC LIMIT 1"
            ).fetchone()
            if latest_nav is not None and aware_datetime(occurred_at) <= aware_datetime(
                str(latest_nav["marked_at"])
            ):
                raise RuntimeLedgerError("fill_occurs_in_closed_nav_period")
            prior_fill_quantity = float(
                connection.execute(
                    "SELECT COALESCE(SUM(quantity),0) FROM fills WHERE client_order_id = ?",
                    (client_order_id,),
                ).fetchone()[0]
            )
            if prior_fill_quantity + quantity > float(order["executed_quantity"]) + 1e-12:
                raise RuntimeLedgerError("fill_quantity_exceeds_order_observation")
            position = connection.execute(
                "SELECT * FROM positions WHERE symbol = ?", (order["symbol"],)
            ).fetchone()
            if position is not None and aware_datetime(occurred_at) < aware_datetime(
                str(position["updated_at"])
            ):
                raise RuntimeLedgerError("fill_position_time_regression")
            old_quantity = 0.0 if position is None else float(position["quantity"])
            old_cost = 0.0 if position is None else float(position["average_cost"])
            old_realized = (
                0.0 if position is None else float(position["realized_trading_pnl"])
            )
            new_quantity, new_cost, new_realized = _apply_signed_fill(
                old_quantity=old_quantity,
                old_cost=old_cost,
                old_realized=old_realized,
                side=str(order["side"]),
                quantity=quantity,
                price=price,
            )
            if bool(order["reduce_only"] or order["close_position"]):
                changed_side = (
                    abs(old_quantity) <= 1e-15
                    or old_quantity * new_quantity < -1e-15
                )
                increased_exposure = abs(new_quantity) > abs(old_quantity) + 1e-12
                if changed_side or increased_exposure:
                    raise RuntimeLedgerError("fill_reduce_only_would_increase_position")
            position_core = {
                "symbol": str(order["symbol"]),
                "quantity": new_quantity,
                "average_cost": new_cost,
                "realized_trading_pnl": new_realized,
                "updated_at": occurred_at,
                "source_hash": source_hash,
            }
            position_hash = canonical_hash(position_core)
            connection.execute(
                "INSERT INTO fills(fill_id,client_order_id,exchange_trade_id,quantity,"
                "price,fee,fee_asset,occurred_at,source_hash,fill_hash) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    fill_id,
                    client_order_id,
                    exchange_trade_id,
                    quantity,
                    price,
                    fee,
                    fee_asset,
                    occurred_at,
                    source_hash,
                    fill_hash,
                ),
            )
            connection.execute(
                "INSERT INTO positions(symbol,quantity,average_cost,realized_trading_pnl,"
                "updated_at,source_hash,position_hash) VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(symbol) DO UPDATE SET quantity=excluded.quantity,"
                "average_cost=excluded.average_cost,"
                "realized_trading_pnl=excluded.realized_trading_pnl,"
                "updated_at=excluded.updated_at,source_hash=excluded.source_hash,"
                "position_hash=excluded.position_hash",
                (
                    order["symbol"],
                    new_quantity,
                    new_cost,
                    new_realized,
                    occurred_at,
                    source_hash,
                    position_hash,
                ),
            )
            self._queue_outbox(
                connection,
                event_type="fill_recorded",
                entity_type="fill",
                entity_id=fill_id,
                occurred_at=occurred_at,
                payload=core
                | {
                    "fill_id": fill_id,
                    "fill_hash": fill_hash,
                    "position_hash": position_hash,
                },
            )
            created = True
        self._after_commit()
        return created

    def has_fill(self, *, client_order_id: str, exchange_trade_id: str) -> bool:
        """Return whether this immutable venue trade is already recorded."""

        fill_id = trace_id(
            "fill",
            {
                "client_order_id": client_order_id,
                "exchange_trade_id": exchange_trade_id,
            },
        )
        with self._connection() as connection:
            return (
                connection.execute(
                    "SELECT 1 FROM fills WHERE fill_id = ?", (fill_id,)
                ).fetchone()
                is not None
            )

    def record_cash_event(
        self,
        *,
        event_key: str,
        event_type: str,
        amount: float,
        asset: str,
        occurred_at: str,
        source_hash: str,
        symbol: str | None = None,
    ) -> str:
        if not event_key or not asset:
            raise RuntimeLedgerError("cash_event_identity_invalid")
        if event_type not in {"funding", "fee", "transfer", "adjustment"}:
            raise RuntimeLedgerError("cash_event_type_invalid")
        amount = _finite(amount, name="cash_event_amount")
        if event_type == "fee" and amount < 0.0:
            raise RuntimeLedgerError("cash_event_fee_negative")
        occurred_at = _time(occurred_at, name="cash_event_time")
        _source_hash(source_hash)
        cash_event_id = trace_id("cash_event", {"event_key": event_key})
        core = {
            "cash_event_id": cash_event_id,
            "event_key": event_key,
            "event_type": event_type,
            "amount": amount,
            "asset": asset,
            "symbol": symbol,
            "occurred_at": occurred_at,
            "source_hash": source_hash,
        }
        event_hash = canonical_hash(core)
        with self._transaction() as connection:
            latest_nav = connection.execute(
                "SELECT marked_at FROM nav_marks ORDER BY marked_at DESC LIMIT 1"
            ).fetchone()
            if latest_nav is not None and aware_datetime(occurred_at) <= aware_datetime(
                str(latest_nav["marked_at"])
            ):
                raise RuntimeLedgerError("cash_event_occurs_in_closed_nav_period")
            existing = connection.execute(
                "SELECT event_hash FROM cash_events WHERE cash_event_id = ?",
                (cash_event_id,),
            ).fetchone()
            if existing is not None:
                if existing["event_hash"] != event_hash:
                    raise RuntimeLedgerConflictError("cash_event_conflict")
                return cash_event_id
            connection.execute(
                "INSERT INTO cash_events VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    cash_event_id,
                    event_key,
                    event_type,
                    amount,
                    asset,
                    symbol,
                    occurred_at,
                    source_hash,
                    event_hash,
                ),
            )
            self._queue_outbox(
                connection,
                event_type="cash_event_recorded",
                entity_type="cash_event",
                entity_id=cash_event_id,
                occurred_at=occurred_at,
                payload=core | {"event_hash": event_hash},
            )
        self._after_commit()
        return cash_event_id

    def position_quantities(self) -> dict[str, float]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT symbol,quantity FROM positions ORDER BY symbol"
            ).fetchall()
        return {str(row["symbol"]): float(row["quantity"]) for row in rows}

    def open_order_ids(self) -> tuple[str, ...]:
        placeholders = ",".join("?" for _ in _OPEN_ORDER_STATUSES)
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT client_order_id FROM orders WHERE status IN ({placeholders}) "
                "ORDER BY client_order_id",
                _OPEN_ORDER_STATUSES,
            ).fetchall()
        return tuple(str(row["client_order_id"]) for row in rows)

    def fill_fee_total(self, *, after: str, through: str) -> float:
        """Return fees for fills recorded in one open NAV period."""

        return sum(self.fill_fee_totals(after=after, through=through).values())

    def fill_fee_totals(self, *, after: str, through: str) -> dict[str, float]:
        """Return fill fees by original asset for one open NAV period."""

        after = _time(after, name="fill_fee_period_start")
        through = _time(through, name="fill_fee_period_end")
        if aware_datetime(through) <= aware_datetime(after):
            raise RuntimeLedgerError("fill_fee_period_invalid")
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT fee_asset,COALESCE(SUM(fee),0) total FROM fills "
                "WHERE occurred_at > ? AND occurred_at <= ? GROUP BY fee_asset ",
                (after, through),
            ).fetchall()
        return {str(row["fee_asset"]): float(row["total"]) for row in rows}

    def _period_cash_components(
        self,
        connection: sqlite3.Connection,
        *,
        after: str | None,
        through: str,
    ) -> tuple[float, float, float]:
        range_sql = "occurred_at <= ?" if after is None else "occurred_at > ? AND occurred_at <= ?"
        parameters: Sequence[object] = (through,) if after is None else (after, through)
        cash = connection.execute(
            f"SELECT event_type,COALESCE(SUM(amount),0) total FROM cash_events "
            f"WHERE {range_sql} GROUP BY event_type",
            parameters,
        ).fetchall()
        by_type = {str(row["event_type"]): float(row["total"]) for row in cash}
        fill_fees = float(
            connection.execute(
                f"SELECT COALESCE(SUM(fee),0) FROM fills WHERE {range_sql}",
                parameters,
            ).fetchone()[0]
        )
        return (
            by_type.get("funding", 0.0),
            by_type.get("fee", 0.0) + fill_fees,
            by_type.get("transfer", 0.0),
        )

    def record_nav_mark(
        self,
        *,
        marked_at: str,
        equity: float,
        trading_pnl: float,
        residual_tolerance: float,
        source_hash: str,
        opening_equity: float | None = None,
        signal_nav: float | None = None,
        standalone_executable_nav: float | None = None,
    ) -> NavMark:
        marked_at = _time(marked_at, name="nav_mark_time")
        equity = _finite(equity, name="nav_equity", minimum=0.0)
        trading_pnl = _finite(trading_pnl, name="nav_trading_pnl")
        tolerance = _finite(
            residual_tolerance, name="nav_residual_tolerance", minimum=0.0
        )
        _source_hash(source_hash)
        for name, value in (
            ("signal_nav", signal_nav),
            ("standalone_executable_nav", standalone_executable_nav),
        ):
            if value is not None and _finite(value, name=name, minimum=0.0) <= 0.0:
                raise RuntimeLedgerError(f"{name}_invalid")
        result: NavMark
        with self._transaction() as connection:
            same_time = connection.execute(
                "SELECT * FROM nav_marks WHERE marked_at = ?", (marked_at,)
            ).fetchone()
            previous = connection.execute(
                "SELECT * FROM nav_marks WHERE marked_at < ? ORDER BY marked_at DESC LIMIT 1",
                (marked_at,),
            ).fetchone()
            if same_time is not None:
                result = self._nav_mark_from_row(same_time)
                if (
                    result.equity != equity
                    or result.trading_pnl != trading_pnl
                    or result.residual_tolerance != tolerance
                    or result.source_hash != source_hash
                    or result.signal_nav != signal_nav
                    or result.standalone_executable_nav
                    != standalone_executable_nav
                    or (
                        opening_equity is not None
                        and result.previous_equity != float(opening_equity)
                    )
                ):
                    raise RuntimeLedgerConflictError("nav_mark_conflict")
                return result
            later = connection.execute(
                "SELECT 1 FROM nav_marks WHERE marked_at > ? LIMIT 1", (marked_at,)
            ).fetchone()
            if later is not None:
                raise RuntimeLedgerError("nav_mark_time_regression")
            if previous is None:
                if opening_equity is None:
                    raise RuntimeLedgerError("nav_opening_equity_required")
                previous_equity = _finite(
                    opening_equity, name="nav_opening_equity", minimum=0.0
                )
                previous_time = None
                cumulative = (0.0, 0.0, 0.0, 0.0)
            else:
                if opening_equity is not None:
                    raise RuntimeLedgerError("nav_opening_equity_unexpected")
                previous_equity = float(previous["equity"])
                previous_time = str(previous["marked_at"])
                cumulative = (
                    float(previous["trading_pnl_cumulative"]),
                    float(previous["funding_cumulative"]),
                    float(previous["fees_cumulative"]),
                    float(previous["transfers_cumulative"]),
                )
            funding, fees, transfers = self._period_cash_components(
                connection,
                after=previous_time,
                through=marked_at,
            )
            equity_change = equity - previous_equity
            residual = equity_change - trading_pnl - funding + fees - transfers
            passed = abs(residual) <= tolerance
            core = {
                "marked_at": marked_at,
                "previous_equity": previous_equity,
                "equity": equity,
                "equity_change": equity_change,
                "trading_pnl": trading_pnl,
                "funding": funding,
                "fees": fees,
                "transfers": transfers,
                "residual": residual,
                "residual_tolerance": tolerance,
                "passed": passed,
                "trading_pnl_cumulative": cumulative[0] + trading_pnl,
                "funding_cumulative": cumulative[1] + funding,
                "fees_cumulative": cumulative[2] + fees,
                "transfers_cumulative": cumulative[3] + transfers,
                "signal_nav": signal_nav,
                "standalone_executable_nav": standalone_executable_nav,
                "source_hash": source_hash,
            }
            mark_hash = canonical_hash(core)
            nav_mark_id = trace_id(
                "nav_mark", {"marked_at": marked_at, "mark_hash": mark_hash}
            )
            result = NavMark(
                nav_mark_id=nav_mark_id,
                mark_hash=mark_hash,
                **core,
            )
            connection.execute(
                "INSERT INTO nav_marks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                tuple(result.as_dict().values()),
            )
            self._queue_outbox(
                connection,
                event_type="nav_mark_recorded",
                entity_type="nav_mark",
                entity_id=nav_mark_id,
                occurred_at=marked_at,
                payload=result.as_dict(),
            )
        self._after_commit()
        return result

    @staticmethod
    def _nav_mark_from_row(row: sqlite3.Row) -> NavMark:
        return NavMark(
            nav_mark_id=str(row["nav_mark_id"]),
            marked_at=str(row["marked_at"]),
            previous_equity=float(row["previous_equity"]),
            equity=float(row["equity"]),
            equity_change=float(row["equity_change"]),
            trading_pnl=float(row["trading_pnl"]),
            funding=float(row["funding"]),
            fees=float(row["fees"]),
            transfers=float(row["transfers"]),
            residual=float(row["residual"]),
            residual_tolerance=float(row["residual_tolerance"]),
            passed=bool(row["passed"]),
            trading_pnl_cumulative=float(row["trading_pnl_cumulative"]),
            funding_cumulative=float(row["funding_cumulative"]),
            fees_cumulative=float(row["fees_cumulative"]),
            transfers_cumulative=float(row["transfers_cumulative"]),
            signal_nav=(float(row["signal_nav"]) if row["signal_nav"] is not None else None),
            standalone_executable_nav=(
                float(row["standalone_executable_nav"])
                if row["standalone_executable_nav"] is not None
                else None
            ),
            source_hash=str(row["source_hash"]),
            mark_hash=str(row["mark_hash"]),
        )

    def latest_nav_mark(self) -> NavMark | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM nav_marks ORDER BY marked_at DESC LIMIT 1"
            ).fetchone()
        return None if row is None else self._nav_mark_from_row(row)

    def record_account_observation(
        self,
        *,
        batch_id: str,
        observed_at: str,
        quote_asset: str,
        wallet_balance: float,
        available_balance: float,
        actual_gross_notional: float,
        margin_used: float,
        source_id: str,
        source_hash: str,
    ) -> AccountObservation:
        """Persist one read-only account observation before reconciliation."""

        if not is_sha256(batch_id):
            raise RuntimeLedgerError("account_observation_batch_id_invalid")
        observed_at = _time(observed_at, name="account_observation_time")
        if not isinstance(quote_asset, str) or not re.fullmatch(
            r"[A-Z0-9]{2,16}", quote_asset
        ):
            raise RuntimeLedgerError("account_observation_quote_asset_invalid")
        wallet_balance = _finite(
            wallet_balance, name="account_wallet_balance", minimum=0.0
        )
        available_balance = _finite(
            available_balance, name="account_available_balance", minimum=0.0
        )
        actual_gross_notional = _finite(
            actual_gross_notional,
            name="account_actual_gross_notional",
            minimum=0.0,
        )
        margin_used = _finite(
            margin_used, name="account_margin_used", minimum=0.0
        )
        for name, value in (("source_id", source_id), ("source_hash", source_hash)):
            if not is_sha256(value):
                raise RuntimeLedgerError(f"account_observation_{name}_invalid")
        core = {
            "batch_id": batch_id,
            "observed_at": observed_at,
            "quote_asset": quote_asset,
            "wallet_balance": wallet_balance,
            "available_balance": available_balance,
            "actual_gross_notional": actual_gross_notional,
            "margin_used": margin_used,
            "source_id": source_id,
            "source_hash": source_hash,
        }
        observation_hash = canonical_hash(core)
        result = AccountObservation(
            account_observation_id=trace_id(
                "account_observation",
                {"observed_at": observed_at, "observation_hash": observation_hash},
            ),
            observation_hash=observation_hash,
            **core,
        )
        with self._transaction() as connection:
            if connection.execute(
                "SELECT 1 FROM batches WHERE batch_id = ?", (batch_id,)
            ).fetchone() is None:
                raise RuntimeLedgerError("account_observation_batch_missing")
            existing = connection.execute(
                "SELECT * FROM account_observations WHERE observed_at = ?",
                (observed_at,),
            ).fetchone()
            if existing is not None:
                current = self._account_observation_from_row(existing)
                if current != result:
                    raise RuntimeLedgerConflictError("account_observation_conflict")
                return current
            if connection.execute(
                "SELECT 1 FROM account_observations WHERE observed_at > ? LIMIT 1",
                (observed_at,),
            ).fetchone() is not None:
                raise RuntimeLedgerError("account_observation_time_regression")
            connection.execute(
                "INSERT INTO account_observations VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                tuple(result.as_dict().values()),
            )
            self._queue_outbox(
                connection,
                event_type="account_observation_recorded",
                entity_type="account_observation",
                entity_id=result.account_observation_id,
                occurred_at=observed_at,
                payload=result.as_dict(),
            )
        self._after_commit()
        return result

    @staticmethod
    def _account_observation_from_row(row: sqlite3.Row) -> AccountObservation:
        return AccountObservation(
            account_observation_id=str(row["account_observation_id"]),
            batch_id=str(row["batch_id"]),
            observed_at=str(row["observed_at"]),
            quote_asset=str(row["quote_asset"]),
            wallet_balance=float(row["wallet_balance"]),
            available_balance=float(row["available_balance"]),
            actual_gross_notional=float(row["actual_gross_notional"]),
            margin_used=float(row["margin_used"]),
            source_id=str(row["source_id"]),
            source_hash=str(row["source_hash"]),
            observation_hash=str(row["observation_hash"]),
        )

    def latest_account_observation(self) -> AccountObservation | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM account_observations ORDER BY observed_at DESC LIMIT 1"
            ).fetchone()
        return None if row is None else self._account_observation_from_row(row)

    def record_reconciliation(self, report: ThreeWayReconciliation) -> bool:
        report.validate()
        payload = report.as_dict()
        payload_json = _json_text(payload)
        created = False
        with self._transaction() as connection:
            batch = connection.execute(
                "SELECT expected_positions_json,reconciliation_tolerance_json "
                "FROM batches WHERE batch_id = ?",
                (report.batch_id,),
            ).fetchone()
            if batch is None:
                raise RuntimeLedgerError("reconciliation_batch_missing")
            expected_positions = _json_object(
                str(batch["expected_positions_json"]),
                name="ledger_expected_positions",
            )
            expected_tolerances = _json_object(
                str(batch["reconciliation_tolerance_json"]),
                name="ledger_reconciliation_tolerances",
            )
            ledger_positions = {
                str(row["symbol"]): float(row["quantity"])
                for row in connection.execute(
                    "SELECT symbol,quantity FROM positions ORDER BY symbol"
                )
            }
            placeholders = ",".join("?" for _ in _OPEN_ORDER_STATUSES)
            ledger_orders = tuple(
                str(row["client_order_id"])
                for row in connection.execute(
                    f"SELECT client_order_id FROM orders WHERE status IN ({placeholders}) "
                    "ORDER BY client_order_id",
                    _OPEN_ORDER_STATUSES,
                )
            )
            nav = connection.execute(
                "SELECT marked_at,residual,residual_tolerance FROM nav_marks "
                "ORDER BY marked_at DESC LIMIT 1"
            ).fetchone()
            if nav is None:
                raise RuntimeLedgerError("reconciliation_nav_mark_missing")
            if aware_datetime(report.reconciled_at) < aware_datetime(
                str(nav["marked_at"])
            ):
                raise RuntimeLedgerError("reconciliation_before_nav_mark")
            previous_reconciliation = connection.execute(
                "SELECT reconciled_at FROM reconciliations ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            if (
                previous_reconciliation is not None
                and aware_datetime(report.reconciled_at)
                < aware_datetime(str(previous_reconciliation["reconciled_at"]))
            ):
                raise RuntimeLedgerError("reconciliation_time_regression")
            authoritative_target = (
                ledger_positions
                if report.phase == "pre_dispatch"
                else expected_positions
            )
            if dict(report.target_positions) != authoritative_target:
                raise RuntimeLedgerError("reconciliation_target_not_phase_authoritative")
            if dict(report.position_tolerances) != expected_tolerances:
                raise RuntimeLedgerError("reconciliation_tolerance_not_batch_authoritative")
            if dict(report.ledger_positions) != ledger_positions:
                raise RuntimeLedgerError("reconciliation_positions_not_ledger_authoritative")
            if report.ledger_open_order_ids != ledger_orders:
                raise RuntimeLedgerError("reconciliation_orders_not_ledger_authoritative")
            if (
                report.equity_residual != float(nav["residual"])
                or report.equity_residual_tolerance
                != float(nav["residual_tolerance"])
            ):
                raise RuntimeLedgerError("reconciliation_residual_not_ledger_authoritative")
            existing = connection.execute(
                "SELECT payload_json FROM reconciliations WHERE reconciliation_id = ?",
                (report.reconciliation_id,),
            ).fetchone()
            if existing is not None:
                if existing["payload_json"] != payload_json:
                    raise RuntimeLedgerConflictError("reconciliation_conflict")
            else:
                connection.execute(
                    "INSERT INTO reconciliations VALUES (?,?,?,?,?,?,?,?)",
                    (
                        report.reconciliation_id,
                        report.batch_id,
                        report.reconciled_at,
                        report.report_hash,
                        payload_json,
                        int(report.passed),
                        int(report.risk_increase_allowed),
                        int(report.halt_required),
                    ),
                )
                self._queue_outbox(
                    connection,
                    event_type="reconciliation_recorded",
                    entity_type="reconciliation",
                    entity_id=report.reconciliation_id,
                    occurred_at=report.reconciled_at,
                    payload=payload,
                )
                created = True
        self._after_commit()
        return created

    def risk_increase_allowed(self) -> bool:
        with self._connection() as connection:
            unresolved = connection.execute(
                "SELECT 1 FROM orders WHERE status IN "
                "('SUBMITTING','PARTIALLY_FILLED','UNKNOWN') LIMIT 1"
            ).fetchone()
            nav = connection.execute(
                "SELECT passed FROM nav_marks ORDER BY marked_at DESC LIMIT 1"
            ).fetchone()
            reconciliation = connection.execute(
                "SELECT risk_increase_allowed FROM reconciliations "
                "ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        return bool(
            unresolved is None
            and nav is not None
            and bool(nav["passed"])
            and reconciliation is not None
            and bool(reconciliation["risk_increase_allowed"])
        )

    def integrity_check(self) -> dict[str, Any]:
        with self._connection() as connection:
            integrity = tuple(
                str(row[0]) for row in connection.execute("PRAGMA integrity_check")
            )
            foreign_keys = tuple(connection.execute("PRAGMA foreign_key_check"))
            outbox = connection.execute(
                "SELECT * FROM audit_outbox ORDER BY sequence"
            ).fetchall()
            journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
            foreign_keys_enabled = int(
                connection.execute("PRAGMA foreign_keys").fetchone()[0]
            )
            synchronous = int(connection.execute("PRAGMA synchronous").fetchone()[0])
        if integrity != ("ok",):
            raise RuntimeLedgerError("ledger_integrity_check_failed")
        if foreign_keys:
            raise RuntimeLedgerError("ledger_foreign_key_check_failed")
        expected_rows = [self._audit_row_from_outbox(row) for row in outbox]
        previous_hash = "0" * 64
        for index, row in enumerate(expected_rows, 1):
            if row["sequence"] != index or row["previous_hash"] != previous_hash:
                raise RuntimeLedgerError("audit_outbox_chain_invalid")
            previous_hash = str(row["row_hash"])
        journal = verify_audit_journal(self.audit_path)
        if journal.last_sequence != len(expected_rows):
            raise RuntimeLedgerError("audit_outbox_not_fully_published")
        for sequence, expected in enumerate(expected_rows, 1):
            if journal.rows_by_sequence[sequence] != expected:
                raise RuntimeLedgerError(
                    f"audit_journal_outbox_mismatch:{sequence}"
                )
        if any(row["published_at"] is None for row in outbox):
            raise RuntimeLedgerError("audit_outbox_publish_marker_missing")
        if journal_mode.lower() != "wal" or not foreign_keys_enabled or synchronous != 2:
            raise RuntimeLedgerError("ledger_pragma_invalid")
        return {
            "integrity": "ok",
            "journal_mode": journal_mode.lower(),
            "foreign_keys": True,
            "synchronous": "full",
            "audit_rows": len(expected_rows),
            "audit_last_hash": journal.last_hash,
        }
