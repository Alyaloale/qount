from __future__ import annotations

import unittest
from typing import Any

from qount.shadow_accounting import FetchResult
from qount.shadow_accounting import QueryMetadata
from qount.shadow_accounting import fetch_income_history
from qount.shadow_accounting import fetch_open_orders
from qount.shadow_accounting import fetch_private_trades


class MockExchange:
    """Mock exchange implementing ReadOnlyExchange Protocol."""

    def __init__(self) -> None:
        self._trades: dict[str, list[dict[str, Any]]] = {}
        self._income: list[dict[str, Any]] = []
        self._open_orders: list[dict[str, Any]] = []
        self._fail_count: dict[str, int] = {}
        self.call_log: list[tuple[str, dict[str, Any]]] = []

    def set_trades(self, symbol: str, trades: list[dict[str, Any]]) -> None:
        self._trades[symbol] = trades

    def set_income(self, income: list[dict[str, Any]]) -> None:
        self._income = income

    def set_open_orders(self, orders: list[dict[str, Any]]) -> None:
        self._open_orders = orders

    def set_failures(self, endpoint: str, count: int) -> None:
        self._fail_count[endpoint] = count

    def fetch_my_trades(
        self, symbol: str, *, start_time: int, end_time: int, limit: int = 1000
    ) -> list[dict[str, Any]]:
        self.call_log.append(
            ("fetch_my_trades", {"symbol": symbol, "start_time": start_time, "end_time": end_time, "limit": limit})
        )
        if self._fail_count.get("fetch_my_trades", 0) > 0:
            self._fail_count["fetch_my_trades"] -= 1
            raise ConnectionError("mock exchange error")
        all_trades = self._trades.get(symbol, [])
        result = [t for t in all_trades if start_time <= t.get("time", 0) <= end_time]
        return result[:limit]

    def fetch_income_history(
        self, *, start_time: int, end_time: int, limit: int = 1000
    ) -> list[dict[str, Any]]:
        self.call_log.append(
            ("fetch_income_history", {"start_time": start_time, "end_time": end_time, "limit": limit})
        )
        if self._fail_count.get("fetch_income_history", 0) > 0:
            self._fail_count["fetch_income_history"] -= 1
            raise ConnectionError("mock exchange error")
        result = [i for i in self._income if start_time <= i.get("time", 0) <= end_time]
        return result[:limit]

    def fetch_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        self.call_log.append(("fetch_open_orders", {"symbol": symbol}))
        if self._fail_count.get("fetch_open_orders", 0) > 0:
            self._fail_count["fetch_open_orders"] -= 1
            raise ConnectionError("mock exchange error")
        if symbol is None:
            return list(self._open_orders)
        return [o for o in self._open_orders if o.get("symbol") == symbol]


class FetchPrivateTradesTest(unittest.TestCase):
    def test_single_symbol_single_page(self) -> None:
        exchange = MockExchange()
        exchange.set_trades("BTCUSDT", [
            {"symbol": "BTCUSDT", "side": "BUY", "price": "100000",
             "qty": "0.001", "commission": "0.04", "realizedPnl": "0",
             "time": 1000},
        ])
        result = fetch_private_trades(
            exchange, ["BTCUSDT"], start_ms=0, end_ms=2000,
            max_retries=0, retry_delay_seconds=0,
        )
        self.assertEqual(result.data_type, "trades")
        self.assertEqual(len(result.records), 1)
        self.assertEqual(len(result.queries), 1)
        self.assertEqual(result.queries[0].symbol, "BTCUSDT")
        self.assertEqual(result.queries[0].result_count, 1)
        self.assertTrue(result.queries[0].coverage_complete)

    def test_pagination_multiple_pages(self) -> None:
        exchange = MockExchange()
        trades = [
            {"symbol": "BTCUSDT", "side": "BUY", "price": "100000",
             "qty": "0.001", "commission": "0.04", "realizedPnl": "0",
             "time": 1000 + i}
            for i in range(1500)
        ]
        exchange.set_trades("BTCUSDT", trades)
        result = fetch_private_trades(
            exchange, ["BTCUSDT"], start_ms=0, end_ms=100000,
            page_size=1000, max_retries=0, retry_delay_seconds=0,
        )
        self.assertEqual(len(result.records), 1500)
        self.assertEqual(len(result.queries), 1)
        self.assertEqual(result.queries[0].page_count, 2)
        self.assertEqual(result.queries[0].result_count, 1500)

    def test_multiple_symbols(self) -> None:
        exchange = MockExchange()
        exchange.set_trades("BTCUSDT", [
            {"symbol": "BTCUSDT", "side": "BUY", "price": "100000",
             "qty": "0.001", "commission": "0.04", "realizedPnl": "0",
             "time": 1000},
        ])
        exchange.set_trades("ETHUSDT", [
            {"symbol": "ETHUSDT", "side": "BUY", "price": "3000",
             "qty": "0.1", "commission": "0.012", "realizedPnl": "0",
             "time": 1000},
        ])
        result = fetch_private_trades(
            exchange, ["BTCUSDT", "ETHUSDT"], start_ms=0, end_ms=2000,
            max_retries=0, retry_delay_seconds=0,
        )
        self.assertEqual(len(result.records), 2)
        self.assertEqual(len(result.queries), 2)

    def test_empty_result(self) -> None:
        exchange = MockExchange()
        result = fetch_private_trades(
            exchange, ["BTCUSDT"], start_ms=0, end_ms=2000,
            max_retries=0, retry_delay_seconds=0,
        )
        self.assertEqual(len(result.records), 0)
        self.assertEqual(result.queries[0].result_count, 0)

    def test_retry_succeeds(self) -> None:
        exchange = MockExchange()
        exchange.set_trades("BTCUSDT", [
            {"symbol": "BTCUSDT", "side": "BUY", "price": "100000",
             "qty": "0.001", "commission": "0.04", "realizedPnl": "0",
             "time": 1000},
        ])
        exchange.set_failures("fetch_my_trades", 1)
        result = fetch_private_trades(
            exchange, ["BTCUSDT"], start_ms=0, end_ms=2000,
            max_retries=2, retry_delay_seconds=0,
        )
        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.queries[0].retry_count, 1)

    def test_all_retries_fail(self) -> None:
        exchange = MockExchange()
        exchange.set_failures("fetch_my_trades", 5)
        with self.assertRaises(ConnectionError):
            fetch_private_trades(
                exchange, ["BTCUSDT"], start_ms=0, end_ms=2000,
                max_retries=2, retry_delay_seconds=0,
            )

    def test_fetch_result_hash_consistent(self) -> None:
        exchange = MockExchange()
        exchange.set_trades("BTCUSDT", [
            {"symbol": "BTCUSDT", "side": "BUY", "price": "100000",
             "qty": "0.001", "commission": "0.04", "realizedPnl": "0",
             "time": 1000},
        ])
        result1 = fetch_private_trades(
            exchange, ["BTCUSDT"], start_ms=0, end_ms=2000,
            max_retries=0, retry_delay_seconds=0,
        )
        result2 = FetchResult.create(
            data_type="trades",
            records=result1.records,
            queries=result1.queries,
        )
        self.assertEqual(result1.fetch_hash, result2.fetch_hash)


class FetchIncomeHistoryTest(unittest.TestCase):
    def test_single_page(self) -> None:
        exchange = MockExchange()
        exchange.set_income([
            {"symbol": "BTCUSDT", "incomeType": "COMMISSION",
             "income": "-0.04", "asset": "USDT", "time": 1000},
            {"symbol": "BTCUSDT", "incomeType": "FUNDING_FEE",
             "income": "0.01", "asset": "USDT", "time": 2000},
        ])
        result = fetch_income_history(
            exchange, start_ms=0, end_ms=3000,
            max_retries=0, retry_delay_seconds=0,
        )
        self.assertEqual(result.data_type, "income_history")
        self.assertEqual(len(result.records), 2)
        self.assertEqual(len(result.queries), 1)
        self.assertEqual(result.queries[0].result_count, 2)

    def test_pagination(self) -> None:
        exchange = MockExchange()
        income = [
            {"symbol": "BTCUSDT", "incomeType": "FUNDING_FEE",
             "income": "0.01", "asset": "USDT", "time": 1000 + i}
            for i in range(1500)
        ]
        exchange.set_income(income)
        result = fetch_income_history(
            exchange, start_ms=0, end_ms=100000,
            page_size=1000, max_retries=0, retry_delay_seconds=0,
        )
        self.assertEqual(len(result.records), 1500)
        self.assertEqual(result.queries[0].page_count, 2)

    def test_empty(self) -> None:
        exchange = MockExchange()
        result = fetch_income_history(
            exchange, start_ms=0, end_ms=3000,
            max_retries=0, retry_delay_seconds=0,
        )
        self.assertEqual(len(result.records), 0)


class FetchOpenOrdersTest(unittest.TestCase):
    def test_all_symbols(self) -> None:
        exchange = MockExchange()
        exchange.set_open_orders([
            {"symbol": "BTCUSDT", "side": "BUY", "type": "LIMIT",
             "price": "99000", "origQty": "0.001", "status": "NEW"},
            {"symbol": "ETHUSDT", "side": "SELL", "type": "STOP_MARKET",
             "stopPrice": "2900", "origQty": "0.1", "status": "NEW"},
        ])
        result = fetch_open_orders(
            exchange, None, max_retries=0, retry_delay_seconds=0,
        )
        self.assertEqual(result.data_type, "open_orders")
        self.assertEqual(len(result.records), 2)
        self.assertEqual(len(result.queries), 1)

    def test_per_symbol(self) -> None:
        exchange = MockExchange()
        exchange.set_open_orders([
            {"symbol": "BTCUSDT", "side": "BUY", "type": "LIMIT",
             "price": "99000", "origQty": "0.001", "status": "NEW"},
            {"symbol": "ETHUSDT", "side": "SELL", "type": "STOP_MARKET",
             "stopPrice": "2900", "origQty": "0.1", "status": "NEW"},
        ])
        result = fetch_open_orders(
            exchange, ["BTCUSDT", "ETHUSDT"],
            max_retries=0, retry_delay_seconds=0,
        )
        self.assertEqual(len(result.records), 2)
        self.assertEqual(len(result.queries), 2)

    def test_empty(self) -> None:
        exchange = MockExchange()
        result = fetch_open_orders(
            exchange, None, max_retries=0, retry_delay_seconds=0,
        )
        self.assertEqual(len(result.records), 0)


class QueryMetadataTest(unittest.TestCase):
    def test_validate_passes(self) -> None:
        meta = QueryMetadata.create(
            endpoint="fetch_my_trades",
            symbol="BTCUSDT",
            query_start_ms=0,
            query_end_ms=1000,
            observed_at="2026-07-23T00:00:00+00:00",
            page_count=1,
            retry_count=0,
            result_count=5,
            source_hash="abc123",
            coverage_complete=True,
        )
        errors = meta.validate()
        self.assertEqual(errors, ())

    def test_inverted_window_fails(self) -> None:
        meta = QueryMetadata.create(
            endpoint="fetch_my_trades",
            symbol="BTCUSDT",
            query_start_ms=1000,
            query_end_ms=500,
            observed_at="2026-07-23T00:00:00+00:00",
            page_count=1,
            retry_count=0,
            result_count=0,
            source_hash="abc123",
            coverage_complete=True,
        )
        errors = meta.validate()
        self.assertIn("query_metadata_window_inverted", errors)


if __name__ == "__main__":
    unittest.main()
