"""Unit tests for R0-DECISION kill tests: independent NAV reconciliation + PIT data gap."""

from __future__ import annotations

import unittest

from qount.research_data.cost_model import default_cxd_carry_cost_model
from qount.research_data.cost_model import default_cxd_trend_cost_model
from qount.research_data.nav import compute_carry_standalone_nav
from qount.research_data.nav import compute_standalone_nav
from scripts.research.governance.run_r0_decision import _independent_carry_nav
from scripts.research.governance.run_r0_decision import _independent_trend_nav
from scripts.research.governance.run_r0_decision import evaluate_kill_tests


class TestIndependentTrendNav(unittest.TestCase):
    """Verify the independent trend NAV reconciler matches compute_standalone_nav."""

    def test_reconciles_with_compute_standalone_nav(self) -> None:
        closes = [100.0, 105.0, 110.0, 108.0, 112.0]
        positions = [0.0, 1.0, 1.0, 0.0, 1.0]
        funding = [0.0001, 0.0002, 0.0001, 0.0003, 0.0001]
        cost_model = default_cxd_trend_cost_model(frozen_at="2026-07-24T00:00:00+00:00")
        expected = compute_standalone_nav(closes, positions, cost_model, funding_rates=funding)
        result = _independent_trend_nav(closes, positions, cost_model, funding)
        self.assertAlmostEqual(result, expected.nav_series[-1], places=8)

    def test_reconciles_without_funding(self) -> None:
        closes = [100.0, 110.0, 120.0]
        positions = [1.0, 1.0, 1.0]
        cost_model = default_cxd_trend_cost_model(frozen_at="2026-07-24T00:00:00+00:00")
        expected = compute_standalone_nav(closes, positions, cost_model)
        result = _independent_trend_nav(closes, positions, cost_model, None)
        self.assertAlmostEqual(result, expected.nav_series[-1], places=8)

    def test_flat_position_nav_is_one(self) -> None:
        closes = [100.0, 110.0, 120.0]
        positions = [0.0, 0.0, 0.0]
        cost_model = default_cxd_trend_cost_model(frozen_at="2026-07-24T00:00:00+00:00")
        result = _independent_trend_nav(closes, positions, cost_model, None)
        self.assertAlmostEqual(result, 1.0, places=8)


class TestIndependentCarryNav(unittest.TestCase):
    """Verify the independent carry NAV reconciler matches compute_carry_standalone_nav."""

    def test_reconciles_with_compute_carry_standalone_nav(self) -> None:
        spot = [100.0, 105.0, 110.0, 108.0, 112.0]
        perp = [101.0, 105.0, 110.0, 108.0, 112.0]
        funding = [0.0001, 0.0002, 0.0001, 0.0003, 0.0001]
        cost_model = default_cxd_carry_cost_model(frozen_at="2026-07-24T00:00:00+00:00")
        expected = compute_carry_standalone_nav(spot, perp, cost_model, funding_rates=funding)
        result = _independent_carry_nav(spot, perp, cost_model, funding)
        self.assertAlmostEqual(result, expected.nav_series[-1], places=6)

    def test_reconciles_without_funding(self) -> None:
        spot = [100.0, 105.0, 110.0]
        perp = [101.0, 105.0, 110.0]
        cost_model = default_cxd_carry_cost_model(frozen_at="2026-07-24T00:00:00+00:00")
        expected = compute_carry_standalone_nav(spot, perp, cost_model)
        result = _independent_carry_nav(spot, perp, cost_model, None)
        self.assertAlmostEqual(result, expected.nav_series[-1], places=6)


class TestKillTest2IndependentNavReconciliation(unittest.TestCase):
    """Kill test 2: independent NAV reconciliation."""

    def test_pass_when_navs_match(self) -> None:
        result = evaluate_kill_tests(
            baseline_nav=4.48,
            stress_results={"cost_doubling": {"final_nav": 4.41}},
            candidate_name="cxd_trend_leg",
            independent_nav=4.4766,
            runtime_nav=4.4766,
            r0_data_available=True,
        )
        kt2 = result["kill_tests"]["independent_nav_reconciliation_failure"]
        self.assertTrue(kt2["pass"])

    def test_fail_when_navs_mismatch(self) -> None:
        result = evaluate_kill_tests(
            baseline_nav=4.48,
            stress_results={"cost_doubling": {"final_nav": 4.41}},
            candidate_name="cxd_trend_leg",
            independent_nav=4.4766,
            runtime_nav=5.0,
            r0_data_available=True,
        )
        kt2 = result["kill_tests"]["independent_nav_reconciliation_failure"]
        self.assertFalse(kt2["pass"])
        self.assertIn("delta", kt2)

    def test_fail_when_no_reconciliation_data(self) -> None:
        result = evaluate_kill_tests(
            baseline_nav=4.48,
            stress_results={"cost_doubling": {"final_nav": 4.41}},
            candidate_name="cxd_trend_leg",
        )
        kt2 = result["kill_tests"]["independent_nav_reconciliation_failure"]
        self.assertFalse(kt2["pass"])

    def test_tolerance_is_1e6(self) -> None:
        result = evaluate_kill_tests(
            baseline_nav=4.48,
            stress_results={},
            candidate_name="cxd_trend_leg",
            independent_nav=4.4766,
            runtime_nav=4.4766001,
            r0_data_available=True,
        )
        kt2 = result["kill_tests"]["independent_nav_reconciliation_failure"]
        self.assertTrue(kt2["pass"])


class TestKillTest3PointInTimeDataGap(unittest.TestCase):
    """Kill test 3: PIT data gap."""

    def test_fail_when_r0_data_unavailable(self) -> None:
        result = evaluate_kill_tests(
            baseline_nav=4.48,
            stress_results={},
            candidate_name="cxd_trend_leg",
            independent_nav=4.48,
            runtime_nav=4.48,
            r0_data_available=False,
        )
        kt3 = result["kill_tests"]["point_in_time_data_gap"]
        self.assertFalse(kt3["pass"])
        self.assertIn("R0-DATA", kt3["reasoning"])

    def test_fail_when_funding_gaps_exist(self) -> None:
        result = evaluate_kill_tests(
            baseline_nav=4.48,
            stress_results={},
            candidate_name="cxd_trend_leg",
            independent_nav=4.48,
            runtime_nav=4.48,
            funding_missing_count=5,
            funding_incomplete=True,
            r0_data_available=True,
        )
        kt3 = result["kill_tests"]["point_in_time_data_gap"]
        self.assertFalse(kt3["pass"])
        self.assertIn("Funding gaps", kt3["reasoning"])

    def test_pass_when_r0_data_available_and_no_gaps(self) -> None:
        result = evaluate_kill_tests(
            baseline_nav=4.48,
            stress_results={},
            candidate_name="cxd_trend_leg",
            independent_nav=4.48,
            runtime_nav=4.48,
            funding_missing_count=0,
            funding_incomplete=False,
            r0_data_available=True,
        )
        kt3 = result["kill_tests"]["point_in_time_data_gap"]
        self.assertTrue(kt3["pass"])

    def test_fail_when_funding_incomplete_even_with_zero_missing(self) -> None:
        result = evaluate_kill_tests(
            baseline_nav=4.48,
            stress_results={},
            candidate_name="cxd_trend_leg",
            independent_nav=4.48,
            runtime_nav=4.48,
            funding_missing_count=0,
            funding_incomplete=True,
            r0_data_available=True,
        )
        kt3 = result["kill_tests"]["point_in_time_data_gap"]
        self.assertFalse(kt3["pass"])


class TestKillTestDecisionLogic(unittest.TestCase):
    """Verify the retain/revise/reject decision respects kill test results."""

    def test_retain_when_all_pass(self) -> None:
        result = evaluate_kill_tests(
            baseline_nav=4.48,
            stress_results={"cost_doubling": {"final_nav": 4.41}},
            candidate_name="cxd_trend_leg",
            independent_nav=4.48,
            runtime_nav=4.48,
            funding_missing_count=0,
            funding_incomplete=False,
            r0_data_available=True,
        )
        self.assertEqual(result["decision"], "retain")
        self.assertTrue(result["all_kill_tests_pass"])

    def test_revise_when_kt3_fails_but_nav_positive(self) -> None:
        result = evaluate_kill_tests(
            baseline_nav=4.48,
            stress_results={"cost_doubling": {"final_nav": 4.41}},
            candidate_name="cxd_trend_leg",
            independent_nav=4.48,
            runtime_nav=4.48,
            r0_data_available=False,
        )
        self.assertEqual(result["decision"], "revise")
        self.assertFalse(result["all_kill_tests_pass"])

    def test_reject_when_nav_leq_one(self) -> None:
        result = evaluate_kill_tests(
            baseline_nav=0.98,
            stress_results={"cost_doubling": {"final_nav": 0.95}},
            candidate_name="cxd_trend_leg",
            independent_nav=0.98,
            runtime_nav=0.98,
            r0_data_available=True,
        )
        self.assertEqual(result["decision"], "reject")


if __name__ == "__main__":
    unittest.main()
