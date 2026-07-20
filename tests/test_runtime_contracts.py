from __future__ import annotations

import unittest
from dataclasses import replace

from qount.contracts import MarketSnapshot
from qount.contracts import OrderPlan
from qount.contracts import PlannedCancellation
from qount.contracts import PlannedOrder
from qount.contracts import RiskDecision
from qount.contracts import StrategyIntent
from qount.contracts import canonical_hash
from qount.contracts import trace_id
from qount.portfolio import SleeveRiskBudget
from qount.portfolio import allocate_strategy_intents
from qount.portfolio import portfolio_target_from_allocation


DECISION_TIME = "2026-07-20T00:05:00+00:00"
DATA_CUTOFF = "2026-07-20T00:00:00+00:00"


def _snapshot() -> MarketSnapshot:
    return MarketSnapshot.create(
        decision_time=DECISION_TIME,
        data_cutoff=DATA_CUTOFF,
        prices={"BTCUSDT": 100_000.0, "ETHUSDT": 3_500.0},
        funding={"BTCUSDT": 0.0001, "ETHUSDT": -0.00005},
        features={"BTCUSDT_ABOVE_SMA200": True},
        exchange_rules_hash="a" * 64,
        account_snapshot_hash="b" * 64,
        data_quality={"complete": True, "blockers": ()},
        source_hashes={"market_data": "c" * 64, "funding": "d" * 64},
    )


def _intent(snapshot: MarketSnapshot) -> StrategyIntent:
    return StrategyIntent.create(
        strategy_id="MiniTrend-UM-Base-v0.2",
        strategy_version="0.2.0",
        snapshot_id=snapshot.snapshot_id,
        decision_time=DECISION_TIME,
        data_cutoff=DATA_CUTOFF,
        target_weights={"BTCUSDT": 0.4, "ETHUSDT": 0.2},
        expected_holding_bars=1,
        target_stress_loss_fraction=0.10,
        reason_codes=("BASE_MASTER_GATE_ACTIVE", "BTCUSDT_TARGET_LONG"),
        evidence_hash="e" * 64,
        state_hash="f" * 64,
    )


class RuntimeContractTest(unittest.TestCase):
    def test_snapshot_is_deterministic_and_detects_tampering(self) -> None:
        first = _snapshot()
        second = _snapshot()
        self.assertEqual(first.snapshot_id, second.snapshot_id)
        self.assertEqual(first.snapshot_hash, second.snapshot_hash)
        self.assertEqual(first.validate(), ())

        tampered = replace(first, prices={"BTCUSDT": 99_000.0, "ETHUSDT": 3_500.0})
        self.assertIn("snapshot_hash_invalid", tampered.validate())
        self.assertIn("snapshot_id_invalid", tampered.validate())

    def test_legacy_intent_remains_valid_but_is_not_trace_eligible(self) -> None:
        legacy = StrategyIntent(
            strategy_id="legacy",
            decision_time=DECISION_TIME,
            data_cutoff=DATA_CUTOFF,
            target_weights={"BTCUSDT": 0.2},
            expected_holding_bars=1,
            target_stress_loss_fraction=0.1,
            evidence_hash="a" * 64,
            state_hash="b" * 64,
        )
        self.assertEqual(legacy.validate(), ())
        self.assertFalse(legacy.traced)

    def test_traced_intent_hash_detects_reason_tampering(self) -> None:
        intent = _intent(_snapshot())
        tampered = replace(intent, reason_codes=("BASE_MASTER_GATE_CASH",))
        self.assertIn("intent_hash_mismatch", tampered.validate())

    def test_complete_trace_chain_links_every_contract(self) -> None:
        snapshot = _snapshot()
        intent = _intent(snapshot)
        allocation = allocate_strategy_intents(
            (intent,),
            (SleeveRiskBudget(intent.strategy_id, 0.10, 0.20, 1.0),),
            account_equity_usdt=500.0,
            allowed_strategy_ids=(intent.strategy_id,),
            minimum_notional_by_symbol={"BTCUSDT": 5.0, "ETHUSDT": 5.0},
            maximum_weight_by_symbol={"BTCUSDT": 0.5, "ETHUSDT": 0.5},
        )
        target = portfolio_target_from_allocation((intent,), allocation)
        batch_id = trace_id(
            "decision_batch",
            {
                "snapshot_id": snapshot.snapshot_id,
                "portfolio_target_id": target.portfolio_target_id,
            },
        )
        risk = RiskDecision.create(
            batch_id=batch_id,
            portfolio_target_id=target.portfolio_target_id,
            decision_time=DECISION_TIME,
            approved=True,
            input_target=target.target_weights,
            approved_target=target.target_weights,
            adjustments=(),
            violations=(),
            risk_state_hash=canonical_hash(
                {"gross": sum(target.target_weights.values()), "healthy": True}
            ),
            increase_risk_allowed=True,
            reduce_risk_allowed=True,
        )
        orders = (
            PlannedOrder.create(
                batch_id=batch_id,
                decision_ids=target.decision_ids,
                symbol="ETHUSDT",
                side="sell",
                quantity=0.01,
                reduce_only=True,
                phase="reduce",
                sequence=1,
            ),
            PlannedOrder.create(
                batch_id=batch_id,
                decision_ids=target.decision_ids,
                symbol="BTCUSDT",
                side="buy",
                quantity=0.001,
                reduce_only=False,
                phase="increase",
                sequence=2,
            ),
            PlannedOrder.create(
                batch_id=batch_id,
                decision_ids=target.decision_ids,
                symbol="BTCUSDT",
                side="sell",
                quantity=None,
                reduce_only=True,
                phase="protective",
                sequence=3,
                order_type="stop_market",
                close_position=True,
                stop_price=90_000.0,
            ),
        )
        plan = OrderPlan.create(
            batch_id=batch_id,
            risk_decision_id=risk.risk_decision_id,
            portfolio_target_id=target.portfolio_target_id,
            snapshot_id=snapshot.snapshot_id,
            decision_ids=target.decision_ids,
            created_at=DECISION_TIME,
            current_position_hash=canonical_hash({"BTCUSDT": 0.0, "ETHUSDT": 1.0}),
            approved_target=risk.approved_target,
            orders=orders,
            blockers=(),
            executable=True,
        )

        self.assertEqual(intent.snapshot_id, snapshot.snapshot_id)
        self.assertEqual(target.decision_ids, (intent.decision_id,))
        self.assertEqual(risk.portfolio_target_id, target.portfolio_target_id)
        self.assertEqual(plan.risk_decision_id, risk.risk_decision_id)
        self.assertEqual(plan.validate(), ())

    def test_portfolio_target_with_blockers_must_be_zero(self) -> None:
        snapshot = _snapshot()
        intent = _intent(snapshot)
        allocation = allocate_strategy_intents(
            (intent,),
            (SleeveRiskBudget(intent.strategy_id, 0.10, 0.20, 1.0),),
            account_equity_usdt=100.0,
            allowed_strategy_ids=(intent.strategy_id,),
            minimum_notional_by_symbol={"BTCUSDT": 1_000.0, "ETHUSDT": 1_000.0},
        )
        target = portfolio_target_from_allocation((intent,), allocation)
        self.assertFalse(target.allocatable)
        self.assertTrue(target.blockers)
        self.assertEqual(set(target.target_weights.values()), {0.0})

        with self.assertRaisesRegex(ValueError, "portfolio_target_not_fail_closed"):
            type(target).create(
                snapshot_id=target.snapshot_id,
                decision_ids=target.decision_ids,
                decision_time=target.decision_time,
                proposed_target_weights=target.proposed_target_weights,
                target_weights={"BTCUSDT": 0.1},
                sleeve_contributions=target.sleeve_contributions,
                blockers=target.blockers,
                allocatable=False,
                allocation_hash=target.allocation_hash,
            )

    def test_risk_violation_cannot_allow_increasing_risk(self) -> None:
        with self.assertRaisesRegex(ValueError, "risk_increase_not_fail_closed"):
            RiskDecision.create(
                batch_id="a" * 64,
                portfolio_target_id="b" * 64,
                decision_time=DECISION_TIME,
                approved=False,
                input_target={"BTCUSDT": 0.2},
                approved_target={},
                adjustments=(),
                violations=("ACCOUNT_STATE_UNKNOWN",),
                risk_state_hash="c" * 64,
                increase_risk_allowed=True,
                reduce_risk_allowed=True,
            )

    def test_order_plan_requires_reductions_before_increases(self) -> None:
        orders = (
            PlannedOrder.create(
                batch_id="a" * 64,
                decision_ids=("e" * 64,),
                symbol="BTCUSDT",
                side="buy",
                quantity=0.001,
                reduce_only=False,
                phase="increase",
                sequence=1,
            ),
            PlannedOrder.create(
                batch_id="a" * 64,
                decision_ids=("e" * 64,),
                symbol="ETHUSDT",
                side="sell",
                quantity=0.01,
                reduce_only=True,
                phase="reduce",
                sequence=2,
            ),
        )
        with self.assertRaisesRegex(
            ValueError,
            "order_plan_reduction_increase_order_invalid",
        ):
            OrderPlan.create(
                batch_id="a" * 64,
                risk_decision_id="b" * 64,
                portfolio_target_id="c" * 64,
                snapshot_id="d" * 64,
                decision_ids=("e" * 64,),
                created_at=DECISION_TIME,
                current_position_hash="f" * 64,
                approved_target={"BTCUSDT": 0.2},
                orders=orders,
                blockers=(),
                executable=True,
            )

    def test_order_plan_requires_cancellation_before_new_protection(self) -> None:
        cancellation = PlannedCancellation.create(
            batch_id="a" * 64,
            decision_ids=("e" * 64,),
            symbol="BTCUSDT",
            target_exchange_order_id="12345",
            target_client_order_id="old-stop",
            sequence=2,
            reason="replace_protective_stop",
        )
        protective = PlannedOrder.create(
            batch_id="a" * 64,
            decision_ids=("e" * 64,),
            symbol="BTCUSDT",
            side="sell",
            quantity=None,
            reduce_only=False,
            phase="protective",
            sequence=1,
            order_type="stop_market",
            close_position=True,
            stop_price=90_000.0,
        )
        with self.assertRaisesRegex(
            ValueError,
            "order_plan_global_action_order_invalid",
        ):
            OrderPlan.create(
                batch_id="a" * 64,
                risk_decision_id="b" * 64,
                portfolio_target_id="c" * 64,
                snapshot_id="d" * 64,
                decision_ids=("e" * 64,),
                created_at=DECISION_TIME,
                current_position_hash="f" * 64,
                approved_target={"BTCUSDT": 0.2},
                orders=(protective,),
                cancellations=(cancellation,),
                blockers=(),
                executable=True,
            )


if __name__ == "__main__":
    unittest.main()
