from __future__ import annotations

import stat
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from qount.notifications import NotificationStore
from qount.notifications import build_notification_snapshot
from qount.persistence import read_decision_batch
from qount.small_account.fomc_runtime import FomcEventDefinition
from qount.small_account.fomc_runtime import FomcFreezeSnapshot
from qount.small_account.fomc_watcher import FomcStateStore
from qount.small_account.fomc_watcher import FomcWatcherError
from qount.small_account.fomc_watcher import run_fomc_shadow_cycle


UTC = timezone.utc
FREEZE_AT = datetime(2026, 7, 29, 17, 30, tzinfo=UTC)


def _event() -> FomcEventDefinition:
    return FomcEventDefinition.create(
        event_name="FOMC-2026-07",
        instrument_key="binance|crypto|perpetual|BTCUSDT|USDT",
        symbol="BTCUSDT",
        source_url="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
        source_hash="a" * 64,
        cash_only_from="2026-07-29T17:00:00+00:00",
        freeze_at=FREEZE_AT.isoformat(),
        statement_at="2026-07-29T18:00:00+00:00",
        press_conference_at="2026-07-29T18:30:00+00:00",
        observation_starts_at="2026-07-29T22:30:00+00:00",
        entry_cutoff_at="2026-07-30T04:00:00+00:00",
        force_exit_at="2026-07-30T11:00:00+00:00",
    )


def _freeze(*, h0: float = 100.0) -> FomcFreezeSnapshot:
    event = _event()
    return FomcFreezeSnapshot.create(
        event_id=event.event_id,
        symbol=event.symbol,
        frozen_at=event.freeze_at,
        data_cutoff=event.freeze_at,
        h0=h0,
        l0=90.0,
        atr0=4.0,
        v20_1h=500.0,
        v20_15m=100.0,
        pivot_highs=(115.0,),
        pivot_lows=(75.0,),
        hourly_candle_count=720,
        fifteen_minute_candle_count=40,
        hourly_candle_hash="b" * 64,
        fifteen_minute_candle_hash="c" * 64,
        exchange_rules_hash="d" * 64,
        source_hashes={"market": "e" * 64},
    )


def _row(
    closed_at: datetime,
    *,
    interval_minutes: int,
    open_price: float,
    high: float,
    low: float,
    close: float,
    volume: float,
) -> list[float]:
    opened_at = closed_at - timedelta(minutes=interval_minutes)
    return [
        opened_at.timestamp() * 1_000.0,
        open_price,
        high,
        low,
        close,
        volume,
    ]


def _freeze_history() -> tuple[list[list[float]], list[list[float]]]:
    hourly: list[list[float]] = []
    last_hourly_close = FREEZE_AT.replace(minute=0)
    for index in range(720):
        closed_at = last_hourly_close - timedelta(hours=719 - index)
        center = 100.0 + ((index % 12) - 6) * 0.05
        hourly.append(
            _row(
                closed_at,
                interval_minutes=60,
                open_price=center - 0.1,
                high=center + 1.0 + (2.0 if index % 24 == 6 else 0.0),
                low=center - 1.0 - (2.0 if index % 24 == 18 else 0.0),
                close=center + 0.1,
                volume=500.0 + index % 20,
            )
        )
    fifteen: list[list[float]] = []
    for index in range(40):
        closed_at = FREEZE_AT - timedelta(minutes=15 * (39 - index))
        fifteen.append(
            _row(
                closed_at,
                interval_minutes=15,
                open_price=100.0,
                high=100.6,
                low=99.4,
                close=100.1,
                volume=100.0 + index % 5,
            )
        )
    return hourly, fifteen


def _armed_history() -> tuple[list[list[float]], list[list[float]]]:
    anchor_at = datetime(2026, 7, 29, 23, 0, tzinfo=UTC)
    hourly = [
        _row(
            anchor_at,
            interval_minutes=60,
            open_price=100.0,
            high=103.0,
            low=99.5,
            close=102.2,
            volume=500.0,
        )
    ]
    fifteen = [
        _row(
            anchor_at,
            interval_minutes=15,
            open_price=100.7,
            high=103.0,
            low=100.6,
            close=102.9,
            volume=160.0,
        ),
        _row(
            anchor_at + timedelta(minutes=15),
            interval_minutes=15,
            open_price=102.9,
            high=103.0,
            low=101.25,
            close=101.5,
            volume=70.0,
        ),
        _row(
            anchor_at + timedelta(minutes=30),
            interval_minutes=15,
            open_price=101.5,
            high=102.8,
            low=100.8,
            close=102.7,
            volume=128.0,
        ),
    ]
    return hourly, fifteen


class FakePublicExchange:
    def __init__(
        self,
        hourly: list[list[float]],
        fifteen: list[list[float]],
    ) -> None:
        self.hourly = hourly
        self.fifteen = fifteen
        self.calls: list[str] = []

    def load_markets(self):
        self.calls.append("load_markets")
        return {
            "BTC/USDT:USDT": {
                "id": "BTCUSDT",
                "symbol": "BTC/USDT:USDT",
                "linear": True,
                "swap": True,
                "settle": "USDT",
                "active": True,
                "contractSize": 1.0,
                "info": {
                    "filters": [
                        {
                            "filterType": "LOT_SIZE",
                            "stepSize": "0.001",
                            "minQty": "0.001",
                        },
                        {"filterType": "MIN_NOTIONAL", "notional": "5"},
                    ]
                },
            }
        }

    def fetch_ohlcv(self, symbol, *, timeframe, limit):
        self.calls.append(f"fetch_ohlcv:{symbol}:{timeframe}:{limit}")
        return self.hourly if timeframe == "1h" else self.fifteen

    def fetch_ticker(self, symbol):
        self.calls.append(f"fetch_ticker:{symbol}")
        return {"last": 101.95, "bid": 101.9, "ask": 102.0}

    def fetch_funding_rate(self, symbol):
        self.calls.append(f"fetch_funding_rate:{symbol}")
        return {
            "markPrice": 101.96,
            "indexPrice": 101.94,
            "fundingRate": 0.0001,
        }


class FomcWatcherTest(unittest.TestCase):
    def test_scheduled_cycle_never_touches_the_exchange(self) -> None:
        class NoNetwork:
            def __getattr__(self, name):
                raise AssertionError(f"unexpected exchange access: {name}")

        with tempfile.TemporaryDirectory() as temporary:
            store = FomcStateStore(temporary, _event().event_id)
            result = run_fomc_shadow_cycle(
                _event(),
                store,
                observed_at="2026-07-29T17:00:00+00:00",
                exchange=NoNetwork(),
            )

            self.assertEqual(result["stage"], "SCHEDULED")
            self.assertIsNone(result["market"])
            self.assertFalse(result["permissions"]["private_api_used"])
            self.assertFalse(result["permissions"]["exchange_mutation_attempted"])
            self.assertTrue(store.latest_path.is_file())

    def test_freeze_is_owner_only_and_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = FomcStateStore(temporary, _event().event_id)
            written = store.write_freeze(_freeze())

            self.assertEqual(store.write_freeze(_freeze()), written)
            self.assertEqual(
                stat.S_IMODE(store.freeze_path.stat().st_mode),
                0o600,
            )
            self.assertEqual(
                stat.S_IMODE(store.event_root.stat().st_mode),
                0o700,
            )
            with self.assertRaisesRegex(
                FomcWatcherError, "fomc_freeze_immutable_conflict"
            ):
                store.write_freeze(_freeze(h0=101.0))

    def test_state_store_rejects_non_hash_event_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(FomcWatcherError, "fomc_event_id_invalid"):
                FomcStateStore(temporary, "../outside")

    def test_blackout_builds_freeze_but_no_decision_batch(self) -> None:
        hourly, fifteen = _freeze_history()
        exchange = FakePublicExchange(hourly, fifteen)
        with tempfile.TemporaryDirectory() as temporary:
            store = FomcStateStore(temporary, _event().event_id)
            result = run_fomc_shadow_cycle(
                _event(),
                store,
                observed_at="2026-07-29T19:00:00+00:00",
                exchange=exchange,
            )

            self.assertEqual(result["stage"], "BLACKOUT")
            self.assertIsNotNone(result["freeze"])
            self.assertIsNone(result["signal"])
            self.assertIsNone(result["standard_chain"])
            self.assertEqual(tuple(store.batches_root.iterdir()), ())
            self.assertEqual(store.read_freeze().hourly_candle_count, 720)
            self.assertEqual(len(exchange.calls), 5)

    def test_armed_cycle_publishes_non_executable_standard_batch_and_alert(self) -> None:
        hourly, fifteen = _armed_history()
        exchange = FakePublicExchange(hourly, fifteen)
        observed_at = "2026-07-29T23:31:00+00:00"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = FomcStateStore(root / "fomc", _event().event_id)
            store.write_freeze(_freeze())
            notifications = NotificationStore(root / "notifications" / "store.sqlite3")
            result = run_fomc_shadow_cycle(
                _event(),
                store,
                observed_at=observed_at,
                exchange=exchange,
                notification_store=notifications,
            )

            self.assertEqual(result["stage"], "ARMED")
            self.assertEqual(result["signal"]["side"], "long")
            self.assertFalse(result["standard_chain"]["standard_chain"]["plan_executable"])
            self.assertEqual(
                result["blockers"],
                [
                    "FOMC_ACCOUNT_SNAPSHOT_NOT_LINKED",
                    "FOMC_MANUAL_ARM_REQUIRED",
                ],
            )
            batches = tuple(store.batches_root.iterdir())
            self.assertEqual(len(batches), 1)
            batch = read_decision_batch(batches[0])
            self.assertFalse(batch.plan.executable)
            self.assertFalse(batch.manifest.orders_authorized)
            self.assertEqual(len(batch.plan.orders), 2)
            snapshot = build_notification_snapshot(
                notifications,
                captured_at=observed_at,
            )
            self.assertEqual(snapshot.open_alert_count, 1)
            self.assertEqual(snapshot.alerts[0]["source_type"], "event_strategy")
            self.assertIn("planned notional=", snapshot.alerts[0]["summary"])
            self.assertFalse(result["permissions"]["paper_or_live_allowed"])
            self.assertFalse(result["permissions"]["private_api_order_attempted"])

    def test_insufficient_freeze_history_halts_and_persists_blocker(self) -> None:
        hourly, fifteen = _freeze_history()
        exchange = FakePublicExchange(hourly[-10:], fifteen[-10:])
        with tempfile.TemporaryDirectory() as temporary:
            store = FomcStateStore(temporary, _event().event_id)
            result = run_fomc_shadow_cycle(
                _event(),
                store,
                observed_at="2026-07-29T19:00:00+00:00",
                exchange=exchange,
            )

            self.assertEqual(result["stage"], "HALTED")
            self.assertTrue(
                any(
                    "FREEZE_HOURLY_HISTORY_INSUFFICIENT" in blocker
                    for blocker in result["blockers"]
                )
            )
            self.assertEqual(store.read_freeze(), None)
            self.assertEqual(store.latest_path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
