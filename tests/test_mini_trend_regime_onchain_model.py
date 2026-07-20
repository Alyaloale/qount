from __future__ import annotations

import unittest

from qount.mini_trend.regime_ml import FEATURE_NAMES
from qount.mini_trend.regime_onchain_model import ONCHAIN_MODEL_FEATURE_NAMES
from qount.mini_trend.regime_onchain_model import OnchainModelConfig
from qount.mini_trend.regime_onchain_model import augment_dataset_with_hashrate


class MiniTrendRegimeOnchainModelTest(unittest.TestCase):
    def test_augmentation_joins_only_decision_time_hashrate(self) -> None:
        dataset = {
            "contract": {"contract_hash": "base"},
            "rows": [
                {
                    "decision_date": "2026-01-01",
                    "features": {name: 0.0 for name in FEATURE_NAMES},
                },
                {
                    "decision_date": "2026-01-02",
                    "features": {name: 0.0 for name in FEATURE_NAMES},
                },
            ],
        }
        onchain = {
            "contract": {"contract_hash": "onchain", "decision_lag_days": 1},
            "data_hash": "data",
            "daily_features": [
                {"decision_date": "2026-01-01", "hashrate_z90": 1.25}
            ],
        }
        result = augment_dataset_with_hashrate(dataset, onchain)
        self.assertEqual(result["onchain_feature_coverage"], 0.5)
        self.assertEqual(result["rows"][0]["features"]["hashrate_z90"], 1.25)
        self.assertEqual(tuple(result["contract"]["feature_names"]), ONCHAIN_MODEL_FEATURE_NAMES)

    def test_model_ablation_is_exactly_one_new_trial(self) -> None:
        config = OnchainModelConfig(prior_research_trial_count=127)
        self.assertEqual(config.trial_count, 1)
        self.assertEqual(config.cumulative_trial_count, 128)


if __name__ == "__main__":
    unittest.main()
