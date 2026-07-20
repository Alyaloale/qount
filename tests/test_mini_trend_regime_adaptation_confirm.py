from __future__ import annotations

import unittest
from unittest.mock import patch

from qount.mini_trend.regime_adaptation_confirm import AdaptationConfirmConfig
from qount.mini_trend.regime_adaptation_confirm import build_adaptation_confirmation


class MiniTrendRegimeAdaptationConfirmTest(unittest.TestCase):
    def test_fixed_candidate_passes_only_when_source_and_sensitivities_match(self) -> None:
        config = AdaptationConfirmConfig(
            bootstrap_samples=10,
            sensitivity_block_days=(30, 60, 90),
        )
        source_trial = {
            "trial_id": config.candidate_id,
            "pooled_rank_ic": 0.16,
            "pooled_high_minus_low_actual": 0.07,
            "positive_rank_ic_fold_count": 3,
        }
        source = {
            "contract": {"contract_hash": "source-contract"},
            "diagnostics": {"trial_count": 24},
            "retained_trial_ids": [config.candidate_id],
            "trials": [source_trial],
        }
        result = {
            "pooled_rank_ic": 0.16,
            "pooled_high_minus_low_actual": 0.07,
            "positive_rank_ic_fold_count": 3,
            "positive_spread_fold_count": 3,
            "folds": [
                {"test_year": 2026, "rank_ic": 0.5, "high_minus_low_actual": 0.2}
            ],
            "prediction_rows": [
                {"decision_date": "2026-01-01", "predicted": 1.0, "actual": 0.1}
            ],
        }
        bootstrap = {
            "probability_spread_positive": 0.8,
            "median_spread": 0.05,
            "p05_spread": -0.01,
        }
        dataset = {
            "contract": {"contract_hash": "dataset-contract"},
            "data_hash": "dataset-data",
        }

        with (
            patch(
                "qount.mini_trend.regime_adaptation_confirm.build_regime_ml_dataset",
                return_value=dataset,
            ),
            patch(
                "qount.mini_trend.regime_adaptation_confirm.run_economic_ml_walk_forward",
                return_value=result,
            ),
            patch(
                "qount.mini_trend.regime_adaptation_confirm._bootstrap_spread",
                return_value=bootstrap,
            ),
        ):
            payload = build_adaptation_confirmation({}, {}, source, config)

        self.assertEqual(
            payload["diagnostics"]["verdict"],
            "retain_rolling_return_ranker_for_strategy_ablation",
        )
        self.assertEqual(payload["diagnostics"]["passed_gate_count"], 7)
        self.assertFalse(payload["meta"]["paper_or_live_allowed"])
        self.assertEqual(set(payload["bootstrap_sensitivity"]), {"30", "60", "90"})


if __name__ == "__main__":
    unittest.main()
