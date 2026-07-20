from __future__ import annotations

import unittest
from unittest.mock import patch

from qount.mini_trend.futures_recovery_backtest import VariantResult
from qount.mini_trend.regime_hmm_matrix import HMMTargetMatrixConfig
from qount.mini_trend.regime_hmm_matrix import build_hmm_target_matrix


def _audit(horizon: int) -> dict:
    retained = horizon == 20
    quality = [
        {
            "test_year": year,
            "purge_check_passed": True,
            "brier_improvement_vs_constant": 0.01 if retained else -0.01,
        }
        for year in (2023, 2024, 2025, 2026)
    ]
    return {
        "sample": {"economically_aligned_rows": 100},
        "lineage": {
            "dataset_contract_hash": f"contract-{horizon}",
            "dataset_data_hash": "data",
        },
        "fold_probability_quality": quality,
        "probability_reliability": {},
        "economic_conditioning": {
            "risk_score_top3_return_spearman": 0.2 if retained else -0.2,
            "risk_score_base_return_spearman": 0.1,
            "bear_probability_base_drawdown_spearman": 0.1,
            "high_minus_low_top3_return": 0.03 if retained else -0.03,
            "high_minus_low_base_return": 0.01,
            "high_minus_low_base_drawdown": -0.01,
            "positive_top3_return_spread_fold_count": 4 if retained else 0,
            "folds": [],
            "block_bootstrap": {
                "forward_return_horizon": {
                    "probability_spread_positive": 0.9 if retained else 0.1
                }
            },
        },
        "diagnostics": {
            "gates": {"economic": retained},
            "passed_gate_count": 7 if retained else 2,
            "gate_count": 7,
            "verdict": (
                "retain_hmm_for_dynamic_risk_ablation"
                if retained
                else "reject_hmm_as_economic_risk_signal"
            ),
        },
    }


class MiniTrendRegimeHMMMatrixTest(unittest.TestCase):
    def test_matrix_counts_and_ranks_all_trials(self) -> None:
        def fake_dataset(_bars, _funding, config):
            return {
                "contract": {"contract_hash": f"contract-{config.horizon_days}"},
                "data_hash": "data",
                "horizon": config.horizon_days,
            }

        def fake_audit(dataset, _base, _config):
            return _audit(dataset["horizon"])

        with patch(
            "qount.mini_trend.regime_hmm_matrix.build_regime_ml_dataset",
            side_effect=fake_dataset,
        ), patch(
            "qount.mini_trend.regime_hmm_matrix.build_hmm_economic_audit",
            side_effect=fake_audit,
        ):
            result = build_hmm_target_matrix(
                {},
                {},
                VariantResult(metrics={}, equity=[]),
                HMMTargetMatrixConfig(
                    horizons=(10, 20), barrier_sigmas=(1.0,), bootstrap_samples=10
                ),
            )
        self.assertEqual(result["diagnostics"]["trial_count"], 2)
        self.assertEqual(result["best_trial"]["trial_id"], "h20_sigma1")
        self.assertEqual(result["retained_trial_ids"], ["h20_sigma1"])
        self.assertFalse(result["meta"]["paper_or_live_allowed"])


if __name__ == "__main__":
    unittest.main()
