from __future__ import annotations

import unittest
from typing import Any

from qount.certification.arm import CertificationArm
from qount.certification.real_client import CertificationArmNotAuthorized
from qount.certification.real_client import RealVenueClient

_HASH_A = "a" * 64
_HASH_B = "b" * 64
_PLAN_ID = "c" * 64
_AUTHORIZED = "2026-07-23T10:00:00+00:00"
_EXPIRES = "2026-07-23T11:00:00+00:00"
_NOW_VALID = "2026-07-23T10:30:00+00:00"
_NOW_EXPIRED = "2026-07-23T11:30:00+00:00"


class MockExchange:
    def __init__(self) -> None:
        self.created_orders: list[dict[str, Any]] = []
        self.cancelled_orders: list[dict[str, Any]] = []
        self.fetched_orders: list[dict[str, Any]] = []
        self._next_id = 1
        self._positions: list[dict[str, Any]] = []
        self._open_orders: list[dict[str, Any]] = []
        self._trades: list[dict[str, Any]] = []

    def create_order(self, symbol, type, side, amount, params=None):
        order_id = str(self._next_id)
        self._next_id += 1
        filled = amount if type == "market" else 0.0
        status = "closed" if type == "market" else "open"
        response = {
            "id": order_id,
            "symbol": symbol,
            "type": type,
            "side": side,
            "amount": amount,
            "filled": filled,
            "status": status,
        }
        self.created_orders.append(response)
        return response

    def cancel_order(self, id, symbol, params=None):
        self.cancelled_orders.append({"id": id, "symbol": symbol})
        return {"id": id, "status": "canceled"}

    def fetch_order(self, id, symbol, params=None):
        self.fetched_orders.append({"id": id, "symbol": symbol})
        return {"id": id, "status": "closed", "filled": 0.001, "amount": 0.001}

    def fetch_open_orders(self, symbol=None):
        return list(self._open_orders)

    def fetch_positions(self):
        return list(self._positions)

    def fetch_my_trades(self, symbol=None, limit=100):
        return list(self._trades)


def _make_arm(**overrides) -> CertificationArm:
    params: dict = dict(
        plan_id=_PLAN_ID,
        authorized_at=_AUTHORIZED,
        expires_at=_EXPIRES,
        owner_authorization_hash=_HASH_A,
        arm_token_hash=_HASH_B,
    )
    params.update(overrides)
    return CertificationArm.create(**params)


def _make_client(mock, arm, now=_NOW_VALID):
    clock = {"now": now}
    client = RealVenueClient(mock, arm, now_provider=lambda: clock["now"])
    return client, clock


class RealVenueClientArmGateTest(unittest.TestCase):
    """Section 3.1: real submit gated by independent certification arm."""

    def test_submit_allowed_when_arm_valid(self):
        mock = MockExchange()
        arm = _make_arm()
        client, _ = _make_client(mock, arm, _NOW_VALID)
        result = client.submit(
            client_order_id="real-001",
            symbol="BTCUSDT",
            side="BUY",
            qty=0.001,
        )
        self.assertEqual(result["status"], "FILLED")
        self.assertEqual(len(mock.created_orders), 1)

    def test_submit_blocked_when_arm_expired(self):
        mock = MockExchange()
        arm = _make_arm()
        client, _ = _make_client(mock, arm, _NOW_EXPIRED)
        with self.assertRaises(CertificationArmNotAuthorized):
            client.submit(
                client_order_id="real-002",
                symbol="BTCUSDT",
                side="BUY",
                qty=0.001,
            )
        self.assertEqual(len(mock.created_orders), 0)

    def test_submit_blocked_when_arm_used(self):
        mock = MockExchange()
        arm = _make_arm().mark_used()
        client, _ = _make_client(mock, arm, _NOW_VALID)
        with self.assertRaises(CertificationArmNotAuthorized):
            client.submit(
                client_order_id="real-003",
                symbol="BTCUSDT",
                side="BUY",
                qty=0.001,
            )
        self.assertEqual(len(mock.created_orders), 0)

    def test_orders_authorized_reflects_arm_validity(self):
        mock = MockExchange()
        arm = _make_arm()
        client_valid, _ = _make_client(mock, arm, _NOW_VALID)
        self.assertTrue(client_valid.orders_authorized)
        client_expired, _ = _make_client(mock, arm, _NOW_EXPIRED)
        self.assertFalse(client_expired.orders_authorized)

    def test_orders_authorized_false_when_arm_used(self):
        mock = MockExchange()
        arm = _make_arm().mark_used()
        client, _ = _make_client(mock, arm, _NOW_VALID)
        self.assertFalse(client.orders_authorized)

    def test_arm_exposed_for_persistence(self):
        mock = MockExchange()
        arm = _make_arm()
        client, _ = _make_client(mock, arm, _NOW_VALID)
        self.assertIs(client.arm, arm)


class RealVenueClientQueryCancelTest(unittest.TestCase):
    """Query/cancel are not arm-gated: they reduce risk, never add it.

    A certification arm may expire mid-run; query and cancel must still
    work to resolve UNKNOWN and zero out the position (section 3.1, 5.3).
    """

    def test_query_allowed_after_arm_expiry(self):
        mock = MockExchange()
        arm = _make_arm()
        client, clock = _make_client(mock, arm, _NOW_VALID)
        client.submit(
            client_order_id="q-001",
            symbol="BTCUSDT",
            side="BUY",
            qty=0.001,
        )
        clock["now"] = _NOW_EXPIRED
        self.assertFalse(client.orders_authorized)
        result = client.query(client_order_id="q-001")
        self.assertEqual(len(mock.fetched_orders), 1)

    def test_cancel_allowed_after_arm_expiry(self):
        mock = MockExchange()
        arm = _make_arm()
        client, clock = _make_client(mock, arm, _NOW_VALID)
        client.submit(
            client_order_id="c-001",
            symbol="BTCUSDT",
            side="BUY",
            qty=0.001,
        )
        clock["now"] = _NOW_EXPIRED
        self.assertFalse(client.orders_authorized)
        result = client.cancel(client_order_id="c-001")
        self.assertEqual(result["status"], "CANCELLED")
        self.assertEqual(len(mock.cancelled_orders), 1)


if __name__ == "__main__":
    unittest.main()
