from __future__ import annotations

import os
import sqlite3
import stat
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path

from qount.contracts import canonical_hash
from qount.notifications import AlertEvent
from qount.notifications import NotificationContractError
from qount.notifications import NotificationStore
from qount.notifications import NotificationStoreConflictError
from qount.notifications import NotificationStoreError
from qount.notifications import build_notification_snapshot


OCCURRED_AT = "2026-07-20T00:10:00+00:00"
RECORDED_AT = "2026-07-20T00:10:01+00:00"


def _hash(name: str) -> str:
    return canonical_hash({"notification_fixture": name})


def _alert(
    *,
    title: str = "Runtime reconciliation blocked",
    severity: str = "HALT",
) -> AlertEvent:
    return AlertEvent.create(
        severity=severity,
        category="reconciliation",
        title=title,
        summary="Ledger and exchange positions do not match.",
        occurred_at=OCCURRED_AT,
        source_type="reconciliation",
        source_id=_hash("report-1"),
        source_hash=_hash("source-1"),
        dedupe_key="reconciliation:report-1",
        trace_id_value=_hash("batch-1"),
    )


class NotificationContractTest(unittest.TestCase):
    def test_alert_identity_is_stable_but_content_hash_is_not(self) -> None:
        first = _alert()
        changed = _alert(title="Changed title")

        self.assertEqual(first.alert_id, changed.alert_id)
        self.assertNotEqual(first.event_hash, changed.event_hash)
        first.validate()
        with self.assertRaisesRegex(
            NotificationContractError, "alert_event_hash_invalid"
        ):
            replace(first, title="tampered").validate()


class NotificationStoreTest(unittest.TestCase):
    def _store(self, root: Path) -> NotificationStore:
        return NotificationStore(root / "private" / "notifications.sqlite3")

    def test_wal_private_files_and_exact_idempotent_enqueue(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = self._store(Path(temporary))
            first = store.enqueue(_alert(), recorded_at=RECORDED_AT)
            second = store.enqueue(_alert(), recorded_at=RECORDED_AT)

            self.assertEqual(first, second)
            self.assertEqual(
                stat.S_IMODE(os.stat(store.database_path).st_mode), 0o600
            )
            self.assertEqual(
                stat.S_IMODE(os.stat(store.database_path.parent).st_mode), 0o700
            )
            with closing(sqlite3.connect(store.database_path)) as connection:
                self.assertEqual(
                    connection.execute("PRAGMA journal_mode").fetchone()[0].lower(),
                    "wal",
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM alert_events").fetchone()[0],
                    1,
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM delivery_jobs").fetchone()[0],
                    1,
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM notification_audit").fetchone()[0],
                    2,
                )

    def test_same_identity_with_changed_content_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = self._store(Path(temporary))
            store.enqueue(_alert(), recorded_at=RECORDED_AT)
            with self.assertRaisesRegex(
                NotificationStoreConflictError,
                "notification_alert_identity_conflict",
            ):
                store.enqueue(
                    _alert(title="Changed title"), recorded_at=RECORDED_AT
                )

    def test_retry_backoff_then_success_preserves_delivery_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = self._store(Path(temporary))
            store.enqueue(_alert(), recorded_at=RECORDED_AT, max_attempts=3)
            delivery_keys: list[str] = []

            def fail(payload, delivery_key):
                self.assertEqual(payload["alert_id"], _alert().alert_id)
                delivery_keys.append(delivery_key)
                raise TimeoutError("fixture timeout")

            first = store.deliver_due(
                attempted_at=RECORDED_AT,
                transport=fail,
                retry_base_seconds=60,
            )
            self.assertEqual(first[0]["status"], "RETRY_WAIT")
            self.assertEqual(
                store.deliver_due(
                    attempted_at="2026-07-20T00:11:00+00:00",
                    transport=fail,
                    retry_base_seconds=60,
                ),
                (),
            )

            second = store.deliver_due(
                attempted_at="2026-07-20T00:11:01+00:00",
                transport=lambda payload, key: (
                    delivery_keys.append(key) or {"accepted": True}
                ),
                retry_base_seconds=60,
            )
            self.assertEqual(second[0]["status"], "DELIVERED")
            self.assertEqual(len(set(delivery_keys)), 1)
            snapshot = build_notification_snapshot(
                store, captured_at="2026-07-20T00:11:02+00:00"
            )
            delivery = snapshot.alerts[0]["deliveries"][0]
            self.assertEqual(delivery["attempt_count"], 2)
            self.assertEqual(delivery["status"], "DELIVERED")
            self.assertEqual(snapshot.delivery_state_counts["DELIVERED"], 1)

    def test_exhausted_retry_enters_dead_letter(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = self._store(Path(temporary))
            store.enqueue(_alert(), recorded_at=RECORDED_AT, max_attempts=2)

            def fail(payload, delivery_key):
                raise ConnectionError("fixture offline")

            store.deliver_due(
                attempted_at=RECORDED_AT,
                transport=fail,
                retry_base_seconds=1,
            )
            result = store.deliver_due(
                attempted_at="2026-07-20T00:10:02+00:00",
                transport=fail,
                retry_base_seconds=1,
            )
            self.assertEqual(result[0]["status"], "DEAD_LETTER")
            snapshot = build_notification_snapshot(
                store, captured_at="2026-07-20T00:10:03+00:00"
            )
            self.assertEqual(snapshot.delivery_state_counts["DEAD_LETTER"], 1)
            self.assertEqual(
                snapshot.alerts[0]["deliveries"][0]["last_error"],
                "ConnectionError",
            )

    def test_external_success_before_marker_retries_same_key_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = self._store(root)
            store.enqueue(_alert(), recorded_at=RECORDED_AT, max_attempts=1)
            keys: list[str] = []

            def accepted(payload, delivery_key):
                keys.append(delivery_key)
                return {"accepted": True}

            with self.assertRaisesRegex(RuntimeError, "fixture_crash"):
                store.deliver_due(
                    attempted_at=RECORDED_AT,
                    transport=accepted,
                    after_transport=lambda job_id, attempt: (_ for _ in ()).throw(
                        RuntimeError("fixture_crash")
                    ),
                )
            restarted = self._store(root)
            result = restarted.deliver_due(
                attempted_at="2026-07-20T00:10:02+00:00",
                transport=accepted,
            )
            self.assertEqual(result[0]["status"], "DELIVERED")
            self.assertEqual(keys[0], keys[1])
            rows = restarted.verified_rows()
            self.assertEqual(
                [row["status"] for row in rows["attempts"]],
                ["SUCCEEDED"],
            )
            self.assertEqual(rows["jobs"][0]["attempt_count"], 1)

    def test_resolution_is_idempotent_and_snapshot_separates_open_count(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = self._store(Path(temporary))
            alert = _alert(severity="CRITICAL")
            store.enqueue(alert, recorded_at=RECORDED_AT)
            resolved_at = "2026-07-20T00:12:00+00:00"
            store.resolve_alert(alert.alert_id, resolved_at=resolved_at)
            store.resolve_alert(alert.alert_id, resolved_at=resolved_at)

            snapshot = build_notification_snapshot(
                store, captured_at="2026-07-20T00:12:01+00:00"
            )
            self.assertEqual(snapshot.open_alert_count, 0)
            self.assertEqual(snapshot.alerts[0]["status"], "RESOLVED")
            self.assertEqual(snapshot.severity_counts["CRITICAL"], 1)

    def test_database_tamper_fails_snapshot_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = self._store(Path(temporary))
            store.enqueue(_alert(), recorded_at=RECORDED_AT)
            with closing(sqlite3.connect(store.database_path)) as connection:
                connection.execute(
                    "UPDATE delivery_jobs SET attempt_count=9"
                )
                connection.commit()
            with self.assertRaisesRegex(
                NotificationStoreError, "notification_job_row_invalid"
            ):
                build_notification_snapshot(
                    store, captured_at="2026-07-20T00:12:01+00:00"
                )


if __name__ == "__main__":
    unittest.main()
