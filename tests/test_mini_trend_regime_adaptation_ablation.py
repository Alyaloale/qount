from __future__ import annotations

import datetime as dt
import unittest

from qount.grid.data import Bar
from qount.mini_trend.forward import TOP3, frozen_top3_config
from qount.mini_trend.regime_adaptation_ablation import AdaptationAblationConfig
from qount.mini_trend.regime_adaptation_ablation import RISK_REDUCTION_SPECS
from qount.mini_trend.regime_adaptation_ablation import RiskScoreSelector


def _bars(date: dt.date) -> dict[str, list[Bar]]:
    ts_ms = int(dt.datetime.combine(date, dt.time(), tzinfo=dt.UTC).timestamp() * 1000)
    return {
        symbol: [Bar(ts_ms, 100.0, 101.0, 99.0, 100.0, 1_000.0)]
        for symbol in TOP3
    }


class MiniTrendRegimeAdaptationAblationTest(unittest.TestCase):
    def test_specs_only_reduce_the_base_risk_target(self) -> None:
        base = frozen_top3_config().vol_target
        self.assertEqual(RISK_REDUCTION_SPECS[0].vol_target(-0.5), 0.010)
        self.assertEqual(RISK_REDUCTION_SPECS[0].vol_target(0.1), base)
        self.assertEqual(RISK_REDUCTION_SPECS[2].vol_target(-1.5), 0.005)
        self.assertEqual(RISK_REDUCTION_SPECS[2].vol_target(-0.5), 0.010)
        self.assertEqual(RISK_REDUCTION_SPECS[2].vol_target(0.5), base)

    def test_selector_requires_an_oos_score_for_every_decision_date(self) -> None:
        selector = RiskScoreSelector(
            {"2026-01-01": -0.75}, RISK_REDUCTION_SPECS[0]
        )
        config, stage = selector(_bars(dt.date(2026, 1, 1)))
        self.assertEqual(config.vol_target, 0.010)
        self.assertTrue(stage.startswith("ml_reduced"))
        self.assertTrue(selector.state_snapshot()["risk_reduced"])
        with self.assertRaisesRegex(ValueError, "missing OOS risk score"):
            selector(_bars(dt.date(2026, 1, 2)))

    def test_trial_ledger_counts_all_fixed_ablation_specs(self) -> None:
        config = AdaptationAblationConfig(prior_family_trial_count=117)
        self.assertEqual(config.trial_count, 3)
        self.assertEqual(config.cumulative_trial_count, 120)


if __name__ == "__main__":
    unittest.main()
