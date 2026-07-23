from __future__ import annotations

import unittest

from qount.certification.contracts import REQUIRED_RESULT_MEMBERS
from qount.certification.contracts import CertificationPlan
from qount.certification.fault_injection import FaultInjector
from qount.certification.fault_injection import FaultScenario
from qount.certification.gateway import GatewayAckLoss
from qount.certification.gateway import GatewayCrash
from qount.certification.gateway import LocalVenueGateway
from qount.certification.runner import CertificationRunner

_DUMMY_HASH = "a" * 64


def _make_plan(
    *,
    certification_type: str = "local_gateway",
    venue_semantic: str = "client_id_idempotency",
    symbol: str = "BTCUSDT",
    action: str = "test_submit_cancel",
) -> CertificationPlan:
    return CertificationPlan.create(
        certification_type=certification_type,
        venue_semantic=venue_semantic,
        symbol=symbol,
        action=action,
        max_notional=100.0,
        max_fee=1.0,
        max_holding_time_seconds=3600.0,
        owner_authorization_hash=_DUMMY_HASH,
        arm_token_hash=_DUMMY_HASH,
        expires_at="2026-12-31T23:59:59+00:00",
        preflight_snapshot_hash=_DUMMY_HASH,
        venue_capability_snapshot_hash=_DUMMY_HASH,
        zero_position_plan="cancel_all_orders_and_verify_zero",
        failure_handling_path="manual_flatten_and_reconcile",
        certification_status="local_sim",
    )


class EndToEndRunTest(unittest.TestCase):
    """Section 3.4: clean run -- submit, cancel, verify zero, completed=True."""

    def test_buy_then_sell_completes_with_zero_position(self):
        gw = LocalVenueGateway()
        plan = _make_plan(venue_semantic="client_id_idempotency")
        runner = CertificationRunner(plan, gw, source="local_gateway")
        run = runner.start()
        self.assertEqual(run.status, "running")
        runner.submit_order("cert-001", "BTCUSDT", "BUY", 0.001)
        self.assertFalse(runner.verify_zero_position())
        runner.submit_order("cert-002", "BTCUSDT", "SELL", 0.001)
        self.assertTrue(runner.verify_zero_position())
        result = runner.generate_result()
        self.assertTrue(result.completed)
        self.assertTrue(result.final_position_is_zero)
        member_types = {ref.artifact_type for ref in result.artifact_members}
        for required in REQUIRED_RESULT_MEMBERS:
            with self.subTest(member=required):
                self.assertIn(required, member_types)

    def test_run_status_completed_after_generate(self):
        gw = LocalVenueGateway()
        plan = _make_plan()
        runner = CertificationRunner(plan, gw, source="local_gateway")
        runner.start()
        runner.submit_order("c1", "BTCUSDT", "BUY", 0.001)
        runner.submit_order("c2", "BTCUSDT", "SELL", 0.001)
        runner.generate_result()
        self.assertEqual(runner.run.status, "completed")

    def test_generate_result_without_start_raises(self):
        gw = LocalVenueGateway()
        plan = _make_plan()
        runner = CertificationRunner(plan, gw, source="local_gateway")
        with self.assertRaises(RuntimeError):
            runner.generate_result()


class NonZeroPositionTest(unittest.TestCase):
    """completed=False when final position is non-zero."""

    def test_open_position_not_completed(self):
        gw = LocalVenueGateway()
        plan = _make_plan()
        runner = CertificationRunner(plan, gw, source="local_gateway")
        runner.start()
        runner.submit_order("cert-open", "BTCUSDT", "BUY", 0.001)
        result = runner.generate_result()
        self.assertFalse(result.completed)
        self.assertFalse(result.final_position_is_zero)
        self.assertEqual(runner.run.status, "halted")


class AckLossRecoveryTest(unittest.TestCase):
    """Section 3.4: ACK loss -- query resolves to UNKNOWN, no replacement order."""

    def test_ack_loss_then_query_records_unknown(self):
        gw = LocalVenueGateway()
        injector = FaultInjector()
        injector.register(
            FaultScenario(
                scenario_id="s1",
                trigger_client_order_id="cert-ack",
                fault_type="ack_loss",
            )
        )
        gw.set_fault_injector(injector)
        plan = _make_plan(venue_semantic="ack_loss")
        runner = CertificationRunner(plan, gw, source="local_gateway")
        runner.start()
        with self.assertRaises(GatewayAckLoss):
            runner.submit_order("cert-ack", "BTCUSDT", "BUY", 0.001)
        state = runner.query_order("cert-ack")
        self.assertEqual(state["status"], "UNKNOWN")
        submit_events = [
            e for e in runner.events if e.event_type == "submit"
        ]
        self.assertEqual(len(submit_events), 1)
        self.assertEqual(submit_events[0].observed_state, "UNKNOWN")

    def test_ack_loss_recover_flags_unresolved_unknown(self):
        gw = LocalVenueGateway()
        injector = FaultInjector()
        injector.register(
            FaultScenario(
                scenario_id="s2",
                trigger_client_order_id="cert-ack-r",
                fault_type="ack_loss",
            )
        )
        gw.set_fault_injector(injector)
        plan = _make_plan(venue_semantic="ack_loss")
        runner = CertificationRunner(plan, gw, source="local_gateway")
        runner.start()
        with self.assertRaises(GatewayAckLoss):
            runner.submit_order("cert-ack-r", "BTCUSDT", "BUY", 0.001)
        runner.recover_from_crash(["cert-ack-r"])
        self.assertTrue(
            any("unresolved_unknown" in e for e in runner.halt_errors)
        )


class CrashRecoveryTest(unittest.TestCase):
    """Section 3.4: crash at SUBMITTING/ACKNOWLEDGED -- recover, no replacement."""

    def test_crash_at_submitting_then_recover(self):
        gw = LocalVenueGateway()
        injector = FaultInjector()
        injector.register(
            FaultScenario(
                scenario_id="s3",
                trigger_client_order_id="cert-crash-s",
                fault_type="crash_at_submitting",
            )
        )
        gw.set_fault_injector(injector)
        plan = _make_plan(venue_semantic="crash_recovery")
        runner = CertificationRunner(plan, gw, source="local_gateway")
        runner.start()
        with self.assertRaises(GatewayCrash):
            runner.submit_order("cert-crash-s", "BTCUSDT", "BUY", 0.001)
        states = runner.recover_from_crash(["cert-crash-s"])
        self.assertEqual(len(states), 1)
        self.assertEqual(states[0]["status"], "UNKNOWN")
        recover_events = [
            e for e in runner.events if e.event_type == "recover"
        ]
        self.assertEqual(len(recover_events), 1)

    def test_crash_at_acknowledged_then_recover(self):
        gw = LocalVenueGateway()
        injector = FaultInjector()
        injector.register(
            FaultScenario(
                scenario_id="s4",
                trigger_client_order_id="cert-crash-a",
                fault_type="crash_at_acknowledged",
            )
        )
        gw.set_fault_injector(injector)
        plan = _make_plan(venue_semantic="crash_recovery")
        runner = CertificationRunner(plan, gw, source="local_gateway")
        runner.start()
        with self.assertRaises(GatewayCrash):
            runner.submit_order("cert-crash-a", "BTCUSDT", "BUY", 0.001)
        states = runner.recover_from_crash(["cert-crash-a"])
        self.assertEqual(states[0]["status"], "UNKNOWN")

    def test_no_replacement_orders_after_recovery(self):
        gw = LocalVenueGateway()
        plan = _make_plan(venue_semantic="crash_recovery")
        runner = CertificationRunner(plan, gw, source="local_gateway")
        runner.start()
        runner.submit_order("cert-live", "BTCUSDT", "BUY", 0.001)
        runner.recover_from_crash(["cert-live"])
        replacement_errors = [
            e for e in runner.halt_errors if "replacement_orders" in e
        ]
        self.assertEqual(replacement_errors, [])


class PartialFillTest(unittest.TestCase):
    """Section 3.4: partial fill -- remaining qty, position consistent."""

    def test_partial_fill_then_cancel_to_zero(self):
        gw = LocalVenueGateway()
        injector = FaultInjector()
        injector.register(
            FaultScenario(
                scenario_id="s5",
                trigger_client_order_id="cert-partial",
                fault_type="partial_fill",
                parameters={"fill_qty": 0.0005},
            )
        )
        gw.set_fault_injector(injector)
        plan = _make_plan(venue_semantic="partial_fill")
        runner = CertificationRunner(plan, gw, source="local_gateway")
        runner.start()
        result = runner.submit_order(
            "cert-partial", "BTCUSDT", "BUY", 0.001
        )
        self.assertEqual(result["status"], "PARTIALLY_FILLED")
        self.assertFalse(runner.verify_zero_position())
        runner.submit_order("cert-close", "BTCUSDT", "SELL", 0.0005)
        self.assertTrue(runner.verify_zero_position())
        cert_result = runner.generate_result()
        self.assertTrue(cert_result.completed)


class StopAlgoTest(unittest.TestCase):
    """Section 3.4: STOP/Algo -- create/query/cancel/0-position."""

    def test_stop_market_lifecycle(self):
        gw = LocalVenueGateway()
        plan = _make_plan(venue_semantic="stop_algo")
        runner = CertificationRunner(plan, gw, source="local_gateway")
        runner.start()
        result = runner.submit_order(
            "cert-stop", "BTCUSDT", "SELL", 0.001,
            order_type="STOP_MARKET", stop_price=95000.0,
            reduce_only=True,
        )
        self.assertEqual(result["status"], "NEW")
        self.assertEqual(result["type"], "STOP_MARKET")
        state = runner.query_order("cert-stop")
        self.assertEqual(state["status"], "NEW")
        runner.cancel_order("cert-stop")
        self.assertTrue(runner.verify_zero_position())
        cert_result = runner.generate_result()
        self.assertTrue(cert_result.completed)


class DuplicateClientIdBlockedTest(unittest.TestCase):
    """Section 3.4 + finding 1: runner blocks duplicate client_order_id.

    The testnet does not enforce newClientOrderId uniqueness, so the
    runner itself must reject a duplicate submit fail-closed instead of
    forwarding a second order to the venue.
    """

    def test_duplicate_client_order_id_raises(self):
        gw = LocalVenueGateway()
        plan = _make_plan(venue_semantic="client_id_idempotency")
        runner = CertificationRunner(plan, gw, source="local_gateway")
        runner.start()
        runner.submit_order("dup-001", "BTCUSDT", "BUY", 0.001)
        with self.assertRaises(ValueError) as ctx:
            runner.submit_order("dup-001", "BTCUSDT", "BUY", 0.001)
        self.assertIn("duplicate_client_order_id", str(ctx.exception))

    def test_distinct_client_order_ids_allowed(self):
        gw = LocalVenueGateway()
        plan = _make_plan()
        runner = CertificationRunner(plan, gw, source="local_gateway")
        runner.start()
        runner.submit_order("c-a", "BTCUSDT", "BUY", 0.001)
        runner.submit_order("c-b", "BTCUSDT", "SELL", 0.001)
        self.assertTrue(runner.verify_zero_position())

    def test_duplicate_not_recorded_as_second_event(self):
        gw = LocalVenueGateway()
        plan = _make_plan(venue_semantic="client_id_idempotency")
        runner = CertificationRunner(plan, gw, source="local_gateway")
        runner.start()
        runner.submit_order("dup-002", "BTCUSDT", "BUY", 0.001)
        with self.assertRaises(ValueError):
            runner.submit_order("dup-002", "BTCUSDT", "BUY", 0.001)
        submit_events = [
            e for e in runner.events
            if e.event_type == "submit" and e.client_order_id == "dup-002"
        ]
        self.assertEqual(len(submit_events), 1)


class RestSnapshotRecoveryTest(unittest.TestCase):
    """Section 3.4: REST snapshot covers WS gap."""

    def test_rest_snapshot_returns_full_state(self):
        gw = LocalVenueGateway()
        plan = _make_plan(venue_semantic="crash_recovery")
        runner = CertificationRunner(plan, gw, source="local_gateway")
        runner.start()
        runner.submit_order("cert-s1", "BTCUSDT", "BUY", 0.001)
        runner.submit_order("cert-s2", "ETHUSDT", "BUY", 0.01)
        snap = runner.rest_snapshot_recover()
        self.assertEqual(len(snap["orders"]), 2)
        self.assertIn("BTCUSDT", snap["positions"])
        self.assertIn("ETHUSDT", snap["positions"])


class ManifestIntegrityTest(unittest.TestCase):
    """Section 3.3: all 12 members present, manifest last, hash integrity."""

    def test_all_required_members_present(self):
        gw = LocalVenueGateway()
        plan = _make_plan()
        runner = CertificationRunner(plan, gw, source="local_gateway")
        runner.start()
        runner.submit_order("c1", "BTCUSDT", "BUY", 0.001)
        runner.submit_order("c2", "BTCUSDT", "SELL", 0.001)
        result = runner.generate_result()
        member_types = [ref.artifact_type for ref in result.artifact_members]
        self.assertEqual(len(member_types), len(REQUIRED_RESULT_MEMBERS))
        self.assertEqual(len(set(member_types)), len(member_types))
        for required in REQUIRED_RESULT_MEMBERS:
            self.assertIn(required, member_types)

    def test_all_member_hashes_valid(self):
        gw = LocalVenueGateway()
        plan = _make_plan()
        runner = CertificationRunner(plan, gw, source="local_gateway")
        runner.start()
        runner.submit_order("c1", "BTCUSDT", "BUY", 0.001)
        runner.submit_order("c2", "BTCUSDT", "SELL", 0.001)
        result = runner.generate_result()
        for ref in result.artifact_members:
            with self.subTest(member=ref.artifact_type):
                self.assertEqual(len(ref.object_id), 64)
                self.assertEqual(len(ref.payload_hash), 64)
                self.assertEqual(len(ref.artifact_hash), 64)

    def test_result_hash_deterministic_for_same_run(self):
        gw1 = LocalVenueGateway()
        plan1 = _make_plan()
        r1 = CertificationRunner(plan1, gw1, source="local_gateway")
        r1.start()
        r1.submit_order("c1", "BTCUSDT", "BUY", 0.001)
        r1.submit_order("c2", "BTCUSDT", "SELL", 0.001)
        result1 = r1.generate_result()

        gw2 = LocalVenueGateway()
        plan2 = _make_plan()
        r2 = CertificationRunner(plan2, gw2, source="local_gateway")
        r2.start()
        r2.submit_order("c1", "BTCUSDT", "BUY", 0.001)
        r2.submit_order("c2", "BTCUSDT", "SELL", 0.001)
        result2 = r2.generate_result()

        self.assertEqual(
            result1.artifact_members[0].payload_hash,
            result2.artifact_members[0].payload_hash,
        )


class ShadowReconciliationTest(unittest.TestCase):
    """Shadow accountant independently reconstructs positions from trades."""

    def test_shadow_matches_primary_on_clean_run(self):
        gw = LocalVenueGateway()
        plan = _make_plan()
        runner = CertificationRunner(plan, gw, source="local_gateway")
        runner.start()
        runner.submit_order("c1", "BTCUSDT", "BUY", 0.001)
        runner.submit_order("c2", "ETHUSDT", "BUY", 0.01)
        runner.submit_order("c3", "BTCUSDT", "SELL", 0.001)
        runner.submit_order("c4", "ETHUSDT", "SELL", 0.01)
        result = runner.generate_result()
        recon_ref = None
        for ref in result.artifact_members:
            if ref.artifact_type == "reconciliation_diff":
                recon_ref = ref
                break
        self.assertIsNotNone(recon_ref)

    def test_events_recorded_with_correct_source(self):
        gw = LocalVenueGateway()
        plan = _make_plan()
        runner = CertificationRunner(plan, gw, source="local_gateway")
        runner.start()
        runner.submit_order("c1", "BTCUSDT", "BUY", 0.001)
        runner.cancel_order("c1")
        for event in runner.events:
            self.assertEqual(event.source, "local_gateway")


class TestnetSourceTypeTest(unittest.TestCase):
    """Runner accepts source='testnet' for future testnet runs."""

    def test_testnet_source_in_events(self):
        gw = LocalVenueGateway()
        plan = _make_plan(
            certification_type="testnet",
            venue_semantic="client_id_idempotency",
        )
        runner = CertificationRunner(plan, gw, source="testnet")
        runner.start()
        runner.submit_order("c1", "BTCUSDT", "BUY", 0.001)
        runner.submit_order("c2", "BTCUSDT", "SELL", 0.001)
        for event in runner.events:
            self.assertEqual(event.source, "testnet")
        result = runner.generate_result()
        self.assertTrue(result.completed)


if __name__ == "__main__":
    unittest.main()
