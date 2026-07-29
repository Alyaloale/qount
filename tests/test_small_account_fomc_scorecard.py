from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from qount.contracts import canonical_hash
from qount.small_account.event_signal import CompletedCandle
from qount.small_account.fomc_adapter import FomcMarketObservation
from qount.small_account.fomc_adapter import build_fomc_standard_chain
from qount.small_account.fomc_runtime import FomcEventDefinition
from qount.small_account.fomc_runtime import FomcFreezeSnapshot
from qount.small_account.fomc_runtime import scan_fomc_hybrid_signal
from qount.small_account.fomc_scorecard import FomcShadowScorecardError
from qount.small_account.fomc_scorecard import build_fomc_v02_shadow_scorecard
from qount.small_account.fomc_scorecard import validate_fomc_v02_shadow_scorecard
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


def _candle(
    closed_at: datetime,
    *,
    open_price: float,
    high: float,
    low: float,
    close: float,
    volume: float,
) -> CompletedCandle:
    return CompletedCandle(
        interval_minutes=15,
        closed_at=closed_at,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


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
        # Retain a >=2R structural target under the conservative 6bp funding
        # reserve and 50bp stop-gap model.
        pivot_highs=(112.0,),
        pivot_lows=(80.0,),
        hourly_candle_count=720,
        fifteen_minute_candle_count=40,
        hourly_candle_hash="b" * 64,
        fifteen_minute_candle_hash="c" * 64,
        exchange_rules_hash="d" * 64,
        source_hashes={"market": "e" * 64},
    )


def _market() -> FomcMarketObservation:
    return FomcMarketObservation.create(
        symbol="BTCUSDT",
        observed_at="2026-07-29T23:31:00+00:00",
        data_cutoff="2026-07-29T23:30:00+00:00",
        last_price=101.95,
        bid_price=101.9,
        ask_price=102.0,
        mark_price=101.96,
        index_price=101.94,
        funding_rate=0.0001,
        price_tick=0.1,
        quantity_step=0.001,
        minimum_quantity=0.001,
        minimum_notional_usdt=5.0,
        exchange_rules_hash="d" * 64,
        source_hashes={
            "hourly_candles": "1" * 64,
            "fifteen_minute_candles": "2" * 64,
            "ticker": "3" * 64,
            "funding": "4" * 64,
            "exchange_rules": "d" * 64,
        },
    )


def _armed_result() -> tuple[dict[str, object], FomcFreezeSnapshot]:
    event = _event()
    freeze = _freeze()
    anchor_at = datetime(2026, 7, 29, 23, 0, tzinfo=UTC)
    hourly = (
        CompletedCandle(
            interval_minutes=60,
            closed_at=anchor_at,
            open=100.0,
            high=103.0,
            low=99.5,
            close=102.2,
            volume=500.0,
        ),
    )
    fifteen = (
        _candle(
            anchor_at,
            open_price=100.7,
            high=103.0,
            low=100.6,
            close=102.9,
            volume=160.0,
        ),
        _candle(
            anchor_at + timedelta(minutes=15),
            open_price=102.9,
            high=103.0,
            low=101.25,
            close=101.5,
            volume=70.0,
        ),
        _candle(
            anchor_at + timedelta(minutes=30),
            open_price=101.5,
            high=102.8,
            low=100.8,
            close=102.7,
            volume=128.0,
        ),
    )
    market = _market()
    scan = scan_fomc_hybrid_signal(
        event,
        freeze,
        hourly_candles=hourly,
        fifteen_minute_candles=fifteen,
        planned_entry_price=market.ask_price,
        evaluated_at=market.observed_at,
    )
    assert scan.armed
    chain = build_fomc_standard_chain(
        event,
        freeze,
        scan,
        market,
        account_snapshot=None,
        orders_authorized=False,
    )
    assert chain.sizing is not None and chain.sizing.allowed
    core: dict[str, object] = {
        "schema_version": 1,
        "artifact_type": "fomc_shadow_runtime",
        "event": event.as_dict(),
        "observed_at": market.observed_at,
        "stage": "ARMED",
        "freeze": freeze.as_dict(),
        "market": market.as_dict(),
        "signal": scan.as_dict(),
        "standard_chain": chain.as_dict(),
        "blockers": list(chain.blockers),
        "scorecard": None,
        "permissions": {
            "orders_authorized": False,
            "paper_or_live_allowed": False,
            "private_api_used": False,
            "private_api_order_attempted": False,
            "exchange_mutation_attempted": False,
        },
    }
    return core | {"result_hash": canonical_hash(core)}, freeze


def _outcome_candles(*, stop: bool = False) -> tuple[CompletedCandle, ...]:
    candles: list[CompletedCandle] = []
    closed_at = datetime(2026, 7, 29, 23, 45, tzinfo=UTC)
    final_at = _event().force_exit_time
    index = 0
    while closed_at <= final_at:
        if stop and index == 1:
            candles.append(
                _candle(
                    closed_at,
                    open_price=102.0,
                    high=102.5,
                    low=98.0,
                    close=99.0,
                    volume=120.0,
                )
            )
        else:
            candles.append(
                _candle(
                    closed_at,
                    open_price=102.0,
                    high=104.0,
                    low=101.0,
                    close=103.5 if closed_at != final_at else 104.0,
                    volume=120.0,
                )
            )
        closed_at += timedelta(minutes=15)
        index += 1
    return tuple(candles)


def _no_trade_scan_result(observed_at: str) -> dict[str, object]:
    event = _event()
    result, _ = _armed_result()
    observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    stage = "NO_TRADE" if observed >= event.entry_cutoff_time else "OBSERVE"
    signal_core: dict[str, object] = {
        "schema_version": result["signal"]["schema_version"],
        "event_id": event.event_id,
        "evaluated_at": observed.isoformat(),
        "state": stage,
        "side": "none",
        "reasons": ["entry_window_elapsed" if stage == "NO_TRADE" else "retest_missing"],
        "breakout_line": None,
        "retest_extreme": None,
        "structural_stop_price": None,
        "anchor_candle_id": None,
        "breakout_candle_id": None,
        "retest_candle_ids": [],
        "signal_available_at": None,
    }
    signal = signal_core | {"scan_hash": canonical_hash(signal_core)}
    core: dict[str, object] = {
        "schema_version": result["schema_version"],
        "artifact_type": result["artifact_type"],
        "event": result["event"],
        "observed_at": observed.isoformat(),
        "stage": stage,
        "freeze": result["freeze"],
        "market": result["market"],
        "signal": signal,
        "standard_chain": None,
        "blockers": [],
        "scorecard": None,
        "permissions": result["permissions"],
    }
    return core | {"result_hash": canonical_hash(core)}


class FomcShadowScorecardTest(unittest.TestCase):
    def test_force_exit_scorecard_records_cost_adjusted_mfe_mae_and_no_promotion(self) -> None:
        result, _ = _armed_result()
        scorecard = build_fomc_v02_shadow_scorecard(
            _event(),
            run_results=(result,),
            fifteen_minute_candles=_outcome_candles(),
            generated_at="2026-07-30T11:01:00+00:00",
        )

        validate_fomc_v02_shadow_scorecard(scorecard)
        self.assertEqual(scorecard["outcome"]["status"], "scored_frozen_v02_plan")
        self.assertEqual(scorecard["outcome"]["exit_reason"], "event_force_exit_mark")
        self.assertGreater(scorecard["outcome"]["mfe_net_r"], 0.0)
        self.assertLess(scorecard["outcome"]["mae_net_r"], 0.0)
        self.assertFalse(scorecard["permissions"]["orders_authorized"])
        self.assertFalse(scorecard["promotion"]["promotion_evidence"])

    def test_protective_stop_uses_frozen_stress_fill_not_optimistic_bar_close(self) -> None:
        result, _ = _armed_result()
        scorecard = build_fomc_v02_shadow_scorecard(
            _event(),
            run_results=(result,),
            fifteen_minute_candles=_outcome_candles(stop=True),
            generated_at="2026-07-30T11:01:00+00:00",
        )

        self.assertEqual(
            scorecard["outcome"]["exit_reason"], "protective_stop_stress_fill"
        )
        self.assertAlmostEqual(scorecard["outcome"]["final_net_r"], -1.0, places=9)
        self.assertLess(scorecard["outcome"]["exit_price"], 99.0)

    def test_tampered_immutable_result_cannot_be_scored(self) -> None:
        result, _ = _armed_result()
        result["stage"] = "NO_TRADE"
        with self.assertRaisesRegex(FomcShadowScorecardError, "run_result_hash_invalid"):
            build_fomc_v02_shadow_scorecard(
                _event(),
                run_results=(result,),
                fifteen_minute_candles=_outcome_candles(),
                generated_at="2026-07-30T11:01:00+00:00",
            )

    def test_no_trade_scorecard_requires_saved_entry_cutoff_scan_coverage(self) -> None:
        before_cutoff = _no_trade_scan_result("2026-07-30T03:55:00+00:00")
        with self.assertRaisesRegex(
            FomcShadowScorecardError, "entry_cutoff_coverage_missing"
        ):
            build_fomc_v02_shadow_scorecard(
                _event(),
                run_results=(before_cutoff,),
                fifteen_minute_candles=_outcome_candles(),
                generated_at="2026-07-30T11:01:00+00:00",
            )

        cutoff_coverage = _no_trade_scan_result("2026-07-30T04:00:01+00:00")
        scorecard = build_fomc_v02_shadow_scorecard(
            _event(),
            run_results=(before_cutoff, cutoff_coverage),
            fifteen_minute_candles=_outcome_candles(),
            generated_at="2026-07-30T11:01:00+00:00",
        )

        self.assertEqual(
            scorecard["outcome"]["status"], "no_eligible_v02_shadow_setup"
        )
        self.assertEqual(
            scorecard["source"]["entry_cutoff_coverage"]["result_hash"],
            cutoff_coverage["result_hash"],
        )
        self.assertEqual(scorecard["source"]["entry_cutoff_coverage_run_count"], 1)

    def test_state_store_rejects_scorecard_bound_to_another_event(self) -> None:
        result, _ = _armed_result()
        scorecard = build_fomc_v02_shadow_scorecard(
            _event(),
            run_results=(result,),
            fifteen_minute_candles=_outcome_candles(),
            generated_at="2026-07-30T11:01:00+00:00",
        )
        foreign_scorecard = dict(scorecard)
        foreign_scorecard["event_id"] = "f" * 64
        foreign_scorecard["scorecard_hash"] = canonical_hash(
            {
                key: value
                for key, value in foreign_scorecard.items()
                if key != "scorecard_hash"
            }
        )
        validate_fomc_v02_shadow_scorecard(foreign_scorecard)

        import tempfile

        with tempfile.TemporaryDirectory() as temporary:
            store = FomcStateStore(temporary, _event().event_id)
            with self.assertRaisesRegex(
                FomcWatcherError, "fomc_scorecard_store_event_mismatch"
            ):
                store.write_v02_scorecard(foreign_scorecard)

    def test_expired_watcher_writes_scorecard_once_from_public_market_data(self) -> None:
        result, freeze = _armed_result()
        with self.subTest("first finalization"):
            import tempfile

            with tempfile.TemporaryDirectory() as temporary:
                store = FomcStateStore(temporary, _event().event_id)
                store.write_freeze(freeze)
                store.write_result(result)
                with patch(
                    "qount.small_account.fomc_watcher.collect_fomc_public_market",
                    return_value=((), _outcome_candles(), _market()),
                ) as collect:
                    expired = run_fomc_shadow_cycle(
                        _event(),
                        store,
                        observed_at="2026-07-30T11:01:00+00:00",
                        exchange=object(),
                    )

                self.assertEqual(expired["stage"], "EXPIRED")
                self.assertEqual(expired["scorecard"]["status"], "completed")
                self.assertEqual(collect.call_count, 1)
                written = store.read_v02_scorecard()
                self.assertIsNotNone(written)
                self.assertEqual(
                    expired["scorecard"]["scorecard_hash"], written["scorecard_hash"]
                )
                self.assertEqual(store.v02_scorecard_path.stat().st_mode & 0o777, 0o600)

                repeated = run_fomc_shadow_cycle(
                    _event(),
                    store,
                    observed_at="2026-07-30T11:02:00+00:00",
                    exchange=object(),
                )
                self.assertEqual(repeated["scorecard"]["status"], "completed")
                self.assertEqual(collect.call_count, 1)

    def test_expired_watcher_retries_a_pending_public_scorecard(self) -> None:
        result, freeze = _armed_result()
        import tempfile

        with tempfile.TemporaryDirectory() as temporary:
            store = FomcStateStore(temporary, _event().event_id)
            store.write_freeze(freeze)
            store.write_result(result)
            with patch(
                "qount.small_account.fomc_watcher.collect_fomc_public_market",
                side_effect=(
                    FomcWatcherError("fomc_public_data_unavailable"),
                    ((), _outcome_candles(), _market()),
                ),
            ) as collect:
                first = run_fomc_shadow_cycle(
                    _event(),
                    store,
                    observed_at="2026-07-30T11:00:00+00:00",
                    exchange=object(),
                )
                self.assertEqual(first["scorecard"]["status"], "pending")
                self.assertIsNone(store.read_v02_scorecard())
                second = run_fomc_shadow_cycle(
                    _event(),
                    store,
                    observed_at="2026-07-30T11:05:00+00:00",
                    exchange=object(),
                )

            self.assertEqual(second["scorecard"]["status"], "completed")
            self.assertEqual(collect.call_count, 2)


if __name__ == "__main__":
    unittest.main()
