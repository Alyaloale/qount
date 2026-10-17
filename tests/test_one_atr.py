import unittest
from datetime import datetime, timezone

from qount.one_atr import DailyBar, build_signal, select_signal, wilder_atr
from scripts.operations.run_1atr_live import _bars, build_plan


def bars(n=140, start=100.0):
    return [DailyBar(i * 86400, start + i * 0.2, start + i * 0.5, start - 0.1 + i * 0.2, start + i * 0.3, 1000.0) for i in range(n)]


class OneAtrTest(unittest.TestCase):
    def test_runner_drops_current_incomplete_daily_bar(self):
        class FakeExchange:
            def fetch_ohlcv(self, _symbol, timeframe, limit):
                if timeframe != "1d":
                    raise AssertionError(f"unexpected timeframe: {timeframe}")
                complete = [[i * 86400000, 100, 101, 99, 100.5, 1] for i in range(121)]
                current = [121 * 86400000, 100, 140, 90, 130, 1]
                return complete + [current]

        rows = _bars(FakeExchange(), "BTCUSDT", 160, now=datetime(1970, 5, 2, tzinfo=timezone.utc))
        self.assertEqual(len(rows), 121)
        self.assertEqual(rows[-1].timestamp, 120 * 86400)

    def test_atr_requires_warmup_and_is_positive(self):
        with self.assertRaises(ValueError):
            wilder_atr(bars(14))
        self.assertGreater(wilder_atr(bars()), 0)

    def test_signal_is_causal_and_has_two_atr_stop(self):
        signal = build_signal("BTCUSDT", bars())
        self.assertEqual(signal.symbol, "BTCUSDT")
        self.assertEqual(signal.stop_price, signal.close - 2 * signal.atr)
        self.assertTrue(signal.eligible)

    def test_selection_uses_momentum_then_symbol(self):
        first = build_signal("BTCUSDT", bars())
        second = build_signal("ETHUSDT", bars(start=80.0))
        self.assertEqual(select_signal([first, second]).symbol, "ETHUSDT")
        self.assertIsNone(select_signal([first.__class__(**{**first.__dict__, "eligible": False})]))

    def test_runner_is_always_plan_only(self):
        class FakeExchange:
            def load_markets(self):
                return {}

        plan = build_plan(FakeExchange())
        self.assertEqual(plan["execution_mode"], "plan_only")
        self.assertTrue(plan["research_only"])
        self.assertFalse(plan["orders_authorized"])


if __name__ == "__main__":
    unittest.main()
