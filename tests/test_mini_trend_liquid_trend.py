from __future__ import annotations

import datetime as dt
import unittest

from qount.research_data.market_data import Bar, Funding
from qount.mini_trend.liquid_trend import LiquidTrendCapacityConfig
from qount.mini_trend.liquid_trend import LiquidTrendPreprocessingContract
from qount.mini_trend.liquid_trend import build_liquid_trend_capacity_report
from qount.mini_trend.liquid_trend import effective_breadth


_DAY_MS = 86_400_000


def _bars(prices: list[float], *, volume: float = 1_000_000.0) -> list[Bar]:
    start = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
    return [
        Bar(
            ts_ms=int((start + dt.timedelta(days=index)).timestamp() * 1000),
            open=price,
            high=price * 1.01,
            low=price * 0.99,
            close=price,
            volume=volume,
            quote_volume=price * volume,
        )
        for index, price in enumerate(prices)
    ]


def _funding(
    rows: list[Bar], complete: bool = True, *, jitter_ms: int = 0
) -> list[Funding]:
    offsets = (8, 16, 24) if complete else (8, 16)
    return [
        Funding(
            ts_ms=bar.ts_ms + hour * 3_600_000 + jitter_ms,
            rate=0.0001,
        )
        for bar in rows
        for hour in offsets
    ]


def _rules(symbols: tuple[str, ...]) -> dict:
    return {
        "market": "um",
        "source_type": "runtime_exchange_info",
        "raw_exchange_info_hash": "rules-hash",
        "rules": [
            {
                "symbol": symbol,
                "status": "TRADING",
                "min_notional": "5",
                "min_qty": "0.001",
            }
            for symbol in symbols
        ],
    }


class LiquidTrendCapacityTests(unittest.TestCase):
    def test_effective_breadth_collapses_identical_series(self) -> None:
        result = effective_breadth(
            {
                "A": [0.01, -0.02, 0.03, -0.01],
                "B": [0.01, -0.02, 0.03, -0.01],
                "C": [0.01, -0.02, 0.03, -0.01],
            }
        )
        self.assertAlmostEqual(result["mean_abs_pairwise_correlation"], 1.0)
        self.assertAlmostEqual(result["effective_breadth"], 1.0)
        self.assertAlmostEqual(result["effective_breadth_eigen"], 1.0)
        self.assertAlmostEqual(result["first_principal_component_share"], 1.0)

    def test_eigen_breadth_preserves_independent_dimensions(self) -> None:
        result = effective_breadth(
            {
                "BTCUSDT": [1.0, 0.0, -1.0, 0.0],
                "ETHUSDT": [0.0, 1.0, 0.0, -1.0],
            }
        )
        self.assertAlmostEqual(result["effective_breadth_eigen"], 2.0)
        self.assertAlmostEqual(result["first_principal_component_share"], 0.5)
        self.assertAlmostEqual(result["btc_beta_by_symbol"]["BTCUSDT"], 1.0)

    def test_preprocessing_is_frozen_before_first_pnl_trial(self) -> None:
        contract = LiquidTrendPreprocessingContract()
        self.assertEqual(contract.score_transform, "cross_sectional_percentile_rank")
        self.assertEqual(contract.minimum_cross_section, 8)
        self.assertEqual(contract.listing_warmup_completed_bars, 121)
        self.assertEqual(contract.missing_execution_quote_policy, "no_trade")
        with self.assertRaisesRegex(ValueError, "robust ranks"):
            LiquidTrendPreprocessingContract(score_transform="z_score")

    def test_high_correlation_blocks_cross_sectional_capacity(self) -> None:
        symbols = ("BTCUSDT", "ETHUSDT", "BNBUSDT")
        prices = [100.0, 102.0, 101.0, 104.0, 103.0, 106.0]
        bars = {symbol: _bars(prices) for symbol in symbols}
        funding = {symbol: _funding(bars[symbol]) for symbol in symbols}
        config = LiquidTrendCapacityConfig(
            universe=symbols,
            start_date="2024-01-01",
            end_date="2024-01-06",
            minimum_effective_breadth=1.5,
        )
        report = build_liquid_trend_capacity_report(
            bars, funding, _rules(symbols), config
        )
        self.assertEqual(report["diagnostics"]["verdict"], "block_liquid_trend_g0_breadth")
        self.assertFalse(report["meta"]["strategy_results_evaluated"])
        self.assertEqual(report["breadth"]["cluster_count"], 1)
        self.assertIn("effective_breadth_eigen", report["breadth"])
        self.assertIn("downside_btc_negative", report["breadth"])
        self.assertIn("cluster_stability", report["breadth"])

    def test_incomplete_funding_blocks_data_gate(self) -> None:
        symbols = ("BTCUSDT", "ETHUSDT")
        btc = _bars([100.0, 102.0, 101.0, 104.0, 103.0, 106.0])
        eth = _bars([100.0, 99.0, 102.0, 100.0, 105.0, 101.0])
        config = LiquidTrendCapacityConfig(
            universe=symbols,
            start_date="2024-01-01",
            end_date="2024-01-06",
            minimum_effective_breadth=1.0,
        )
        report = build_liquid_trend_capacity_report(
            {"BTCUSDT": btc, "ETHUSDT": eth},
            {"BTCUSDT": _funding(btc), "ETHUSDT": _funding(eth, complete=False)},
            _rules(symbols),
            config,
        )
        self.assertEqual(
            report["diagnostics"]["verdict"],
            "block_liquid_trend_g0_data_or_execution",
        )
        self.assertIn("all_funding_coverage", report["diagnostics"]["blockers"])

    def test_subsecond_funding_jitter_is_not_a_false_gap(self) -> None:
        symbols = ("BTCUSDT", "ETHUSDT")
        btc = _bars([100.0, 102.0, 101.0, 104.0, 103.0, 106.0])
        eth = _bars([100.0, 99.0, 102.0, 100.0, 105.0, 101.0])
        config = LiquidTrendCapacityConfig(
            universe=symbols,
            start_date="2024-01-01",
            end_date="2024-01-06",
            minimum_effective_breadth=1.0,
        )
        report = build_liquid_trend_capacity_report(
            {"BTCUSDT": btc, "ETHUSDT": eth},
            {
                "BTCUSDT": _funding(btc, jitter_ms=46),
                "ETHUSDT": _funding(eth, jitter_ms=13),
            },
            _rules(symbols),
            config,
        )
        self.assertTrue(report["diagnostics"]["gates"]["all_funding_coverage"])

    def test_missing_runtime_rule_blocks_execution_gate(self) -> None:
        symbols = ("BTCUSDT", "ETHUSDT")
        btc = _bars([100.0, 102.0, 101.0, 104.0, 103.0, 106.0])
        eth = _bars([100.0, 99.0, 102.0, 100.0, 105.0, 101.0])
        config = LiquidTrendCapacityConfig(
            universe=symbols,
            start_date="2024-01-01",
            end_date="2024-01-06",
            minimum_effective_breadth=1.0,
        )
        report = build_liquid_trend_capacity_report(
            {"BTCUSDT": btc, "ETHUSDT": eth},
            {"BTCUSDT": _funding(btc), "ETHUSDT": _funding(eth)},
            _rules(("BTCUSDT",)),
            config,
        )
        self.assertEqual(
            report["diagnostics"]["verdict"],
            "block_liquid_trend_g0_data_or_execution",
        )
        self.assertFalse(report["execution_capacity"]["rules"]["ETHUSDT"]["present"])


if __name__ == "__main__":
    unittest.main()
