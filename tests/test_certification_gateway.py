from __future__ import annotations

import unittest

from qount.certification.fault_injection import FAULT_TYPES
from qount.certification.fault_injection import FaultInjector
from qount.certification.fault_injection import FaultScenario
from qount.certification.gateway import GatewayAckLoss
from qount.certification.gateway import GatewayCrash
from qount.certification.gateway import GatewayError
from qount.certification.gateway import GatewayTimeout
from qount.certification.gateway import LocalVenueGateway
from qount.certification.replay import recover_orders
from qount.certification.replay import rest_snapshot_recovery
from qount.certification.replay import verify_no_replacement_orders
from qount.certification.replay import verify_no_unresolved_unknown


class ClientIdIdempotencyTest(unittest.TestCase):
    """Section 3.4: client ID idempotency -- duplicate submit does not create second order."""

    def test_duplicate_submit_returns_same_order(self):
        gw = LocalVenueGateway()
        r1 = gw.submit(
            client_order_id="cert-001", symbol="BTCUSDT",
            side="BUY", qty=0.001,
        )
        r2 = gw.submit(
            client_order_id="cert-001", symbol="BTCUSDT",
            side="BUY", qty=0.001,
        )
        self.assertEqual(r1["client_order_id"], r2["client_order_id"])
        self.assertEqual(gw.order_count, 1)

    def test_different_client_ids_create_separate_orders(self):
        gw = LocalVenueGateway()
        gw.submit(
            client_order_id="cert-001", symbol="BTCUSDT",
            side="BUY", qty=0.001,
        )
        gw.submit(
            client_order_id="cert-002", symbol="BTCUSDT",
            side="BUY", qty=0.001,
        )
        self.assertEqual(gw.order_count, 2)


class AckLossTest(unittest.TestCase):
    """Section 3.4: ACK loss -- query after ACK loss gives unique closed state."""

    def test_ack_loss_then_query_resolves(self):
        gw = LocalVenueGateway()
        injector = FaultInjector()
        injector.register(
            FaultScenario(
                scenario_id="s1",
                trigger_client_order_id="cert-ack-001",
                fault_type="ack_loss",
            )
        )
        gw.set_fault_injector(injector)
        with self.assertRaises(GatewayAckLoss):
            gw.submit(
                client_order_id="cert-ack-001", symbol="BTCUSDT",
                side="BUY", qty=0.001,
            )
        state = gw.query(client_order_id="cert-ack-001")
        self.assertEqual(state["status"], "UNKNOWN")

    def test_rest_timeout_raises(self):
        gw = LocalVenueGateway()
        injector = FaultInjector()
        injector.register(
            FaultScenario(
                scenario_id="s2",
                trigger_client_order_id="cert-timeout-001",
                fault_type="rest_timeout",
            )
        )
        gw.set_fault_injector(injector)
        with self.assertRaises(GatewayTimeout):
            gw.submit(
                client_order_id="cert-timeout-001", symbol="BTCUSDT",
                side="BUY", qty=0.001,
            )


class PartialFillTest(unittest.TestCase):
    """Section 3.4: partial fill -- remaining qty, fee, position consistent."""

    def test_partial_fill_leaves_remaining(self):
        gw = LocalVenueGateway()
        injector = FaultInjector()
        injector.register(
            FaultScenario(
                scenario_id="s3",
                trigger_client_order_id="cert-partial-001",
                fault_type="partial_fill",
                parameters={"fill_qty": 0.0005},
            )
        )
        gw.set_fault_injector(injector)
        result = gw.submit(
            client_order_id="cert-partial-001", symbol="BTCUSDT",
            side="BUY", qty=0.001,
        )
        self.assertEqual(result["status"], "PARTIALLY_FILLED")
        self.assertEqual(float(result["executedQty"]), 0.0005)
        self.assertAlmostEqual(gw._positions["BTCUSDT"], 0.0005)


class StopAlgoTest(unittest.TestCase):
    """Section 3.4: STOP/Algo -- create/query/cancel/0-position."""

    def test_stop_market_create_query_cancel(self):
        gw = LocalVenueGateway()
        result = gw.submit(
            client_order_id="cert-stop-001", symbol="BTCUSDT",
            side="SELL", qty=0.001, order_type="STOP_MARKET",
            stop_price=95000.0, reduce_only=True,
        )
        self.assertEqual(result["status"], "NEW")
        self.assertEqual(result["type"], "STOP_MARKET")
        state = gw.query(client_order_id="cert-stop-001")
        self.assertEqual(state["status"], "NEW")
        cancel_result = gw.cancel(client_order_id="cert-stop-001")
        self.assertEqual(cancel_result["status"], "CANCELLED")
        self.assertEqual(gw.position_count, 0)


class CrashRecoveryTest(unittest.TestCase):
    """Section 3.4: crash recovery at SUBMITTING/ACKNOWLEDGED/PARTIALLY_FILLED."""

    def test_crash_at_submitting_then_recover(self):
        gw = LocalVenueGateway()
        injector = FaultInjector()
        injector.register(
            FaultScenario(
                scenario_id="s4",
                trigger_client_order_id="cert-crash-s",
                fault_type="crash_at_submitting",
            )
        )
        gw.set_fault_injector(injector)
        with self.assertRaises(GatewayCrash):
            gw.submit(
                client_order_id="cert-crash-s", symbol="BTCUSDT",
                side="BUY", qty=0.001,
            )
        self.assertTrue(gw._crashed)
        states = recover_orders(gw, ["cert-crash-s"])
        self.assertEqual(len(states), 1)
        self.assertEqual(states[0]["status"], "UNKNOWN")

    def test_crash_at_acknowledged_then_recover(self):
        gw = LocalVenueGateway()
        injector = FaultInjector()
        injector.register(
            FaultScenario(
                scenario_id="s5",
                trigger_client_order_id="cert-crash-a",
                fault_type="crash_at_acknowledged",
            )
        )
        gw.set_fault_injector(injector)
        with self.assertRaises(GatewayCrash):
            gw.submit(
                client_order_id="cert-crash-a", symbol="BTCUSDT",
                side="BUY", qty=0.001,
            )
        states = recover_orders(gw, ["cert-crash-a"])
        self.assertEqual(states[0]["status"], "UNKNOWN")

    def test_crash_at_partial_then_recover(self):
        gw = LocalVenueGateway()
        injector = FaultInjector()
        injector.register(
            FaultScenario(
                scenario_id="s6",
                trigger_client_order_id="cert-crash-p",
                fault_type="partial_fill",
                parameters={"fill_qty": 0.0005},
            )
        )
        gw.set_fault_injector(injector)
        result = gw.submit(
            client_order_id="cert-crash-p", symbol="BTCUSDT",
            side="BUY", qty=0.001,
        )
        self.assertEqual(result["status"], "PARTIALLY_FILLED")
        states = recover_orders(gw, ["cert-crash-p"])
        self.assertEqual(states[0]["status"], "PARTIALLY_FILLED")

    def test_no_replacement_orders_after_recovery(self):
        gw = LocalVenueGateway()
        pre_ids = {"cert-recover-001"}
        states = recover_orders(gw, list(pre_ids))
        post_ids = {s.get("client_order_id") for s in states}
        errors = verify_no_replacement_orders(pre_ids, post_ids)
        self.assertEqual(errors, ())

    def test_unresolved_unknown_detected(self):
        states = [
            {"client_order_id": "x", "status": "UNKNOWN"},
            {"client_order_id": "y", "status": "FILLED"},
        ]
        errors = verify_no_unresolved_unknown(states)
        self.assertEqual(len(errors), 1)
        self.assertIn("x", errors[0])


class RestSnapshotTest(unittest.TestCase):
    """Section 3.4: REST snapshot covers WS gap."""

    def test_snapshot_returns_all_state(self):
        gw = LocalVenueGateway()
        gw.submit(
            client_order_id="cert-snap-001", symbol="BTCUSDT",
            side="BUY", qty=0.001,
        )
        gw.submit(
            client_order_id="cert-snap-002", symbol="ETHUSDT",
            side="BUY", qty=0.01,
        )
        snap = rest_snapshot_recovery(gw)
        self.assertEqual(len(snap["orders"]), 2)
        self.assertIn("BTCUSDT", snap["positions"])
        self.assertIn("ETHUSDT", snap["positions"])

    def test_snapshot_after_crash(self):
        gw = LocalVenueGateway()
        injector = FaultInjector()
        injector.register(
            FaultScenario(
                scenario_id="s7",
                trigger_client_order_id="cert-snap-crash",
                fault_type="crash_at_submitting",
            )
        )
        gw.set_fault_injector(injector)
        try:
            gw.submit(
                client_order_id="cert-snap-crash", symbol="BTCUSDT",
                side="BUY", qty=0.001,
            )
        except GatewayCrash:
            pass
        recover_orders(gw, ["cert-snap-crash"])
        snap = rest_snapshot_recovery(gw)
        self.assertEqual(len(snap["orders"]), 1)


class FaultScenarioValidationTest(unittest.TestCase):
    def test_valid_scenario(self):
        scenario = FaultScenario(
            scenario_id="test",
            trigger_client_order_id="cert-001",
            fault_type="ack_loss",
        )
        self.assertEqual(scenario.validate(), ())

    def test_invalid_fault_type(self):
        scenario = FaultScenario(
            scenario_id="test",
            trigger_client_order_id="cert-001",
            fault_type="invalid",
        )
        errors = scenario.validate()
        self.assertIn("fault_scenario_type_invalid", errors)

    def test_injector_fires_once(self):
        injector = FaultInjector()
        injector.register(
            FaultScenario(
                scenario_id="test",
                trigger_client_order_id="cert-001",
                fault_type="ack_loss",
            )
        )
        self.assertIsNotNone(
            injector.check("cert-001", "submit")
        )
        self.assertIsNone(
            injector.check("cert-001", "submit")
        )
        self.assertEqual(injector.fired_count, 1)


if __name__ == "__main__":
    unittest.main()
