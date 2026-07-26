from __future__ import annotations

import unittest

from qount.small_account.management import DEFAULT_TAIL_STOP_POLICY
from qount.small_account.management import calculate_post_2r_tail_stop


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


if __name__ == "__main__":
    unittest.main()
