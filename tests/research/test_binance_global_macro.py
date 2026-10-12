from __future__ import annotations

import math
import unittest
from qount.research.binance_global_macro import (
    AssetBar,
    PositionState,
    StrategyConfig,
    compute_atr,
    compute_kaufman_efficiency_ratio,
    compute_sma,
    evaluate_macro_regimes,
    run_binance_global_macro_backtest,
)


class TestBinanceGlobalMacro(unittest.TestCase):
    def test_compute_sma(self) -> None:
        prices = [10.0, 20.0, 30.0, 40.0, 50.0]
        sma = compute_sma(prices, 3)
        self.assertTrue(math.isnan(sma[0]))
        self.assertTrue(math.isnan(sma[1]))
        self.assertAlmostEqual(sma[2], 20.0)
        self.assertAlmostEqual(sma[3], 30.0)
        self.assertAlmostEqual(sma[4], 40.0)

    def test_compute_atr_and_ker(self) -> None:
        bars = [
            AssetBar(
                date=f"2024-01-{i+1:02d}",
                open=100.0 + i,
                high=102.0 + i,
                low=99.0 + i,
                close=101.0 + i,
            )
            for i in range(25)
        ]
        atr = compute_atr(bars, end_idx=24, window=14)
        self.assertGreater(atr, 0.0)

        ker = compute_kaufman_efficiency_ratio(bars, end_idx=24, window=20)
        self.assertAlmostEqual(ker, 1.0, places=4)

    def test_evaluate_macro_regimes(self) -> None:
        crypto_bars = [
            AssetBar(date=f"2024-01-{i+1:03d}", open=100.0, high=105.0, low=95.0, close=100.0 + i)
            for i in range(140)
        ]
        us_bars = [
            AssetBar(date=f"2024-01-{i+1:03d}", open=100.0, high=105.0, low=95.0, close=100.0 - i)
            for i in range(140)
        ]
        c_bull, c_bear, u_bull = evaluate_macro_regimes(crypto_bars, us_bars, 135, 135)
        self.assertTrue(c_bull)
        self.assertFalse(c_bear)
        self.assertFalse(u_bull)

    def test_backtest_execution_bidirectional_futures(self) -> None:
        dates = [f"2024-01-{i+1:02d}" for i in range(30)]
        btc_bars = [
            AssetBar(date=d, open=50000.0 + i * 200, high=51000.0 + i * 200, low=49000.0 + i * 200, close=50500.0 + i * 200)
            for i, d in enumerate(dates)
        ]
        xlk_bars = [
            AssetBar(date=d, open=100.0 + i * 1, high=102.0 + i * 1, low=99.0 + i * 1, close=101.0 + i * 1)
            for i, d in enumerate(dates)
        ]
        market_data = {
            "BTCUSDT": btc_bars,
            "XLKBUSDT": xlk_bars,
        }
        res = run_binance_global_macro_backtest(
            market_data=market_data,
            calendar=dates,
            initial_capital=10_000.0,
            execution_delay=1,
        )
        self.assertGreater(res.final_equity, 0.0)
        self.assertEqual(len(res.nav_series), len(dates))

    def test_synthetic_trailing_stop_after_profit_lock(self) -> None:
        """Synthetic test: price rallies +40% (entering profit lock), then drops -20% from peak.
        Ensures ATR trailing stop MUST trigger and is never bypassed by profit lock branch."""
        # 140 warmup bars so macro is bull
        dates = [f"2024-{i//28+1:02d}-{i%28+1:02d}" for i in range(160)]
        btc_bars = [
            AssetBar(date=d, open=100.0 + i * 0.5, high=101.0 + i * 0.5, low=99.0 + i * 0.5, close=100.0 + i * 0.5)
            for i, d in enumerate(dates)
        ]
        # Target token: rally from 100 to 140 (+40%), then drop to 110 (-21.4% from peak 140)
        target_bars = []
        for i, d in enumerate(dates):
            if i < 140:
                p = 100.0
                target_bars.append(AssetBar(date=d, open=p, high=p + 1.0, low=p - 1.0, close=p))
            elif i < 150:
                # Rally to 140
                p = 100.0 + (i - 139) * 4.0
                target_bars.append(AssetBar(date=d, open=p - 2.0, high=p, low=p - 2.0, close=p))
            else:
                # Drop from 140 down to 110 (pullback 21.4% from 140 peak, but still above 100*1.08 = 108 lock buffer)
                p = 140.0 - (i - 149) * 3.0
                target_bars.append(AssetBar(date=d, open=p + 1.0, high=p + 1.0, low=p - 1.0, close=p))

        market_data = {
            "BTCUSDT": btc_bars,
            "ETHUSDT": target_bars,
        }
        res = run_binance_global_macro_backtest(
            market_data=market_data,
            calendar=dates,
            initial_capital=10_000.0,
            execution_delay=1,
        )
        # Verify that ETHUSDT triggered crypto_long_atr_trailing
        eth_exits = [t for t in res.trade_logs if t["symbol"] == "ETHUSDT"]
        self.assertTrue(len(eth_exits) > 0, "ETHUSDT should have been traded")
        self.assertEqual(eth_exits[0]["reason"], "crypto_long_atr_trailing", "Must exit via ATR trailing stop!")


if __name__ == "__main__":
    unittest.main()
