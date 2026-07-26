from __future__ import annotations

import unittest

from qount.contracts import InstrumentId
from qount.contracts import MarketSnapshot
from qount.contracts import ProductCapability
from qount.contracts import StrategyIntent
from qount.execution import build_portfolio_order_plan
from qount.persistence import dump_artifact
from qount.persistence import load_artifact
from qount.portfolio import SleeveRiskBudget
from qount.portfolio import allocate_strategy_intents
from qount.portfolio import portfolio_target_from_allocation
from qount.risk import build_portfolio_risk_decision


DECISION_TIME = "2026-07-26T12:05:00+00:00"
DATA_CUTOFF = "2026-07-26T12:00:00+00:00"


def _instrument(
    *,
    symbol: str = "BTCUSDT",
    asset_class: str = "crypto",
    product_kind: str = "perpetual",
    underlying: str = "BTC",
    settlement: str = "USDT",
) -> InstrumentId:
    return InstrumentId.create(
        venue="binance",
        symbol=symbol,
        asset_class=asset_class,
        product_kind=product_kind,
        underlying=underlying,
        price_currency="USD",
        settlement_asset=settlement,
        multiplier=1.0,
        session_calendar="continuous" if asset_class == "crypto" else "us_equities",
    )


def _capability(
    instrument: InstrumentId,
    *,
    short_allowed: bool,
    sell_close_only: bool,
    funding_applicable: bool,
) -> ProductCapability:
    return ProductCapability.create(
        instrument_key=instrument.instrument_key,
        observed_at=DECISION_TIME,
        source_hash="a" * 64,
        long_allowed=True,
        short_allowed=short_allowed,
        buy_allowed=True,
        sell_allowed=True,
        sell_close_only=sell_close_only,
        reduce_only_supported=short_allowed,
        fractional_supported=True,
        funding_applicable=funding_applicable,
        order_types=("MARKET", "LIMIT"),
        trading_sessions=("CONTINUOUS",)
        if instrument.asset_class == "crypto"
        else ("RTH",),
    )


def _snapshot(instrument: InstrumentId) -> MarketSnapshot:
    return MarketSnapshot.create(
        decision_time=DECISION_TIME,
        data_cutoff=DATA_CUTOFF,
        prices={instrument.instrument_key: 100.0},
        funding={instrument.instrument_key: 0.0001},
        features={},
        exchange_rules_hash="b" * 64,
        account_snapshot_hash=None,
        data_quality={"complete": True, "blockers": ()},
        source_hashes={"market": "c" * 64},
    )


def _intent(snapshot: MarketSnapshot, instrument: InstrumentId, weight: float) -> StrategyIntent:
    return StrategyIntent.create(
        strategy_id="signed_test",
        strategy_version="2.0.0",
        snapshot_id=snapshot.snapshot_id,
        decision_time=DECISION_TIME,
        data_cutoff=DATA_CUTOFF,
        target_weights={instrument.instrument_key: weight},
        expected_holding_bars=1,
        target_stress_loss_fraction=0.1,
        reason_codes=("SIGNED_TARGET",),
        evidence_hash="d" * 64,
        state_hash="e" * 64,
    )


def _target(snapshot: MarketSnapshot, instrument: InstrumentId, weight: float):
    intent = _intent(snapshot, instrument, weight)
    budget = SleeveRiskBudget(intent.strategy_id, 0.1, 0.1)
    allocation = allocate_strategy_intents(
        (intent,),
        (budget,),
        account_equity_usdt=1_000.0,
        allowed_strategy_ids=(intent.strategy_id,),
    )
    return intent, portfolio_target_from_allocation((intent,), allocation)


class CrossAssetSignedContractTest(unittest.TestCase):
    def test_product_identity_distinguishes_same_underlying(self) -> None:
        cash = _instrument(
            symbol="AAPL",
            asset_class="equity",
            product_kind="cash_equity",
            underlying="AAPL",
            settlement="USDC",
        )
        tokenized = _instrument(
            symbol="AAPL",
            asset_class="equity",
            product_kind="tokenized_equity",
            underlying="AAPL",
            settlement="USDC",
        )
        perpetual = _instrument(
            symbol="AAPLUSDT",
            asset_class="equity",
            product_kind="equity_perpetual",
            underlying="AAPL",
            settlement="USDT",
        )
        self.assertEqual({cash.underlying, tokenized.underlying, perpetual.underlying}, {"AAPL"})
        self.assertEqual(len({cash.instrument_key, tokenized.instrument_key, perpetual.instrument_key}), 3)
        capability = _capability(
            perpetual,
            short_allowed=True,
            sell_close_only=False,
            funding_applicable=True,
        )
        self.assertEqual(load_artifact(dump_artifact(cash)), cash)
        self.assertEqual(load_artifact(dump_artifact(capability)), capability)

    def test_strategy_v2_is_signed_but_v1_remains_long_only_and_round_trips(self) -> None:
        instrument = _instrument()
        snapshot = _snapshot(instrument)
        v2 = _intent(snapshot, instrument, -0.4)
        self.assertEqual(v2.schema_version, 2)
        self.assertEqual(v2.validate(), ())
        self.assertEqual(load_artifact(dump_artifact(v2)), v2)

        v1 = StrategyIntent.create(
            strategy_id="legacy_v1",
            strategy_version="1.0.0",
            snapshot_id=snapshot.snapshot_id,
            decision_time=DECISION_TIME,
            data_cutoff=DATA_CUTOFF,
            target_weights={instrument.instrument_key: 0.4},
            expected_holding_bars=1,
            target_stress_loss_fraction=0.1,
            reason_codes=("LONG_ONLY",),
            evidence_hash="f" * 64,
            state_hash="1" * 64,
            schema_version=1,
        )
        self.assertEqual(load_artifact(dump_artifact(v1)), v1)
        self.assertEqual(v1.schema_version, 1)
        with self.assertRaisesRegex(ValueError, "short_target_forbidden"):
            StrategyIntent.create(
                strategy_id="legacy_v1_short",
                strategy_version="1.0.0",
                snapshot_id=snapshot.snapshot_id,
                decision_time=DECISION_TIME,
                data_cutoff=DATA_CUTOFF,
                target_weights={instrument.instrument_key: -0.1},
                expected_holding_bars=1,
                target_stress_loss_fraction=0.1,
                reason_codes=("SHORT",),
                evidence_hash="2" * 64,
                state_hash="3" * 64,
                schema_version=1,
            )

    def test_allocator_applies_minimums_and_caps_to_absolute_exposure(self) -> None:
        instrument = _instrument()
        snapshot = _snapshot(instrument)
        intent = _intent(snapshot, instrument, -0.4)
        budget = SleeveRiskBudget(intent.strategy_id, 0.1, 0.2)
        allocation = allocate_strategy_intents(
            (intent,),
            (budget,),
            account_equity_usdt=500.0,
            allowed_strategy_ids=(intent.strategy_id,),
            minimum_notional_by_symbol={instrument.instrument_key: 90.0},
            maximum_weight_by_symbol={instrument.instrument_key: 0.25},
        )
        self.assertTrue(allocation["allocatable"])
        self.assertAlmostEqual(allocation["proposed_gross"], 0.2)
        self.assertAlmostEqual(
            allocation["portfolio_target_weights"][instrument.instrument_key],
            -0.2,
        )

        blocked = allocate_strategy_intents(
            (intent,),
            (budget,),
            account_equity_usdt=500.0,
            allowed_strategy_ids=(intent.strategy_id,),
            maximum_weight_by_symbol={instrument.instrument_key: 0.19},
        )
        self.assertIn(
            f"symbol_weight_cap_exceeded:{instrument.instrument_key}",
            blocked["blockers"],
        )

    def test_cash_stock_short_is_blocked_but_perpetual_short_is_planned(self) -> None:
        stock = _instrument(
            symbol="AAPL",
            asset_class="equity",
            product_kind="cash_equity",
            underlying="AAPL",
            settlement="USDC",
        )
        stock_capability = _capability(
            stock,
            short_allowed=False,
            sell_close_only=True,
            funding_applicable=False,
        )
        stock_snapshot = _snapshot(stock)
        _, stock_target = _target(stock_snapshot, stock, -0.2)
        stock_risk = build_portfolio_risk_decision(
            stock_snapshot,
            stock_target,
            current_positions={},
            account_equity_usdt=1_000.0,
            instruments={stock.instrument_key: stock},
            product_capabilities={stock.instrument_key: stock_capability},
        )
        self.assertFalse(stock_risk.approved)
        self.assertIn(
            f"portfolio_risk_short_not_allowed:{stock.instrument_key}",
            stock_risk.violations,
        )

        perpetual = _instrument()
        capability = _capability(
            perpetual,
            short_allowed=True,
            sell_close_only=False,
            funding_applicable=True,
        )
        snapshot = _snapshot(perpetual)
        _, target = _target(snapshot, perpetual, -0.4)
        risk = build_portfolio_risk_decision(
            snapshot,
            target,
            current_positions={},
            account_equity_usdt=1_000.0,
            instruments={perpetual.instrument_key: perpetual},
            product_capabilities={perpetual.instrument_key: capability},
        )
        plan = build_portfolio_order_plan(
            snapshot,
            target,
            risk,
            current_positions={},
            account_equity_usdt=1_000.0,
            symbol_rules={
                perpetual.instrument_key: {
                    "step_size": 0.1,
                    "minimum_quantity": 0.1,
                    "minimum_notional": 5.0,
                }
            },
            instruments={perpetual.instrument_key: perpetual},
            product_capabilities={perpetual.instrument_key: capability},
        )
        self.assertTrue(plan.executable)
        self.assertEqual(
            [(order.side, order.phase, order.reduce_only) for order in plan.orders],
            [("sell", "increase", False)],
        )
        self.assertAlmostEqual(plan.expected_positions[perpetual.instrument_key], -4.0)

    def test_short_reduction_without_capability_and_cross_zero_flip(self) -> None:
        instrument = _instrument()
        snapshot = _snapshot(instrument)
        _, reduce_target = _target(snapshot, instrument, -0.2)
        reduce_risk = build_portfolio_risk_decision(
            snapshot,
            reduce_target,
            current_positions={instrument.instrument_key: -4.0},
            account_equity_usdt=1_000.0,
        )
        reduce_plan = build_portfolio_order_plan(
            snapshot,
            reduce_target,
            reduce_risk,
            current_positions={instrument.instrument_key: -4.0},
            account_equity_usdt=1_000.0,
            symbol_rules={
                instrument.instrument_key: {
                    "step_size": 0.1,
                    "minimum_quantity": 0.1,
                    "minimum_notional": 5.0,
                }
            },
        )
        self.assertTrue(reduce_plan.executable)
        self.assertEqual(
            [(order.side, order.phase, order.reduce_only) for order in reduce_plan.orders],
            [("buy", "reduce", True)],
        )

        capability = _capability(
            instrument,
            short_allowed=True,
            sell_close_only=False,
            funding_applicable=True,
        )
        _, flip_target = _target(snapshot, instrument, -0.2)
        flip_risk = build_portfolio_risk_decision(
            snapshot,
            flip_target,
            current_positions={instrument.instrument_key: 1.0},
            account_equity_usdt=1_000.0,
            instruments={instrument.instrument_key: instrument},
            product_capabilities={instrument.instrument_key: capability},
        )
        flip_plan = build_portfolio_order_plan(
            snapshot,
            flip_target,
            flip_risk,
            current_positions={instrument.instrument_key: 1.0},
            account_equity_usdt=1_000.0,
            symbol_rules={
                instrument.instrument_key: {
                    "step_size": 0.1,
                    "minimum_quantity": 0.1,
                    "minimum_notional": 5.0,
                }
            },
            instruments={instrument.instrument_key: instrument},
            product_capabilities={instrument.instrument_key: capability},
        )
        self.assertEqual(
            [(order.side, order.phase, order.quantity) for order in flip_plan.orders],
            [("sell", "reduce", 1.0), ("sell", "increase", 2.0)],
        )
        self.assertAlmostEqual(flip_plan.expected_positions[instrument.instrument_key], -2.0)


if __name__ == "__main__":
    unittest.main()
