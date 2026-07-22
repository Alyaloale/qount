from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from qount.contracts import canonical_hash
from qount.halt import HALT_SCHEMA_VERSION
from qount.halt import HaltEvent
from qount.halt import classify_from_halt_reason
from qount.halt import classify_from_runtime_state
from qount.halt import classify_halt
from qount.halt import escalate_scope
from qount.halt import read_halt_reason
from qount.halt import should_escalate_to_account_level
from qount.halt import validate_recovery_flow
from qount.persistence import ArtifactCodecError
from qount.persistence import dump_artifact
from qount.persistence import load_artifact

_CREATED = "2026-07-23T10:00:00+00:00"
_HASH_A = "a" * 64


class HaltEventContractTest(unittest.TestCase):
    def test_create_produces_valid_event(self):
        event = HaltEvent.create(
            halt_type="operational",
            scope="execution_plane",
            reason="test_reason",
            severity="HALT",
            evidence_hash=_HASH_A,
            recommended_action="freeze_risk",
            recommended_scope="execution_plane",
            created_at=_CREATED,
        )
        self.assertEqual(event.schema_version, HALT_SCHEMA_VERSION)
        self.assertTrue(event.bypass_mode)
        self.assertTrue(event.risk_increase_frozen)
        self.assertTrue(event.recovery_requires_owner_auth)
        self.assertTrue(event.recovery_requires_dual_diff)
        self.assertFalse(event.validate())

    def test_invalid_halt_type_rejected(self):
        with self.assertRaises(ValueError):
            HaltEvent.create(
                halt_type="invalid",
                scope="execution_plane",
                reason="test_reason",
                severity="HALT",
                evidence_hash=_HASH_A,
                recommended_action="freeze_risk",
                recommended_scope="execution_plane",
                created_at=_CREATED,
            )

    def test_invalid_scope_rejected(self):
        with self.assertRaises(ValueError):
            HaltEvent.create(
                halt_type="operational",
                scope="invalid",
                reason="test_reason",
                severity="HALT",
                evidence_hash=_HASH_A,
                recommended_action="freeze_risk",
                recommended_scope="execution_plane",
                created_at=_CREATED,
            )

    def test_invalid_severity_rejected(self):
        with self.assertRaises(ValueError):
            HaltEvent.create(
                halt_type="operational",
                scope="execution_plane",
                reason="test_reason",
                severity="INVALID",
                evidence_hash=_HASH_A,
                recommended_action="freeze_risk",
                recommended_scope="execution_plane",
                created_at=_CREATED,
            )

    def test_invalid_evidence_hash_rejected(self):
        with self.assertRaises(ValueError):
            HaltEvent.create(
                halt_type="operational",
                scope="execution_plane",
                reason="test_reason",
                severity="HALT",
                evidence_hash="not-a-hash",
                recommended_action="freeze_risk",
                recommended_scope="execution_plane",
                created_at=_CREATED,
            )

    def test_invalid_reason_format_rejected(self):
        with self.assertRaises(ValueError):
            HaltEvent.create(
                halt_type="operational",
                scope="execution_plane",
                reason="Invalid Reason",
                severity="HALT",
                evidence_hash=_HASH_A,
                recommended_action="freeze_risk",
                recommended_scope="execution_plane",
                created_at=_CREATED,
            )

    def test_deterministic_hash(self):
        e1 = classify_from_halt_reason(
            "pilot_risk_halt", created_at=_CREATED
        )
        e2 = classify_from_halt_reason(
            "pilot_risk_halt", created_at=_CREATED
        )
        self.assertEqual(e1.event_hash, e2.event_hash)
        self.assertEqual(e1.event_id, e2.event_id)

    def test_round_trip(self):
        event = classify_from_halt_reason(
            "pilot_daily_loss_halt", created_at=_CREATED
        )
        raw = dump_artifact(event)
        restored = load_artifact(raw, expected_artifact_type="halt_event")
        self.assertEqual(restored.event_id, event.event_id)
        self.assertEqual(restored.halt_type, "portfolio")

    def test_tampered_payload_detected(self):
        event = classify_from_halt_reason(
            "pilot_risk_halt", created_at=_CREATED
        )
        raw = json.loads(dump_artifact(event))
        raw["payload"]["reason"] = "tampered_reason"
        with self.assertRaises(ArtifactCodecError) as cm:
            load_artifact(
                json.dumps(raw, sort_keys=True).encode("ascii") + b"\n"
            )
        self.assertIn("payload_hash_mismatch", str(cm.exception))


class HaltClassificationTest(unittest.TestCase):
    def test_operational_reasons_classified_correctly(self):
        for reason in (
            "live_execution_error",
            "post_dispatch_accounting_error",
            "pilot_risk_halt",
        ):
            event = classify_from_halt_reason(reason, created_at=_CREATED)
            self.assertEqual(event.halt_type, "operational")
            self.assertEqual(event.scope, "execution_plane")
            self.assertEqual(event.recommended_action, "freeze_risk")

    def test_slippage_halt_classified_correctly(self):
        event = classify_from_halt_reason(
            "pilot_slippage_halt", created_at=_CREATED
        )
        self.assertEqual(event.halt_type, "operational")
        self.assertEqual(
            event.recommended_action, "halt_after_protected_fill"
        )

    def test_portfolio_reasons_classified_correctly(self):
        for reason in (
            "pilot_drawdown_halt",
            "pilot_drawdown_flatten_then_halt",
            "pilot_daily_loss_halt",
            "pilot_daily_loss_flatten_then_halt",
        ):
            event = classify_from_halt_reason(reason, created_at=_CREATED)
            self.assertEqual(event.halt_type, "portfolio")
            self.assertEqual(event.scope, "full_account")
            self.assertEqual(
                event.recommended_action, "flatten_then_halt"
            )

    def test_unknown_reason_defaults_to_operational(self):
        event = classify_from_halt_reason(
            "unknown_halt_reason", created_at=_CREATED
        )
        self.assertEqual(event.halt_type, "operational")
        self.assertEqual(event.recommended_action, "freeze_risk")

    def test_source_halt_reason_recorded(self):
        event = classify_from_halt_reason(
            "pilot_risk_halt", created_at=_CREATED
        )
        self.assertEqual(event.source_halt_reason, "pilot_risk_halt")

    def test_unknown_unresolved_flag_propagated(self):
        event = classify_from_halt_reason(
            "pilot_risk_halt",
            created_at=_CREATED,
            unknown_unresolved=True,
        )
        self.assertTrue(event.unknown_unresolved)


class HaltRuntimeClassificationTest(unittest.TestCase):
    def test_unknown_orders_generate_event(self):
        events = classify_from_runtime_state(
            unknown_order_count=2, created_at=_CREATED
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].halt_type, "operational")
        self.assertTrue(events[0].unknown_unresolved)

    def test_reconciliation_halt_generates_event(self):
        events = classify_from_runtime_state(
            reconciliation_halt_required=True, created_at=_CREATED
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].severity, "HALT")

    def test_reconciliation_failed_generates_critical(self):
        events = classify_from_runtime_state(
            reconciliation_passed=False, created_at=_CREATED
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].severity, "CRITICAL")

    def test_data_quality_blockers_generate_event(self):
        events = classify_from_runtime_state(
            data_quality_blockers=3, created_at=_CREATED
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].severity, "CRITICAL")

    def test_no_conditions_no_events(self):
        events = classify_from_runtime_state(
            unknown_order_count=0,
            reconciliation_halt_required=False,
            reconciliation_passed=True,
            data_quality_blockers=0,
            created_at=_CREATED,
        )
        self.assertEqual(len(events), 0)

    def test_multiple_conditions_generate_multiple_events(self):
        events = classify_from_runtime_state(
            unknown_order_count=1,
            reconciliation_halt_required=True,
            data_quality_blockers=2,
            created_at=_CREATED,
        )
        self.assertEqual(len(events), 3)


class HaltBypassRouterTest(unittest.TestCase):
    def test_read_halt_reason_from_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            halt_path = Path(tmp) / "HALT"
            halt_path.write_text("pilot_risk_halt\n", encoding="ascii")
            reason = read_halt_reason(halt_path)
            self.assertEqual(reason, "pilot_risk_halt")

    def test_read_halt_reason_missing_file(self):
        self.assertIsNone(read_halt_reason("/nonexistent/HALT"))
        self.assertIsNone(read_halt_reason(None))

    def test_classify_halt_does_not_modify_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            halt_path = Path(tmp) / "HALT"
            halt_path.write_text("pilot_risk_halt\n", encoding="ascii")
            os.chmod(halt_path, 0o600)
            original_content = halt_path.read_text(encoding="ascii")
            original_mode = os.stat(halt_path).st_mode

            events = classify_halt(
                halt_path=halt_path, created_at=_CREATED
            )
            self.assertTrue(len(events) >= 1)

            after_content = halt_path.read_text(encoding="ascii")
            after_mode = os.stat(halt_path).st_mode
            self.assertEqual(original_content, after_content)
            self.assertEqual(original_mode, after_mode)

    def test_classify_halt_no_file_no_runtime_issues(self):
        events = classify_halt(
            halt_path=None,
            created_at=_CREATED,
            unknown_order_count=0,
            reconciliation_passed=True,
        )
        self.assertEqual(len(events), 0)

    def test_classify_halt_combines_file_and_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            halt_path = Path(tmp) / "HALT"
            halt_path.write_text("pilot_risk_halt\n", encoding="ascii")
            events = classify_halt(
                halt_path=halt_path,
                created_at=_CREATED,
                unknown_order_count=1,
            )
            self.assertGreaterEqual(len(events), 2)
            file_event = next(
                e for e in events if e.source_halt_reason == "pilot_risk_halt"
            )
            self.assertTrue(file_event.unknown_unresolved)

    def test_should_escalate_for_portfolio_halt(self):
        with tempfile.TemporaryDirectory() as tmp:
            halt_path = Path(tmp) / "HALT"
            halt_path.write_text(
                "pilot_drawdown_halt\n", encoding="ascii"
            )
            events = classify_halt(
                halt_path=halt_path, created_at=_CREATED
            )
            self.assertTrue(should_escalate_to_account_level(events))

    def test_should_not_escalate_for_operational_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            halt_path = Path(tmp) / "HALT"
            halt_path.write_text("pilot_risk_halt\n", encoding="ascii")
            events = classify_halt(
                halt_path=halt_path, created_at=_CREATED
            )
            self.assertFalse(should_escalate_to_account_level(events))


class HaltEscalationTest(unittest.TestCase):
    def test_widest_scope_selected(self):
        events = [
            classify_from_halt_reason(
                "pilot_risk_halt", created_at=_CREATED
            ),
            classify_from_halt_reason(
                "pilot_drawdown_halt", created_at=_CREATED
            ),
        ]
        self.assertEqual(escalate_scope(events), "full_account")

    def test_empty_events_returns_venue(self):
        self.assertEqual(escalate_scope([]), "venue")


class HaltRecoveryFlowTest(unittest.TestCase):
    def test_valid_recovery(self):
        errors = validate_recovery_flow(
            halt_active=True,
            unknown_unresolved=False,
            dual_accounting_diff_passed=True,
            recovery_report_written=True,
            owner_authorized=True,
        )
        self.assertEqual(errors, ())

    def test_no_active_halt(self):
        errors = validate_recovery_flow(
            halt_active=False,
            unknown_unresolved=False,
            dual_accounting_diff_passed=True,
            recovery_report_written=True,
            owner_authorized=True,
        )
        self.assertIn("recovery_no_active_halt", errors)

    def test_unknown_orders_block_recovery(self):
        errors = validate_recovery_flow(
            halt_active=True,
            unknown_unresolved=True,
            dual_accounting_diff_passed=True,
            recovery_report_written=True,
            owner_authorized=True,
        )
        self.assertIn("recovery_unknown_orders_not_closed", errors)

    def test_missing_dual_diff_blocks_recovery(self):
        errors = validate_recovery_flow(
            halt_active=True,
            unknown_unresolved=False,
            dual_accounting_diff_passed=False,
            recovery_report_written=True,
            owner_authorized=True,
        )
        self.assertIn(
            "recovery_dual_accounting_diff_not_passed", errors
        )

    def test_missing_owner_auth_blocks_recovery(self):
        errors = validate_recovery_flow(
            halt_active=True,
            unknown_unresolved=False,
            dual_accounting_diff_passed=True,
            recovery_report_written=True,
            owner_authorized=False,
        )
        self.assertIn("recovery_owner_authorization_missing", errors)


if __name__ == "__main__":
    unittest.main()
