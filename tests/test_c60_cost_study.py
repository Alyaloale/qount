import math
import random
import unittest

from qount.dual_engine.contracts import C60_SYMBOLS
from qount.dual_engine.strategy import build_c60_decision
from qount.research import c60_cost_study as study


def _synthetic_series(days: int = 500, seed: int = 7) -> dict[str, dict[str, float]]:
    rng = random.Random(seed)
    import datetime as dt

    start = dt.date(2024, 1, 1)
    series = {}
    for offset, symbol in enumerate(C60_SYMBOLS):
        price, drift = 100.0 + offset, (offset - 4) * 0.0015
        values = {}
        for day in range(days):
            price *= math.exp(drift + rng.gauss(0.0, 0.03))
            values[(start + dt.timedelta(days=day)).isoformat()] = price
        series[symbol] = values
    return series


class C60CostStudyTests(unittest.TestCase):
    def setUp(self):
        self.panel, self.audit = study.build_panel(_synthetic_series())

    def test_frozen_daily_targets_match_frozen_strategy(self):
        targets = study.target_path(self.panel, mode="frozen_daily")
        for index in range(study.WARMUP_BARS - 1, len(self.panel.dates)):
            window = {s: v[index - study.WARMUP_BARS + 1:index + 1] for s, v in self.panel.closes.items()}
            expected = build_c60_decision(window).target_weights
            self.assertEqual(set(expected), set(targets[index]))
            for symbol, weight in expected.items():
                self.assertAlmostEqual(weight, targets[index][symbol], places=12)

    def test_monthly_mode_only_changes_candidates_at_month_end(self):
        targets = study.target_path(self.panel, mode="research_monthly")
        held = None
        for index in range(study.WARMUP_BARS - 1, len(self.panel.dates)):
            window = {s: v[index - study.WARMUP_BARS + 1:index + 1] for s, v in self.panel.closes.items()}
            if study._is_month_end(self.panel.dates, index):
                held = study._rank_candidates(window)
            self.assertTrue(set(targets[index]) <= set(held or ()))

    def test_cost_is_turnover_times_rate(self):
        targets = study.target_path(self.panel, mode="frozen_daily")
        free = study.simulate(self.panel, targets, cost_bps=0.0)
        paid = study.simulate(self.panel, targets, cost_bps=25.0)
        self.assertAlmostEqual(paid.cost_fraction_sum, paid.turnover * 0.0025, places=12)
        self.assertAlmostEqual(free.turnover, paid.turnover, delta=paid.turnover * 0.01)
        self.assertLess(math.prod(1 + r for r in paid.returns), math.prod(1 + r for r in free.returns))

    def test_constant_full_weight_matches_buy_and_hold(self):
        targets = [{} for _ in self.panel.dates]
        for index in range(study.WARMUP_BARS - 1, len(self.panel.dates)):
            targets[index] = {"BTCUSDT": 1.0}
        result = study.simulate(self.panel, targets, cost_bps=25.0)
        btc = self.panel.closes["BTCUSDT"]
        expected = (1 - 0.0025) * btc[-1] / btc[study.WARMUP_BARS - 1]
        self.assertAlmostEqual(math.prod(1 + r for r in result.returns), expected, places=9)
        self.assertAlmostEqual(result.turnover, 1.0, places=9)

    def test_delay_shifts_execution_by_one_bar(self):
        targets = study.target_path(self.panel, mode="frozen_daily")
        delayed = study.simulate(self.panel, targets, cost_bps=0.0, delay_bars=1)
        self.assertEqual(delayed.dates[0], self.panel.dates[study.WARMUP_BARS + 1])

    def test_break_even_is_where_cagr_crosses_zero(self):
        targets = study.target_path(self.panel, mode="frozen_daily")
        even = study.break_even_bps(self.panel, targets)
        if 0.0 < even < 1_000.0:
            self.assertGreater(study.cagr(study.simulate(self.panel, targets, cost_bps=even * 0.9).returns), 0.0)
            self.assertLessEqual(study.cagr(study.simulate(self.panel, targets, cost_bps=even * 1.1).returns), 0.0)

    def test_fetch_drops_unclosed_bars_and_paginates(self):
        day = 86_400_000
        calls = []

        def getter(url, timeout):
            calls.append(url)
            start = int(url.split("startTime=")[1].split("&")[0])
            start = -(-start // day) * day  # like Binance: first bar opening at/after startTime
            count = 1000 if len(calls) == 1 else 3
            return [[start + i * day, "1", "1", "1", str(10 + i), "1", start + (i + 1) * day - 1] for i in range(count)]

        base = 18_500 * day
        observed = base + 1001 * day  # last two synthetic bars close at/after observed
        closes = study.fetch_daily_closes("BTCUSDT", observed_ms=observed, getter=getter, start_ms=base)
        self.assertEqual(len(calls), 2)
        # page 1: days 0..999; page 2: day 1000 kept, days 1001/1002 not closed before observed
        self.assertEqual(len(closes), 1001)

    def test_guards_are_fixed(self):
        results = study.run_study(self.panel, self.audit)
        self.assertTrue(results["research_only"])
        self.assertFalse(results["orders_authorized"])
        self.assertFalse(results["promotion_evidence"])
        self.assertEqual(set(results["trials"]), {"149", "150"})


if __name__ == "__main__":
    unittest.main()
