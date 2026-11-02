import unittest

import numpy as np

from qount.research.crypto_g20_hourly_portfolio import (
    PortfolioRule, _ranked_candidates,
)


class PortfolioSelectionTests(unittest.TestCase):
    def setUp(self):
        self.panel = {
            "symbols": ("ETHUSDT", "SOLUSDT", "SPYUSDT"),
            "close": np.ones((1, 3)),
        }
        self.rule = PortfolioRule(max_positions=2, core_mode="dual")

    def features(self, crypto=True, etf=True):
        rank = np.array([[.3, .2, .1]])
        trend = np.array([[.3, .2, .1 if etf else -.1]])
        mean = np.array([[0., 0., 0.]])
        close = np.array([[1., 1., 1.]])
        return {"rank_return": rank, "trend_return": trend, "trend_mean": mean}

    def test_missing_etf_does_not_replace_crypto_with_crypto(self):
        f = self.features(etf=False)
        self.assertEqual(_ranked_candidates(self.panel, f, 0, self.rule, {0}), [])

    def test_missing_core_is_filled_before_extra_slot(self):
        f = self.features()
        self.assertEqual(_ranked_candidates(self.panel, f, 0, self.rule, {0}), [2])


if __name__ == "__main__":
    unittest.main()
