from __future__ import annotations

import unittest

from qount.small_account.management import DEFAULT_TAIL_STOP_POLICY
from qount.small_account.management import calculate_one_third_exit_quantity
from qount.small_account.management import calculate_post_2r_tail_stop
from qount.small_account.management import calculate_profit_thresholds


class TailStopPolicyTests(unittest.TestCase):
    def test_default_trail_is_one_completed_hour_atr(self) -> None:
        self.assertEqual(DEFAULT_TAIL_STOP_POLICY.validate(), ())
        self.assertEqual(DEFAULT_TAIL_STOP_POLICY.trailing_atr_multiple, 1.0)


class TailStopDecisionTests(unittest.TestCase):
    def test_long_uses_the_most_protective_ratchet(self) -> None:
        cases = (
            (100.0, 105.0, 110.0, 3.0, 107.0),
            (100.0, 105.0, 107.0, 3.0, 105.0),
            (108.0, 105.0, 110.0, 3.0, 108.0),
        )
        for previous, floor, extreme, atr, expected in cases:
            with self.subTest(expected=expected):
                result = calculate_post_2r_tail_stop(
                    side="long",
                    previous_stop_price=previous,
                    net_one_r_floor_price=floor,
                    favorable_completed_1h_close_price=extreme,
                    atr14_1h=atr,
                    partial_exit_confirmed=True,
                )

                self.assertTrue(result.allowed)
                self.assertEqual(result.next_stop_price, expected)

    def test_short_is_directionally_symmetric(self) -> None:
        result = calculate_post_2r_tail_stop(
            side="short",
            previous_stop_price=100.0,
            net_one_r_floor_price=95.0,
            favorable_completed_1h_close_price=90.0,
            atr14_1h=3.0,
            partial_exit_confirmed=True,
        )

        self.assertTrue(result.allowed)
        self.assertEqual(result.atr_trailing_candidate_price, 93.0)
        self.assertEqual(result.next_stop_price, 93.0)

    def test_partial_exit_must_be_confirmed_before_stop_replacement(self) -> None:
        result = calculate_post_2r_tail_stop(
            side="long",
            previous_stop_price=100.0,
            net_one_r_floor_price=105.0,
            favorable_completed_1h_close_price=110.0,
            atr14_1h=3.0,
            partial_exit_confirmed=False,
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.reasons, ("partial_exit_not_confirmed",))
        self.assertIsNone(result.next_stop_price)

    def test_favorable_close_must_have_crossed_the_one_r_floor(self) -> None:
        result = calculate_post_2r_tail_stop(
            side="long",
            previous_stop_price=100.0,
            net_one_r_floor_price=105.0,
            favorable_completed_1h_close_price=104.0,
            atr14_1h=3.0,
            partial_exit_confirmed=True,
        )

        self.assertFalse(result.allowed)
        self.assertEqual(
            result.reasons, ("favorable_close_not_beyond_one_r_floor",)
        )

    def test_previous_stop_cannot_already_be_through_the_completed_close(self) -> None:
        result = calculate_post_2r_tail_stop(
            side="long",
            previous_stop_price=111.0,
            net_one_r_floor_price=105.0,
            favorable_completed_1h_close_price=110.0,
            atr14_1h=3.0,
            partial_exit_confirmed=True,
        )

        self.assertFalse(result.allowed)
        self.assertEqual(
            result.reasons, ("previous_stop_already_through_favorable_close",)
        )

    def test_malformed_policy_fails_closed_without_raising(self) -> None:
        result = calculate_post_2r_tail_stop(
            side="long",
            previous_stop_price=100.0,
            net_one_r_floor_price=105.0,
            favorable_completed_1h_close_price=110.0,
            atr14_1h=3.0,
            partial_exit_confirmed=True,
            policy=None,
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.reasons, ("policy_invalid",))


class ProfitThresholdTests(unittest.TestCase):
    def test_thresholds_keep_actual_entry_cost_and_future_exit_costs(self) -> None:
        long = calculate_profit_thresholds(
            side="long",
            entry_price=100.0,
            initial_quantity=1.0,
            full_risk_usdt=5.0,
            entry_fee_usdt=0.1,
            adverse_funding_usdt=0.06,
            exit_fee_rate=0.0005,
            exit_slippage_rate=0.0005,
        )
        short = calculate_profit_thresholds(
            side="short",
            entry_price=100.0,
            initial_quantity=1.0,
            full_risk_usdt=5.0,
            entry_fee_usdt=0.1,
            adverse_funding_usdt=0.06,
            exit_fee_rate=0.0005,
            exit_slippage_rate=0.0005,
        )

        self.assertTrue(long.allowed)
        self.assertGreater(long.net_break_even_price, 100.0)
        self.assertGreater(long.net_two_r_price, long.net_one_r_price)
        self.assertTrue(short.allowed)
        self.assertLess(short.net_break_even_price, 100.0)
        self.assertLess(short.net_two_r_price, short.net_one_r_price)

    def test_one_third_must_be_representable_without_consuming_tail(self) -> None:
        blocked = calculate_one_third_exit_quantity(
            initial_quantity=0.002,
            quantity_step=0.001,
            minimum_quantity=0.001,
        )
        allowed = calculate_one_third_exit_quantity(
            initial_quantity=0.003,
            quantity_step=0.001,
            minimum_quantity=0.001,
        )

        self.assertFalse(blocked.allowed)
        self.assertIn("one_third_partial_below_minimum_quantity", blocked.reasons)
        self.assertTrue(allowed.allowed)
        self.assertEqual(allowed.partial_quantity, 0.001)
        self.assertEqual(allowed.remaining_quantity, 0.002)


if __name__ == "__main__":
    unittest.main()
