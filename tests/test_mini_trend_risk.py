from __future__ import annotations

import unittest

from qount.mini_trend.config import MiniTrendConfig
from qount.mini_trend.models import GateState, Position, SignalResult, SymbolFilter
from qount.mini_trend.risk import evaluate_risk


def _signal(targets: dict[str, float], *, risk_on: bool = True) -> SignalResult:
    universe = ("BTCUSDT", "ETHUSDT")
    full = {s: targets.get(s, 0.0) for s in universe}
    return SignalResult(
        schema_version=1,
        strategy="MiniTrend-5",
        bar="2026-07-07",
        universe=universe,
        gate=GateState(risk_on=risk_on, btc_close=100.0, btc_sma200=90.0, breadth=1.0),
        targets=full,
        diagnostics={},
    )


class TestMiniTrendRisk(unittest.TestCase):
    def _cfg(self, **over) -> MiniTrendConfig:
        kw = dict(universe=("BTCUSDT", "ETHUSDT"))
        kw.update(over)
        return MiniTrendConfig(**kw)

    def _filters(self) -> dict[str, SymbolFilter]:
        return {
            "BTCUSDT": SymbolFilter(amount_step=1e-5, min_amount=1e-5, min_notional=10.0),
            "ETHUSDT": SymbolFilter(amount_step=1e-4, min_amount=1e-4, min_notional=10.0),
        }

    def test_min_notional_below_threshold_blocks_target(self) -> None:
        cfg = self._cfg(capital_cap_usdt=400.0)
        res = evaluate_risk(_signal({"BTCUSDT": 0.01}), self._filters(), {"BTCUSDT": 60_000.0}, cfg)
        self.assertTrue(res.allow)
        self.assertEqual(res.targets["BTCUSDT"], 0.0)
        self.assertIn("target_below_min_notional", res.reasons)
        self.assertIn("min_notional_coverage_below_gate", res.reasons)
        self.assertEqual(res.min_notional_coverage, 0.0)

    def test_risk_off_defensively_zeros_positive_targets(self) -> None:
        cfg = self._cfg()
        res = evaluate_risk(
            _signal({"BTCUSDT": 0.5}, risk_on=False),
            self._filters(),
            {"BTCUSDT": 60_000.0},
            cfg,
        )
        self.assertTrue(res.allow)
        self.assertEqual(res.targets["BTCUSDT"], 0.0)
        self.assertIn("risk_off_master_gate", res.reasons)

    def test_stop_latch_blocks_same_symbol_until_signal_resets(self) -> None:
        cfg = self._cfg()
        filt = self._filters()
        prices = {"ETHUSDT": 3_000.0}
        blocked = evaluate_risk(_signal({"ETHUSDT": 0.2}), filt, prices, cfg, latches={"ETHUSDT": True})
        self.assertEqual(blocked.targets["ETHUSDT"], 0.0)
        self.assertIn("stop_latch", blocked.reasons)

        reset = evaluate_risk(_signal({"ETHUSDT": 0.0}), filt, prices, cfg, latches={"ETHUSDT": True})
        self.assertIn("ETHUSDT", reset.latch_reset_symbols)

    def test_unknown_target_filter_blocks_entry(self) -> None:
        cfg = self._cfg()
        res = evaluate_risk(_signal({"ETHUSDT": 0.5}), {}, {}, cfg)
        self.assertTrue(res.allow)
        self.assertEqual(res.targets["ETHUSDT"], 0.0)
        self.assertIn("target_unknown_price_or_filter", res.reasons)

    def test_unknown_held_position_halts(self) -> None:
        cfg = self._cfg()
        res = evaluate_risk(
            _signal({"BTCUSDT": 0.0}),
            self._filters(),
            {"BTCUSDT": 60_000.0},
            cfg,
            positions={"ETHUSDT": Position("ETHUSDT", 0.01)},
        )
        self.assertTrue(res.halt)
        self.assertFalse(res.allow)
        self.assertIn("held_position_unknown_price_or_filter", res.reasons)

    def test_spot_liability_halts(self) -> None:
        cfg = self._cfg()
        res = evaluate_risk(
            _signal({"BTCUSDT": 0.0}),
            self._filters(),
            {"BTCUSDT": 60_000.0},
            cfg,
            positions={"BTCUSDT": Position("BTCUSDT", 0.0, liability=0.1)},
        )
        self.assertTrue(res.halt)
        self.assertIn("spot_liability", res.reasons)


if __name__ == "__main__":
    unittest.main()
