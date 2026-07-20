from __future__ import annotations

import unittest
from unittest.mock import patch

from qount.mini_trend.regime_macro_strategy import MACRO_AUDIT_VERDICT
from qount.mini_trend.regime_macro_strategy import MACRO_CANDIDATE_ID
from qount.mini_trend.regime_macro_strategy import build_macro_strategy_ablation


class MiniTrendRegimeMacroStrategyTest(unittest.TestCase):
    def test_adapter_reuses_three_frozen_risk_trials(self) -> None:
        audit = {
            "diagnostics": {"verdict": MACRO_AUDIT_VERDICT},
            "retained_trial_ids": [MACRO_CANDIDATE_ID],
            "contract": {"contract_hash": "contract"},
            "data_lineage": {"h41_data_hash": "data"},
            "trials": [
                {
                    "trial_id": MACRO_CANDIDATE_ID,
                    "prediction_rows": [{"decision_date": "2025-01-01"}],
                }
            ],
        }
        base_payload = {
            "meta": {},
            "lineage": {},
            "retained_trial_ids": [],
            "diagnostics": {},
        }
        with patch(
            "qount.mini_trend.regime_macro_strategy.build_adaptation_risk_ablation",
            return_value=base_payload,
        ) as mocked:
            result = build_macro_strategy_ablation({}, {}, {}, audit)
        config = mocked.call_args.args[-1]
        self.assertEqual(config.prior_family_trial_count, 135)
        self.assertEqual(config.trial_count, 3)
        self.assertEqual(
            result["diagnostics"]["verdict"],
            "reject_h41_ml_risk_overlay_after_strategy_ablation",
        )


if __name__ == "__main__":
    unittest.main()
