from __future__ import annotations

import unittest

from qount.mini_trend.regime_macro_onchain_fusion import MacroOnchainFusionConfig
from qount.mini_trend.regime_macro_onchain_fusion import build_macro_onchain_fusion


class MiniTrendRegimeMacroOnchainFusionTest(unittest.TestCase):
    def test_contract_adds_exactly_one_trial(self) -> None:
        config = MacroOnchainFusionConfig()
        self.assertEqual(config.trial_count, 1)
        self.assertEqual(config.cumulative_trial_count, 135)
        self.assertEqual(config.model_seed, config.seed + 60 * 100 + 365)

    def test_requires_retained_macro_parent(self) -> None:
        with self.assertRaisesRegex(ValueError, "H.4.1"):
            build_macro_onchain_fusion({}, {}, {}, {"retained_trial_ids": []}, {}, {})


if __name__ == "__main__":
    unittest.main()
