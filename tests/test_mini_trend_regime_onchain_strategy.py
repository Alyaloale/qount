from __future__ import annotations

import unittest
from unittest.mock import patch

from qount.mini_trend.regime_onchain_strategy import ONCHAIN_MODEL_VERDICT
from qount.mini_trend.regime_onchain_strategy import build_onchain_strategy_ablation


class MiniTrendRegimeOnchainStrategyTest(unittest.TestCase):
    def test_adapter_reuses_three_frozen_risk_trials(self) -> None:
        model = {
            "diagnostics": {"verdict": ONCHAIN_MODEL_VERDICT},
            "contract": {"candidate_id": "candidate", "contract_hash": "hash"},
            "candidate": {"prediction_rows": []},
        }
        base_payload = {
            "meta": {},
            "lineage": {},
            "retained_trial_ids": [],
            "diagnostics": {},
        }
        with patch(
            "qount.mini_trend.regime_onchain_strategy.build_adaptation_risk_ablation",
            return_value=base_payload,
        ) as mocked:
            result = build_onchain_strategy_ablation({}, {}, {}, model)
        config = mocked.call_args.args[-1]
        self.assertEqual(config.prior_family_trial_count, 128)
        self.assertEqual(config.trial_count, 3)
        self.assertEqual(
            result["diagnostics"]["verdict"],
            "reject_onchain_ml_risk_overlay_after_strategy_ablation",
        )


if __name__ == "__main__":
    unittest.main()
