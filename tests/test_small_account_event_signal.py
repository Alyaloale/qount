from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from qount.small_account.event_signal import CompletedCandle
from qount.small_account.event_signal import DEFAULT_FOMC_SIGNAL_POLICY
from qount.small_account.event_signal import SIGNAL_CONTRACT_VERSION
from qount.small_account.event_signal import evaluate_fomc_hybrid_signal


OBSERVATION_START = datetime(2026, 7, 29, 22, 30, tzinfo=timezone.utc)
ANCHOR_CLOSE = datetime(2026, 7, 29, 23, 0, tzinfo=timezone.utc)
ENTRY_CUTOFF = datetime(2026, 7, 30, 4, 0, tzinfo=timezone.utc)


def _candle(
    *,
    interval_minutes: int,
    closed_at: datetime,
    open: float,
    high: float,
    low: float,
    close: float,
    volume: float,
) -> CompletedCandle:
    return CompletedCandle(
        interval_minutes=interval_minutes,
        closed_at=closed_at,
        open=open,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def _long_kwargs() -> dict[str, object]:
    return {
        "side": "long",
        "h0": 100.0,
        "l0": 90.0,
        "atr0": 4.0,
        "v20_15m": 100.0,
        "anchor_1h": _candle(
            interval_minutes=60,
            closed_at=ANCHOR_CLOSE,
            open=100.0,
            high=103.0,
            low=99.5,
            close=102.2,
            volume=500.0,
        ),
        "breakout_15m": _candle(
            interval_minutes=15,
            closed_at=ANCHOR_CLOSE,
            open=100.7,
            high=103.0,
            low=100.6,
            close=102.9,
            volume=160.0,
        ),
        "retest_15m": (
            _candle(
                interval_minutes=15,
                closed_at=ANCHOR_CLOSE + timedelta(minutes=15),
                open=102.9,
                high=103.0,
                low=101.25,
                close=101.5,
                volume=70.0,
            ),
            _candle(
                interval_minutes=15,
                closed_at=ANCHOR_CLOSE + timedelta(minutes=30),
                open=101.5,
                high=102.8,
                low=100.8,
                close=102.7,
                volume=128.0,
            ),
        ),
        "planned_entry_price": 102.0,
        "observation_started_at": OBSERVATION_START,
        "entry_cutoff_at": ENTRY_CUTOFF,
        "evaluated_at": ANCHOR_CLOSE + timedelta(minutes=31),
    }


def _short_kwargs() -> dict[str, object]:
    return {
        "side": "short",
        "h0": 110.0,
        "l0": 100.0,
        "atr0": 4.0,
        "v20_15m": 100.0,
        "anchor_1h": _candle(
            interval_minutes=60,
            closed_at=ANCHOR_CLOSE,
            open=100.0,
            high=100.5,
            low=97.0,
            close=97.8,
            volume=500.0,
        ),
        "breakout_15m": _candle(
            interval_minutes=15,
            closed_at=ANCHOR_CLOSE,
            open=99.3,
            high=99.4,
            low=97.0,
            close=97.1,
            volume=160.0,
        ),
        "retest_15m": (
            _candle(
                interval_minutes=15,
                closed_at=ANCHOR_CLOSE + timedelta(minutes=15),
                open=97.1,
                high=98.75,
                low=97.0,
                close=98.5,
                volume=70.0,
            ),
            _candle(
                interval_minutes=15,
                closed_at=ANCHOR_CLOSE + timedelta(minutes=30),
                open=98.5,
                high=99.2,
                low=97.2,
                close=97.3,
                volume=128.0,
            ),
        ),
        "planned_entry_price": 98.0,
        "observation_started_at": OBSERVATION_START,
        "entry_cutoff_at": ENTRY_CUTOFF,
        "evaluated_at": ANCHOR_CLOSE + timedelta(minutes=31),
    }


class FomcSignalPolicyTests(unittest.TestCase):
    def test_default_policy_is_the_v02_shadow_contract(self) -> None:
        policy = DEFAULT_FOMC_SIGNAL_POLICY
        self.assertEqual(policy.validate(), ())
        self.assertEqual(SIGNAL_CONTRACT_VERSION, "SmallAccount-FOMC-RightSide-v0.2")
        self.assertEqual(policy.breakout_atr_offset, 0.25)
        self.assertEqual(policy.retest_touch_tolerance_atr, 0.10)
        self.assertEqual(policy.maximum_retest_bars, 8)
        self.assertEqual(policy.minimum_breakout_body_fraction, 0.60)
        self.assertEqual(policy.reclaim_volume_fraction, 0.80)


class FomcHybridSignalTests(unittest.TestCase):
    def test_long_pattern_arms_at_the_frozen_boundaries(self) -> None:
        result = evaluate_fomc_hybrid_signal(**_long_kwargs())

        self.assertTrue(result.armed)
        self.assertEqual(result.state, "ARMED")
        self.assertEqual(result.reasons, ())
        self.assertEqual(result.breakout_line, 101.0)
        self.assertEqual(result.retest_extreme, 100.8)
        self.assertAlmostEqual(result.structural_stop_price, 98.8)

    def test_short_pattern_is_directionally_symmetric(self) -> None:
        result = evaluate_fomc_hybrid_signal(**_short_kwargs())

        self.assertTrue(result.armed)
        self.assertEqual(result.breakout_line, 99.0)
        self.assertEqual(result.retest_extreme, 99.2)
        self.assertAlmostEqual(result.structural_stop_price, 101.2)

    def test_touching_original_range_boundary_is_allowed(self) -> None:
        kwargs = _long_kwargs()
        bars = list(kwargs["retest_15m"])
        reclaim = bars[-1]
        bars[-1] = _candle(
            interval_minutes=15,
            closed_at=reclaim.closed_at,
            open=reclaim.open,
            high=reclaim.high,
            low=100.0,
            close=reclaim.close,
            volume=reclaim.volume,
        )
        kwargs["retest_15m"] = tuple(bars)

        result = evaluate_fomc_hybrid_signal(**kwargs)

        self.assertTrue(result.armed)
        self.assertEqual(result.retest_extreme, 100.0)

    def test_wick_back_inside_original_range_invalidates_the_event_candidate(self) -> None:
        cases = ((_long_kwargs(), "long"), (_short_kwargs(), "short"))
        for kwargs, side in cases:
            with self.subTest(side=side):
                bars = list(kwargs["retest_15m"])
                reclaim = bars[-1]
                if side == "long":
                    bars[-1] = _candle(
                        interval_minutes=15,
                        closed_at=reclaim.closed_at,
                        open=reclaim.open,
                        high=reclaim.high,
                        low=99.99,
                        close=reclaim.close,
                        volume=reclaim.volume,
                    )
                else:
                    bars[-1] = _candle(
                        interval_minutes=15,
                        closed_at=reclaim.closed_at,
                        open=reclaim.open,
                        high=100.01,
                        low=reclaim.low,
                        close=reclaim.close,
                        volume=reclaim.volume,
                    )
                kwargs["retest_15m"] = tuple(bars)

                result = evaluate_fomc_hybrid_signal(**kwargs)

                self.assertEqual(result.state, "NO_TRADE")
                self.assertEqual(
                    result.reasons, ("retest_returned_to_original_range",)
                )

    def test_missing_or_shallow_retest_stays_in_observe(self) -> None:
        missing = _long_kwargs()
        missing["retest_15m"] = ()
        missing_result = evaluate_fomc_hybrid_signal(**missing)
        self.assertEqual(missing_result.state, "OBSERVE")
        self.assertEqual(missing_result.reasons, ("retest_missing",))

        shallow = _long_kwargs()
        bars = list(shallow["retest_15m"])
        shallow["retest_15m"] = tuple(
            _candle(
                interval_minutes=bar.interval_minutes,
                closed_at=bar.closed_at,
                open=max(bar.open, 101.6),
                high=max(bar.high, 102.9),
                low=101.5,
                close=max(bar.close, 101.7),
                volume=bar.volume,
            )
            for bar in bars
        )
        shallow_result = evaluate_fomc_hybrid_signal(**shallow)
        self.assertEqual(shallow_result.state, "OBSERVE")
        self.assertIn("retest_not_deep_enough", shallow_result.reasons)

    def test_breakout_requires_volume_body_and_strong_close_location(self) -> None:
        cases: tuple[tuple[str, CompletedCandle, str], ...] = (
            (
                "volume",
                _candle(
                    interval_minutes=15,
                    closed_at=ANCHOR_CLOSE,
                    open=100.7,
                    high=103.0,
                    low=100.6,
                    close=102.9,
                    volume=149.99,
                ),
                "breakout_volume_not_confirmed",
            ),
            (
                "body",
                _candle(
                    interval_minutes=15,
                    closed_at=ANCHOR_CLOSE,
                    open=102.6,
                    high=103.0,
                    low=100.6,
                    close=102.9,
                    volume=160.0,
                ),
                "breakout_body_fraction_too_small",
            ),
            (
                "close_location",
                _candle(
                    interval_minutes=15,
                    closed_at=ANCHOR_CLOSE,
                    open=104.0,
                    high=104.0,
                    low=100.0,
                    close=101.5,
                    volume=160.0,
                ),
                "breakout_close_location_weak",
            ),
        )
        for label, breakout, expected_reason in cases:
            with self.subTest(label=label):
                kwargs = _long_kwargs()
                kwargs["breakout_15m"] = breakout

                result = evaluate_fomc_hybrid_signal(**kwargs)

                self.assertEqual(result.state, "OBSERVE")
                self.assertIn(expected_reason, result.reasons)

    def test_reclaim_requires_eighty_percent_of_breakout_volume(self) -> None:
        kwargs = _long_kwargs()
        bars = list(kwargs["retest_15m"])
        reclaim = bars[-1]
        bars[-1] = _candle(
            interval_minutes=15,
            closed_at=reclaim.closed_at,
            open=reclaim.open,
            high=reclaim.high,
            low=reclaim.low,
            close=reclaim.close,
            volume=127.99,
        )
        kwargs["retest_15m"] = tuple(bars)

        result = evaluate_fomc_hybrid_signal(**kwargs)

        self.assertEqual(result.state, "OBSERVE")
        self.assertIn("reclaim_volume_not_confirmed", result.reasons)

    def test_entry_must_remain_outside_and_within_quarter_atr(self) -> None:
        cases = (
            (100.99, "planned_entry_inside_breakout_line"),
            (102.01, "planned_entry_too_extended"),
        )
        for entry, expected_reason in cases:
            with self.subTest(entry=entry):
                kwargs = _long_kwargs()
                kwargs["planned_entry_price"] = entry

                result = evaluate_fomc_hybrid_signal(**kwargs)

                self.assertEqual(result.state, "OBSERVE")
                self.assertIn(expected_reason, result.reasons)

    def test_retest_expires_after_eight_completed_15m_bars(self) -> None:
        kwargs = _long_kwargs()
        bars = []
        for index in range(9):
            bars.append(
                _candle(
                    interval_minutes=15,
                    closed_at=ANCHOR_CLOSE + timedelta(minutes=15 * (index + 1)),
                    open=101.5,
                    high=102.8,
                    low=100.8,
                    close=102.7,
                    volume=128.0,
                )
            )
        kwargs["retest_15m"] = tuple(bars)
        kwargs["evaluated_at"] = bars[-1].closed_at + timedelta(minutes=1)

        result = evaluate_fomc_hybrid_signal(**kwargs)

        self.assertEqual(result.state, "NO_TRADE")
        self.assertEqual(result.reasons, ("retest_window_exceeded",))

    def test_new_entry_is_terminally_closed_after_noon_shanghai(self) -> None:
        kwargs = _long_kwargs()
        kwargs["evaluated_at"] = ENTRY_CUTOFF + timedelta(seconds=1)

        result = evaluate_fomc_hybrid_signal(**kwargs)

        self.assertEqual(result.state, "NO_TRADE")
        self.assertEqual(result.reasons, ("entry_window_closed",))

    def test_only_completed_ordered_bars_after_observation_are_accepted(self) -> None:
        cases: tuple[tuple[str, dict[str, object], str], ...] = ()

        before_observation = _long_kwargs()
        anchor = before_observation["anchor_1h"]
        before_observation["anchor_1h"] = _candle(
            interval_minutes=60,
            closed_at=OBSERVATION_START - timedelta(minutes=30),
            open=anchor.open,
            high=anchor.high,
            low=anchor.low,
            close=anchor.close,
            volume=anchor.volume,
        )
        cases += (("anchor", before_observation, "anchor_before_observation_window"),)

        future_bar = _long_kwargs()
        future_bar["evaluated_at"] = ANCHOR_CLOSE + timedelta(minutes=29)
        cases += (("future", future_bar, "signal_uses_uncompleted_candle"),)

        for label, kwargs, expected_reason in cases:
            with self.subTest(label=label):
                result = evaluate_fomc_hybrid_signal(**kwargs)
                self.assertEqual(result.state, "OBSERVE")
                self.assertIn(expected_reason, result.reasons)

    def test_malformed_candle_sequence_fails_closed_without_raising(self) -> None:
        kwargs = _long_kwargs()
        kwargs["anchor_1h"] = None
        kwargs["retest_15m"] = "not-candles"

        result = evaluate_fomc_hybrid_signal(**kwargs)

        self.assertEqual(result.state, "OBSERVE")
        self.assertIn("anchor_candle_invalid", result.reasons)
        self.assertIn("retest_sequence_invalid", result.reasons)


if __name__ == "__main__":
    unittest.main()
