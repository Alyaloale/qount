from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from qount.contracts import OrderPlan
from qount.contracts import RiskDecision
from qount.contracts import canonical_hash
from qount.ledger import RuntimeLedgerSnapshot
from qount.ledger import build_runtime_ledger_snapshot
from qount.ledger import reconcile_three_way
from qount.notifications import AlertProducerError
from qount.notifications import NotificationStore
from qount.notifications import SystemHealthObservation
from qount.notifications import alerts_from_runtime_ledger_snapshot
from qount.notifications import alerts_from_system_health
from qount.notifications import alerts_from_verified_decision_batch
from qount.notifications import build_notification_snapshot
from qount.notifications import synchronize_producer_incidents
from qount.persistence import VerifiedDecisionBatch
from qount.persistence import build_decision_batch_manifest
from qount.reporting import build_dashboard_v1
from qount.reporting import build_daily_brief
from tests.test_ledger_dashboard_bridge import CAPTURED_AT
from tests.test_ledger_dashboard_bridge import _ledger_with_accounting
from tests.test_runtime_ledger import _batch


def _hash(name: str) -> str:
    return canonical_hash({"notification_producer_fixture": name})


def _blocked_batch() -> VerifiedDecisionBatch:
    original = _batch()
    approved_target = {
        symbol: 0.0 for symbol in original.target.target_weights
    }
    risk = RiskDecision.create(
        batch_id=original.risk.batch_id,
        portfolio_target_id=original.target.portfolio_target_id,
        decision_time=original.risk.decision_time,
        approved=False,
        input_target=original.target.target_weights,
        approved_target=approved_target,
        adjustments=(),
        violations=("ACCOUNT_STATE_UNKNOWN",),
        risk_state_hash=_hash("blocked-risk-state"),
        increase_risk_allowed=False,
        reduce_risk_allowed=True,
    )
    plan = OrderPlan.create(
        batch_id=risk.batch_id,
        risk_decision_id=risk.risk_decision_id,
        portfolio_target_id=original.target.portfolio_target_id,
        snapshot_id=original.snapshot.snapshot_id,
        decision_ids=original.target.decision_ids,
        created_at=original.plan.created_at,
        current_position_hash=original.plan.current_position_hash,
        approved_target=approved_target,
        orders=(),
        cancellations=(),
        retained_order_ids=(),
        expected_positions=approved_target,
        reconciliation_tolerance=original.plan.reconciliation_tolerance,
        blockers=("ACCOUNT_STATE_UNKNOWN",),
        executable=False,
    )
    manifest = build_decision_batch_manifest(
        snapshot=original.snapshot,
        intents=original.intents,
        target=original.target,
        risk=risk,
        plan=plan,
        created_at=original.manifest.created_at,
    )
    return VerifiedDecisionBatch(
        manifest=manifest,
        snapshot=original.snapshot,
        intents=original.intents,
        target=original.target,
        risk=risk,
        plan=plan,
    )


def _failing_reconciliation(snapshot: RuntimeLedgerSnapshot):
    return reconcile_three_way(
        batch_id=snapshot.batch_id,
        reconciled_at=str(snapshot.reconciliation["reconciled_at"]),
        target_positions=dict(snapshot.reconciliation["target_positions"]),
        ledger_positions=dict(snapshot.positions),
        exchange_positions=dict(snapshot.positions) | {"SOLUSDT": 1.0},
        position_tolerances=dict(snapshot.reconciliation["position_tolerances"])
        | {"SOLUSDT": 0.0},
        ledger_open_order_ids=snapshot.open_order_ids,
        exchange_open_order_ids=snapshot.open_order_ids,
        equity_residual=float(snapshot.nav["residual"]),
        equity_residual_tolerance=float(snapshot.nav["residual_tolerance"]),
    )


def _non_halt_reconciliation(snapshot: RuntimeLedgerSnapshot):
    target_positions = dict(snapshot.positions)
    first_symbol = sorted(target_positions)[0]
    target_positions[first_symbol] += 1.0
    return reconcile_three_way(
        batch_id=snapshot.batch_id,
        reconciled_at=str(snapshot.reconciliation["reconciled_at"]),
        target_positions=target_positions,
        ledger_positions=dict(snapshot.positions),
        exchange_positions=dict(snapshot.positions),
        position_tolerances=dict(snapshot.reconciliation["position_tolerances"]),
        ledger_open_order_ids=snapshot.open_order_ids,
        exchange_open_order_ids=snapshot.open_order_ids,
        equity_residual=float(snapshot.nav["residual"]),
        equity_residual_tolerance=float(snapshot.nav["residual_tolerance"]),
    )


def _snapshot_with_reconciliation(
    snapshot: RuntimeLedgerSnapshot,
    reconciliation,
) -> RuntimeLedgerSnapshot:
    core = snapshot.as_dict()
    core.pop("snapshot_hash")
    core["reconciliation"] = reconciliation.as_dict()
    return RuntimeLedgerSnapshot(
        **core,
        snapshot_hash=canonical_hash(core),
    )


class NotificationProducerTest(unittest.TestCase):
    def test_healthy_authority_surfaces_produce_no_alerts(self) -> None:
        self.assertEqual(alerts_from_verified_decision_batch(_batch()), ())
        with tempfile.TemporaryDirectory() as temporary:
            ledger, batch, _ = _ledger_with_accounting(Path(temporary))
            snapshot = build_runtime_ledger_snapshot(
                ledger, batch, captured_at=CAPTURED_AT
            )
        self.assertEqual(alerts_from_runtime_ledger_snapshot(snapshot), ())

    def test_blocked_decision_batch_produces_stable_risk_and_plan_alerts(self) -> None:
        batch = _blocked_batch()
        first = alerts_from_verified_decision_batch(batch)
        second = alerts_from_verified_decision_batch(batch)

        self.assertEqual(first, second)
        self.assertEqual(
            [(event.category, event.severity) for event in first],
            [("risk_decision", "CRITICAL"), ("execution_plan", "WARNING")],
        )
        self.assertTrue(all(event.trace_id == batch.manifest.batch_id for event in first))
        self.assertTrue(all(event.source_type == "decision_batch" for event in first))

    def test_decision_batch_tamper_fails_before_event_creation(self) -> None:
        batch = _blocked_batch()
        tampered = replace(
            batch,
            risk=replace(batch.risk, violations=("TAMPERED",)),
        )
        with self.assertRaisesRegex(
            AlertProducerError, "alert_producer_decision_batch_invalid"
        ):
            alerts_from_verified_decision_batch(tampered)

    def test_runtime_recovery_and_reconciliation_generate_halt_alerts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ledger, batch, _ = _ledger_with_accounting(
                Path(temporary), unresolved=True
            )
            snapshot = build_runtime_ledger_snapshot(
                ledger, batch, captured_at=CAPTURED_AT
            )
        failed = _snapshot_with_reconciliation(
            snapshot,
            _failing_reconciliation(snapshot),
        )
        failed.validate()
        events = alerts_from_runtime_ledger_snapshot(failed)

        self.assertEqual(
            [(event.category, event.severity) for event in events],
            [("order_recovery", "HALT"), ("reconciliation", "HALT")],
        )
        self.assertEqual(events[1].source_id, failed.reconciliation["reconciliation_id"])
        self.assertEqual(events[1].source_hash, failed.reconciliation["report_hash"])

    def test_target_ledger_only_mismatch_is_critical_not_halt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ledger, batch, _ = _ledger_with_accounting(Path(temporary))
            snapshot = build_runtime_ledger_snapshot(
                ledger, batch, captured_at=CAPTURED_AT
            )
        failed = _snapshot_with_reconciliation(
            snapshot,
            _non_halt_reconciliation(snapshot),
        )
        failed.validate()
        event = alerts_from_runtime_ledger_snapshot(failed)[0]

        self.assertEqual(event.category, "reconciliation")
        self.assertEqual(event.severity, "CRITICAL")
        self.assertFalse(failed.reconciliation["halt_required"])

    def test_failed_nav_produces_accounting_and_reconciliation_alerts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ledger, batch, _ = _ledger_with_accounting(Path(temporary))
            ledger.record_account_observation(
                batch_id=batch.manifest.batch_id,
                observed_at="2026-07-20T00:08:00+00:00",
                quote_asset="USDT",
                wallet_balance=1_017.9,
                available_balance=902.0,
                actual_gross_notional=135.0,
                margin_used=67.5,
                source_id=_hash("failed-nav-account-source-id"),
                source_hash=_hash("failed-nav-account-source"),
            )
            nav = ledger.record_nav_mark(
                marked_at="2026-07-20T00:08:00+00:00",
                equity=1_017.9,
                trading_pnl=1.0,
                residual_tolerance=0.01,
                source_hash=_hash("failed-nav"),
            )
            report = reconcile_three_way(
                batch_id=batch.manifest.batch_id,
                reconciled_at="2026-07-20T00:08:10+00:00",
                target_positions=dict(batch.plan.expected_positions),
                ledger_positions=ledger.position_quantities(),
                exchange_positions=ledger.position_quantities(),
                position_tolerances=dict(batch.plan.reconciliation_tolerance),
                ledger_open_order_ids=ledger.open_order_ids(),
                exchange_open_order_ids=ledger.open_order_ids(),
                equity_residual=nav.residual,
                equity_residual_tolerance=nav.residual_tolerance,
            )
            ledger.record_reconciliation(report)
            snapshot = build_runtime_ledger_snapshot(
                ledger,
                batch,
                captured_at="2026-07-20T00:08:20+00:00",
            )
        events = alerts_from_runtime_ledger_snapshot(snapshot)

        self.assertEqual(
            [(event.category, event.severity) for event in events],
            [("reconciliation", "HALT"), ("accounting_residual", "CRITICAL")],
        )
        self.assertFalse(snapshot.nav["passed"])

    def test_runtime_snapshot_tamper_fails_before_event_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ledger, batch, _ = _ledger_with_accounting(
                Path(temporary), unresolved=True
            )
            snapshot = build_runtime_ledger_snapshot(
                ledger, batch, captured_at=CAPTURED_AT
            )
        with self.assertRaisesRegex(
            AlertProducerError, "alert_producer_runtime_snapshot_invalid"
        ):
            alerts_from_runtime_ledger_snapshot(
                replace(snapshot, unresolved_order_ids=("tampered",))
            )

    def test_runtime_recapture_cannot_duplicate_the_same_incident(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ledger, batch, _ = _ledger_with_accounting(
                Path(temporary), unresolved=True
            )
            first = build_runtime_ledger_snapshot(
                ledger, batch, captured_at=CAPTURED_AT
            )
            later = build_runtime_ledger_snapshot(
                ledger,
                batch,
                captured_at="2026-07-20T00:10:00+00:00",
            )

        self.assertNotEqual(first.snapshot_hash, later.snapshot_hash)
        self.assertEqual(first.audit_last_hash, later.audit_last_hash)
        self.assertEqual(
            alerts_from_runtime_ledger_snapshot(first),
            alerts_from_runtime_ledger_snapshot(later),
        )

    def test_system_health_observation_is_deterministic_and_fail_closed(self) -> None:
        healthy = SystemHealthObservation.create(
            component="dashboard_publisher",
            status="healthy",
            observed_at="2026-07-20T00:07:10+00:00",
            detail_codes=(),
            source_id=_hash("publisher-health-source"),
            source_hash=_hash("publisher-health-payload"),
        )
        degraded = SystemHealthObservation.create(
            component="dashboard_publisher",
            status="degraded",
            observed_at="2026-07-20T00:07:10+00:00",
            detail_codes=("PUBLICATION_STALE",),
            source_id=_hash("publisher-health-source"),
            source_hash=_hash("publisher-health-payload"),
        )

        self.assertEqual(alerts_from_system_health(healthy), ())
        event = alerts_from_system_health(degraded)[0]
        self.assertEqual(event.severity, "WARNING")
        self.assertEqual(event.source_type, "system")
        self.assertEqual(event.source_hash, degraded.observation_hash)
        with self.assertRaisesRegex(
            AlertProducerError, "system_health_observation_hash_invalid"
        ):
            alerts_from_system_health(replace(degraded, status="unavailable"))

    def test_produced_alert_is_idempotent_through_store_and_daily_brief(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ledger, batch, registry = _ledger_with_accounting(
                root / "ledger", unresolved=True
            )
            ledger_snapshot = build_runtime_ledger_snapshot(
                ledger, batch, captured_at=CAPTURED_AT
            )
            event = alerts_from_runtime_ledger_snapshot(ledger_snapshot)[0]
            store = NotificationStore(root / "notifications" / "store.sqlite3")
            first = store.enqueue(
                event,
                channels=("dashboard",),
                recorded_at=CAPTURED_AT,
            )
            second = store.enqueue(
                event,
                channels=("dashboard",),
                recorded_at=CAPTURED_AT,
            )
            notification_snapshot = build_notification_snapshot(
                store,
                captured_at=CAPTURED_AT,
            )
            brief = build_daily_brief(
                batch,
                registry,
                ledger_snapshot,
                notification_snapshot,
                generated_at=CAPTURED_AT,
            )
            dashboard = build_dashboard_v1(
                batch,
                registry,
                generated_at=CAPTURED_AT,
                ledger_snapshot=ledger_snapshot,
                notification_snapshot=notification_snapshot,
                daily_brief=brief,
            )

        self.assertEqual(first, second)
        self.assertEqual(notification_snapshot.open_alert_count, 1)
        self.assertEqual(notification_snapshot.alerts[0]["category"], "order_recovery")
        self.assertEqual(brief.status, "halt_required")
        self.assertIn("review_open_halt_alerts", brief.owner_actions)
        self.assertEqual(
            dashboard.alerts.payload["alerts"][0]["category"],
            "order_recovery",
        )
        self.assertEqual(
            dashboard.reports.payload["summary"]["brief_status"],
            "halt_required",
        )

    def test_healthy_observation_resolves_superseded_system_incident(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = NotificationStore(Path(temporary) / "notifications.sqlite3")
            degraded = SystemHealthObservation.create(
                component="dashboard_publisher",
                status="degraded",
                observed_at="2026-07-20T00:07:10+00:00",
                detail_codes=("PUBLICATION_STALE",),
                source_id=_hash("publisher-degraded-source"),
                source_hash=_hash("publisher-degraded-payload"),
            )
            active = alerts_from_system_health(degraded)
            first = synchronize_producer_incidents(
                store,
                active,
                source_type="system",
                categories=("system_health",),
                observed_at=degraded.observed_at,
            )
            healthy = SystemHealthObservation.create(
                component="dashboard_publisher",
                status="healthy",
                observed_at="2026-07-20T00:08:10+00:00",
                detail_codes=(),
                source_id=_hash("publisher-healthy-source"),
                source_hash=_hash("publisher-healthy-payload"),
            )
            resolved = synchronize_producer_incidents(
                store,
                alerts_from_system_health(healthy),
                source_type="system",
                categories=("system_health",),
                observed_at=healthy.observed_at,
            )
            snapshot = build_notification_snapshot(
                store, captured_at="2026-07-20T00:08:11+00:00"
            )

        first.validate()
        resolved.validate()
        self.assertEqual(first.active_alert_ids, (active[0].alert_id,))
        self.assertEqual(first.resolved_alert_ids, ())
        self.assertEqual(resolved.active_alert_ids, ())
        self.assertEqual(resolved.resolved_alert_ids, (active[0].alert_id,))
        self.assertEqual(snapshot.open_alert_count, 0)
        self.assertEqual(snapshot.alerts[0]["status"], "RESOLVED")
        with self.assertRaisesRegex(AlertProducerError, "sync_hash_invalid"):
            replace(resolved, sync_hash="f" * 64).validate()

    def test_producer_output_matches_golden_fixture(self) -> None:
        batch_events = alerts_from_verified_decision_batch(_blocked_batch())
        system = SystemHealthObservation.create(
            component="dashboard_publisher",
            status="degraded",
            observed_at="2026-07-20T00:07:10+00:00",
            detail_codes=("PUBLICATION_STALE",),
            source_id=_hash("publisher-health-source"),
            source_hash=_hash("publisher-health-payload"),
        )
        value = {
            "schema_version": 1,
            "decision_batch_alerts": [event.as_dict() for event in batch_events],
            "system_health_observation": system.as_dict(),
            "system_alerts": [
                event.as_dict() for event in alerts_from_system_health(system)
            ],
        }
        actual = (
            json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("ascii")
        expected = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "notification_producers_v1_golden.json"
        ).read_bytes()
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
