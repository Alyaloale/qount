import datetime as dt
import json
import math
import random
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from qount.research import cta_r_us_replication as rep
from qount.research.cta_r_paper import REBALANCE_DAYS, _weights


def _series(days: int = 2000, seed: int = 3) -> dict[str, dict[str, float]]:
    rng = random.Random(seed)
    start = dt.date(2008, 1, 1)
    out = {}
    for offset, symbol in enumerate(sorted(rep.UNIVERSE)):
        price, drift = 100.0, (offset - 3) * 0.0002
        values = {}
        day, count = start, 0
        while count < days:
            if day.weekday() < 5:
                price *= math.exp(drift + rng.gauss(0.0, 0.012))
                values[day.isoformat()] = price
                count += 1
            day += dt.timedelta(days=1)
        out[symbol] = values
    return out


class CtaRUsReplicationTests(unittest.TestCase):
    def setUp(self):
        self.series = _series()
        self.dates, self.prices, _ = rep.align(self.series)

    def test_replay_matches_frozen_weights_and_cost(self):
        free = rep.replay(self.dates, self.prices, cost=0.0)
        paid = rep.replay(self.dates, self.prices, cost=0.001)
        self.assertEqual(free["dates"], paid["dates"])
        self.assertLess(math.prod(1 + r for r in paid["returns"]), math.prod(1 + r for r in free["returns"]))
        # First rebalance uses the unchanged frozen rule.
        symbols = sorted(self.prices)
        returns = {s: [0.0] + [self.prices[s][i] / self.prices[s][i - 1] - 1.0 for i in range(1, len(self.dates))]
                   for s in symbols}
        first = next(i for i in range(253, len(self.dates)) if i % REBALANCE_DAYS == 0)
        expected = _weights({s: list(self.prices[s]) for s in symbols}, returns, first)
        self.assertTrue(all(w <= 0.35 + 1e-12 for w in expected.values()))
        self.assertLessEqual(sum(expected.values()), 1.0 + 1e-12)

    def test_evaluate_shapes_gates_and_guards(self):
        series = {s: {d: v for d, v in values.items()} for s, values in self.series.items()}
        result = rep.evaluate(series)
        self.assertEqual(set(result["gates"]), {"R1_sharpe_10bps", "R2_sharpe_20bps", "R3_positive_folds",
                                                 "R4_both_halves_positive", "R5_max_drawdown"})
        self.assertIn(result["verdict"], {"replicated", "not_replicated"})
        self.assertEqual(len(result["fold_sharpes"]), rep.FOLDS)
        self.assertFalse(result["guards"]["orders_authorized"])
        self.assertEqual(result["trial"], "151")

    def test_fetch_uses_header_token_and_filters_rows(self):
        seen = {}

        def getter(url, headers):
            seen["url"], seen["headers"] = url, dict(headers)
            return [{"date": "2020-01-02T00:00:00.000Z", "adjClose": 10.0},
                    {"date": "2020-01-03T00:00:00.000Z", "adjClose": None}]

        out = rep.fetch_adjusted_closes("SPY", token="t0k", end=dt.date(2020, 1, 10), getter=getter)
        self.assertEqual(out, {"2020-01-02": 10.0})
        self.assertNotIn("t0k", seen["url"])
        self.assertEqual(seen["headers"]["Authorization"], "Token t0k")
        with self.assertRaises(rep.CtaRUsReplicationError):
            rep.fetch_adjusted_closes("SPY", token="", end=dt.date(2020, 1, 10), getter=getter)

    def test_per_symbol_tiingo_cache_reuses_history_and_fetches_from_cached_tail(self):
        end = dt.date(2026, 10, 10)
        calls = []

        def getter(url, headers):
            calls.append((url, dict(headers)))
            return [
                {"date": "2026-10-09T00:00:00Z", "adjClose": 101.0},
                {"date": "2026-10-10T00:00:00Z", "adjClose": 102.0},
            ]

        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "tiingo_SPY.json"
            fetched, source = rep.load_or_fetch_adjusted_closes(
                "SPY", token="fixture-key", end=end, cache_path=cache_path, getter=getter
            )
            cached, cached_source = rep.load_or_fetch_adjusted_closes(
                "SPY", token="", end=end, cache_path=cache_path, getter=getter
            )
            later, later_source = rep.load_or_fetch_adjusted_closes(
                "SPY",
                token="fixture-key",
                end=dt.date(2026, 10, 12),
                cache_path=cache_path,
                getter=getter,
            )
            stored = json.loads(cache_path.read_text())
            cache_text = cache_path.read_text()

        self.assertEqual(source, "network")
        self.assertEqual(cached_source, "cache")
        self.assertEqual(fetched, cached)
        self.assertEqual(later_source, "network")
        self.assertEqual(len(calls), 2)
        self.assertEqual(parse_qs(urlparse(calls[1][0]).query)["startDate"], ["2026-10-09"])
        self.assertEqual(later["2026-10-10"], 102.0)
        self.assertNotIn("fixture-key", cache_text)
        self.assertEqual(stored, later)

    def test_benchmark_monthly_rebalance_holds_weights(self):
        ret = rep.benchmark(self.dates, self.prices, {"SPY": 1.0}, first=self.dates[300], cost=0.0)
        spy = self.prices["SPY"]
        start = self.dates.index(self.dates[300])
        self.assertAlmostEqual(math.prod(1 + r for r in ret), spy[-1] / spy[start - 1], places=9)


if __name__ == "__main__":
    unittest.main()
