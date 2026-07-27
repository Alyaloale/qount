from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from qount.small_account.event_signal import CompletedCandle
from qount.small_account.range_signal import DEFAULT_RANGE_FADE_POLICY
from qount.small_account.range_signal import RANGE_CONTRACT_VERSION
from qount.small_account.range_signal import RangeFadePolicy
from qount.small_account.range_signal import evaluate_range_fade_signal


TRIGGER_CLOSE = datetime(2026, 7, 28, 10, 0, tzinfo=timezone.utc)
CASH_CUTOFF = datetime(2026, 7, 29, 17, 0, tzinfo=timezone.utc)


def _candle(
    *,
    closed_at: datetime,
    open: float,
    high: float,
    low: float,
    close: float,
    volume: float,
    interval_minutes: int = 15,
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
        "h0": 62000.0,
        "l0": 60000.0,
        "atr0": 400.0,
        "v20_15m": 100.0,
        "recent_15m": (
            _candle(
                closed_at=TRIGGER_CLOSE - timedelta(minutes=15),
                open=60300.0,
                high=60350.0,
                low=60120.0,
                close=60150.0,
                volume=90.0,
            ),
            _candle(
                closed_at=TRIGGER_CLOSE,
                open=60140.0,
                high=60200.0,
                low=60050.0,
                close=60180.0,
                volume=120.0,
            ),
        ),
        "planned_entry_price": 60180.0,
        "cash_cutoff_at": CASH_CUTOFF,
        "evaluated_at": TRIGGER_CLOSE + timedelta(minutes=1),
    }


def _short_kwargs() -> dict[str, object]:
    return {
        "side": "short",
        "h0": 62000.0,
        "l0": 60000.0,
        "atr0": 400.0,
        "v20_15m": 100.0,
        "recent_15m": (
            _candle(
                closed_at=TRIGGER_CLOSE - timedelta(minutes=15),
                open=61700.0,
                high=61880.0,
                low=61650.0,
                close=61850.0,
                volume=90.0,
            ),
            _candle(
                closed_at=TRIGGER_CLOSE,
                open=61860.0,
                high=61950.0,
                low=61700.0,
                close=61760.0,
                volume=130.0,
            ),
        ),
        "planned_entry_price": 61760.0,
        "cash_cutoff_at": CASH_CUTOFF,
        "evaluated_at": TRIGGER_CLOSE + timedelta(minutes=1),
    }


class RangeFadePolicyTest(unittest.TestCase):
    def test_default_policy_is_valid(self) -> None:
        self.assertEqual(DEFAULT_RANGE_FADE_POLICY.validate(), ())

    def test_stop_buffer_must_exceed_break_buffer(self) -> None:
        policy = RangeFadePolicy(break_buffer_atr=0.4, stop_buffer_atr=0.3)
        self.assertIn(
            "policy_stop_buffer_not_beyond_break_buffer", policy.validate()
        )


class RangeFadeSignalTest(unittest.TestCase):
    def test_long_fade_armed(self) -> None:
        decision = evaluate_range_fade_signal(**_long_kwargs())
        self.assertEqual(decision.state, "ARMED")
        self.assertEqual(decision.reasons, ())
        self.assertEqual(decision.contract_version, RANGE_CONTRACT_VERSION)
        self.assertAlmostEqual(decision.entry_zone_line, 60100.0)
        self.assertAlmostEqual(decision.break_line, 59900.0)
        self.assertAlmostEqual(decision.structural_stop_price, 59860.0)
        self.assertAlmostEqual(decision.target_price, 61000.0)

    def test_short_fade_armed(self) -> None:
        decision = evaluate_range_fade_signal(**_short_kwargs())
        self.assertEqual(decision.state, "ARMED")
        self.assertEqual(decision.reasons, ())
        self.assertAlmostEqual(decision.entry_zone_line, 61900.0)
        self.assertAlmostEqual(decision.break_line, 62100.0)
        self.assertAlmostEqual(decision.structural_stop_price, 62140.0)
        self.assertAlmostEqual(decision.target_price, 61000.0)

    def test_range_break_blocks_both_sides(self) -> None:
        kwargs = _long_kwargs()
        kwargs["recent_15m"] = (
            _candle(
                closed_at=TRIGGER_CLOSE - timedelta(minutes=15),
                open=60000.0,
                high=60050.0,
                low=59700.0,
                close=59800.0,
                volume=200.0,
            ),
        ) + tuple(kwargs["recent_15m"])[1:]
        decision = evaluate_range_fade_signal(**kwargs)
        self.assertEqual(decision.state, "NO_TRADE")
        self.assertIn("range_broken", decision.reasons)

    def test_range_too_narrow_is_no_trade(self) -> None:
        kwargs = _long_kwargs()
        kwargs["atr0"] = 800.0
        decision = evaluate_range_fade_signal(**kwargs)
        self.assertEqual(decision.state, "NO_TRADE")
        self.assertIn("range_too_narrow", decision.reasons)

    def test_cash_deadline_blocks_new_entries(self) -> None:
        kwargs = _long_kwargs()
        kwargs["evaluated_at"] = CASH_CUTOFF - timedelta(minutes=10)
        kwargs["recent_15m"] = tuple(kwargs["recent_15m"])
        decision = evaluate_range_fade_signal(**kwargs)
        self.assertEqual(decision.state, "NO_TRADE")
        self.assertIn("cash_deadline_reached", decision.reasons)

    def test_weak_close_location_blocks(self) -> None:
        kwargs = _long_kwargs()
        kwargs["recent_15m"] = tuple(kwargs["recent_15m"])[:-1] + (
            _candle(
                closed_at=TRIGGER_CLOSE,
                open=60250.0,
                high=60300.0,
                low=60050.0,
                close=60120.0,
                volume=120.0,
            ),
        )
        kwargs["planned_entry_price"] = 60120.0
        decision = evaluate_range_fade_signal(**kwargs)
        self.assertEqual(decision.state, "OBSERVE")
        self.assertIn("trigger_close_location_weak", decision.reasons)

    def test_low_volume_blocks(self) -> None:
        kwargs = _long_kwargs()
        kwargs["recent_15m"] = tuple(kwargs["recent_15m"])[:-1] + (
            _candle(
                closed_at=TRIGGER_CLOSE,
                open=60140.0,
                high=60200.0,
                low=60050.0,
                close=60180.0,
                volume=50.0,
            ),
        )
        decision = evaluate_range_fade_signal(**kwargs)
        self.assertEqual(decision.state, "OBSERVE")
        self.assertIn("trigger_volume_not_confirmed", decision.reasons)

    def test_no_zone_touch_blocks(self) -> None:
        kwargs = _long_kwargs()
        kwargs["recent_15m"] = tuple(kwargs["recent_15m"])[:-1] + (
            _candle(
                closed_at=TRIGGER_CLOSE,
                open=60400.0,
                high=60500.0,
                low=60250.0,
                close=60450.0,
                volume=120.0,
            ),
        )
        kwargs["planned_entry_price"] = 60450.0
        decision = evaluate_range_fade_signal(**kwargs)
        self.assertEqual(decision.state, "OBSERVE")
        self.assertIn("trigger_did_not_touch_entry_zone", decision.reasons)

    def test_entry_too_far_from_trigger_close_blocks(self) -> None:
        kwargs = _long_kwargs()
        kwargs["planned_entry_price"] = 60300.0
        decision = evaluate_range_fade_signal(**kwargs)
        self.assertEqual(decision.state, "OBSERVE")
        self.assertIn(
            "planned_entry_too_far_from_trigger_close", decision.reasons
        )

    def test_entry_outside_fade_zone_blocks(self) -> None:
        kwargs = _short_kwargs()
        kwargs["planned_entry_price"] = 60900.0
        decision = evaluate_range_fade_signal(**kwargs)
        self.assertEqual(decision.state, "OBSERVE")
        self.assertIn("planned_entry_outside_fade_zone", decision.reasons)

    def test_naive_datetime_blocks(self) -> None:
        kwargs = _long_kwargs()
        kwargs["evaluated_at"] = datetime(2026, 7, 28, 10, 1)
        decision = evaluate_range_fade_signal(**kwargs)
        self.assertEqual(decision.state, "OBSERVE")
        self.assertIn("evaluated_at_not_timezone_aware", decision.reasons)

    def test_invalid_side_blocks(self) -> None:
        kwargs = _long_kwargs()
        kwargs["side"] = "both"
        decision = evaluate_range_fade_signal(**kwargs)
        self.assertEqual(decision.state, "OBSERVE")
        self.assertIn("side_invalid", decision.reasons)

    def test_uncompleted_candle_blocks(self) -> None:
        kwargs = _long_kwargs()
        kwargs["evaluated_at"] = TRIGGER_CLOSE - timedelta(minutes=1)
        decision = evaluate_range_fade_signal(**kwargs)
        self.assertEqual(decision.state, "OBSERVE")
        self.assertIn("signal_uses_uncompleted_candle", decision.reasons)


if __name__ == "__main__":
    unittest.main()
