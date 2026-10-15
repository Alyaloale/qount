"""
Unit Tests for Binance Regime Execution Engine
"""

import unittest
from unittest.mock import MagicMock

from qount.research.binance_regime_execution import (
    BINANCE_SYMBOL_MAPPING,
    BinanceFuturesClient,
    BinanceKlineBar,
    BinanceRegimeExecutionEngine,
    compute_profile_state,
    round_step,
    round_tick,
)


class TestBinanceRegimeExecution(unittest.TestCase):

    def setUp(self):
        self.client = BinanceFuturesClient(api_key="test_key", api_secret="test_secret")
        self.engine = BinanceRegimeExecutionEngine(
            client=self.client,
            mode="DYNAMIC_BULL_2_5X",
            dry_run=True,
            orders_authorized=False,
            max_positions=1,
            risk_budget_pct=0.08,
        )

    def test_symbol_mapping(self):
        self.assertEqual(BINANCE_SYMBOL_MAPPING["SPY"], "SPYUSDT")
        self.assertEqual(BINANCE_SYMBOL_MAPPING["SMH"], "SMHUSDT")
        self.assertEqual(BINANCE_SYMBOL_MAPPING["CPER"], "COPPERUSDT")
        self.assertEqual(BINANCE_SYMBOL_MAPPING["GLD"], "XAUUSDT")

    def test_round_step_and_tick(self):
        self.assertEqual(round_step(0.1264, 0.01), 0.12)
        self.assertEqual(round_step(0.0059, 0.001), 0.005)
        self.assertEqual(round_tick(583.456, 0.01), 583.46)
        self.assertEqual(round_tick(4.1234, 0.001), 4.123)

    def test_profile_state_calculation(self):
        bars = []
        for i in range(30):
            bars.append(BinanceKlineBar(
                open_time_ms=1700000000000 + i * 86400000,
                o=100.0 + i * 0.1,
                h=101.0 + i * 0.1,
                l=99.0 + i * 0.1,
                c=100.5 + i * 0.1,
                v=1000.0,
                close_time_ms=1700000000000 + (i + 1) * 86400000 - 1,
            ))
        state, name, poc, vah, val, pr, conc = compute_profile_state(bars, 103.5, 1.5)
        self.assertIn(state, [1, 2, 3, 4])
        self.assertTrue(val <= poc <= vah)

    def test_bear_market_cash_defense(self):
        spy_bars = []
        for i in range(70):
            p = 500.0 - i * 2.0
            spy_bars.append(BinanceKlineBar(
                open_time_ms=1700000000000 + i * 86400000,
                o=p,
                h=p + 1.0,
                l=p - 1.0,
                c=p - 0.5,
                v=50000.0,
                close_time_ms=1700000000000 + (i + 1) * 86400000 - 1,
            ))
        candles = {"SPYUSDT": spy_bars}
        plan = self.engine.evaluate_live_decision_plan(
            account_equity=100.0, historical_candles=candles, fetch_missing=False
        )
        self.assertEqual(plan["decision"], "100% CASH DEFENSE")
        self.assertEqual(plan["effective_leverage"], 0.0)
        self.assertEqual(len(plan["orders"]), 0)

    def test_bull_market_trade_generation_and_dry_run(self):
        # Create ascending SPY bars (Strong Bull)
        spy_bars = []
        for i in range(75):
            p = 400.0 + i * 2.5
            spy_bars.append(BinanceKlineBar(
                open_time_ms=1700000000000 + i * 86400000,
                o=p,
                h=p + 2.0,
                l=p - 0.5,
                c=p + 1.5,
                v=50000.0,
                close_time_ms=1700000000000 + (i + 1) * 86400000 - 1,
            ))

        # Create consolidating then breaking out SMH bars
        smh_bars = []
        for i in range(74):
            p = 200.0 + (i % 5) * 0.5
            smh_bars.append(BinanceKlineBar(
                open_time_ms=1700000000000 + i * 86400000,
                o=p,
                h=p + 2.0,
                l=p - 1.0,
                c=p + 0.5,
                v=10000.0,
                close_time_ms=1700000000000 + (i + 1) * 86400000 - 1,
            ))
        # Final breakout bar
        smh_bars.append(BinanceKlineBar(
            open_time_ms=1700000000000 + 74 * 86400000,
            o=203.0,
            h=210.0,
            l=202.5,
            c=209.5,
            v=50000.0,
            close_time_ms=1700000000000 + 75 * 86400000 - 1,
        ))

        candles = {"SPYUSDT": spy_bars, "SMHUSDT": smh_bars}
        self.engine.client.get_symbol_rules = MagicMock(return_value={
            "symbol": "SMHUSDT",
            "minQty": 0.01,
            "stepSize": 0.01,
            "tickSize": 0.01,
            "minNotional": 5.0,
        })

        plan = self.engine.evaluate_live_decision_plan(
            account_equity=100.0, historical_candles=candles, fetch_missing=False
        )
        self.assertEqual(plan["decision"], "EXECUTE_TRADE")
        self.assertEqual(plan["symbol"], "SMHUSDT")
        self.assertEqual(plan["effective_leverage"], 2.5)  # Dynamic bull 2.5X
        self.assertEqual(len(plan["orders"]), 2)  # Entry + Stop Loss

        entry_order = plan["orders"][0]
        self.assertEqual(entry_order["side"], "BUY")
        self.assertGreaterEqual(entry_order["notional"], 5.0)

        sl_order = plan["orders"][1]
        self.assertEqual(sl_order["side"], "SELL")
        self.assertEqual(sl_order["type"], "STOP_MARKET")
        self.assertTrue(sl_order["close_position"])

        # Execute in dry run
        exec_res = self.engine.execute_plan(plan)
        self.assertEqual(exec_res["status"], "SIMULATED_SUCCESS")
        self.assertIn("DRY_RUN", exec_res["mode"])


if __name__ == "__main__":
    unittest.main()
