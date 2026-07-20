"""Durable SQLite notification outbox and delivery audit."""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sqlite3
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

from qount.contracts import canonical_hash
from qount.contracts import is_sha256
from qount.contracts import trace_id
from qount.contracts.trace import aware_datetime
from qount.notifications.contracts import AlertEvent
from qount.notifications.contracts import ALERT_SOURCE_TYPES


DELIVERY_STATES = ("PENDING", "RETRY_WAIT", "DELIVERED", "DEAD_LETTER")
ATTEMPT_STATES = ("STARTED", "SUCCEEDED", "FAILED")
ALERT_STATES = ("OPEN", "RESOLVED")
_CHANNEL_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")


class NotificationStoreError(ValueError):
    """Raised when notification state is invalid or cannot be verified."""


class NotificationStoreConflictError(NotificationStoreError):
    """Raised when an immutable notification identity changes content."""


class NotificationStoreSecurityError(NotificationStoreError):
    """Raised when private store path constraints are violated."""


Transport = Callable[[Mapping[str, Any], str], Mapping[str, Any] | None]
AfterTransport = Callable[[str, int], None]


def _utc_time(value: str, *, name: str) -> str:
    try:
        parsed = aware_datetime(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise NotificationStoreError(f"{name}_invalid") from exc
    return parsed.astimezone(dt.timezone.utc).isoformat()


def _json_text(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def _json_object(raw: str, *, name: str) -> dict[str, Any]:
    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise NotificationStoreError(f"{name}_duplicate_key:{key}")
            value[key] = item
        return value

    try:
        value = json.loads(raw, object_pairs_hook=reject_duplicate)
    except NotificationStoreError:
        raise
    except json.JSONDecodeError as exc:
        raise NotificationStoreError(f"{name}_invalid") from exc
    if not isinstance(value, dict) or _json_text(value) != raw:
        raise NotificationStoreError(f"{name}_not_canonical")
    return value


def _prepare_private_parent(path: Path) -> None:
    parent = path.parent
    if parent.is_symlink():
        raise NotificationStoreSecurityError(
            "notification_state_directory_symlink_forbidden"
        )
    existed = parent.exists()
    parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if not existed:
        os.chmod(parent, 0o700)
    if not parent.is_dir():
        raise NotificationStoreSecurityError(
            "notification_state_directory_invalid"
        )
    if stat.S_IMODE(os.stat(parent, follow_symlinks=False).st_mode) & 0o077:
        raise NotificationStoreSecurityError(
            "notification_state_directory_mode_invalid"
        )


def _state_hash(
    *, alert_id: str, status: str, resolved_at: str | None
) -> str:
    return canonical_hash(
        {
            "alert_id": alert_id,
            "status": status,
            "resolved_at": resolved_at,
        }
    )


def _job_core(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        name: row[name]
        for name in (
            "job_id",
            "alert_id",
            "channel",
            "delivery_key",
            "status",
            "attempt_count",
            "max_attempts",
            "next_attempt_at",
            "last_attempt_at",
            "delivered_at",
            "last_error",
        )
    }


def _attempt_core(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        name: row[name]
        for name in (
            "attempt_id",
            "job_id",
            "attempt_number",
            "started_at",
            "completed_at",
            "status",
            "response_hash",
            "error_type",
        )
    }


class NotificationStore:
    """Single-writer notification store; delivery transport is always injected."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        busy_timeout_ms: int = 5_000,
    ) -> None:
        self.database_path = Path(database_path)
        if busy_timeout_ms < 1:
            raise ValueError("notification_busy_timeout_invalid")
        self.busy_timeout_ms = int(busy_timeout_ms)
        self._prepare_path()
        self._initialize()

    def _prepare_path(self) -> None:
        _prepare_private_parent(self.database_path)
        if self.database_path.is_symlink():
            raise NotificationStoreSecurityError(
                "notification_database_symlink_forbidden"
            )
        if self.database_path.exists():
            if not self.database_path.is_file():
                raise NotificationStoreSecurityError(
                    "notification_database_path_invalid"
                )
            if stat.S_IMODE(
                os.stat(self.database_path, follow_symlinks=False).st_mode
            ) != 0o600:
                raise NotificationStoreSecurityError(
                    "notification_database_mode_invalid"
                )
        for suffix in ("-wal", "-shm"):
            if Path(f"{self.database_path}{suffix}").is_symlink():
                raise NotificationStoreSecurityError(
                    "notification_sidecar_symlink_forbidden"
                )

    def _secure_runtime_files(self) -> None:
        for path in (
            self.database_path,
            Path(f"{self.database_path}-wal"),
            Path(f"{self.database_path}-shm"),
        ):
            if path.exists():
                if path.is_symlink() or not path.is_file():
                    raise NotificationStoreSecurityError(
                        "notification_runtime_file_invalid"
                    )
                os.chmod(path, 0o600)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        self._prepare_path()
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
        delivery_sql = ",".join(f"'{value}'" for value in DELIVERY_STATES)
        attempt_sql = ",".join(f"'{value}'" for value in ATTEMPT_STATES)
        alert_sql = ",".join(f"'{value}'" for value in ALERT_STATES)
        with self._connection() as connection:
            mode = str(connection.execute("PRAGMA journal_mode = WAL").fetchone()[0])
            if mode.lower() != "wal":
                raise NotificationStoreError("notification_wal_not_enabled")
            connection.executescript(
                f"""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS schema_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS alert_events (
                    alert_id TEXT PRIMARY KEY,
                    event_hash TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    dedupe_key TEXT NOT NULL UNIQUE,
                    recorded_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS alert_states (
                    alert_id TEXT PRIMARY KEY REFERENCES alert_events(alert_id),
                    status TEXT NOT NULL CHECK(status IN ({alert_sql})),
                    resolved_at TEXT,
                    state_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS delivery_jobs (
                    job_id TEXT PRIMARY KEY,
                    alert_id TEXT NOT NULL REFERENCES alert_events(alert_id),
                    channel TEXT NOT NULL,
                    delivery_key TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL CHECK(status IN ({delivery_sql})),
                    attempt_count INTEGER NOT NULL CHECK(attempt_count >= 0),
                    max_attempts INTEGER NOT NULL CHECK(max_attempts >= 1),
                    next_attempt_at TEXT,
                    last_attempt_at TEXT,
                    delivered_at TEXT,
                    last_error TEXT,
                    job_hash TEXT NOT NULL,
                    UNIQUE(alert_id, channel)
                );
                CREATE TABLE IF NOT EXISTS delivery_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES delivery_jobs(job_id),
                    attempt_number INTEGER NOT NULL CHECK(attempt_number >= 1),
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    status TEXT NOT NULL CHECK(status IN ({attempt_sql})),
                    response_hash TEXT,
                    error_type TEXT,
                    attempt_hash TEXT NOT NULL,
                    UNIQUE(job_id, attempt_number)
                );
                CREATE TABLE IF NOT EXISTS notification_audit (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT,
                    row_hash TEXT NOT NULL UNIQUE
                );
                INSERT OR IGNORE INTO schema_metadata(key, value)
                VALUES ('schema_version', '1');
                COMMIT;
                """
            )
            version = connection.execute(
                "SELECT value FROM schema_metadata WHERE key='schema_version'"
            ).fetchone()
            if version is None or version[0] != "1":
                raise NotificationStoreError("notification_schema_version_invalid")
        self._secure_runtime_files()

    def _append_audit(
        self,
        connection: sqlite3.Connection,
        *,
        event_type: str,
        entity_id: str,
        occurred_at: str,
        payload: Mapping[str, Any],
    ) -> str:
        previous = connection.execute(
            "SELECT sequence, row_hash FROM notification_audit ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        sequence = 1 if previous is None else int(previous["sequence"]) + 1
        previous_hash = None if previous is None else str(previous["row_hash"])
        payload_json = _json_text(payload)
        row_hash = canonical_hash(
            {
                "sequence": sequence,
                "event_type": event_type,
                "entity_id": entity_id,
                "occurred_at": occurred_at,
                "payload": dict(payload),
                "previous_hash": previous_hash,
            }
        )
        connection.execute(
            """
            INSERT INTO notification_audit(
                sequence,event_type,entity_id,occurred_at,payload_json,
                previous_hash,row_hash
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (
                sequence,
                event_type,
                entity_id,
                occurred_at,
                payload_json,
                previous_hash,
                row_hash,
            ),
        )
        return row_hash

    def enqueue(
        self,
        alert: AlertEvent,
        *,
        channels: Sequence[str] = ("webhook",),
        recorded_at: str,
        max_attempts: int = 3,
    ) -> tuple[str, ...]:
        if not isinstance(alert, AlertEvent):
            raise TypeError("notification_alert_event_required")
        alert.validate()
        recorded_at = _utc_time(recorded_at, name="notification_recorded_at")
        if aware_datetime(recorded_at) < aware_datetime(alert.occurred_at):
            raise NotificationStoreError("notification_recorded_before_alert")
        if (
            not isinstance(max_attempts, int)
            or isinstance(max_attempts, bool)
            or not 1 <= max_attempts <= 20
        ):
            raise NotificationStoreError("notification_max_attempts_invalid")
        normalized_channels = tuple(channels)
        if (
            not normalized_channels
            or len(normalized_channels) != len(set(normalized_channels))
            or any(
                not isinstance(channel, str)
                or not _CHANNEL_RE.fullmatch(channel)
                for channel in normalized_channels
            )
        ):
            raise NotificationStoreError("notification_channels_invalid")
        normalized_channels = tuple(sorted(normalized_channels))
        payload_json = _json_text(alert.as_dict())
        job_ids: list[str] = []
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT payload_json FROM alert_events WHERE alert_id=?",
                (alert.alert_id,),
            ).fetchone()
            inserted_alert = existing is None
            if existing is not None and str(existing["payload_json"]) != payload_json:
                raise NotificationStoreConflictError(
                    "notification_alert_identity_conflict"
                )
            if inserted_alert:
                try:
                    connection.execute(
                        """
                        INSERT INTO alert_events(
                            alert_id,event_hash,payload_json,occurred_at,
                            source_hash,dedupe_key,recorded_at
                        ) VALUES (?,?,?,?,?,?,?)
                        """,
                        (
                            alert.alert_id,
                            alert.event_hash,
                            payload_json,
                            alert.occurred_at,
                            alert.source_hash,
                            alert.dedupe_key,
                            recorded_at,
                        ),
                    )
                except sqlite3.IntegrityError as exc:
                    raise NotificationStoreConflictError(
                        "notification_alert_dedupe_conflict"
                    ) from exc
                state_hash = _state_hash(
                    alert_id=alert.alert_id,
                    status="OPEN",
                    resolved_at=None,
                )
                connection.execute(
                    "INSERT INTO alert_states(alert_id,status,resolved_at,state_hash) VALUES (?,?,?,?)",
                    (alert.alert_id, "OPEN", None, state_hash),
                )
                self._append_audit(
                    connection,
                    event_type="alert_enqueued",
                    entity_id=alert.alert_id,
                    occurred_at=recorded_at,
                    payload={
                        "event_hash": alert.event_hash,
                        "state_hash": state_hash,
                    },
                )
            for channel in normalized_channels:
                job_id = trace_id(
                    "notification_job",
                    {"alert_id": alert.alert_id, "channel": channel},
                )
                delivery_key = trace_id(
                    "notification_delivery",
                    {"job_id": job_id, "event_hash": alert.event_hash},
                )
                job_ids.append(job_id)
                job_core = {
                    "job_id": job_id,
                    "alert_id": alert.alert_id,
                    "channel": channel,
                    "delivery_key": delivery_key,
                    "status": "PENDING",
                    "attempt_count": 0,
                    "max_attempts": max_attempts,
                    "next_attempt_at": recorded_at,
                    "last_attempt_at": None,
                    "delivered_at": None,
                    "last_error": None,
                }
                existing_job = connection.execute(
                    "SELECT * FROM delivery_jobs WHERE job_id=?", (job_id,)
                ).fetchone()
                if existing_job is not None:
                    if (
                        int(existing_job["max_attempts"]) != max_attempts
                        or str(existing_job["delivery_key"]) != delivery_key
                    ):
                        raise NotificationStoreConflictError(
                            "notification_job_identity_conflict"
                        )
                    continue
                job_hash = canonical_hash(job_core)
                connection.execute(
                    """
                    INSERT INTO delivery_jobs(
                        job_id,alert_id,channel,delivery_key,status,
                        attempt_count,max_attempts,next_attempt_at,last_attempt_at,
                        delivered_at,last_error,job_hash
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (*job_core.values(), job_hash),
                )
                self._append_audit(
                    connection,
                    event_type="delivery_queued",
                    entity_id=job_id,
                    occurred_at=recorded_at,
                    payload={"job_hash": job_hash, "delivery_key": delivery_key},
                )
        return tuple(job_ids)

    def resolve_alert(self, alert_id: str, *, resolved_at: str) -> None:
        resolved_at = _utc_time(resolved_at, name="notification_resolved_at")
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM alert_states WHERE alert_id=?", (alert_id,)
            ).fetchone()
            if row is None:
                raise NotificationStoreError("notification_alert_missing")
            if row["status"] == "RESOLVED":
                if row["resolved_at"] != resolved_at:
                    raise NotificationStoreConflictError(
                        "notification_resolution_conflict"
                    )
                return
            event = connection.execute(
                "SELECT occurred_at FROM alert_events WHERE alert_id=?", (alert_id,)
            ).fetchone()
            if aware_datetime(resolved_at) < aware_datetime(event["occurred_at"]):
                raise NotificationStoreError("notification_resolved_before_alert")
            state_hash = _state_hash(
                alert_id=alert_id,
                status="RESOLVED",
                resolved_at=resolved_at,
            )
            connection.execute(
                "UPDATE alert_states SET status='RESOLVED',resolved_at=?,state_hash=? WHERE alert_id=?",
                (resolved_at, state_hash, alert_id),
            )
            self._append_audit(
                connection,
                event_type="alert_resolved",
                entity_id=alert_id,
                occurred_at=resolved_at,
                payload={"state_hash": state_hash},
            )

    def resolve_superseded_alerts(
        self,
        *,
        active_alert_ids: Sequence[str],
        source_type: str,
        categories: Sequence[str],
        resolved_at: str,
    ) -> tuple[str, ...]:
        """Resolve open incidents in one explicit producer scope.

        Active alerts must already be durable in this store. An empty active set is
        valid and closes the scope after a healthy producer observation.
        """

        resolved_at = _utc_time(
            resolved_at, name="notification_supersession_time"
        )
        normalized_active = tuple(sorted(active_alert_ids))
        normalized_categories = tuple(sorted(categories))
        if source_type not in ALERT_SOURCE_TYPES:
            raise NotificationStoreError(
                "notification_supersession_source_type_invalid"
            )
        if (
            len(normalized_active) != len(set(normalized_active))
            or any(not is_sha256(value) for value in normalized_active)
        ):
            raise NotificationStoreError(
                "notification_supersession_active_ids_invalid"
            )
        if (
            not normalized_categories
            or len(normalized_categories) != len(set(normalized_categories))
            or any(
                not isinstance(category, str)
                or not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", category)
                for category in normalized_categories
            )
        ):
            raise NotificationStoreError(
                "notification_supersession_categories_invalid"
            )
        resolved_ids: list[str] = []
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT event.alert_id,event.payload_json,state.status "
                "FROM alert_events event JOIN alert_states state "
                "ON state.alert_id=event.alert_id"
            ).fetchall()
            scoped: dict[str, AlertEvent] = {}
            for row in rows:
                payload = _json_object(
                    str(row["payload_json"]),
                    name="notification_supersession_alert",
                )
                try:
                    alert = AlertEvent(**payload)
                    alert.validate()
                except (TypeError, ValueError) as exc:
                    raise NotificationStoreError(
                        "notification_supersession_alert_invalid"
                    ) from exc
                if (
                    alert.source_type == source_type
                    and alert.category in normalized_categories
                ):
                    scoped[alert.alert_id] = alert
            if any(alert_id not in scoped for alert_id in normalized_active):
                raise NotificationStoreError(
                    "notification_supersession_active_alert_missing"
                )
            active = set(normalized_active)
            for row in rows:
                alert_id = str(row["alert_id"])
                if (
                    alert_id not in scoped
                    or alert_id in active
                    or row["status"] != "OPEN"
                ):
                    continue
                alert = scoped[alert_id]
                if aware_datetime(resolved_at) < aware_datetime(alert.occurred_at):
                    raise NotificationStoreError(
                        "notification_supersession_before_alert"
                    )
                state_hash = _state_hash(
                    alert_id=alert_id,
                    status="RESOLVED",
                    resolved_at=resolved_at,
                )
                connection.execute(
                    "UPDATE alert_states SET status='RESOLVED',resolved_at=?,"
                    "state_hash=? WHERE alert_id=?",
                    (resolved_at, state_hash, alert_id),
                )
                self._append_audit(
                    connection,
                    event_type="alert_superseded",
                    entity_id=alert_id,
                    occurred_at=resolved_at,
                    payload={
                        "state_hash": state_hash,
                        "source_type": source_type,
                        "categories": normalized_categories,
                        "active_alert_ids": normalized_active,
                    },
                )
                resolved_ids.append(alert_id)
        return tuple(sorted(resolved_ids))

    def _claim_job(self, job_id: str, *, attempted_at: str) -> dict[str, Any] | None:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM delivery_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None or row["status"] not in {"PENDING", "RETRY_WAIT"}:
                return None
            if row["next_attempt_at"] is None or aware_datetime(
                str(row["next_attempt_at"])
            ) > aware_datetime(attempted_at):
                return None
            started_attempt = connection.execute(
                """
                SELECT * FROM delivery_attempts
                WHERE job_id=? AND status='STARTED'
                ORDER BY attempt_number DESC LIMIT 1
                """,
                (job_id,),
            ).fetchone()
            alert_row = connection.execute(
                "SELECT payload_json FROM alert_events WHERE alert_id=?",
                (row["alert_id"],),
            ).fetchone()
            if started_attempt is not None:
                return {
                    "job_id": job_id,
                    "attempt_id": str(started_attempt["attempt_id"]),
                    "attempt_number": int(started_attempt["attempt_number"]),
                    "delivery_key": str(row["delivery_key"]),
                    "max_attempts": int(row["max_attempts"]),
                    "alert": _json_object(
                        str(alert_row["payload_json"]),
                        name="notification_alert_payload",
                    ),
                }
            attempt_number = int(row["attempt_count"]) + 1
            if attempt_number > int(row["max_attempts"]):
                raise NotificationStoreConflictError(
                    "notification_attempt_limit_exceeded"
                )
            attempt_id = trace_id(
                "notification_attempt",
                {"job_id": job_id, "attempt_number": attempt_number},
            )
            attempt_core = {
                "attempt_id": attempt_id,
                "job_id": job_id,
                "attempt_number": attempt_number,
                "started_at": attempted_at,
                "completed_at": None,
                "status": "STARTED",
                "response_hash": None,
                "error_type": None,
            }
            attempt_hash = canonical_hash(attempt_core)
            connection.execute(
                """
                INSERT INTO delivery_attempts(
                    attempt_id,job_id,attempt_number,started_at,completed_at,
                    status,response_hash,error_type,attempt_hash
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (*attempt_core.values(), attempt_hash),
            )
            updated = dict(row)
            updated["attempt_count"] = attempt_number
            updated["last_attempt_at"] = attempted_at
            updated["last_error"] = None
            updated["job_hash"] = canonical_hash(_job_core(updated))
            connection.execute(
                """
                UPDATE delivery_jobs
                SET attempt_count=?,last_attempt_at=?,last_error=NULL,job_hash=?
                WHERE job_id=?
                """,
                (attempt_number, attempted_at, updated["job_hash"], job_id),
            )
            self._append_audit(
                connection,
                event_type="delivery_started",
                entity_id=attempt_id,
                occurred_at=attempted_at,
                payload={
                    "attempt_hash": attempt_hash,
                    "delivery_key": row["delivery_key"],
                    "job_hash": updated["job_hash"],
                },
            )
            return {
                "job_id": job_id,
                "attempt_id": attempt_id,
                "attempt_number": attempt_number,
                "delivery_key": str(row["delivery_key"]),
                "max_attempts": int(row["max_attempts"]),
                "alert": _json_object(
                    str(alert_row["payload_json"]), name="notification_alert_payload"
                ),
            }

    def _complete_attempt(
        self,
        claim: Mapping[str, Any],
        *,
        completed_at: str,
        response: Mapping[str, Any] | None = None,
        error: Exception | None = None,
        retry_base_seconds: int,
    ) -> str:
        with self._transaction() as connection:
            attempt = connection.execute(
                "SELECT * FROM delivery_attempts WHERE attempt_id=?",
                (claim["attempt_id"],),
            ).fetchone()
            job = connection.execute(
                "SELECT * FROM delivery_jobs WHERE job_id=?", (claim["job_id"],)
            ).fetchone()
            if attempt is None or job is None or attempt["status"] != "STARTED":
                raise NotificationStoreConflictError(
                    "notification_attempt_completion_conflict"
                )
            if error is None:
                response_hash = canonical_hash(dict(response or {}))
                attempt_status = "SUCCEEDED"
                error_type = None
                job_status = "DELIVERED"
                next_attempt_at = None
                delivered_at = completed_at
                last_error = None
                event_type = "delivery_succeeded"
            else:
                response_hash = None
                attempt_status = "FAILED"
                error_type = type(error).__name__[:120]
                exhausted = int(job["attempt_count"]) >= int(job["max_attempts"])
                job_status = "DEAD_LETTER" if exhausted else "RETRY_WAIT"
                next_attempt_at = (
                    None
                    if exhausted
                    else (
                        aware_datetime(completed_at)
                        + dt.timedelta(
                            seconds=retry_base_seconds
                            * (2 ** (int(job["attempt_count"]) - 1))
                        )
                    ).isoformat()
                )
                delivered_at = None
                last_error = error_type
                event_type = (
                    "delivery_dead_lettered"
                    if exhausted
                    else "delivery_retry_scheduled"
                )
            attempt_updated = dict(attempt)
            attempt_updated.update(
                {
                    "completed_at": completed_at,
                    "status": attempt_status,
                    "response_hash": response_hash,
                    "error_type": error_type,
                }
            )
            attempt_hash = canonical_hash(_attempt_core(attempt_updated))
            connection.execute(
                """
                UPDATE delivery_attempts
                SET completed_at=?,status=?,response_hash=?,error_type=?,attempt_hash=?
                WHERE attempt_id=?
                """,
                (
                    completed_at,
                    attempt_status,
                    response_hash,
                    error_type,
                    attempt_hash,
                    claim["attempt_id"],
                ),
            )
            job_updated = dict(job)
            job_updated.update(
                {
                    "status": job_status,
                    "next_attempt_at": next_attempt_at,
                    "delivered_at": delivered_at,
                    "last_error": last_error,
                }
            )
            job_hash = canonical_hash(_job_core(job_updated))
            connection.execute(
                """
                UPDATE delivery_jobs
                SET status=?,next_attempt_at=?,delivered_at=?,last_error=?,job_hash=?
                WHERE job_id=?
                """,
                (
                    job_status,
                    next_attempt_at,
                    delivered_at,
                    last_error,
                    job_hash,
                    claim["job_id"],
                ),
            )
            self._append_audit(
                connection,
                event_type=event_type,
                entity_id=str(claim["attempt_id"]),
                occurred_at=completed_at,
                payload={
                    "attempt_hash": attempt_hash,
                    "job_hash": job_hash,
                    "response_hash": response_hash,
                    "error_type": error_type,
                },
            )
            return job_status

    def deliver_due(
        self,
        *,
        attempted_at: str,
        transport: Transport,
        limit: int = 100,
        retry_base_seconds: int = 60,
        after_transport: AfterTransport | None = None,
    ) -> tuple[Mapping[str, Any], ...]:
        attempted_at = _utc_time(attempted_at, name="notification_attempted_at")
        if not callable(transport):
            raise TypeError("notification_transport_required")
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit < 1
            or not isinstance(retry_base_seconds, int)
            or isinstance(retry_base_seconds, bool)
            or retry_base_seconds < 1
        ):
            raise NotificationStoreError("notification_delivery_options_invalid")
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT job_id FROM delivery_jobs
                WHERE status IN ('PENDING','RETRY_WAIT')
                  AND next_attempt_at <= ?
                ORDER BY next_attempt_at, job_id
                LIMIT ?
                """,
                (attempted_at, limit),
            ).fetchall()
        results: list[Mapping[str, Any]] = []
        for row in rows:
            claim = self._claim_job(str(row["job_id"]), attempted_at=attempted_at)
            if claim is None:
                continue
            try:
                response = transport(claim["alert"], str(claim["delivery_key"]))
                if response is not None and not isinstance(response, Mapping):
                    raise NotificationStoreError(
                        "notification_transport_response_invalid"
                    )
            except Exception as exc:
                status = self._complete_attempt(
                    claim,
                    completed_at=attempted_at,
                    error=exc,
                    retry_base_seconds=retry_base_seconds,
                )
            else:
                if after_transport is not None:
                    after_transport(
                        str(claim["job_id"]), int(claim["attempt_number"])
                    )
                status = self._complete_attempt(
                    claim,
                    completed_at=attempted_at,
                    response=response,
                    retry_base_seconds=retry_base_seconds,
                )
            results.append(
                {
                    "job_id": claim["job_id"],
                    "attempt_number": claim["attempt_number"],
                    "status": status,
                }
            )
        return tuple(results)

    def verified_rows(self) -> dict[str, Any]:
        """Read and verify all rows in one SQLite snapshot transaction."""

        with self._connection() as connection:
            connection.execute("BEGIN")
            events = connection.execute(
                "SELECT * FROM alert_events ORDER BY occurred_at DESC, alert_id"
            ).fetchall()
            states = connection.execute(
                "SELECT * FROM alert_states ORDER BY alert_id"
            ).fetchall()
            jobs = connection.execute(
                "SELECT * FROM delivery_jobs ORDER BY alert_id, channel"
            ).fetchall()
            attempts = connection.execute(
                "SELECT * FROM delivery_attempts ORDER BY job_id, attempt_number"
            ).fetchall()
            audit = connection.execute(
                "SELECT * FROM notification_audit ORDER BY sequence"
            ).fetchall()
            connection.commit()
        event_payloads: dict[str, dict[str, Any]] = {}
        for row in events:
            payload = _json_object(
                str(row["payload_json"]), name="notification_alert_payload"
            )
            try:
                alert = AlertEvent(**payload)
                alert.validate()
            except (TypeError, ValueError) as exc:
                raise NotificationStoreError(
                    "notification_alert_row_invalid"
                ) from exc
            if (
                alert.alert_id != row["alert_id"]
                or alert.event_hash != row["event_hash"]
                or alert.occurred_at != row["occurred_at"]
                or alert.source_hash != row["source_hash"]
                or alert.dedupe_key != row["dedupe_key"]
            ):
                raise NotificationStoreError("notification_alert_row_mismatch")
            _utc_time(str(row["recorded_at"]), name="notification_recorded_at")
            event_payloads[alert.alert_id] = payload
        state_map: dict[str, dict[str, Any]] = {}
        for row_value in states:
            row = dict(row_value)
            if row["status"] not in ALERT_STATES or row["state_hash"] != _state_hash(
                alert_id=row["alert_id"],
                status=row["status"],
                resolved_at=row["resolved_at"],
            ):
                raise NotificationStoreError("notification_alert_state_invalid")
            if (row["status"] == "OPEN") is not (row["resolved_at"] is None):
                raise NotificationStoreError("notification_alert_state_invalid")
            if row["resolved_at"] is not None:
                _utc_time(row["resolved_at"], name="notification_resolved_at")
            state_map[row["alert_id"]] = row
        if set(state_map) != set(event_payloads):
            raise NotificationStoreError("notification_alert_state_set_invalid")
        job_rows: list[dict[str, Any]] = []
        for row_value in jobs:
            row = dict(row_value)
            if (
                row["status"] not in DELIVERY_STATES
                or not is_sha256(row["delivery_key"])
                or row["job_hash"] != canonical_hash(_job_core(row))
                or row["alert_id"] not in event_payloads
            ):
                raise NotificationStoreError("notification_job_row_invalid")
            expected_job_id = trace_id(
                "notification_job",
                {"alert_id": row["alert_id"], "channel": row["channel"]},
            )
            if row["job_id"] != expected_job_id:
                raise NotificationStoreError("notification_job_id_invalid")
            job_rows.append(row)
        attempt_rows: list[dict[str, Any]] = []
        job_ids = {row["job_id"] for row in job_rows}
        for row_value in attempts:
            row = dict(row_value)
            if (
                row["status"] not in ATTEMPT_STATES
                or row["job_id"] not in job_ids
                or row["attempt_hash"] != canonical_hash(_attempt_core(row))
            ):
                raise NotificationStoreError("notification_attempt_row_invalid")
            expected_id = trace_id(
                "notification_attempt",
                {
                    "job_id": row["job_id"],
                    "attempt_number": row["attempt_number"],
                },
            )
            if row["attempt_id"] != expected_id:
                raise NotificationStoreError("notification_attempt_id_invalid")
            attempt_rows.append(row)
        previous_hash: str | None = None
        audit_rows: list[dict[str, Any]] = []
        for expected_sequence, row_value in enumerate(audit, start=1):
            row = dict(row_value)
            payload = _json_object(
                str(row["payload_json"]), name="notification_audit_payload"
            )
            expected_hash = canonical_hash(
                {
                    "sequence": expected_sequence,
                    "event_type": row["event_type"],
                    "entity_id": row["entity_id"],
                    "occurred_at": row["occurred_at"],
                    "payload": payload,
                    "previous_hash": previous_hash,
                }
            )
            if (
                row["sequence"] != expected_sequence
                or row["previous_hash"] != previous_hash
                or row["row_hash"] != expected_hash
            ):
                raise NotificationStoreError("notification_audit_chain_invalid")
            _utc_time(row["occurred_at"], name="notification_audit_time")
            row["payload"] = payload
            audit_rows.append(row)
            previous_hash = expected_hash
        if event_payloads and not audit_rows:
            raise NotificationStoreError("notification_audit_missing")
        return {
            "events": event_payloads,
            "states": state_map,
            "jobs": job_rows,
            "attempts": attempt_rows,
            "audit": audit_rows,
        }
