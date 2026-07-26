from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from qount.contracts import validate_decision_batch
from qount.small_account import AccountRiskSnapshot
from qount.small_account import CompletedCandle
from qount.small_account import FomcEventDefinition
from qount.small_account import FomcFreezeSnapshot
from qount.small_account import FomcMarketObservation
from qount.small_account import FomcSignalDecision
from qount.small_account import FomcSignalScan
from qount.small_account import build_fomc_standard_chain


UTC = timezone.utc
ANCHOR_AT = datetime(2026, 7, 29, 23, 0, tzinfo=UTC)


def _event() -> FomcEventDefinition:
    return FomcEventDefinition.create(
        event_name="FOMC-2026-07",
        instrument_key="binance|crypto|perpetual|BTCUSDT|USDT",
        symbol="BTCUSDT",
        source_url="https://www.federalreserve.gov/newsevents/2026-july.htm",
        source_hash="a" * 64,
        cash_only_from="2026-07-29T17:00:00+00:00",
        freeze_at="2026-07-29T17:30:00+00:00",
        statement_at="2026-07-29T18:00:00+00:00",
        press_conference_at="2026-07-29T18:30:00+00:00",
        observation_starts_at="2026-07-29T22:30:00+00:00",
        entry_cutoff_at="2026-07-30T04:00:00+00:00",
        force_exit_at="2026-07-30T11:00:00+00:00",
    )


def _freeze(*, long_target: bool = True) -> FomcFreezeSnapshot:
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
        pivot_highs=(115.0,) if long_target else (101.0,),
        pivot_lows=(75.0,),
        hourly_candle_count=720,
        fifteen_minute_candle_count=40,
        hourly_candle_hash="b" * 64,
        fifteen_minute_candle_hash="c" * 64,
        exchange_rules_hash="d" * 64,
        source_hashes={"market": "e" * 64},
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


def _scan(side: str) -> FomcSignalScan:
    if side == "long":
        decision = FomcSignalDecision(
            contract_version="SmallAccount-FOMC-RightSide-v0.2",
            state="ARMED",
            side="long",
            reasons=(),
            breakout_line=101.0,
            retest_extreme=100.0,
            structural_stop_price=98.0,
        )
        anchor = _candle(
            interval=60,
            closed_at=ANCHOR_AT,
            open=100.0,
            high=103.0,
            low=99.5,
            close=102.2,
            volume=500.0,
        )
        breakout = _candle(
            interval=15,
            closed_at=ANCHOR_AT,
            open=100.7,
            high=103.0,
            low=100.6,
            close=102.9,
            volume=160.0,
        )
        retest = (
            _candle(
                interval=15,
                closed_at=ANCHOR_AT + timedelta(minutes=15),
                open=102.0,
                high=103.0,
                low=100.0,
                close=102.7,
                volume=128.0,
            ),
        )
    else:
        decision = FomcSignalDecision(
            contract_version="SmallAccount-FOMC-RightSide-v0.2",
            state="ARMED",
            side="short",
            reasons=(),
            breakout_line=89.0,
            retest_extreme=90.0,
            structural_stop_price=92.0,
        )
        anchor = _candle(
            interval=60,
            closed_at=ANCHOR_AT,
            open=90.0,
            high=90.5,
            low=87.0,
            close=87.8,
            volume=500.0,
        )
        breakout = _candle(
            interval=15,
            closed_at=ANCHOR_AT,
            open=89.3,
            high=89.4,
            low=87.0,
            close=87.1,
            volume=160.0,
        )
        retest = (
            _candle(
                interval=15,
                closed_at=ANCHOR_AT + timedelta(minutes=15),
                open=88.0,
                high=90.0,
                low=87.0,
                close=87.3,
                volume=128.0,
            ),
        )
    return FomcSignalScan.create(
        event_id=_event().event_id,
        evaluated_at="2026-07-29T23:16:00+00:00",
        decision=decision,
        anchor=anchor,
        breakout=breakout,
        retest=retest,
    )


def _market(
    *, side: str = "long", minimum_quantity: float = 0.001
) -> FomcMarketObservation:
    if side == "long":
        last, bid, ask, mark, index = 101.95, 101.9, 102.0, 101.96, 101.94
    else:
        last, bid, ask, mark, index = 88.05, 88.0, 88.1, 88.04, 88.02
    return FomcMarketObservation.create(
        symbol="BTCUSDT",
        observed_at="2026-07-29T23:16:00+00:00",
        data_cutoff="2026-07-29T23:15:00+00:00",
        last_price=last,
        bid_price=bid,
        ask_price=ask,
        mark_price=mark,
        index_price=index,
        funding_rate=0.0001,
        quantity_step=0.001,
        minimum_quantity=minimum_quantity,
        minimum_notional_usdt=5.0,
        exchange_rules_hash="f" * 64,
        source_hashes={"ticker": "1" * 64, "funding": "2" * 64},
    )


def _healthy_account() -> AccountRiskSnapshot:
    return AccountRiskSnapshot(
        net_liquidation_equity_usdt=200.0,
        high_water_equity_usdt=200.0,
        day_start_equity_usdt=200.0,
        rolling_24h_start_equity_usdt=200.0,
        protective_cycle_verified=False,
    )


class FomcStandardAdapterTest(unittest.TestCase):
    def test_long_arms_signed_intent_and_native_protective_plan(self) -> None:
        chain = build_fomc_standard_chain(
            _event(), _freeze(), _scan("long"), _market()
        )
        batch = chain.batch

        self.assertGreater(batch.intents[0].target_weights[_event().instrument_key], 0.0)
        self.assertTrue(batch.risk.approved)
        self.assertEqual(
            [(order.side, order.phase, order.order_type) for order in batch.plan.orders],
            [
                ("buy", "increase", "MARKET"),
                ("sell", "protective", "STOP_MARKET"),
            ],
        )
        self.assertTrue(batch.plan.orders[1].close_position)
        self.assertTrue(batch.plan.orders[1].reduce_only)
        self.assertFalse(batch.plan.executable)
        self.assertEqual(
            batch.plan.blockers,
            (
                "FOMC_ACCOUNT_SNAPSHOT_NOT_LINKED",
                "FOMC_MANUAL_ARM_REQUIRED",
            ),
        )
        self.assertFalse(batch.manifest.orders_authorized)
        self.assertEqual(
            validate_decision_batch(
                batch.snapshot,
                batch.intents,
                batch.target,
                batch.risk,
                batch.plan,
            ),
            (),
        )

    def test_short_is_signed_and_protection_buys_to_close(self) -> None:
        chain = build_fomc_standard_chain(
            _event(), _freeze(), _scan("short"), _market(side="short")
        )
        weight = chain.batch.intents[0].target_weights[_event().instrument_key]

        self.assertLess(weight, 0.0)
        self.assertEqual(chain.batch.plan.orders[0].side, "sell")
        self.assertEqual(chain.batch.plan.orders[1].side, "buy")
        self.assertLess(
            chain.batch.plan.expected_positions[_event().instrument_key], 0.0
        )

    def test_linked_healthy_account_and_explicit_arm_make_plan_executable(self) -> None:
        chain = build_fomc_standard_chain(
            _event(),
            _freeze(),
            _scan("long"),
            _market(),
            account_snapshot=_healthy_account(),
            orders_authorized=True,
        )

        self.assertTrue(chain.account_snapshot_linked)
        self.assertTrue(chain.batch.plan.executable)
        self.assertEqual(chain.blockers, ())
        self.assertFalse(chain.batch.manifest.orders_authorized)

    def test_unknown_account_blocks_new_risk_and_all_orders(self) -> None:
        account = AccountRiskSnapshot(
            **{
                **_healthy_account().__dict__,
                "has_unknown_state": True,
            }
        )
        chain = build_fomc_standard_chain(
            _event(),
            _freeze(),
            _scan("long"),
            _market(),
            account_snapshot=account,
            orders_authorized=True,
        )

        self.assertFalse(chain.account_guard.allow_new_risk)
        self.assertEqual(chain.batch.plan.orders, ())
        self.assertFalse(chain.batch.plan.executable)
        self.assertTrue(
            any("UNKNOWN" in blocker for blocker in chain.batch.plan.blockers)
        )

    def test_missing_frozen_obstacle_blocks_sizing_and_plan(self) -> None:
        chain = build_fomc_standard_chain(
            _event(), _freeze(long_target=False), _scan("long"), _market()
        )

        self.assertIsNone(chain.structure_target_price)
        self.assertIsNone(chain.sizing)
        self.assertEqual(chain.batch.plan.orders, ())
        self.assertIn("FOMC_FROZEN_TARGET_MISSING", chain.batch.plan.blockers)

    def test_market_observation_rejects_crossed_quote(self) -> None:
        with self.assertRaisesRegex(ValueError, "crossed_quote"):
            FomcMarketObservation.create(
                symbol="BTCUSDT",
                observed_at="2026-07-29T23:16:00+00:00",
                data_cutoff="2026-07-29T23:15:00+00:00",
                last_price=100.0,
                bid_price=101.0,
                ask_price=100.0,
                mark_price=100.0,
                index_price=100.0,
                funding_rate=0.0,
                quantity_step=0.001,
                minimum_quantity=0.001,
                minimum_notional_usdt=5.0,
                exchange_rules_hash="f" * 64,
                source_hashes={"ticker": "1" * 64},
            )

    def test_exchange_minimum_quantity_blocks_order_plan(self) -> None:
        chain = build_fomc_standard_chain(
            _event(),
            _freeze(),
            _scan("long"),
            _market(minimum_quantity=2.0),
        )

        self.assertFalse(chain.batch.plan.executable)
        self.assertEqual(chain.batch.plan.orders, ())
        self.assertIn(
            "FOMC_QUANTITY_BELOW_EXCHANGE_MINIMUM",
            chain.batch.plan.blockers,
        )


if __name__ == "__main__":
    unittest.main()
