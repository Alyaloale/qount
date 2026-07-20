from __future__ import annotations

import unittest

from qount.portfolio_governance import FormalTrial
from qount.portfolio_governance import EquityMappingExecutionContract
from qount.portfolio_governance import ForwardPeriod
from qount.portfolio_governance import NavAttribution
from qount.portfolio_governance import SleeveRiskBudget
from qount.portfolio_governance import SleeveRuntimeEligibility
from qount.portfolio_governance import StrategyIntent
from qount.portfolio_governance import allocate_strategy_intents
from qount.portfolio_governance import base_operational_evidence
from qount.portfolio_governance import equity_mapping_independence
from qount.portfolio_governance import equity_mapping_event_capacity
from qount.portfolio_governance import funding_episode_independence
from qount.portfolio_governance import record_forward_review
from qount.portfolio_governance import register_formal_trial
from qount.portfolio_governance import scale_standalone_weights
from qount.portfolio_governance import validate_runtime_eligibility


class PortfolioGovernanceTests(unittest.TestCase):
    def _intent(
        self,
        strategy_id: str,
        weights: dict[str, float],
    ) -> StrategyIntent:
        return StrategyIntent(
            strategy_id=strategy_id,
            decision_time="2026-07-20T00:05:00+00:00",
            data_cutoff="2026-07-20T00:00:00+00:00",
            target_weights=weights,
            expected_holding_bars=1,
            target_stress_loss_fraction=0.01,
            evidence_hash="a" * 64,
            state_hash="b" * 64,
        )

    def test_small_account_allows_one_continuous_and_one_minimal_event(self) -> None:
        sleeves = (
            SleeveRuntimeEligibility("base", "continuous", "live"),
            SleeveRuntimeEligibility("equity", "event", "minimal_live"),
            SleeveRuntimeEligibility("liquid", "continuous", "shadow"),
            SleeveRuntimeEligibility("funding", "filter", "research"),
        )
        self.assertEqual(validate_runtime_eligibility(1_000.0, sleeves), ())

    def test_small_account_blocks_parallel_continuous_live_sleeves(self) -> None:
        sleeves = (
            SleeveRuntimeEligibility("base", "continuous", "live"),
            SleeveRuntimeEligibility("liquid", "continuous", "minimal_live"),
        )
        self.assertIn(
            "small_account_multiple_continuous_live_sleeves",
            validate_runtime_eligibility(1_000.0, sleeves),
        )

    def test_promotion_and_account_nav_have_distinct_contracts(self) -> None:
        attribution = NavAttribution("base", 1.1, 1.08, 1.07)
        self.assertEqual(attribution.promotion_nav, 1.08)
        self.assertEqual(attribution.account_nav, 1.07)
        polluted = NavAttribution("base", 1.1, 1.09, 1.07, 0.01)
        self.assertIn(
            "netting_savings_must_not_enter_standalone_nav", polluted.validate()
        )

    def test_risk_budget_is_stress_loss_contribution_not_cash_fraction(self) -> None:
        budget = SleeveRiskBudget(
            "equity", target_stress_loss_fraction=0.0025,
            estimated_standalone_stress_loss_fraction=0.05,
            capacity_scalar_cap=0.20,
        )
        self.assertAlmostEqual(budget.risk_scalar(), 0.05)
        self.assertEqual(scale_standalone_weights({"NVDA": 0.4}, budget), {"NVDA": 0.02})

    def test_allocator_aggregates_allowlisted_stress_scaled_intents(self) -> None:
        result = allocate_strategy_intents(
            (
                self._intent("base", {"BTCUSDT": 0.4, "ETHUSDT": 0.2}),
                self._intent("event", {"BTCUSDT": 0.2}),
            ),
            (
                SleeveRiskBudget("base", 0.10, 0.20, 1.0),
                SleeveRiskBudget("event", 0.0025, 0.05, 0.10),
            ),
            account_equity_usdt=500.0,
            allowed_strategy_ids=("base", "event"),
            minimum_notional_by_symbol={"BTCUSDT": 5.0, "ETHUSDT": 5.0},
            maximum_weight_by_symbol={"BTCUSDT": 0.5, "ETHUSDT": 0.25},
            correlation_cluster_by_symbol={
                "BTCUSDT": "crypto_beta",
                "ETHUSDT": "crypto_beta",
            },
        )
        self.assertTrue(result["allocatable"])
        self.assertAlmostEqual(result["portfolio_target_weights"]["BTCUSDT"], 0.21)
        self.assertAlmostEqual(result["portfolio_target_weights"]["ETHUSDT"], 0.10)
        self.assertEqual(len(result["allocation_hash"]), 64)

    def test_allocator_fails_entire_batch_closed_on_capacity_or_contract_error(self) -> None:
        result = allocate_strategy_intents(
            (
                self._intent("base", {"BTCUSDT": 0.8}),
                self._intent("unknown", {"ETHUSDT": 0.8}),
            ),
            (
                SleeveRiskBudget("base", 0.20, 0.20, 1.0),
                SleeveRiskBudget("unknown", 0.20, 0.20, 1.0),
            ),
            account_equity_usdt=100.0,
            allowed_strategy_ids=("base",),
            minimum_notional_by_symbol={"BTCUSDT": 100.0, "ETHUSDT": 100.0},
            maximum_weight_by_symbol={"BTCUSDT": 0.5, "ETHUSDT": 0.5},
        )
        self.assertFalse(result["allocatable"])
        self.assertEqual(
            result["portfolio_target_weights"],
            {"BTCUSDT": 0.0, "ETHUSDT": 0.0},
        )
        self.assertIn("portfolio_gross_limit_exceeded", result["blockers"])
        self.assertIn("strategy_not_allowlisted:unknown", result["blockers"])
        self.assertIn("symbol_weight_cap_exceeded:BTCUSDT", result["blockers"])
        self.assertIn("target_below_minimum_notional:BTCUSDT", result["blockers"])

    def test_allocator_does_not_let_base_netting_subsidize_small_sleeve_capacity(self) -> None:
        result = allocate_strategy_intents(
            (
                self._intent("base", {"BTCUSDT": 0.5}),
                self._intent("event", {"BTCUSDT": 0.2}),
            ),
            (
                SleeveRiskBudget("base", 0.20, 0.20, 1.0),
                SleeveRiskBudget("event", 0.0025, 0.10, 0.10),
            ),
            account_equity_usdt=500.0,
            allowed_strategy_ids=("base", "event"),
            minimum_notional_by_symbol={"BTCUSDT": 50.0},
            maximum_weight_by_symbol={"BTCUSDT": 1.0},
        )
        self.assertGreater(result["proposed_target_weights"]["BTCUSDT"] * 500.0, 50.0)
        self.assertFalse(result["allocatable"])
        self.assertIn(
            "sleeve_target_below_minimum_notional:event:BTCUSDT",
            result["blockers"],
        )

    def test_strategy_intent_rejects_future_data_and_short_weights(self) -> None:
        intent = StrategyIntent(
            strategy_id="bad",
            decision_time="2026-07-20T00:00:00+00:00",
            data_cutoff="2026-07-20T00:01:00+00:00",
            target_weights={"BTCUSDT": -0.1},
            expected_holding_bars=1,
            target_stress_loss_fraction=0.01,
            evidence_hash="a" * 64,
            state_hash="b" * 64,
        )
        self.assertIn("data_cutoff_after_decision_time", intent.validate())
        self.assertIn("short_target_forbidden:BTCUSDT", intent.validate())

    def test_equity_mapping_is_long_only_and_stress_sized(self) -> None:
        capacity = equity_mapping_event_capacity(
            account_equity_usdt=1_000.0,
            true_gap=-0.03,
            stress_loss_fraction=0.10,
            minimum_notional_usdt=5.0,
            corporate_action_status="point_in_time_adjusted",
        )
        self.assertEqual(capacity["notional_usdt"], 25.0)
        self.assertTrue(capacity["live_trial_eligible"])
        self.assertEqual(
            EquityMappingExecutionContract().timezone, "America/New_York"
        )

    def test_equity_mapping_unknown_action_or_small_notional_stays_shadow(self) -> None:
        capacity = equity_mapping_event_capacity(
            account_equity_usdt=1_000.0,
            true_gap=-0.03,
            stress_loss_fraction=0.75,
            minimum_notional_usdt=5.0,
            corporate_action_status="unknown",
        )
        self.assertTrue(capacity["shadow_only"])
        self.assertIn(
            "corporate_action_not_point_in_time_reconstructable",
            capacity["reasons"],
        )
        self.assertIn(
            "stress_sized_notional_below_exchange_minimum", capacity["reasons"]
        )

    def test_fourth_formal_trial_in_family_is_rejected(self) -> None:
        trials: tuple[FormalTrial, ...] = ()
        for index in range(3):
            trials = register_formal_trial(
                trials,
                FormalTrial(
                    trial_id=f"trial-{index}",
                    hypothesis_family="liquid_rank",
                    preregistered_primary_metric="net_return_vs_base",
                    preregistered_failure_condition="net_return_not_positive",
                    allowed_sensitivity_range="cost 12-24 bps only",
                    number_of_prior_trials=index,
                ),
            )
        with self.assertRaisesRegex(ValueError, "trial_budget_exhausted"):
            register_formal_trial(
                trials,
                FormalTrial(
                    trial_id="trial-3",
                    hypothesis_family="liquid_rank",
                    preregistered_primary_metric="net_return_vs_base",
                    preregistered_failure_condition="net_return_not_positive",
                    allowed_sensitivity_range="cost 12-24 bps only",
                    number_of_prior_trials=3,
                ),
            )

    def test_rule_change_consumes_forward_period(self) -> None:
        reviewed = record_forward_review(
            ForwardPeriod("2026Q3"), rules_changed_after_review=True
        )
        self.assertEqual(reviewed.pool_role, "consumed_pool")
        self.assertTrue(reviewed.next_unseen_period_required)

    def test_independence_units_do_not_count_correlated_rows_as_dates(self) -> None:
        records = [
            {
                "cash_trading_date": "2026-07-20",
                "is_earnings": True,
                "is_ordinary_weekend": False,
                "is_holiday": False,
            },
            {
                "cash_trading_date": "2026-07-20",
                "is_earnings": False,
                "is_ordinary_weekend": False,
                "is_holiday": False,
            },
        ]
        evidence = equity_mapping_independence(records)
        self.assertEqual(evidence["asset_event_count"], 2)
        self.assertEqual(evidence["independent_cash_trading_dates"], 1)
        self.assertEqual(
            funding_episode_independence(
                ({"episode_id": "crowding-1"}, {"episode_id": "crowding-1"})
            )["independent_episode_count"],
            1,
        )
        self.assertEqual(
            base_operational_evidence(("2026-07-19", "2026-07-19"))[
                "statistical_alpha_units"
            ],
            0,
        )


if __name__ == "__main__":
    unittest.main()
