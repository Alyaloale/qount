from __future__ import annotations

import math
import unittest

from qount.small_account.risk import AccountRiskSnapshot
from qount.small_account.risk import DEFAULT_SMALL_ACCOUNT_POLICY
from qount.small_account.risk import ExecutionCostRates
from qount.small_account.risk import SmallAccountRiskPolicy
from qount.small_account.risk import evaluate_account_guard
from qount.small_account.risk import size_linear_usdt_futures
from qount.small_account.risk import size_spot_long


ZERO_COSTS = ExecutionCostRates(0.0, 0.0, 0.0, 0.0)


def _healthy_snapshot(**overrides: object) -> AccountRiskSnapshot:
    values: dict[str, object] = {
        "net_liquidation_equity_usdt": 200.0,
        "high_water_equity_usdt": 200.0,
        "day_start_equity_usdt": 200.0,
        "rolling_24h_start_equity_usdt": 200.0,
    }
    values.update(overrides)
    return AccountRiskSnapshot(**values)


class SmallAccountPolicyTests(unittest.TestCase):
    def test_default_policy_is_the_frozen_200_usdt_contract(self) -> None:
        policy = DEFAULT_SMALL_ACCOUNT_POLICY
        self.assertEqual(policy.validate(), ())
        self.assertEqual(policy.initial_equity_usdt, 200.0)
        self.assertEqual(policy.first_live_risk_cap_usdt, 5.0)
        self.assertEqual(policy.per_trade_risk_cap_usdt, 10.0)
        self.assertEqual(policy.concurrent_stress_risk_cap_usdt, 10.0)
        self.assertEqual(policy.rolling_24h_loss_limit_usdt, 10.0)
        self.assertEqual(policy.strategy_drawdown_limit_usdt, 20.0)
        self.assertEqual(policy.emergency_drawdown_limit_usdt, 32.0)
        self.assertEqual(policy.disaster_drawdown_limit_usdt, 40.0)
        self.assertEqual(policy.maximum_futures_leverage, 5.0)
        self.assertEqual(policy.maximum_isolated_margin_usdt, 40.0)
        self.assertEqual(policy.maximum_futures_notional_usdt, 200.0)
        self.assertEqual(policy.maximum_spot_notional_usdt, 40.0)
        self.assertEqual(policy.minimum_reward_risk_ratio, 2.0)

    def test_invalid_policy_fails_validation(self) -> None:
        policy = SmallAccountRiskPolicy(
            first_live_risk_cap_usdt=11.0,
            per_trade_risk_cap_usdt=10.0,
        )
        self.assertIn("policy_first_live_cap_above_trade_cap", policy.validate())
        self.assertEqual(policy.active_trade_risk_cap(False), 0.0)


class SmallAccountSizingTests(unittest.TestCase):
    def test_futures_formula_includes_gap_both_fees_slippage_and_funding(self) -> None:
        costs = ExecutionCostRates(
            entry_fee_rate=0.001,
            exit_fee_rate=0.002,
            entry_slippage_rate=0.003,
            exit_slippage_rate=0.004,
            adverse_funding_rate=0.005,
        )
        result = size_linear_usdt_futures(
            side="long",
            entry_price=100.0,
            stop_price=98.0,
            target_price=120.0,
            stop_gap_rate=0.01,
            quantity_step=0.01,
            costs=costs,
        )
        expected_risk_per_unit = 2.98 + 0.1 + 0.3 + 0.19404 + 0.38808 + 0.5
        expected_reward_per_unit = 20.0 - 0.1 - 0.3 - 0.24 - 0.48 - 0.5
        self.assertTrue(result.allowed)
        self.assertAlmostEqual(result.worst_stop_fill_price, 97.02)
        self.assertAlmostEqual(result.risk_per_unit_usdt, expected_risk_per_unit)
        self.assertAlmostEqual(result.reward_per_unit_usdt, expected_reward_per_unit)
        self.assertLessEqual(result.estimated_stress_loss_usdt, 5.0)
        self.assertAlmostEqual(result.quantity, 1.12)

    def test_short_formula_is_directionally_symmetric(self) -> None:
        result = size_linear_usdt_futures(
            side="short",
            entry_price=100.0,
            stop_price=102.0,
            target_price=93.5,
            stop_gap_rate=0.01,
            quantity_step=0.01,
            costs=ZERO_COSTS,
        )
        self.assertTrue(result.allowed)
        self.assertAlmostEqual(result.worst_stop_fill_price, 103.02)
        self.assertAlmostEqual(result.risk_per_unit_usdt, 3.02)
        self.assertGreaterEqual(result.reward_risk_ratio, 2.0)
        self.assertLessEqual(result.estimated_stress_loss_usdt, 5.0)

    def test_quantity_is_floored_to_step_never_rounded_up(self) -> None:
        result = size_linear_usdt_futures(
            side="long",
            entry_price=100.0,
            stop_price=96.0,
            target_price=108.0,
            stop_gap_rate=0.0,
            quantity_step=0.1,
            costs=ZERO_COSTS,
        )
        self.assertTrue(result.allowed)
        self.assertEqual(result.quantity, 1.2)
        self.assertEqual(result.estimated_stress_loss_usdt, 4.8)

    def test_first_live_budget_above_five_is_rejected_not_silently_clamped(self) -> None:
        result = size_linear_usdt_futures(
            side="long",
            entry_price=100.0,
            stop_price=98.0,
            target_price=105.0,
            stop_gap_rate=0.0,
            quantity_step=0.01,
            costs=ZERO_COSTS,
            risk_budget_usdt=10.0,
            protective_cycle_verified=False,
        )
        self.assertFalse(result.allowed)
        self.assertIn("first_live_risk_cap_exceeded", result.reasons)
        self.assertEqual(result.quantity, 0.0)

    def test_verified_futures_is_capped_by_notional_and_isolated_margin(self) -> None:
        result = size_linear_usdt_futures(
            side="long",
            entry_price=100.0,
            stop_price=99.0,
            target_price=103.0,
            stop_gap_rate=0.0,
            quantity_step=0.01,
            costs=ZERO_COSTS,
            risk_budget_usdt=10.0,
            protective_cycle_verified=True,
        )
        self.assertTrue(result.allowed)
        self.assertEqual(result.notional_usdt, 200.0)
        self.assertEqual(result.isolated_margin_usdt, 40.0)
        self.assertEqual(result.leverage, 5.0)
        self.assertEqual(result.estimated_stress_loss_usdt, 2.0)

    def test_lower_leverage_uses_margin_cap_without_changing_risk_formula(self) -> None:
        result = size_linear_usdt_futures(
            side="long",
            entry_price=100.0,
            stop_price=99.0,
            target_price=103.0,
            stop_gap_rate=0.0,
            quantity_step=0.01,
            costs=ZERO_COSTS,
            risk_budget_usdt=10.0,
            leverage=2.0,
            protective_cycle_verified=True,
        )
        self.assertTrue(result.allowed)
        self.assertEqual(result.notional_usdt, 80.0)
        self.assertEqual(result.isolated_margin_usdt, 40.0)
        self.assertEqual(result.estimated_stress_loss_usdt, 0.8)

    def test_leverage_above_five_or_cross_margin_is_rejected(self) -> None:
        high_leverage = size_linear_usdt_futures(
            side="long",
            entry_price=100.0,
            stop_price=98.0,
            target_price=105.0,
            stop_gap_rate=0.0,
            quantity_step=0.01,
            costs=ZERO_COSTS,
            leverage=5.01,
        )
        cross = size_linear_usdt_futures(
            side="long",
            entry_price=100.0,
            stop_price=98.0,
            target_price=105.0,
            stop_gap_rate=0.0,
            quantity_step=0.01,
            costs=ZERO_COSTS,
            margin_mode="cross",
        )
        self.assertIn("maximum_futures_leverage_exceeded", high_leverage.reasons)
        self.assertIn("isolated_margin_required", cross.reasons)

    def test_after_cost_reward_risk_gate_rejects_nominal_two_to_one(self) -> None:
        costs = ExecutionCostRates(0.001, 0.001, 0.001, 0.001)
        result = size_linear_usdt_futures(
            side="long",
            entry_price=100.0,
            stop_price=98.0,
            target_price=104.0,
            stop_gap_rate=0.0,
            quantity_step=0.01,
            costs=costs,
        )
        self.assertFalse(result.allowed)
        self.assertIn("minimum_reward_risk_ratio_not_met", result.reasons)
        self.assertLess(result.reward_risk_ratio, 2.0)

    def test_spot_is_capped_at_forty_under_tail_stress(self) -> None:
        result = size_spot_long(
            entry_price=10.0,
            stop_price=9.0,
            target_price=12.5,
            stop_gap_rate=0.01,
            quantity_step=0.01,
            costs=ExecutionCostRates(0.001, 0.001, 0.001, 0.001),
            risk_budget_usdt=10.0,
            protective_cycle_verified=True,
        )
        self.assertTrue(result.allowed)
        self.assertEqual(result.notional_usdt, 40.0)
        self.assertLessEqual(result.estimated_stress_loss_usdt, 10.0)

    def test_spot_funding_and_exchange_minimum_fail_closed(self) -> None:
        funding = size_spot_long(
            entry_price=10.0,
            stop_price=9.0,
            target_price=13.0,
            stop_gap_rate=0.01,
            quantity_step=0.01,
            costs=ExecutionCostRates(0.0, 0.0, 0.0, 0.0, 0.001),
        )
        too_small = size_spot_long(
            entry_price=10.0,
            stop_price=9.0,
            target_price=13.0,
            stop_gap_rate=0.01,
            quantity_step=0.01,
            costs=ZERO_COSTS,
            minimum_notional_usdt=41.0,
        )
        self.assertIn("spot_funding_rate_must_be_zero", funding.reasons)
        self.assertIn("notional_below_exchange_minimum", too_small.reasons)

    def test_invalid_geometry_and_non_finite_costs_fail_closed(self) -> None:
        result = size_linear_usdt_futures(
            side="long",
            entry_price=100.0,
            stop_price=101.0,
            target_price=99.0,
            stop_gap_rate=0.0,
            quantity_step=0.01,
            costs=ExecutionCostRates(math.nan, 0.0, 0.0, 0.0),
        )
        self.assertFalse(result.allowed)
        self.assertIn("entry_fee_rate_invalid", result.reasons)
        self.assertIn("long_stop_not_below_entry", result.reasons)
        self.assertIn("long_target_not_above_entry", result.reasons)


class SmallAccountGuardTests(unittest.TestCase):
    def test_first_protective_cycle_caps_total_risk_at_five(self) -> None:
        allowed = evaluate_account_guard(
            _healthy_snapshot(),
            requested_new_risk_usdt=5.0,
            requested_crypto_beta_direction="long",
        )
        blocked = evaluate_account_guard(
            _healthy_snapshot(),
            requested_new_risk_usdt=5.01,
            requested_crypto_beta_direction="long",
        )
        self.assertTrue(allowed.allow_new_risk)
        self.assertEqual(allowed.active_risk_cap_usdt, 5.0)
        self.assertFalse(blocked.allow_new_risk)
        self.assertIn("first_live_risk_cap_exceeded", blocked.reasons)
        self.assertIn("concurrent_stress_risk_cap_exceeded", blocked.reasons)

    def test_verified_cycle_allows_ten_when_account_is_flat(self) -> None:
        exact = evaluate_account_guard(
            _healthy_snapshot(protective_cycle_verified=True),
            requested_new_risk_usdt=10.0,
            requested_crypto_beta_direction="long",
        )
        exceeded = evaluate_account_guard(
            _healthy_snapshot(protective_cycle_verified=True),
            requested_new_risk_usdt=10.01,
            requested_crypto_beta_direction="long",
        )
        self.assertTrue(exact.allow_new_risk)
        self.assertEqual(exact.total_stress_risk_after_request_usdt, 10.0)
        self.assertEqual(exact.remaining_stress_risk_capacity_usdt, 10.0)
        self.assertFalse(exceeded.allow_new_risk)
        self.assertIn("concurrent_stress_risk_cap_exceeded", exceeded.reasons)

    def test_existing_risk_above_cap_requires_flatten(self) -> None:
        result = evaluate_account_guard(
            _healthy_snapshot(
                protective_cycle_verified=True,
                open_stress_risk_usdt=8.0,
                pending_stress_risk_usdt=3.0,
                crypto_beta_directions=("long",),
            )
        )
        self.assertFalse(result.allow_new_risk)
        self.assertTrue(result.risk_reduction_required)
        self.assertTrue(result.flatten_required)

    def test_day_or_rolling_loss_at_ten_flattens_and_halts(self) -> None:
        day = evaluate_account_guard(
            _healthy_snapshot(
                net_liquidation_equity_usdt=190.0,
                day_start_equity_usdt=200.0,
                rolling_24h_start_equity_usdt=190.0,
            )
        )
        rolling = evaluate_account_guard(
            _healthy_snapshot(
                net_liquidation_equity_usdt=190.0,
                day_start_equity_usdt=190.0,
                rolling_24h_start_equity_usdt=200.0,
            )
        )
        self.assertIn("day_loss_limit_reached", day.reasons)
        self.assertIn("rolling_24h_loss_limit_reached", rolling.reasons)
        self.assertTrue(day.flatten_required and day.halt_required)
        self.assertTrue(rolling.flatten_required and rolling.halt_required)

    def test_strategy_drawdown_at_twenty_flattens_without_emergency_halt(self) -> None:
        result = evaluate_account_guard(
            _healthy_snapshot(
                net_liquidation_equity_usdt=180.0,
                day_start_equity_usdt=180.0,
                rolling_24h_start_equity_usdt=180.0,
            )
        )
        self.assertFalse(result.allow_new_risk)
        self.assertTrue(result.flatten_required)
        self.assertTrue(result.risk_reduction_required)
        self.assertFalse(result.halt_required)
        self.assertEqual(result.reasons, ("strategy_drawdown_limit_reached",))

    def test_emergency_and_disaster_boundaries_are_inclusive(self) -> None:
        emergency = evaluate_account_guard(
            _healthy_snapshot(
                net_liquidation_equity_usdt=168.0,
                day_start_equity_usdt=168.0,
                rolling_24h_start_equity_usdt=168.0,
            )
        )
        disaster = evaluate_account_guard(
            _healthy_snapshot(
                net_liquidation_equity_usdt=160.0,
                day_start_equity_usdt=160.0,
                rolling_24h_start_equity_usdt=160.0,
            )
        )
        self.assertIn("emergency_drawdown_limit_reached", emergency.reasons)
        self.assertTrue(emergency.flatten_required and emergency.halt_required)
        self.assertFalse(emergency.disaster_limit_breached)
        self.assertIn("disaster_drawdown_limit_reached", disaster.reasons)
        self.assertTrue(disaster.disaster_limit_breached)

    def test_unknown_stale_and_unprotected_states_fail_closed(self) -> None:
        unknown = evaluate_account_guard(
            _healthy_snapshot(has_unknown_state=True)
        )
        stale = evaluate_account_guard(_healthy_snapshot(state_is_stale=True))
        unprotected = evaluate_account_guard(
            _healthy_snapshot(unprotected_position_count=1)
        )
        for result in (unknown, stale, unprotected):
            self.assertFalse(result.allow_new_risk)
            self.assertTrue(result.halt_required)
            self.assertTrue(result.reconciliation_required)
        self.assertFalse(unknown.flatten_required)
        self.assertFalse(stale.flatten_required)
        self.assertTrue(unprotected.flatten_required)

    def test_multiple_crypto_beta_exposures_are_not_treated_as_diversification(self) -> None:
        proposed_conflict = evaluate_account_guard(
            _healthy_snapshot(
                protective_cycle_verified=True,
                open_stress_risk_usdt=1.0,
                crypto_beta_directions=("long",),
            ),
            requested_new_risk_usdt=1.0,
            requested_crypto_beta_direction="long",
        )
        existing_conflict = evaluate_account_guard(
            _healthy_snapshot(
                protective_cycle_verified=True,
                open_stress_risk_usdt=2.0,
                crypto_beta_directions=("long", "short"),
            )
        )
        self.assertIn(
            "crypto_beta_exposure_limit_exceeded", proposed_conflict.reasons
        )
        self.assertFalse(proposed_conflict.flatten_required)
        self.assertTrue(existing_conflict.flatten_required)
        self.assertTrue(existing_conflict.halt_required)

    def test_remaining_loss_budget_reduces_the_next_trade(self) -> None:
        allowed = evaluate_account_guard(
            _healthy_snapshot(
                net_liquidation_equity_usdt=186.0,
                day_start_equity_usdt=186.0,
                rolling_24h_start_equity_usdt=186.0,
                protective_cycle_verified=True,
            ),
            requested_new_risk_usdt=6.0,
            requested_crypto_beta_direction="long",
        )
        blocked = evaluate_account_guard(
            _healthy_snapshot(
                net_liquidation_equity_usdt=186.0,
                day_start_equity_usdt=186.0,
                rolling_24h_start_equity_usdt=186.0,
                protective_cycle_verified=True,
            ),
            requested_new_risk_usdt=6.01,
            requested_crypto_beta_direction="long",
        )
        self.assertTrue(allowed.allow_new_risk)
        self.assertEqual(allowed.remaining_stress_risk_capacity_usdt, 6.0)
        self.assertFalse(blocked.allow_new_risk)
        self.assertIn("strategy_drawdown_budget_exceeded", blocked.reasons)

    def test_daily_loss_headroom_caps_new_risk_before_the_halt_line(self) -> None:
        result = evaluate_account_guard(
            _healthy_snapshot(
                net_liquidation_equity_usdt=192.0,
                day_start_equity_usdt=200.0,
                rolling_24h_start_equity_usdt=192.0,
                protective_cycle_verified=True,
            ),
            requested_new_risk_usdt=2.01,
            requested_crypto_beta_direction="long",
        )
        self.assertFalse(result.allow_new_risk)
        self.assertEqual(result.remaining_stress_risk_capacity_usdt, 2.0)
        self.assertIn("day_loss_budget_exceeded", result.reasons)

    def test_malformed_runtime_values_fail_closed_without_raising(self) -> None:
        bad_size = size_linear_usdt_futures(
            side="long",
            entry_price=None,  # type: ignore[arg-type]
            stop_price=98.0,
            target_price=105.0,
            stop_gap_rate=0.0,
            quantity_step=0.01,
            costs=ZERO_COSTS,
        )
        bad_guard = evaluate_account_guard(
            _healthy_snapshot(
                unprotected_position_count="one",  # type: ignore[arg-type]
            )
        )
        self.assertFalse(bad_size.allowed)
        self.assertIn("entry_price_invalid", bad_size.reasons)
        self.assertFalse(bad_guard.allow_new_risk)
        self.assertTrue(bad_guard.halt_required)

    def test_inconsistent_or_non_finite_account_state_fails_closed(self) -> None:
        inconsistent = evaluate_account_guard(
            _healthy_snapshot(
                net_liquidation_equity_usdt=201.0,
                high_water_equity_usdt=200.0,
            )
        )
        non_finite = evaluate_account_guard(
            _healthy_snapshot(net_liquidation_equity_usdt=math.nan)
        )
        self.assertIn("high_water_below_current_equity", inconsistent.reasons)
        self.assertIn("net_liquidation_equity_usdt_invalid", non_finite.reasons)
        for result in (inconsistent, non_finite):
            self.assertFalse(result.allow_new_risk)
            self.assertTrue(result.halt_required)
            self.assertTrue(result.reconciliation_required)


if __name__ == "__main__":
    unittest.main()
