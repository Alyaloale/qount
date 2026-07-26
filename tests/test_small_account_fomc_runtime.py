from __future__ import annotations

import math
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from qount.contracts import canonical_hash
from qount.small_account import CompletedCandle
from qount.small_account import FomcEventDefinition
from qount.small_account import FomcFreezeSnapshot
from qount.small_account import FomcRuntimeError
from qount.small_account import build_fomc_freeze_snapshot
from qount.small_account import fomc_stage
from qount.small_account import frozen_structure_target
from qount.small_account import scan_fomc_hybrid_signal


UTC = timezone.utc
FREEZE_AT = datetime(2026, 7, 29, 17, 30, tzinfo=UTC)
OBSERVATION_AT = datetime(2026, 7, 29, 22, 30, tzinfo=UTC)


def _event() -> FomcEventDefinition:
    return FomcEventDefinition.create(
        event_name="FOMC-2026-07",
        instrument_key="binance|crypto|perpetual|BTCUSDT|USDT",
        symbol="BTCUSDT",
        source_url="https://www.federalreserve.gov/newsevents/2026-july.htm",
        source_hash="a" * 64,
        cash_only_from="2026-07-29T17:00:00+00:00",
        freeze_at=FREEZE_AT.isoformat(),
        statement_at="2026-07-29T18:00:00+00:00",
        press_conference_at="2026-07-29T18:30:00+00:00",
        observation_starts_at=OBSERVATION_AT.isoformat(),
        entry_cutoff_at="2026-07-30T04:00:00+00:00",
        force_exit_at="2026-07-30T11:00:00+00:00",
    )


def _candle(
    *,
    interval: int,
    closed_at: datetime,
    open: float,
    high: float,
    low: float,
    close: float,
    volume: float,
) -> CompletedCandle:
    return CompletedCandle(
        interval_minutes=interval,
        closed_at=closed_at,
        open=open,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def _history() -> tuple[tuple[CompletedCandle, ...], tuple[CompletedCandle, ...]]:
    hourly = []
    first_close = FREEZE_AT - timedelta(minutes=30, hours=719)
    for index in range(720):
        center = 95.0 + 3.0 * math.sin(index / 7.0)
        hourly.append(
            _candle(
                interval=60,
                closed_at=first_close + timedelta(hours=index),
                open=center - 0.2,
                high=center + 1.0,
                low=center - 1.0,
                close=center + 0.2,
                volume=100.0 + index % 20,
            )
        )
    fifteen = []
    first_fifteen_close = FREEZE_AT - timedelta(minutes=15 * 39)
    for index in range(40):
        center = 96.0 + math.sin(index / 4.0)
        fifteen.append(
            _candle(
                interval=15,
                closed_at=first_fifteen_close + timedelta(minutes=15 * index),
                open=center - 0.1,
                high=center + 0.5,
                low=center - 0.5,
                close=center + 0.1,
                volume=80.0 + index,
            )
        )
    return tuple(hourly), tuple(fifteen)


def _freeze() -> FomcFreezeSnapshot:
    event = _event()
    return FomcFreezeSnapshot.create(
        event_id=event.event_id,
        symbol=event.symbol,
        frozen_at=event.freeze_at,
        data_cutoff=event.freeze_at,
        h0=100.0,
        l0=90.0,
        atr0=4.0,
        v20_1h=500.0,
        v20_15m=100.0,
        pivot_highs=(105.0, 110.0),
        pivot_lows=(80.0, 85.0),
        hourly_candle_count=720,
        fifteen_minute_candle_count=40,
        hourly_candle_hash="b" * 64,
        fifteen_minute_candle_hash="c" * 64,
        exchange_rules_hash="d" * 64,
        source_hashes={"market": "e" * 64},
    )


def _long_signal_candles() -> tuple[tuple[CompletedCandle, ...], tuple[CompletedCandle, ...]]:
    anchor_time = datetime(2026, 7, 29, 23, 0, tzinfo=UTC)
    hourly = (
        _candle(
            interval=60,
            closed_at=anchor_time,
            open=100.0,
            high=103.0,
            low=99.5,
            close=102.2,
            volume=500.0,
        ),
    )
    fifteen = (
        _candle(
            interval=15,
            closed_at=anchor_time,
            open=100.7,
            high=103.0,
            low=100.6,
            close=102.9,
            volume=160.0,
        ),
        _candle(
            interval=15,
            closed_at=anchor_time + timedelta(minutes=15),
            open=102.9,
            high=103.0,
            low=101.25,
            close=101.5,
            volume=70.0,
        ),
        _candle(
            interval=15,
            closed_at=anchor_time + timedelta(minutes=30),
            open=101.5,
            high=102.8,
            low=100.8,
            close=102.7,
            volume=128.0,
        ),
    )
    return hourly, fifteen


class FomcFreezeRuntimeTest(unittest.TestCase):
    def test_event_definition_is_hashed_and_clock_ordered(self) -> None:
        event = _event()
        self.assertEqual(event.validate(), ())
        self.assertEqual(FomcEventDefinition.from_mapping(event.as_dict()), event)
        invalid_clock = {
            key: value
            for key, value in event.as_dict().items()
            if key
            not in {
                "schema_version",
                "event_id",
                "definition_hash",
                "strategy_id",
                "strategy_version",
            }
        }
        invalid_clock["entry_cutoff_at"] = "2026-07-29T21:00:00+00:00"
        with self.assertRaisesRegex(FomcRuntimeError, "event_clock_order_invalid"):
            FomcEventDefinition.create(**invalid_clock)

    def test_freeze_uses_only_completed_pre_event_bars(self) -> None:
        event = _event()
        hourly, fifteen = _history()
        future = _candle(
            interval=60,
            closed_at=FREEZE_AT + timedelta(minutes=30),
            open=1.0,
            high=1_000.0,
            low=1.0,
            close=900.0,
            volume=9_999.0,
        )
        snapshot = build_fomc_freeze_snapshot(
            event,
            hourly_candles=hourly + (future,),
            fifteen_minute_candles=fifteen,
            exchange_rules_hash="f" * 64,
            source_hashes={"binance": "1" * 64},
        )

        self.assertEqual(snapshot.validate(), ())
        self.assertEqual(snapshot.hourly_candle_count, 720)
        self.assertLess(snapshot.h0, 1_000.0)
        self.assertGreater(snapshot.atr0, 0.0)
        self.assertTrue(snapshot.pivot_highs)
        self.assertTrue(snapshot.pivot_lows)
        self.assertEqual(
            FomcFreezeSnapshot.from_mapping(snapshot.as_dict()), snapshot
        )

    def test_freeze_rejects_missing_history_and_tampering(self) -> None:
        event = _event()
        hourly, fifteen = _history()
        with self.assertRaisesRegex(FomcRuntimeError, "history_insufficient"):
            build_fomc_freeze_snapshot(
                event,
                hourly_candles=hourly[-100:],
                fifteen_minute_candles=fifteen,
                exchange_rules_hash="f" * 64,
                source_hashes={"binance": "1" * 64},
            )
        self.assertIn(
            "freeze_hash_invalid",
            replace(_freeze(), h0=101.0).validate(),
        )

    def test_frozen_structure_target_never_uses_post_event_drawing(self) -> None:
        freeze = _freeze()
        self.assertEqual(
            frozen_structure_target(freeze, side="long", entry_price=102.0),
            105.0,
        )
        self.assertEqual(
            frozen_structure_target(freeze, side="short", entry_price=88.0),
            85.0,
        )
        self.assertIsNone(
            frozen_structure_target(freeze, side="long", entry_price=111.0)
        )


class FomcSignalScannerTest(unittest.TestCase):
    def test_completed_long_sequence_arms_and_keeps_lineage(self) -> None:
        hourly, fifteen = _long_signal_candles()
        scan = scan_fomc_hybrid_signal(
            _event(),
            _freeze(),
            hourly_candles=hourly,
            fifteen_minute_candles=fifteen,
            planned_entry_price=102.0,
            evaluated_at="2026-07-29T23:31:00+00:00",
        )

        self.assertTrue(scan.armed)
        self.assertEqual(scan.side, "long")
        self.assertEqual(scan.breakout_line, 101.0)
        self.assertEqual(len(scan.retest_candle_ids), 2)
        self.assertEqual(len(scan.scan_hash), 64)

    def test_first_anchor_locks_direction_and_prevents_reversal_selection(self) -> None:
        long_hourly, _ = _long_signal_candles()
        short_anchor_time = datetime(2026, 7, 30, 0, 0, tzinfo=UTC)
        short_anchor = _candle(
            interval=60,
            closed_at=short_anchor_time,
            open=100.0,
            high=100.5,
            low=97.0,
            close=97.8,
            volume=500.0,
        )
        short_bars = (
            _candle(
                interval=15,
                closed_at=short_anchor_time,
                open=99.3,
                high=99.4,
                low=97.0,
                close=97.1,
                volume=160.0,
            ),
            _candle(
                interval=15,
                closed_at=short_anchor_time + timedelta(minutes=15),
                open=97.1,
                high=98.75,
                low=97.0,
                close=98.5,
                volume=70.0,
            ),
            _candle(
                interval=15,
                closed_at=short_anchor_time + timedelta(minutes=30),
                open=98.5,
                high=99.2,
                low=97.2,
                close=97.3,
                volume=128.0,
            ),
        )
        scan = scan_fomc_hybrid_signal(
            _event(),
            _freeze(),
            hourly_candles=long_hourly + (short_anchor,),
            fifteen_minute_candles=short_bars,
            planned_entry_price=98.0,
            evaluated_at="2026-07-30T00:31:00+00:00",
        )

        self.assertEqual(scan.state, "OBSERVE")
        self.assertEqual(scan.side, "long")
        self.assertEqual(scan.reasons, ("qualified_breakout_missing",))

    def test_deep_retest_is_terminal_no_trade(self) -> None:
        hourly, fifteen = _long_signal_candles()
        bad = replace(fifteen[-1], low=99.9)
        scan = scan_fomc_hybrid_signal(
            _event(),
            _freeze(),
            hourly_candles=hourly,
            fifteen_minute_candles=fifteen[:-1] + (bad,),
            planned_entry_price=102.0,
            evaluated_at="2026-07-29T23:31:00+00:00",
        )

        self.assertEqual(scan.state, "NO_TRADE")
        self.assertEqual(
            scan.reasons, ("retest_returned_to_original_range",)
        )

    def test_stage_clock_fails_closed_around_event_boundaries(self) -> None:
        event = _event()
        self.assertEqual(
            fomc_stage(
                event,
                evaluated_at="2026-07-29T16:00:00+00:00",
                freeze_available=False,
            ),
            "SCHEDULED",
        )
        self.assertEqual(
            fomc_stage(
                event,
                evaluated_at="2026-07-29T17:31:00+00:00",
                freeze_available=False,
            ),
            "FREEZE_REQUIRED",
        )
        self.assertEqual(
            fomc_stage(
                event,
                evaluated_at="2026-07-29T19:00:00+00:00",
                freeze_available=True,
            ),
            "BLACKOUT",
        )
        self.assertEqual(
            fomc_stage(
                event,
                evaluated_at="2026-07-30T04:00:01+00:00",
                freeze_available=True,
            ),
            "NO_TRADE",
        )
        self.assertEqual(
            fomc_stage(
                event,
                evaluated_at="2026-07-30T11:00:00+00:00",
                freeze_available=True,
            ),
            "EXPIRED",
        )


if __name__ == "__main__":
    unittest.main()
