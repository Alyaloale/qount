from __future__ import annotations

import importlib.util
import unittest
from typing import Any

from qount.certification.testnet_client import TestnetVenueClient
from qount.settings import PRODUCTION_CRITICAL_FIELDS
from qount.settings import Settings

_CCXT_AVAILABLE = importlib.util.find_spec("ccxt") is not None


class MockExchange:
    """Minimal mock of a ccxt exchange for testnet client tests."""

    def __init__(self) -> None:
        self.sandbox_mode: bool = False
        self.created_orders: list[dict[str, Any]] = []
        self.cancelled_orders: list[dict[str, Any]] = []
        self.fetched_orders: list[dict[str, Any]] = []
        self.fetched_algo: list[dict[str, Any]] = []
        self.cancelled_algo: list[dict[str, Any]] = []
        self._next_id = 1
        self._positions: list[dict[str, Any]] = []
        self._open_orders: list[dict[str, Any]] = []
        self._trades: list[dict[str, Any]] = []

    def set_sandbox_mode(self, enabled: bool) -> None:
        self.sandbox_mode = enabled

    def create_order(
        self,
        symbol: str,
        type: str,
        side: str,
        amount: float,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
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
        if type == "stop_market":
            client_algo_id = (params or {}).get("newClientOrderId", "")
            response["info"] = {
                "algoId": int(order_id),
                "clientAlgoId": client_algo_id,
                "symbol": symbol,
                "algoType": "CONDITIONAL",
                "algoStatus": "NEW",
            }
        self.created_orders.append(response)
        return response

    def fapiPrivateGetAlgoOrder(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = params or {}
        self.fetched_algo.append(dict(params))
        return {
            "algoId": 0,
            "clientAlgoId": params.get("clientAlgoId", ""),
            "algoStatus": "NEW",
            "algoType": "CONDITIONAL",
            "symbol": "BTCUSDT",
        }

    def fapiPrivateDeleteAlgoOrder(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = params or {}
        self.cancelled_algo.append(dict(params))
        return {"code": 200, "msg": "OK"}

    def cancel_order(
        self,
        id: str,
        symbol: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.cancelled_orders.append({"id": id, "symbol": symbol})
        return {"id": id, "status": "canceled"}

    def fetch_order(
        self,
        id: str,
        symbol: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.fetched_orders.append({"id": id, "symbol": symbol})
        return {
            "id": id,
            "status": "closed",
            "filled": 0.001,
            "amount": 0.001,
        }

    def fetch_open_orders(self, symbol: str | None = None) -> list:
        return list(self._open_orders)

    def fetch_positions(self) -> list:
        return list(self._positions)

    def fetch_my_trades(
        self, symbol: str | None = None, limit: int = 100
    ) -> list:
        return list(self._trades)


class TestnetVenueClientSubmitTest(unittest.TestCase):
    def test_submit_market_order_returns_filled(self):
        mock = MockExchange()
        client = TestnetVenueClient(mock)
        result = client.submit(
            client_order_id="test-001",
            symbol="BTCUSDT",
            side="BUY",
            qty=0.001,
        )
        self.assertEqual(result["status"], "FILLED")
        self.assertEqual(result["client_order_id"], "test-001")
        self.assertTrue(result["exchange_order_id"])
        self.assertEqual(result["raw_response"]["id"], "1")
        self.assertEqual(mock.created_orders[0]["symbol"], "BTC/USDT:USDT")
        self.assertEqual(
            mock.created_orders[0]["params" if False else "side"], "buy"
        )

    def test_submit_records_metadata_for_cancel_query(self):
        mock = MockExchange()
        client = TestnetVenueClient(mock)
        client.submit(
            client_order_id="test-002",
            symbol="ETHUSDT",
            side="SELL",
            qty=0.01,
        )
        self.assertEqual(client.order_count, 1)

    def test_submit_stop_market_passes_stop_price(self):
        mock = MockExchange()
        client = TestnetVenueClient(mock)
        client.submit(
            client_order_id="test-003",
            symbol="BTCUSDT",
            side="SELL",
            qty=0.001,
            order_type="STOP_MARKET",
            stop_price=95000.0,
            reduce_only=True,
        )
        self.assertEqual(mock.created_orders[0]["type"], "stop_market")

    def test_position_count_tracks_buys(self):
        mock = MockExchange()
        client = TestnetVenueClient(mock)
        client.submit(
            client_order_id="test-004",
            symbol="BTCUSDT",
            side="BUY",
            qty=0.001,
        )
        self.assertEqual(client.position_count, 1)

    def test_buy_then_sell_zero_position(self):
        mock = MockExchange()
        client = TestnetVenueClient(mock)
        client.submit(
            client_order_id="test-005a",
            symbol="BTCUSDT",
            side="BUY",
            qty=0.001,
        )
        self.assertEqual(client.position_count, 1)
        client.submit(
            client_order_id="test-005b",
            symbol="BTCUSDT",
            side="SELL",
            qty=0.001,
        )
        self.assertEqual(client.position_count, 0)

    def test_orders_authorized_always_false(self):
        mock = MockExchange()
        client = TestnetVenueClient(mock)
        self.assertFalse(client.orders_authorized)


class TestnetVenueClientCancelQueryTest(unittest.TestCase):
    def test_cancel_uses_exchange_order_id(self):
        mock = MockExchange()
        client = TestnetVenueClient(mock)
        client.submit(
            client_order_id="test-cancel",
            symbol="BTCUSDT",
            side="BUY",
            qty=0.001,
        )
        result = client.cancel(client_order_id="test-cancel")
        self.assertEqual(result["status"], "CANCELLED")
        self.assertEqual(len(mock.cancelled_orders), 1)

    def test_query_returns_current_status(self):
        mock = MockExchange()
        client = TestnetVenueClient(mock)
        client.submit(
            client_order_id="test-query",
            symbol="BTCUSDT",
            side="BUY",
            qty=0.001,
        )
        result = client.query(client_order_id="test-query")
        self.assertIn(result["status"], ("FILLED", "PARTIALLY_FILLED"))
        self.assertEqual(result["raw_response"]["id"], "1")
        self.assertEqual(len(mock.fetched_orders), 1)

    def test_cancel_without_metadata_raises(self):
        mock = MockExchange()
        client = TestnetVenueClient(mock)
        with self.assertRaises(ValueError):
            client.cancel(client_order_id="unknown")


class TestnetVenueClientStopAlgoTest(unittest.TestCase):
    """Section 3.4 + finding 2: STOP_MARKET uses the Algo Order service.

    STOP_MARKET on the Binance USD-M testnet is routed to the Algo
    Order service (POST /fapi/v1/algo/order) and returns algoId instead
    of orderId.  Query must use clientAlgoId; cancel must use algoId.
    """

    def test_submit_stop_market_records_algo_id(self):
        mock = MockExchange()
        client = TestnetVenueClient(mock)
        result = client.submit(
            client_order_id="stop-001",
            symbol="BTCUSDT",
            side="SELL",
            qty=0.001,
            order_type="STOP_MARKET",
            stop_price=95000.0,
            reduce_only=True,
        )
        self.assertEqual(result["status"], "NEW")
        self.assertTrue(result["exchange_order_id"])
        meta = client._order_meta["stop-001"]
        self.assertEqual(meta.get("is_algo"), "true")
        self.assertTrue(meta.get("algo_id"))

    def test_query_stop_market_uses_algo_endpoint(self):
        mock = MockExchange()
        client = TestnetVenueClient(mock)
        client.submit(
            client_order_id="stop-002",
            symbol="BTCUSDT",
            side="SELL",
            qty=0.001,
            order_type="STOP_MARKET",
            stop_price=95000.0,
            reduce_only=True,
        )
        result = client.query(client_order_id="stop-002")
        self.assertEqual(result["status"], "NEW")
        self.assertEqual(len(mock.fetched_algo), 1)
        self.assertEqual(len(mock.fetched_orders), 0)
        self.assertEqual(
            mock.fetched_algo[0].get("clientAlgoId"), "stop-002"
        )

    def test_cancel_stop_market_uses_algo_endpoint(self):
        mock = MockExchange()
        client = TestnetVenueClient(mock)
        client.submit(
            client_order_id="stop-003",
            symbol="BTCUSDT",
            side="SELL",
            qty=0.001,
            order_type="STOP_MARKET",
            stop_price=95000.0,
            reduce_only=True,
        )
        result = client.cancel(client_order_id="stop-003")
        self.assertEqual(result["status"], "CANCELLED")
        self.assertEqual(len(mock.cancelled_algo), 1)
        self.assertEqual(len(mock.cancelled_orders), 0)
        self.assertIn("algoId", mock.cancelled_algo[0])

    def test_market_order_does_not_use_algo_endpoint(self):
        mock = MockExchange()
        client = TestnetVenueClient(mock)
        client.submit(
            client_order_id="mkt-001",
            symbol="BTCUSDT",
            side="BUY",
            qty=0.001,
        )
        client.query(client_order_id="mkt-001")
        self.assertEqual(len(mock.fetched_orders), 1)
        self.assertEqual(len(mock.fetched_algo), 0)


class TestnetVenueClientSnapshotTest(unittest.TestCase):
    def test_snapshot_returns_orders_positions_trades(self):
        mock = MockExchange()
        mock._open_orders = [{"id": "1", "status": "open"}]
        mock._positions = [
            {"symbol": "BTC/USDT:USDT", "contracts": 0.001}
        ]
        mock._trades = [{"id": "t1", "amount": 0.001}]
        client = TestnetVenueClient(mock)
        snap = client.snapshot()
        self.assertEqual(len(snap["orders"]), 1)
        self.assertIn("BTC/USDT:USDT", snap["positions"])
        self.assertEqual(len(snap["trades"]), 1)

    def test_snapshot_handles_exchange_errors(self):
        mock = MockExchange()
        mock.fetch_open_orders = lambda symbol=None: (_ for _ in ()).throw(
            Exception("network_error")
        )
        client = TestnetVenueClient(mock)
        snap = client.snapshot()
        self.assertEqual(snap["orders"], [])

    def test_recover_from_crash_refreshes_positions(self):
        mock = MockExchange()
        mock._positions = [
            {"symbol": "BTC/USDT:USDT", "contracts": 0.002}
        ]
        client = TestnetVenueClient(mock)
        client.recover_from_crash()
        self.assertEqual(client.position_count, 1)


class TestnetSettingsTest(unittest.TestCase):
    def test_testnet_fields_in_production_critical(self):
        self.assertIn("testnet_enable", PRODUCTION_CRITICAL_FIELDS)
        self.assertIn("testnet_api_key", PRODUCTION_CRITICAL_FIELDS)
        self.assertIn("testnet_api_secret", PRODUCTION_CRITICAL_FIELDS)

    def test_testnet_defaults_to_disabled(self):
        import os

        saved = {
            k: os.environ.get(k)
            for k in (
                "QOUNT_TESTNET_ENABLE",
                "QOUNT_TESTNET_API_KEY",
                "QOUNT_TESTNET_API_SECRET",
            )
        }
        for k in saved:
            os.environ.pop(k, None)
        try:
            settings = Settings.from_env()
            self.assertFalse(settings.testnet_enable)
            self.assertIsNone(settings.testnet_api_key)
            self.assertIsNone(settings.testnet_api_secret)
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v

    def test_testnet_keys_separate_from_production(self):
        import os

        os.environ["QOUNT_BINANCE_API_KEY"] = "prod-key"
        os.environ["QOUNT_BINANCE_API_SECRET"] = "prod-secret"
        os.environ["QOUNT_TESTNET_API_KEY"] = "testnet-key"
        os.environ["QOUNT_TESTNET_API_SECRET"] = "testnet-secret"
        try:
            settings = Settings.from_env()
            self.assertEqual(settings.binance_api_key, "prod-key")
            self.assertEqual(settings.testnet_api_key, "testnet-key")
            self.assertNotEqual(
                settings.binance_api_key, settings.testnet_api_key
            )
        finally:
            for k in (
                "QOUNT_BINANCE_API_KEY",
                "QOUNT_BINANCE_API_SECRET",
                "QOUNT_TESTNET_API_KEY",
                "QOUNT_TESTNET_API_SECRET",
            ):
                os.environ.pop(k, None)


@unittest.skipUnless(_CCXT_AVAILABLE, "ccxt not installed")
class BuildTestnetExchangeTest(unittest.TestCase):
    """Tests for build_testnet_exchange (skipped if ccxt not installed)."""

    def test_build_testnet_exchange_sets_sandbox_mode(self):
        from qount.exchange_utils import build_testnet_exchange

        exchange = build_testnet_exchange(
            api_key="test-key",
            api_secret="test-secret",
        )
        api = exchange.urls.get("api", {})
        fapi_url = api.get("fapiPrivate", "")
        self.assertIn("testnet.binancefuture.com", fapi_url)


if __name__ == "__main__":
    unittest.main()
