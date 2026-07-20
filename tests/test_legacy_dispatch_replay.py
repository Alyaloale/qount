from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from qount.contracts import canonical_hash
from qount.contracts import validate_decision_batch
from qount.ledger import AuditJournalError
from qount.ledger import LegacyDispatchReplayError
from qount.ledger import RuntimeLedger
from qount.ledger import build_verified_legacy_dispatch_batch
from qount.ledger import replay_legacy_dry_dispatch
from qount.mini_trend.live_pilot import LIVE_PILOT_CONTRACT
from qount.mini_trend.pilot_projection import PILOT_PROJECTION_VERSION
from qount.risk import legacy_dispatch_plan_hash
from tests.test_mini_trend_pilot_dispatcher import _plan
from tests.test_mini_trend_pilot_dispatcher import _projection
from tests.test_mini_trend_pilot_dispatcher import _rules


CREATED_AT = "2026-08-02T00:00:00+00:00"
PROJECTION_EVIDENCE_HASH = "a" * 64
TARGET_STRESS_LOSS_FRACTION = 0.01
GOLDEN_PATH = Path(__file__).parent / "fixtures" / "legacy_dispatch_replay_golden.json"
GOLDEN_SHA256 = "f52af0a63d22044affee5c1a398341f266d0ffc57407b9f9c5ec57725429529a"


def _artifacts() -> tuple[dict, dict]:
    projection = copy.deepcopy(_projection(_rules()))
    projection["schema_version"] = PILOT_PROJECTION_VERSION
    projection["contract"]["strategy"] = LIVE_PILOT_CONTRACT.strategy
    projection["diagnostics"] = {"projection_ready": True}
    plan = copy.deepcopy(_plan())
    plan["source_hashes"]["projection"] = PROJECTION_EVIDENCE_HASH
    plan["plan_hash"] = legacy_dispatch_plan_hash(plan)
    return projection, plan


def _replay(ledger: RuntimeLedger):
    projection, plan = _artifacts()
    return replay_legacy_dry_dispatch(
        ledger,
        projection,
        plan,
        projection_evidence_hash=PROJECTION_EVIDENCE_HASH,
        target_stress_loss_fraction=TARGET_STRESS_LOSS_FRACTION,
        created_at=CREATED_AT,
    )


def _golden_bytes(value: dict) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("ascii")


class LegacyDispatchReplayTest(unittest.TestCase):
    def test_builds_complete_batch_and_registers_only_planned_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = _replay(RuntimeLedger(Path(temporary) / "runtime.sqlite3"))
            batch = result.batch
            report = result.report

            self.assertEqual(
                validate_decision_batch(
                    batch.snapshot,
                    batch.intents,
                    batch.target,
                    batch.risk,
                    batch.plan,
                ),
                (),
            )
            self.assertFalse(batch.manifest.orders_authorized)
            self.assertTrue(batch.plan.executable)
            self.assertTrue(report.parity["matches"])
            self.assertEqual(
                report.parity["legacy_economic_state_hash"],
                report.parity["standard_economic_state_hash"],
            )
            self.assertEqual(
                report.expected_positions,
                batch.plan.expected_positions,
            )
            self.assertEqual(
                report.reconciliation_tolerance,
                batch.plan.reconciliation_tolerance,
            )
            self.assertEqual(set(report.ledger["order_statuses"].values()), {"PLANNED"})
            self.assertEqual(report.ledger["order_event_count"], 0)
            self.assertEqual(report.ledger["fill_count"], 0)
            self.assertEqual(report.ledger["cash_event_count"], 0)
            self.assertEqual(report.ledger["nav_mark_count"], 0)
            self.assertEqual(report.ledger["reconciliation_count"], 0)
            self.assertFalse(report.ledger["risk_increase_allowed"])
            self.assertFalse(report.execution_claims["orders_authorized"])
            self.assertFalse(report.execution_claims["orders_routed"])
            report.validate()

    def test_restart_replay_is_exactly_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_ledger = RuntimeLedger(root / "runtime.sqlite3")
            first = _replay(first_ledger)
            audit_bytes = first_ledger.audit_path.read_bytes()

            restarted = RuntimeLedger(root / "runtime.sqlite3")
            second = _replay(restarted)

            self.assertEqual(first.batch, second.batch)
            self.assertEqual(first.report, second.report)
            self.assertEqual(restarted.audit_path.read_bytes(), audit_bytes)

    def test_db_commit_before_jsonl_is_recovered_then_replayed(self) -> None:
        projection, plan = _artifacts()
        batch = build_verified_legacy_dispatch_batch(
            projection,
            plan,
            projection_evidence_hash=PROJECTION_EVIDENCE_HASH,
            target_stress_loss_fraction=TARGET_STRESS_LOSS_FRACTION,
            created_at=CREATED_AT,
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            interrupted = RuntimeLedger(root / "runtime.sqlite3", auto_flush=False)
            self.assertTrue(interrupted.record_verified_batch(batch, recorded_at=CREATED_AT))
            self.assertFalse(interrupted.audit_path.exists())

            recovered = RuntimeLedger(root / "runtime.sqlite3")
            result = _replay(recovered)
            self.assertEqual(result.batch, batch)
            self.assertEqual(
                result.report.ledger["audit_row_count"],
                1 + len(batch.plan.orders),
            )

    def test_jsonl_append_before_publish_marker_is_recovered_then_replayed(self) -> None:
        projection, plan = _artifacts()
        batch = build_verified_legacy_dispatch_batch(
            projection,
            plan,
            projection_evidence_hash=PROJECTION_EVIDENCE_HASH,
            target_stress_loss_fraction=TARGET_STRESS_LOSS_FRACTION,
            created_at=CREATED_AT,
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            interrupted = RuntimeLedger(root / "runtime.sqlite3")
            with patch.object(
                interrupted,
                "_mark_outbox_published",
                side_effect=OSError("injected marker failure"),
            ), self.assertRaisesRegex(OSError, "marker failure"):
                interrupted.record_verified_batch(batch, recorded_at=CREATED_AT)

            recovered = RuntimeLedger(root / "runtime.sqlite3")
            result = _replay(recovered)
            self.assertEqual(result.batch, batch)
            self.assertEqual(
                result.report.ledger["audit_row_count"],
                1 + len(batch.plan.orders),
            )

    def test_source_plan_report_and_journal_tampering_fail_closed(self) -> None:
        projection, plan = _artifacts()
        tampered_plan = copy.deepcopy(plan)
        tampered_plan["plan_hash"] = "0" * 64
        with tempfile.TemporaryDirectory() as temporary, self.assertRaisesRegex(
            LegacyDispatchReplayError,
            "legacy_plan_hash_invalid",
        ):
            replay_legacy_dry_dispatch(
                RuntimeLedger(Path(temporary) / "runtime.sqlite3"),
                projection,
                tampered_plan,
                projection_evidence_hash=PROJECTION_EVIDENCE_HASH,
                target_stress_loss_fraction=TARGET_STRESS_LOSS_FRACTION,
                created_at=CREATED_AT,
            )

        mismatched_projection = copy.deepcopy(projection)
        mismatched_projection["decision"]["prices"]["BTCUSDT"] = 99_999.0
        with tempfile.TemporaryDirectory() as temporary, self.assertRaisesRegex(
            LegacyDispatchReplayError,
            "legacy_projection_decision_mismatch",
        ):
            replay_legacy_dry_dispatch(
                RuntimeLedger(Path(temporary) / "runtime.sqlite3"),
                mismatched_projection,
                plan,
                projection_evidence_hash=PROJECTION_EVIDENCE_HASH,
                target_stress_loss_fraction=TARGET_STRESS_LOSS_FRACTION,
                created_at=CREATED_AT,
            )

        mismatched_source = copy.deepcopy(plan)
        mismatched_source["source_hashes"]["projection"] = "b" * 64
        mismatched_source["plan_hash"] = legacy_dispatch_plan_hash(mismatched_source)
        with tempfile.TemporaryDirectory() as temporary, self.assertRaisesRegex(
            LegacyDispatchReplayError,
            "projection_evidence_mismatch",
        ):
            replay_legacy_dry_dispatch(
                RuntimeLedger(Path(temporary) / "runtime.sqlite3"),
                projection,
                mismatched_source,
                projection_evidence_hash=PROJECTION_EVIDENCE_HASH,
                target_stress_loss_fraction=TARGET_STRESS_LOSS_FRACTION,
                created_at=CREATED_AT,
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ledger = RuntimeLedger(root / "runtime.sqlite3")
            result = _replay(ledger)
            tampered_report = replace(
                result.report,
                execution_claims=dict(result.report.execution_claims)
                | {"fills_recorded": True},
            )
            with self.assertRaisesRegex(
                LegacyDispatchReplayError,
                "execution_claims_invalid",
            ):
                tampered_report.validate()

            lines = ledger.audit_path.read_text(encoding="ascii").splitlines()
            row = json.loads(lines[0])
            row["payload"]["manifest_hash"] = "f" * 64
            lines[0] = json.dumps(
                row,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
            ledger.audit_path.write_text("\n".join(lines) + "\n", encoding="ascii")
            with self.assertRaises(AuditJournalError):
                _replay(ledger)

    def test_existing_execution_state_cannot_be_recast_as_dry_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ledger = RuntimeLedger(Path(temporary) / "runtime.sqlite3")
            result = _replay(ledger)
            order_id = result.batch.plan.orders[0].client_order_id
            ledger.transition_order(
                order_id,
                "SUBMITTING",
                event_at="2026-08-02T00:00:01+00:00",
                source_hash=canonical_hash({"test": "submitting"}),
            )
            with self.assertRaisesRegex(
                LegacyDispatchReplayError,
                "ledger_order_not_planned",
            ):
                _replay(ledger)

    def test_golden_report_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = _replay(RuntimeLedger(Path(temporary) / "runtime.sqlite3"))
            expected = GOLDEN_PATH.read_bytes()
            actual = _golden_bytes(result.report.as_dict())

            self.assertEqual(actual, expected)
            self.assertEqual(hashlib.sha256(expected).hexdigest(), GOLDEN_SHA256)


if __name__ == "__main__":
    unittest.main()
