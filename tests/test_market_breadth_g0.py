from __future__ import annotations

import datetime as dt
import math
import unittest

from qount.grid.data import Bar
from qount.mini_trend.market_breadth_g0 import (
    MARKET_BREADTH_G0_PROTOCOL,
    build_market_breadth_g0_report,
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
                    volume=1_000_000.0,
                )
            )
        result[symbol] = rows
    return result


class MarketBreadthG0Tests(unittest.TestCase):
    def test_contract_hash_is_stable(self) -> None:
        self.assertEqual(
            MARKET_BREADTH_G0_PROTOCOL.contract_hash,
            MARKET_BREADTH_G0_PROTOCOL.contract_hash,
        )

    def test_g0_produces_no_direction_and_no_pnl(self) -> None:
        report = build_market_breadth_g0_report(
            _bars(), available_symbols=["BTCUSDT", "ETHUSDT", "BNBUSDT"],
            observed_at="2026-07-25T00:00:00+00:00",
        )
        self.assertFalse(report["meta"]["direction_produced"])
        self.assertFalse(report["meta"]["pnl_evaluated"])
        self.assertFalse(report["meta"]["candidate_pnl_ready"])
        self.assertFalse(report["meta"]["orders_authorized"])

    def test_g0_blocks_on_universe_gap(self) -> None:
        report = build_market_breadth_g0_report(
            _bars(), available_symbols=["BTCUSDT", "ETHUSDT", "BNBUSDT"],
            observed_at="2026-07-25T00:00:00+00:00",
        )
        self.assertEqual(report["verdict"], "block_capacity")
        self.assertTrue(report["kill_tests"]["pit_universe_not_reconstructable"])
        self.assertIn("BTCUSDT", report["universe"]["missing"] + report["universe"]["available"])

    def test_g0_reports_breadth_metrics(self) -> None:
        report = build_market_breadth_g0_report(
            _bars(), available_symbols=["BTCUSDT", "ETHUSDT", "BNBUSDT"],
            observed_at="2026-07-25T00:00:00+00:00",
        )
        self.assertIsNotNone(report["breadth"])
        self.assertIn("effective_breadth", report["breadth"])
        self.assertIn("first_principal_component_share", report["breadth"])
        self.assertGreater(report["advance_ratio"]["count"], 0)
        self.assertGreater(report["trend_distance"]["count"], 0)


if __name__ == "__main__":
    unittest.main()
