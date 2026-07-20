from __future__ import annotations

import copy
import unittest

from qount.contracts import PortfolioTarget
from qount.contracts import canonical_hash
from qount.execution import compare_legacy_dispatch_plan
from qount.execution import order_plan_from_legacy_dry_plan
from qount.risk import legacy_dispatch_plan_hash
from qount.risk import risk_decision_from_legacy_dry_plan
from tests.test_mini_trend_pilot_dispatcher import _plan


def _target(
    plan: dict,
    *,
    decision_id: str | None = None,
) -> PortfolioTarget:
    decision = plan["decision"]
    weights = decision["desired_weights"]
    linked_decision_id = decision_id or decision["decision_id"]
    return PortfolioTarget.create(
        snapshot_id=canonical_hash(
            {"legacy_projection_decision_id": decision["decision_id"]}
        ),
        decision_ids=(linked_decision_id,),
        decision_time=decision["decision_available_after"],
        proposed_target_weights=weights,
        target_weights=weights,
        sleeve_contributions={decision["strategy"]: weights},
        blockers=(),
        allocatable=True,
        allocation_hash=canonical_hash(
            {
                "decision_id": linked_decision_id,
                "target_weights": weights,
            }
        ),
    )


def _converted(plan: dict):
    target = _target(plan)
    risk = risk_decision_from_legacy_dry_plan(plan, target)
    order_plan = order_plan_from_legacy_dry_plan(plan, target, risk)
    return target, risk, order_plan


class DispatchContractAdapterTest(unittest.TestCase):
    def test_clean_plan_converts_to_approved_risk_decision(self) -> None:
        plan = _plan()
        target = _target(plan)
        first = risk_decision_from_legacy_dry_plan(plan, target)
        second = risk_decision_from_legacy_dry_plan(plan, target)

        self.assertTrue(first.approved)
        self.assertTrue(first.increase_risk_allowed)
        self.assertTrue(first.reduce_risk_allowed)
        self.assertEqual(first.violations, ())
        self.assertEqual(first.approved_target, target.target_weights)
        self.assertEqual(first, second)

    def test_market_and_protective_actions_keep_economic_parity(self) -> None:
        plan = _plan()
        _, _, order_plan = _converted(plan)

        market = [order for order in order_plan.orders if order.order_type == "market"]
        protective = [
            order for order in order_plan.orders if order.phase == "protective"
        ]
        self.assertEqual(len(market), 3)
        self.assertEqual(len(protective), 3)
        self.assertTrue(all(order.close_position for order in protective))
        self.assertTrue(all(order.quantity is None for order in protective))
        self.assertTrue(order_plan.executable)
        self.assertEqual(compare_legacy_dispatch_plan(plan, order_plan)["differences"], ())

    def test_standard_client_ids_are_new_deterministic_and_traced(self) -> None:
        plan = _plan()
        target, risk, first = _converted(plan)
        second = order_plan_from_legacy_dry_plan(plan, target, risk)
        legacy_ids = {
            row["client_order_id"]
            for row in (*plan["market_orders"], *plan["stop_orders"])
        }
        standard_ids = {order.client_order_id for order in first.orders}

        self.assertTrue(legacy_ids.isdisjoint(standard_ids))
        self.assertEqual(first, second)
        self.assertTrue(
            all(order.decision_ids == target.decision_ids for order in first.orders)
        )

    def test_tampered_legacy_plan_hash_fails_closed(self) -> None:
        plan = _plan()
        plan["plan_hash"] = "0" * 64
        target = _target(plan)
        risk = risk_decision_from_legacy_dry_plan(plan, target)
        order_plan = order_plan_from_legacy_dry_plan(plan, target, risk)

        self.assertFalse(risk.approved)
        self.assertIn("legacy_plan_hash_invalid", risk.violations)
        self.assertFalse(order_plan.executable)
        self.assertEqual(order_plan.orders, ())
        self.assertEqual(order_plan.cancellations, ())

    def test_decision_target_mismatch_fails_closed(self) -> None:
        plan = _plan()
        target = _target(plan, decision_id="f" * 64)
        risk = risk_decision_from_legacy_dry_plan(plan, target)
        order_plan = order_plan_from_legacy_dry_plan(plan, target, risk)

        self.assertFalse(risk.approved)
        self.assertIn(
            "legacy_decision_portfolio_target_mismatch",
            risk.violations,
        )
        self.assertEqual(set(risk.approved_target.values()), {0.0})
        self.assertFalse(order_plan.executable)
        self.assertEqual(order_plan.orders, ())

    def test_legacy_blocker_zeros_target_and_blocks_execution(self) -> None:
        plan = copy.deepcopy(_plan())
        plan["diagnostics"].update(
            {
                "blockers": ["unresolved_regular_open_orders"],
                "verdict": "blocked_dispatch",
                "dry_evidence_valid": False,
            }
        )
        target = _target(plan)
        risk = risk_decision_from_legacy_dry_plan(plan, target)
        order_plan = order_plan_from_legacy_dry_plan(plan, target, risk)

        self.assertFalse(risk.approved)
        self.assertIn(
            "legacy_dispatch_blocker:unresolved_regular_open_orders",
            risk.violations,
        )
        self.assertEqual(set(risk.approved_target.values()), {0.0})
        self.assertFalse(order_plan.executable)
        self.assertEqual(order_plan.orders, ())

    def test_drawdown_flatten_allows_reduction_but_not_increase(self) -> None:
        plan = copy.deepcopy(_plan())
        plan["desired_weights"] = {
            symbol: 0.0 for symbol in plan["desired_weights"]
        }
        plan["market_orders"] = [
            row | {"side": "sell", "reduce_only": True}
            for row in plan["market_orders"]
        ]
        plan["stop_orders"] = []
        plan["expected_positions_base"] = {
            symbol: 0.0 for symbol in plan["expected_positions_base"]
        }
        plan["risk_flags"] = ["pilot_drawdown_flatten_then_halt"]
        plan["halt_after_dispatch"] = True
        plan["account_equity"] = {
            "margin_balance_usdt": 270.0,
            "peak_margin_balance_usdt": 300.0,
            "drawdown_pct": 10.0,
        }
        plan["plan_hash"] = legacy_dispatch_plan_hash(plan)

        _, risk, order_plan = _converted(plan)
        self.assertTrue(risk.approved)
        self.assertTrue(risk.reduce_risk_allowed)
        self.assertFalse(risk.increase_risk_allowed)
        self.assertEqual(set(risk.approved_target.values()), {0.0})
        self.assertTrue(order_plan.executable)
        self.assertTrue(order_plan.orders)
        self.assertTrue(all(order.phase == "reduce" for order in order_plan.orders))

    def test_stop_cancellation_and_retention_survive_conversion(self) -> None:
        plan = copy.deepcopy(_plan())
        plan["stop_cancels"] = [
            {
                "id": "exchange-stop-1",
                "client_order_id": "qmt-s-old-btc",
                "data_symbol": "BTCUSDT",
                "symbol": "BTC/USDT:USDT",
            }
        ]
        plan["retained_stops"] = [
            {
                "id": "exchange-stop-2",
                "client_order_id": "qmt-s-old-eth",
                "data_symbol": "ETHUSDT",
                "symbol": "ETH/USDT:USDT",
            }
        ]
        plan["plan_hash"] = legacy_dispatch_plan_hash(plan)
        _, _, order_plan = _converted(plan)

        self.assertEqual(len(order_plan.cancellations), 1)
        cancellation = order_plan.cancellations[0]
        self.assertEqual(cancellation.symbol, "BTCUSDT")
        self.assertEqual(cancellation.target_exchange_order_id, "exchange-stop-1")
        self.assertEqual(cancellation.reason, "replace_protective_stop")
        self.assertEqual(order_plan.retained_order_ids, ("exchange-stop-2",))
        self.assertEqual(cancellation.sequence, 4)
        protective_sequences = [
            order.sequence for order in order_plan.orders if order.phase == "protective"
        ]
        self.assertEqual(protective_sequences, [5, 6, 7])
        self.assertEqual(compare_legacy_dispatch_plan(plan, order_plan)["differences"], ())

    def test_golden_parity_covers_positions_and_tolerance(self) -> None:
        plan = _plan()
        _, _, order_plan = _converted(plan)
        report = compare_legacy_dispatch_plan(plan, order_plan)

        self.assertTrue(report["matches"])
        self.assertEqual(report["differences"], ())
        self.assertEqual(
            report["legacy"]["expected_positions"],
            report["standard"]["expected_positions"],
        )
        self.assertEqual(
            report["legacy"]["reconciliation_tolerance"],
            report["standard"]["reconciliation_tolerance"],
        )


if __name__ == "__main__":
    unittest.main()
