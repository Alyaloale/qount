import unittest

from qount.research.active_basis import ActiveBasisConfig
from qount.research.active_basis import DailyBasisBar
from qount.research.active_basis import build_features
from qount.research.active_basis import evaluate_active_basis


def _series(bases: list[float], funding: float = 0.001) -> list[DailyBasisBar]:
    rows: list[DailyBasisBar] = []
    spot = 100.0
    for index, basis in enumerate(bases):
        rows.append(
            DailyBasisBar(
                ts_ms=index * 86_400_000,
                spot_close=spot,
                perp_close=spot * (1.0 + basis),
                basis_pct=basis,
                funding_rate_sum=funding,
                funding_settlement_count=3,
            )
        )
    return rows


class ActiveBasisTest(unittest.TestCase):
    def test_features_use_only_prior_basis_history(self) -> None:
        rows = _series([0.009, 0.011] * 15 + [0.03])
        features = build_features(rows, ActiveBasisConfig())
        self.assertIsNone(features[29].basis_z)
        self.assertIsNotNone(features[30].basis_z)
        self.assertGreater(features[30].basis_z or 0.0, 1.0)

    def test_positive_basis_entry_and_reversion_exit(self) -> None:
        rows = _series([0.01] * 30 + [0.03, 0.025, 0.011, 0.01] + [0.01] * 10)
        report = evaluate_active_basis(rows)
        self.assertGreaterEqual(report["active"]["trade_count"], 1)
        self.assertTrue(any(t["exit_reason"] == "basis_reverted" for t in report["active"]["trades"]))

    def test_incomplete_funding_blocks_entry(self) -> None:
        rows = _series([0.009, 0.011] * 15 + [0.03, 0.01, 0.01])
        rows[-3] = DailyBasisBar(
            ts_ms=rows[-3].ts_ms,
            spot_close=rows[-3].spot_close,
            perp_close=rows[-3].perp_close,
            basis_pct=rows[-3].basis_pct,
            funding_rate_sum=rows[-3].funding_rate_sum,
            funding_settlement_count=1,
        )
        report = evaluate_active_basis(rows)
        self.assertEqual(report["active"]["trade_count"], 0)

    def test_incomplete_executable_cost_model_is_a_kill_gate(self) -> None:
        report = evaluate_active_basis(_series([0.009, 0.011] * 15 + [0.03, 0.01, 0.01]))
        self.assertEqual(report["cost_model"]["status"], "incomplete")
        self.assertFalse(report["cost_model"]["complete_executable_cost_model"])
        self.assertFalse(report["kill_gates"]["complete_executable_cost_model"])
        self.assertIn("collateral_opportunity_cost", report["cost_model"]["unmodeled_components"])


if __name__ == "__main__":
    unittest.main()
