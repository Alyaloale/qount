from __future__ import annotations

import unittest

from qount.mini_trend.config import MiniTrendConfig
from qount.mini_trend.execution import compute_orders
from qount.mini_trend.models import RiskResult, SymbolFilter


def _risk(targets: dict[str, float], *, halt: bool = False) -> RiskResult:
    return RiskResult(
        schema_version=1,
        allow=not halt,
        halt=halt,
        reasons=[],
        limits={},
        blocked_symbols=[],
        targets=targets,
        min_notional_coverage=1.0,
    )


class TestMiniTrendExecution(unittest.TestCase):
    def _cfg(self, **over) -> MiniTrendConfig:
        kw = dict(universe=("BTCUSDT", "ETHUSDT"), capital_cap_usdt=400.0, rebalance_band=0.35)
        kw.update(over)
        return MiniTrendConfig(**kw)

    def _filters(self) -> dict[str, SymbolFilter]:
        return {
            "BTCUSDT": SymbolFilter(amount_step=1e-5, min_amount=1e-5, min_notional=10.0),
            "ETHUSDT": SymbolFilter(amount_step=1e-4, min_amount=1e-4, min_notional=10.0),
        }

    def test_buy_from_cash(self) -> None:
        cfg = self._cfg()
        plan = compute_orders(
            _risk({"BTCUSDT": 0.5}),
            {},
            {"BTCUSDT": 60_000.0},
            self._filters(),
            cfg,
        )
        self.assertEqual(len(plan.orders), 1)
        self.assertEqual(plan.orders[0].side, "buy")
        self.assertAlmostEqual(plan.orders[0].quote_qty, 200.0, places=2)

    def test_rebalance_band_suppresses_small_buy(self) -> None:
        cfg = self._cfg()
        plan = compute_orders(
            _risk({"BTCUSDT": 0.25}),
            {"BTCUSDT": 80.0 / 60_000.0},
            {"BTCUSDT": 60_000.0},
            self._filters(),
            cfg,
        )
        self.assertEqual(plan.orders, [])
        self.assertIn("BTCUSDT: within rebalance_band", plan.no_order_reasons)

    def test_target_zero_exits_even_inside_band(self) -> None:
        cfg = self._cfg(rebalance_band=1.0)
        plan = compute_orders(
            _risk({"BTCUSDT": 0.0}),
            {"BTCUSDT": 100.0 / 60_000.0},
            {"BTCUSDT": 60_000.0},
            self._filters(),
            cfg,
        )
        self.assertEqual(len(plan.orders), 1)
        self.assertEqual(plan.orders[0].side, "sell")
        self.assertEqual(plan.orders[0].reason, "target_exit")

    def test_min_notional_skip_is_explicit(self) -> None:
        cfg = self._cfg()
        plan = compute_orders(
            _risk({"BTCUSDT": 0.01}),
            {},
            {"BTCUSDT": 60_000.0},
            self._filters(),
            cfg,
        )
        self.assertEqual(plan.orders, [])
        self.assertIn("BTCUSDT: buy below notional floor", plan.no_order_reasons)

    def test_live_requires_armed(self) -> None:
        cfg = self._cfg()
        plan = compute_orders(
            _risk({"BTCUSDT": 0.5}),
            {},
            {"BTCUSDT": 60_000.0},
            self._filters(),
            cfg,
            mode="live",
            armed=False,
        )
        self.assertEqual(plan.orders, [])
        self.assertEqual(plan.no_order_reasons, ["not_armed"])


if __name__ == "__main__":
    unittest.main()
