import unittest

from qount.research import c60_cost_study as study
from qount.research import c60_turnover_attribution as attr
from tests.test_c60_cost_study import _synthetic_series


class C60TurnoverAttributionTests(unittest.TestCase):
    def setUp(self):
        self.panel, _ = study.build_panel(_synthetic_series())

    def test_total_matches_simulate_and_components_are_consistent(self):
        for mode in ("frozen_daily", "research_monthly"):
            row = attr.attribute(self.panel, mode=mode)
            targets = study.target_path(self.panel, mode=mode)
            ref = study.simulate(self.panel, targets, cost_bps=attr.COST_BPS)
            self.assertAlmostEqual(row["turnover_total"], ref.turnover, places=5)
            comp = row["components"]
            change = sum(comp[c] for c in attr.CAUSES)
            self.assertAlmostEqual(comp["drift"] + change - comp["netting"], row["turnover_total"], places=5)
            self.assertGreaterEqual(comp["netting"], -1e-9)
            self.assertEqual(row["days"]["traded"] >= row["days"]["small"], True)

    def test_candidate_path_matches_target_support(self):
        for mode in ("frozen_daily", "research_monthly"):
            targets = study.target_path(self.panel, mode=mode)
            cands = attr.candidate_path(self.panel, mode=mode)
            for target, cand in zip(targets, cands):
                self.assertTrue(set(target) <= set(cand))

    def test_monthly_candidate_changes_only_at_month_start(self):
        row = attr.attribute(self.panel, mode="research_monthly")
        cands = attr.candidate_path(self.panel, mode="research_monthly")
        for index in range(study.WARMUP_BARS, len(cands)):
            if set(cands[index]) != set(cands[index - 1]):
                self.assertTrue(study._is_month_end(self.panel.dates, index))
        self.assertGreaterEqual(row["days"]["candidate"], 1)

    def test_guards_and_window(self):
        out = attr.run(self.panel, windows=(None, self.panel.dates[300]))
        self.assertEqual(out["guards"]["trial"], False)
        self.assertEqual(out["guards"]["orders_authorized"], False)
        self.assertEqual(len(out["results"]), 4)
        self.assertEqual(out["results"][1]["start_date"], self.panel.dates[300])


if __name__ == "__main__":
    unittest.main()
