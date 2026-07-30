from __future__ import annotations

import datetime as dt
import math
import unittest

from qount.research_data.market_data import Bar
from qount.mini_trend.liquidity_capacity_g0 import (
    LIQUIDITY_CAPACITY_G0_PROTOCOL,
    build_liquidity_capacity_g0_report,
)


def _bars(count: int = 300) -> dict[str, list[Bar]]:
    start = dt.datetime(2020, 1, 1, tzinfo=dt.UTC)
    growth = {"BTCUSDT": 0.0010, "ETHUSDT": 0.0012, "BNBUSDT": 0.0009}
    result: dict[str, list[Bar]] = {}
    for symbol_index, symbol in enumerate(growth):
        price = 100.0 + symbol_index * 20.0
        rows: list[Bar] = []
        for index in range(count):
            daily = growth[symbol] + math.sin(index / (7.0 + symbol_index)) * 0.002
            opened = price
            price *= 1.0 + daily
            rows.append(
                Bar(
                    ts_ms=int((start + dt.timedelta(days=index)).timestamp() * 1000),
                    open=opened,
                    high=max(opened, price) * 1.005,
                    low=min(opened, price) * 0.995,
                    close=price,
                    volume=50_000_000.0,
                )
            )
        result[symbol] = rows
    return result


class LiquidityCapacityG0Tests(unittest.TestCase):
    def test_contract_hash_is_stable(self) -> None:
        self.assertEqual(
            LIQUIDITY_CAPACITY_G0_PROTOCOL.contract_hash,
            LIQUIDITY_CAPACITY_G0_PROTOCOL.contract_hash,
        )

    def test_g0_produces_no_alpha_and_no_pnl(self) -> None:
        report = build_liquidity_capacity_g0_report(
            _bars(), available_symbols=["BTCUSDT", "ETHUSDT", "BNBUSDT"],
            exchange_rules=None, observed_at="2026-07-25T00:00:00+00:00",
        )
        self.assertFalse(report["meta"]["direction_produced"])
        self.assertFalse(report["meta"]["pnl_evaluated"])
        self.assertFalse(report["meta"]["alpha_attributed"])
        self.assertFalse(report["meta"]["candidate_pnl_ready"])

    def test_g0_blocks_without_rules(self) -> None:
        report = build_liquidity_capacity_g0_report(
            _bars(), available_symbols=["BTCUSDT", "ETHUSDT", "BNBUSDT"],
            exchange_rules=None, observed_at="2026-07-25T00:00:00+00:00",
        )
        self.assertEqual(report["verdict"], "block_capacity")
        self.assertTrue(report["kill_tests"]["rules_coverage_below_100"])
        self.assertTrue(report["kill_tests"]["pit_rules_not_reconstructable"])

    def test_g0_reports_liquidity_metrics(self) -> None:
        report = build_liquidity_capacity_g0_report(
            _bars(), available_symbols=["BTCUSDT", "ETHUSDT", "BNBUSDT"],
            exchange_rules=None, observed_at="2026-07-25T00:00:00+00:00",
        )
        for symbol in ("BTCUSDT", "ETHUSDT", "BNBUSDT"):
            row = report["liquidity"][symbol]
            self.assertGreater(row["bar_count"], 0)
            self.assertIsNotNone(row["median_daily_quote_volume_usdt"])
            self.assertFalse(row["book_spread_depth_available"])


if __name__ == "__main__":
    unittest.main()
