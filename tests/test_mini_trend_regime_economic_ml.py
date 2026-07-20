from __future__ import annotations

import datetime as dt
import unittest

from qount.mini_trend.regime_economic_ml import EconomicMLConfig
from qount.mini_trend.regime_economic_ml import run_economic_ml_walk_forward
from qount.mini_trend.regime_ml import FEATURE_NAMES


def _dataset() -> dict:
    rows = []
    current = dt.date(2021, 7, 20)
    end = dt.date(2026, 5, 1)
    index = 0
    while current <= end:
        signal = ((index % 31) - 15) / 15.0
        rows.append(
            {
                "decision_date": current.isoformat(),
                "horizon_end_date": (current + dt.timedelta(days=10)).isoformat(),
                "forward_return_horizon": signal * 0.05,
                "forward_path_max_drawdown": max(-signal * 0.03, 0.0),
                "features": {
                    name: signal * (feature_index + 1) / len(FEATURE_NAMES)
                    for feature_index, name in enumerate(FEATURE_NAMES)
                },
            }
        )
        current += dt.timedelta(days=1)
        index += 1
    return {
        "contract": {"test_years": [2023, 2024, 2025, 2026], "horizon_days": 10},
        "rows": rows,
    }


class MiniTrendRegimeEconomicMLTest(unittest.TestCase):
    def test_ridge_walk_forward_purges_and_recovers_linear_target(self) -> None:
        result = run_economic_ml_walk_forward(
            _dataset(),
            target="return",
            model_name="ridge",
            use_gpu=False,
            seed=7,
            bootstrap_samples=100,
        )
        self.assertTrue(all(row["purge_check_passed"] for row in result["folds"]))
        self.assertGreater(result["pooled_rank_ic"], 0.99)
        self.assertGreater(result["pooled_high_minus_low_actual"], 0)
        self.assertEqual(result["verdict"], "retain_calibrated_economic_model")

    def test_trial_count_includes_all_targets_models_and_horizons(self) -> None:
        config = EconomicMLConfig(
            horizons=(10, 20), targets=("return", "drawdown"), models=("ridge", "hist_gb")
        )
        self.assertEqual(config.trial_count, 8)
        self.assertEqual(config.cumulative_trial_count, 21)

    def test_rolling_training_window_is_bounded_and_purged(self) -> None:
        result = run_economic_ml_walk_forward(
            _dataset(),
            target="return",
            model_name="ridge",
            use_gpu=False,
            seed=7,
            bootstrap_samples=20,
            training_window_days=365,
            include_predictions=True,
        )
        self.assertTrue(all(row["purge_check_passed"] for row in result["folds"]))
        self.assertTrue(all(row["train_rows"] <= 365 for row in result["folds"]))
        self.assertEqual(result["training_window_days"], 365)
        self.assertEqual(len(result["prediction_rows"]), result["rows"])
        self.assertEqual(
            set(result["prediction_rows"][0]),
            {"decision_date", "test_year", "predicted", "raw_predicted", "actual"},
        )


if __name__ == "__main__":
    unittest.main()
