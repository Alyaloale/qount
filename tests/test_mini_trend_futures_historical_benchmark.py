from __future__ import annotations

import unittest

from qount.grid.data import Bar, Funding
from qount.mini_trend.forward import TOP3
from qount.mini_trend.futures_historical_benchmark import run_buy_hold_benchmark


_T0 = 1_609_459_200_000
_DAY = 86_400_000


def _bars(closes: list[float]) -> list[Bar]:
    return [Bar(_T0 + i * _DAY, c, c, c, c, 1000.0) for i, c in enumerate(closes)]


class MiniTrendFuturesHistoricalBenchmarkTest(unittest.TestCase):
    def test_benchmark_includes_entry_cost_and_funding(self) -> None:
        bars = {symbol: _bars([100.0, 110.0, 110.0]) for symbol in TOP3}
        funding = {symbol: [Funding(_T0 + _DAY + 8 * 60 * 60 * 1000, 0.001)] for symbol in TOP3}
        result = run_buy_hold_benchmark(
            bars,
            funding,
            weights={"BTCUSDT": 1.0},
            start_date="2021-01-01",
            end_date="2021-01-03",
        )
        self.assertEqual(result["bars"], 2)
        self.assertEqual(result["entry_cost_usdt"], 0.48)
        self.assertLess(result["funding_pnl_usdt"], 0.0)
        self.assertGreater(result["return_pct"], 0.0)


if __name__ == "__main__":
    unittest.main()
