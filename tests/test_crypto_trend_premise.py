import datetime as dt
import math
import random
import unittest

from qount.dual_engine.contracts import C60_SYMBOLS
from qount.research import c60_cost_study as study
from qount.research import crypto_trend_premise as premise


def _series(days: int = 900, seed: int = 11) -> dict[str, dict[str, float]]:
    rng = random.Random(seed)
    start = dt.date(2020, 9, 1)
    out = {}
    for offset, symbol in enumerate(C60_SYMBOLS):
        price, drift = 50.0 + offset, (offset - 4) * 0.001
        values = {}
        for day in range(days):
            price *= math.exp(drift + rng.gauss(0.0, 0.03))
            values[(start + dt.timedelta(days=day)).isoformat()] = price
        out[symbol] = values
    return out


class CryptoTrendPremiseTests(unittest.TestCase):
    def setUp(self):
        self.panel, _ = study.build_panel(_series())

    def test_decomposition_is_additive_and_matches_zero_cost_sim(self):
        dec = premise.decomposition(self.panel)
        targets = study.target_path(self.panel, mode=premise.MODE)
        sim = study.simulate(self.panel, targets, cost_bps=0.0)
        for year, row in dec["years"].items():
            self.assertAlmostEqual(row["beta"] + row["timing"] + row["selection"], row["total"], places=3)
            expected = sum(r for d, r in zip(sim.dates, sim.returns) if d[:4] == year)
            self.assertAlmostEqual(row["total"], expected, places=3)

    def test_spearman_known_values(self):
        self.assertAlmostEqual(premise.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertAlmostEqual(premise.spearman([1, 2, 3, 4], [4, 3, 2, 1]), -1.0)
        self.assertAlmostEqual(premise.spearman([1, 1, 2], [1, 1, 2]), 1.0)

    def test_run_shapes_and_guards(self):
        out = premise.run(self.panel)
        self.assertFalse(out["guards"]["trial"])
        self.assertFalse(out["guards"]["orders_authorized"])
        years = set(out["signal_validity"])
        self.assertTrue(years and min(years) >= premise.FIRST_YEAR)
        for row in out["cost_by_year"].values():
            self.assertGreaterEqual(row["cost"], -1e-9)
        for row in out["market_structure"].values():
            self.assertGreaterEqual(row["dispersion_30d"], 0.0)


if __name__ == "__main__":
    unittest.main()
