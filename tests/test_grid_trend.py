"""Unit tests for the GRID-B trend filter (SMA + four-state machine)."""

from __future__ import annotations

import unittest

from qount.legacy.grid_b.trend import HybridRegime
from qount.legacy.grid_b.trend import TrendState
from qount.legacy.grid_b.trend import hybrid_regimes
from qount.legacy.grid_b.trend import sma
from qount.legacy.grid_b.trend import trend_states


class TestSMA(unittest.TestCase):
    def test_warmup_then_average(self) -> None:
        out = sma([1, 2, 3, 4, 5], 3)
        self.assertIsNone(out[0])
        self.assertIsNone(out[1])
        self.assertAlmostEqual(out[2], 2.0)  # (1+2+3)/3
        self.assertAlmostEqual(out[3], 3.0)  # (2+3+4)/3
        self.assertAlmostEqual(out[4], 4.0)  # (3+4+5)/3

    def test_window_one_is_identity(self) -> None:
        self.assertEqual(sma([5, 6, 7], 1), [5, 6, 7])


class TestTrendStates(unittest.TestCase):
    def test_warmup_is_paused(self) -> None:
        states = trend_states([10] * 5, window=3, confirm_bars=2)
        # first window-1 bars warm up -> PAUSED
        self.assertEqual(states[0], TrendState.PAUSED)
        self.assertEqual(states[1], TrendState.PAUSED)

    def test_confirmed_uptrend_goes_active(self) -> None:
        # flat low then a clear rise above its short SMA, held for >= confirm_bars
        closes = [10, 10, 10, 11, 12, 13, 14, 15]
        states = trend_states(closes, window=3, confirm_bars=2)
        self.assertEqual(states[-1], TrendState.ACTIVE)

    def test_drop_below_first_derisks_then_pauses(self) -> None:
        # establish ACTIVE, then drop below the SMA: 1 bar = DERISK, 2 bars = PAUSED
        closes = [10, 11, 12, 13, 14, 15, 8, 7, 6]
        states = trend_states(closes, window=3, confirm_bars=2)
        # find the ACTIVE plateau
        self.assertEqual(states[5], TrendState.ACTIVE)
        # first bar below -> DERISK (unconfirmed)
        self.assertEqual(states[6], TrendState.DERISK)
        # second consecutive bar below -> PAUSED (confirmed)
        self.assertEqual(states[7], TrendState.PAUSED)

    def test_unconfirmed_bounce_out_of_paused_stays_paused(self) -> None:
        # deep below (PAUSED), then a single bar pokes above SMA but not confirmed
        closes = [20, 18, 16, 14, 12, 10, 8, 30, 8]
        states = trend_states(closes, window=3, confirm_bars=2)
        self.assertEqual(states[6], TrendState.PAUSED)
        # single spike above is not enough to re-arm -> still not ACTIVE
        self.assertNotEqual(states[7], TrendState.ACTIVE)

    def test_confirm_bars_one_has_no_derisk(self) -> None:
        closes = [10, 11, 12, 13, 14, 9, 8]
        states = trend_states(closes, window=3, confirm_bars=1)
        # with instant confirmation there is no transitional DERISK state
        self.assertNotIn(TrendState.DERISK, states)

    def test_bad_params(self) -> None:
        with self.assertRaises(ValueError):
            trend_states([1, 2, 3], window=0)
        with self.assertRaises(ValueError):
            trend_states([1, 2, 3], confirm_bars=0)


class TestHybridRegimes(unittest.TestCase):
    def test_three_state_classification(self) -> None:
        # ACTIVE throughout from i=4; r90 (window=3) crosses +15% at i=6.
        closes = [100, 100, 100, 100, 105, 110, 116, 124, 135, 150]
        regimes = hybrid_regimes(closes, window=3, confirm_bars=1,
                                  r90_window=3, r90_threshold=0.15)
        # ACTIVE but r90 < 15% -> RANGE
        self.assertEqual(regimes[4], HybridRegime.RANGE)
        self.assertEqual(regimes[5], HybridRegime.RANGE)
        # r90 has cleared +15% -> UPTREND
        self.assertEqual(regimes[6], HybridRegime.UPTREND)
        self.assertEqual(regimes[-1], HybridRegime.UPTREND)

    def test_below_gate_has_priority_over_r90(self) -> None:
        # unconfirmed bounce out of PAUSED (confirm_bars=2) stays PAUSED -> BELOW,
        # even though r90 at the spike bar is far above +15%.
        closes = [20, 18, 16, 14, 12, 10, 8, 30, 8]
        states = trend_states(closes, window=3, confirm_bars=2)
        self.assertNotEqual(states[7], TrendState.ACTIVE)
        regimes = hybrid_regimes(closes, window=3, confirm_bars=2,
                                  r90_window=3, r90_threshold=0.15)
        r90_at_7 = closes[7] / closes[7 - 3] - 1.0
        self.assertGreaterEqual(r90_at_7, 0.15)
        self.assertEqual(regimes[7], HybridRegime.BELOW)

    def test_active_and_deeply_down_is_range_not_below(self) -> None:
        # crashes from 200 to 100, then a small recovery confirms ACTIVE again while
        # still >= 15% below the level from r90_window bars ago.
        closes = [200, 200, 200, 200, 200, 100, 100, 100, 105, 112]
        states = trend_states(closes, window=3, confirm_bars=1)
        regimes = hybrid_regimes(closes, window=3, confirm_bars=1,
                                  r90_window=5, r90_threshold=0.15)
        self.assertEqual(states[-1], TrendState.ACTIVE)
        r90_last = closes[-1] / closes[-1 - 5] - 1.0
        self.assertLessEqual(r90_last, -0.15)
        self.assertEqual(regimes[-1], HybridRegime.RANGE)

    def test_r90_warmup_is_below_even_when_active(self) -> None:
        # ACTIVE from i=4, but r90_window=10 > any available history -> always BELOW.
        closes = [100, 100, 100, 100, 105, 110, 116]
        states = trend_states(closes, window=3, confirm_bars=1)
        regimes = hybrid_regimes(closes, window=3, confirm_bars=1,
                                  r90_window=10, r90_threshold=0.15)
        self.assertEqual(states[-1], TrendState.ACTIVE)
        self.assertTrue(all(r == HybridRegime.BELOW for r in regimes))


if __name__ == "__main__":
    unittest.main()
