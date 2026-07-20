from __future__ import annotations

import unittest

from qount.mini_trend.forward import TOP3
from qount.mini_trend.live_pilot import LIVE_PILOT_CONTRACT
from qount.mini_trend.pilot_dry import build_pilot_dry_plan


def _preflight(*, verdict: str = "account_preflight_pass", positions=None) -> dict:
    return {
        "contract_hash": LIVE_PILOT_CONTRACT.contract_hash,
        "diagnostics": {"verdict": verdict},
        "evidence": {"available_balance_usdt": 488.89481071},
        "account": {"nonzero_positions": positions or []},
    }


def _rules() -> dict:
    minimums = {"BTCUSDT": "50", "ETHUSDT": "20", "BNBUSDT": "5"}
    steps = {"BTCUSDT": "0.001", "ETHUSDT": "0.001", "BNBUSDT": "0.01"}
    return {
        "market": "um",
        "source_type": "runtime_exchange_info",
        "rules": [
            {
                "symbol": symbol,
                "status": "TRADING",
                "min_qty": steps[symbol],
                "step_size": steps[symbol],
                "market_step_size": steps[symbol],
                "min_notional": minimums[symbol],
            }
            for symbol in TOP3
        ],
    }


def _prices() -> dict[str, float]:
    return {"BTCUSDT": 10_000.0, "ETHUSDT": 2_000.0, "BNBUSDT": 300.0}


class MiniTrendPilotDryTest(unittest.TestCase):
    def test_flat_audited_account_builds_would_place_orders_only(self) -> None:
        plan = build_pilot_dry_plan(
            _preflight(),
            {symbol: 0.2 for symbol in TOP3},
            _prices(),
            _rules(),
        )
        self.assertEqual(plan["diagnostics"]["verdict"], "dry_plan_ready")
        self.assertEqual(len(plan["would_place_orders"]), 3)
        self.assertTrue(all(row["side"] == "buy" for row in plan["would_place_orders"]))
        self.assertFalse(plan["meta"]["live_orders_allowed"])
        self.assertEqual(plan["capital_usdt"], 488.89481071)

    def test_blocked_preflight_cannot_produce_intents(self) -> None:
        plan = build_pilot_dry_plan(
            _preflight(verdict="blocked_account_preflight"),
            {symbol: 0.2 for symbol in TOP3},
            _prices(),
            _rules(),
        )
        self.assertEqual(plan["would_place_orders"], [])
        self.assertIn("account_preflight_blocked", plan["diagnostics"]["blockers"])

    def test_below_exchange_minimum_is_explicitly_blocked(self) -> None:
        plan = build_pilot_dry_plan(
            _preflight(),
            {"BTCUSDT": 0.1, "ETHUSDT": 0.0, "BNBUSDT": 0.0},
            _prices(),
            _rules(),
        )
        self.assertEqual(plan["diagnostics"]["verdict"], "blocked_dry_plan")
        self.assertEqual(len(plan["blocked_orders"]), 1)
        self.assertEqual(plan["blocked_orders"][0]["symbol"], "BTCUSDT")

    def test_deadband_suppresses_small_rebalance(self) -> None:
        plan = build_pilot_dry_plan(
            _preflight(
                positions=[
                    {
                        "symbol": "BTC/USDT:USDT",
                        "side": "long",
                        "notional_usdt": 55.0,
                    }
                ]
            ),
            {"BTCUSDT": 0.2, "ETHUSDT": 0.2, "BNBUSDT": 0.2},
            _prices(),
            _rules(),
        )
        symbols = {row["symbol"] for row in plan["would_place_orders"]}
        self.assertNotIn("BTCUSDT", symbols)
        self.assertEqual(symbols, {"ETHUSDT", "BNBUSDT"})

    def test_short_or_excess_gross_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "short"):
            build_pilot_dry_plan(
                _preflight(),
                {"BTCUSDT": -0.1, "ETHUSDT": 0.0, "BNBUSDT": 0.0},
                _prices(),
                _rules(),
            )
        with self.assertRaisesRegex(ValueError, "gross"):
            build_pilot_dry_plan(
                _preflight(),
                {symbol: 0.5 for symbol in TOP3},
                _prices(),
                _rules(),
            )


if __name__ == "__main__":
    unittest.main()
