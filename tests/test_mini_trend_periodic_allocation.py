from __future__ import annotations

import datetime as dt
import unittest

from qount.mini_trend.periodic_allocation import AssetSeries
from qount.mini_trend.periodic_allocation import PeriodicAllocationConfig
from qount.mini_trend.periodic_allocation import build_action_dataset
from qount.mini_trend.periodic_allocation import run_allocation_policy


def _series(count: int = 520) -> AssetSeries:
    start = dt.date(2021, 1, 1)
    dates = tuple((start + dt.timedelta(days=index)).isoformat() for index in range(count))
    closes = tuple(100.0 * (1.001 ** index) for index in range(count))
    return AssetSeries(
        asset_id="synthetic",
        dates=dates,
        closes=closes,
        funding_returns=tuple(0.0 for _ in range(count - 1)),
        periods_per_year=365.0,
        decision_stride=7,
        allocation_step=0.25,
        turnover_cost_bps=12.0,
    )


class MiniTrendPeriodicAllocationTest(unittest.TestCase):
    def test_dataset_uses_future_values_only_in_targets(self) -> None:
        dataset = build_action_dataset(
            _series(),
            PeriodicAllocationConfig(
                start_date="2021-07-20",
                end_date="2022-05-01",
                test_years=(2022,),
            ),
        )
        self.assertTrue(dataset["rows"])
        self.assertFalse(dataset["diagnostics"]["future_values_in_features"])
        self.assertEqual(
            set(dataset["diagnostics"]["label_counts"]),
            {"buy", "hold", "sell"},
        )

    def test_classic_dca_reaches_full_exposure_in_four_steps(self) -> None:
        series = _series()
        config = PeriodicAllocationConfig(
            start_date="2021-07-20",
            end_date="2022-05-01",
        )
        dataset = build_action_dataset(series, config)
        result = run_allocation_policy(
            series,
            dataset,
            policy="classic_dca",
            start_date=config.start_date,
            end_date=config.end_date,
            capital=config.capital_usdt,
        )
        self.assertEqual(result["metrics"]["maximum_exposure"], 1.0)
        self.assertEqual(result["metrics"]["turnover"], 1.0)
        self.assertEqual(result["metrics"]["trade_count"], 4)

    def test_line_dca_is_long_cash_and_discrete(self) -> None:
        series = _series()
        config = PeriodicAllocationConfig(
            start_date="2021-07-20",
            end_date="2022-05-01",
        )
        dataset = build_action_dataset(series, config)
        result = run_allocation_policy(
            series,
            dataset,
            policy="line_dca_dcr",
            start_date=config.start_date,
            end_date=config.end_date,
            capital=config.capital_usdt,
        )
        self.assertLessEqual(result["metrics"]["maximum_exposure"], 1.0)
        self.assertGreaterEqual(result["metrics"]["average_exposure"], 0.0)
        self.assertGreater(result["metrics"]["return_pct"], 0.0)

    def test_series_rejects_misaligned_funding(self) -> None:
        with self.assertRaisesRegex(ValueError, "funding"):
            AssetSeries(
                asset_id="bad",
                dates=("2026-01-01", "2026-01-02"),
                closes=(1.0, 2.0),
                funding_returns=(),
                periods_per_year=365.0,
                decision_stride=7,
                allocation_step=0.25,
                turnover_cost_bps=12.0,
            )


if __name__ == "__main__":
    unittest.main()
