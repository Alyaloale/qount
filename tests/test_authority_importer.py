from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from qount.contracts import canonical_hash
from qount.ledger import build_runtime_ledger_snapshot
from qount.notifications import AlertEvent
from qount.notifications import NotificationStore
from qount.notifications import build_notification_snapshot
from qount.notifications import collect_system_health
from qount.notifications import SystemHealthCollectorError
from qount.persistence import publish_decision_batch
from qount.persistence import write_immutable_artifact
from qount.reporting import AuthorityArtifactImportError
from qount.reporting import build_daily_brief
from qount.reporting import read_vps_authority_bundle
from tests.test_ledger_dashboard_bridge import CAPTURED_AT
from tests.test_ledger_dashboard_bridge import _ledger_with_accounting
from tests.test_system_health import _health_snapshot


def _hash(name: str) -> str:
    return canonical_hash({"authority_importer_fixture": name})


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        + b"\n"
    )


def _publish_authority_bundle(root: Path) -> None:
    ledger, batch, registry = _ledger_with_accounting(root / "ledger")
    snapshot = build_runtime_ledger_snapshot(
        ledger,
        batch,
        captured_at=CAPTURED_AT,
    )
    store = NotificationStore(root / "notification.sqlite3")
    alert = AlertEvent.create(
        severity="WARNING",
        category="system_health",
        title="Fixture health warning",
        summary="A fixture warning keeps the notification source non-empty.",
        occurred_at="2026-07-20T00:07:10+00:00",
        source_type="system",
        source_id=_hash("health-source"),
        source_hash=_hash("health-payload"),
        dedupe_key="system:fixture-warning",
    )
    store.enqueue(alert, recorded_at="2026-07-20T00:07:11+00:00")
    notification = build_notification_snapshot(
        store,
        captured_at="2026-07-20T00:07:20+00:00",
    )
    health = _health_snapshot()
    brief = build_daily_brief(
        batch,
        registry,
        snapshot,
        notification,
        generated_at="2026-07-20T00:08:00+00:00",
    )

    authority = root / "authority"
    authority.mkdir(mode=0o700)
    os.chmod(authority, 0o700)
    batch_dir = authority / "decision_batch" / batch.manifest.batch_id
    publish_decision_batch(
        batch_dir,
        snapshot=batch.snapshot,
        intents=batch.intents,
        target=batch.target,
        risk=batch.risk,
        plan=batch.plan,
        created_at=batch.manifest.created_at,
    )
    os.chmod(batch_dir.parent, 0o700)
    write_immutable_artifact(authority / "strategy_registry.json", registry)
    for name, value in (
        ("runtime_ledger_snapshot.json", snapshot.as_dict()),
        ("notification_snapshot.json", notification.as_dict()),
        ("system_health_snapshot.json", health.as_dict()),
        ("daily_brief.json", brief.as_dict()),
    ):
        path = authority / name
        path.write_bytes(_canonical_bytes(value))
        os.chmod(path, 0o600)


class AuthorityImporterTest(unittest.TestCase):
    def _publish_bundle(self, root: Path) -> None:
        _publish_authority_bundle(root)

    def test_imports_complete_bundle_and_replays_cross_source_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._publish_bundle(root)
            bundle = read_vps_authority_bundle(root / "authority")

        self.assertEqual(
            bundle.ledger_snapshot.batch_id,
            bundle.batch.manifest.batch_id,
        )
        self.assertEqual(
            bundle.daily_brief.source_hashes["runtime_ledger"],
            bundle.ledger_snapshot.snapshot_hash,
        )
        self.assertEqual(bundle.system_health.status, "healthy")

    def test_extra_file_and_tampered_snapshot_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._publish_bundle(root)
            authority = root / "authority"
            (authority / "legacy_state.json").write_text("{}")
            with self.assertRaisesRegex(
                AuthorityArtifactImportError,
                "authority_root_files_mismatch",
            ):
                read_vps_authority_bundle(authority)
            (authority / "legacy_state.json").unlink()

            path = authority / "runtime_ledger_snapshot.json"
            payload = json.loads(path.read_text())
            payload["account"]["wallet_balance"] = 1.0
            path.write_bytes(_canonical_bytes(payload))
            with self.assertRaisesRegex(
                AuthorityArtifactImportError,
                "authority_source_invalid",
            ):
                read_vps_authority_bundle(authority)

    def test_permissions_and_noncanonical_json_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._publish_bundle(root)
            authority = root / "authority"
            registry = authority / "strategy_registry.json"
            os.chmod(registry, 0o644)
            with self.assertRaisesRegex(
                AuthorityArtifactImportError,
                "strategy_registry_file_mode_invalid",
            ):
                read_vps_authority_bundle(authority)
            os.chmod(registry, 0o600)

            brief = authority / "daily_brief.json"
            brief.write_bytes(brief.read_bytes().rstrip(b"\n"))
            with self.assertRaisesRegex(
                AuthorityArtifactImportError,
                "daily_brief_not_canonical",
            ):
                read_vps_authority_bundle(authority)

    def test_health_collector_requires_all_four_explicit_probes(self) -> None:
        snapshot = _health_snapshot()
        measurements = {
            row["component"]: {
                "status": row["status"],
                "detail_codes": tuple(row["detail_codes"]),
                "metrics": row["metrics"],
                "source_id": row["source_id"],
                "source_hash": row["source_hash"],
            }
            for row in snapshot.observations
        }
        collected = collect_system_health(
            measurements,
            observed_at="2026-07-20T00:07:05+00:00",
            captured_at="2026-07-20T00:07:15+00:00",
        )
        self.assertEqual(collected, snapshot)
        with self.assertRaisesRegex(
            SystemHealthCollectorError,
            "measurements_incomplete",
        ):
            collect_system_health(
                {key: value for key, value in measurements.items() if key != "backup"},
                observed_at="2026-07-20T00:07:05+00:00",
                captured_at="2026-07-20T00:07:15+00:00",
            )


if __name__ == "__main__":
    unittest.main()
