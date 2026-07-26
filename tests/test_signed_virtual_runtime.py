from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from qount.contracts import InstrumentId
from qount.contracts import MarketSnapshot
from qount.contracts import ProductCapability
from qount.contracts import StrategyIntent
from qount.portfolio import SleeveRiskBudget
from qount.portfolio import VirtualExecutionCostModel
from qount.portfolio import run_multi_sleeve_virtual_runtime


class SignedVirtualRuntimeTest(unittest.TestCase):
    def test_short_execution_uses_absolute_cost_gross_and_signed_funding(self) -> None:
        instrument = InstrumentId.create(
            venue="binance",
            symbol="BTCUSDT",
            asset_class="crypto",
            product_kind="perpetual",
            underlying="BTC",
            price_currency="USD",
            settlement_asset="USDT",
            session_calendar="continuous",
        )
        key = instrument.instrument_key
        capability = ProductCapability.create(
            instrument_key=key,
            observed_at="2026-07-26T12:05:00+00:00",
            source_hash="a" * 64,
            long_allowed=True,
            short_allowed=True,
            buy_allowed=True,
            sell_allowed=True,
            sell_close_only=False,
            reduce_only_supported=True,
            fractional_supported=True,
            funding_applicable=True,
            order_types=("MARKET", "LIMIT"),
            trading_sessions=("CONTINUOUS",),
        )
        snapshot = MarketSnapshot.create(
            decision_time="2026-07-26T12:05:00+00:00",
            data_cutoff="2026-07-26T12:00:00+00:00",
            prices={key: 100.0},
            funding={key: 0.001},
            features={},
            exchange_rules_hash="b" * 64,
            account_snapshot_hash=None,
            data_quality={"complete": True, "blockers": ()},
            source_hashes={"market": "c" * 64},
        )
        intent = StrategyIntent.create(
            strategy_id="signed_virtual_short",
            strategy_version="2.0.0",
            snapshot_id=snapshot.snapshot_id,
            decision_time=snapshot.decision_time,
            data_cutoff=snapshot.data_cutoff,
            target_weights={key: -0.4},
            expected_holding_bars=1,
            target_stress_loss_fraction=0.1,
            reason_codes=("SHORT_CAPABILITY_CONFIRMED",),
            evidence_hash="d" * 64,
            state_hash="e" * 64,
        )
        cost_model = VirtualExecutionCostModel.create(
            model_version="signed-test-v1",
            taker_fee_rate=0.001,
            slippage_bps=10.0,
        )

        with tempfile.TemporaryDirectory() as temporary:
            artifact = run_multi_sleeve_virtual_runtime(
                Path(temporary),
                snapshot=snapshot,
                intents=(intent,),
                budgets=(SleeveRiskBudget(intent.strategy_id, 0.1, 0.1),),
                opening_cash_usdt=1_000.0,
                current_positions={},
                symbol_rules={
                    key: {
                        "step_size": 0.1,
                        "minimum_quantity": 0.1,
                        "minimum_notional": 5.0,
                    }
                },
                cost_model=cost_model,
                allowed_strategy_ids=(intent.strategy_id,),
                instruments={key: instrument},
                product_capabilities={key: capability},
            )

        self.assertEqual(
            [(order.side, order.phase) for order in artifact.batch.plan.orders],
            [("sell", "increase")],
        )
        self.assertAlmostEqual(artifact.ledger_snapshot.positions[key], -4.0)
        self.assertGreater(artifact.virtual_execution["fees_usdt"], 0.0)
        self.assertGreater(artifact.virtual_execution["funding_usdt"], 0.0)
        self.assertEqual(
            artifact.virtual_execution["instrument_hashes"][key],
            instrument.instrument_hash,
        )
        self.assertAlmostEqual(
            artifact.ledger_snapshot.account["actual_gross_notional"],
            400.0,
        )
        sleeve = artifact.sleeve_nav["sleeves"][0]
        self.assertGreater(sleeve["estimated_execution_cost_usdt"], 0.0)
        self.assertGreater(sleeve["estimated_funding_usdt"], 0.0)
        self.assertTrue(artifact.result["accounting_passed"])
        self.assertTrue(artifact.result["reconciliation_passed"])


if __name__ == "__main__":
    unittest.main()
