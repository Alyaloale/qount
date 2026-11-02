"""Unit tests for the G20-LP v3 replayer (research script, loaded via importlib)."""
import importlib.util
from pathlib import Path
import unittest

import numpy as np

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "g20_v3_study", REPO / "scripts/research/study_g20_v3_carry_weight.py")
s3 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s3)
replay_v3 = s3.replay_v3


def _panel(symbols, closes):
    closes = np.asarray(closes, dtype=float)
    n, m = closes.shape
    return dict(
        symbols=tuple(symbols),
        times=1_700_000_000 + np.arange(n, dtype=np.int64) * 3600,
        open=closes.copy(), high=closes + 1.0, low=closes - 1.0,
        close=closes, mark_low=closes - 1.0,
        funding_value=np.zeros((n - 1, m)),
        funding_debit=np.zeros((n - 1, m)),
    )


class V3ReplayTests(unittest.TestCase):
    def test_equal_weight_entries_and_exact_recount(self):
        n = 30
        closes = np.repeat((100.0 + 0.2 * np.arange(n))[:, None], 3, axis=1)
        panel = _panel(("ETHUSDT", "SPYUSDT", "XLEUSDT"), closes)
        fund = np.zeros((n, 3))
        run = replay_v3(panel, fund, start=panel["times"][5], end=panel["times"][-1],
                        capital=300.0, gross=1.0, gate_threshold=None,
                        rebalance_bars=1, cost_bp=0.0)
        buys = [f for f in run["fills"] if f["side"] == "BUY" and f["reason"] == "weight_entry"]
        self.assertEqual(len(buys), 3)
        for f in buys:
            self.assertAlmostEqual(f["quantity"] * f["price"], 100.0, places=4)
        s = run["summary"]
        buy = sum(f["quantity"] * f["price"] for f in run["fills"] if f["side"] == "BUY")
        sell = sum(f["quantity"] * f["price"] for f in run["fills"] if f["side"] == "SELL")
        costs = sum(f["costs"] for f in run["fills"])
        self.assertAlmostEqual(s["final_usdt"], 300.0 - buy + sell - costs + s["funding_pnl"],
                               places=6)

    def test_funding_gate_cashes_rich_leg(self):
        n = 30
        closes = np.repeat((100.0 + 0.2 * np.arange(n))[:, None], 3, axis=1)
        panel = _panel(("ETHUSDT", "SPYUSDT", "XLEUSDT"), closes)
        fund = np.zeros((n, 3))
        fund[:, 0] = 0.20  # ETH funding 20%/yr -> gated at 6%
        run = replay_v3(panel, fund, start=panel["times"][5], end=panel["times"][-1],
                        capital=300.0, gross=1.0, gate_threshold=0.06,
                        rebalance_bars=1, cost_bp=0.0)
        traded = {f["symbol"] for f in run["fills"] if f["side"] == "BUY"}
        self.assertNotIn("ETHUSDT", traded)
        self.assertIn("SPYUSDT", traded)

    def test_bnb_is_exempt_from_gate(self):
        n = 30
        closes = np.repeat((100.0 + 0.2 * np.arange(n))[:, None], 2, axis=1)
        panel = _panel(("BNBUSDT", "SPYUSDT"), closes)
        fund = np.zeros((n, 2))
        fund[:, 0] = 0.20
        run = replay_v3(panel, fund, start=panel["times"][5], end=panel["times"][-1],
                        capital=200.0, gross=1.0, gate_threshold=0.06,
                        rebalance_bars=1, cost_bp=0.0)
        traded = {f["symbol"] for f in run["fills"] if f["side"] == "BUY"}
        self.assertIn("BNBUSDT", traded)

    def test_below_min_notional_target_closes_to_cash(self):
        n = 30
        closes = np.full((n, 1), 100.0)
        closes[12:, 0] = 60.0  # -40% crash halves the 1x book's equity
        panel = _panel(("SPYUSDT",), closes)
        fund = np.zeros((n, 1))
        filters = {"SPYUSDT": {"filters": [
            {"filterType": "MARKET_LOT_SIZE", "minQty": 0.001, "stepSize": 0.001, "maxQty": 1000},
            {"filterType": "MIN_NOTIONAL", "notional": 80.0}]}}
        run = replay_v3(panel, fund, start=panel["times"][5], end=panel["times"][-1],
                        capital=100.0, gross=1.0, gate_threshold=None,
                        rebalance_bars=1, cost_bp=0.0, filters=filters)
        sells = [f for f in run["fills"] if f["side"] == "SELL"]
        self.assertTrue(any(f["reason"] == "min_notional_exit" for f in sells))
        self.assertEqual(run["summary"]["counts"].get("min_notional_exit"), 1)


if __name__ == "__main__":
    unittest.main()
