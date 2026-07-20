from __future__ import annotations

import unittest

from qount.mini_trend.regime_adaptation_matrix import AdaptationMatrixConfig


class MiniTrendRegimeAdaptationMatrixTest(unittest.TestCase):
    def test_trial_ledger_counts_feature_window_horizon_cells(self) -> None:
        config = AdaptationMatrixConfig(
            horizons=(10, 20),
            training_windows_days=(365, 730),
            feature_sets=("base", "dvol"),
            prior_family_trial_count=93,
        )
        self.assertEqual(config.trial_count, 8)
        self.assertEqual(config.cumulative_trial_count, 101)


if __name__ == "__main__":
    unittest.main()
