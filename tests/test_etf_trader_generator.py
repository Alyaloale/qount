import unittest

import numpy as np

from qount.research.etf_trader.generator import bootstrap as BS
from qount.research.etf_trader.generator import stylized as SF


def _garch(T, n=3, seed=0, omega=5e-7, a=0.04, b=0.94, gamma=0.03, df=5):
    """GJR-GARCH(1,1) with Student-t shocks and a common factor: should pass most facts."""
    rng = np.random.default_rng(seed)
    z = rng.standard_t(df, size=(T, n)) / np.sqrt(df / (df - 2))
    common = rng.standard_t(df, size=T) / np.sqrt(df / (df - 2))
    z = 0.7 * common[:, None] + np.sqrt(1 - 0.49) * z
    h = np.full(n, omega / (1 - a - b - gamma / 2))
    r = np.empty((T, n))
    for t in range(T):
        r[t] = np.sqrt(h) * z[t]
        h = omega + (a + gamma * (r[t] < 0)) * r[t] ** 2 + b * h
    return r


class StylizedTest(unittest.TestCase):
    def test_primitives(self):
        x = np.random.default_rng(1).standard_normal(20_000)
        self.assertLess(abs(SF.autocorr(x, 1)), 0.03)
        self.assertAlmostEqual(SF.kurtosis(x), 3.0, delta=0.15)
        self.assertAlmostEqual(SF.max_drawdown_from_log(np.array([np.log(0.5), 0.0])), 0.5)
        self.assertEqual(SF.monthly(np.ones((42, 2))).tolist(), [[21.0, 21.0], [21.0, 21.0]])

    def test_leverage_sign(self):
        r = _garch(40_000, n=1, seed=2, a=0.0, b=0.93, gamma=0.12)[:, 0]
        self.assertLess(SF.leverage_corr(r), 0.0)

    def test_garch_world_passes_core_facts(self):
        r = _garch(252 * 40, seed=3)
        tv = 1e8 * (1 + 50 * np.abs(r))  # volume rises with |r|
        checks = SF.world_checks(SF.WorldSample(r, np.array([True, True, False]), traded_value=tv))
        for fact in ("return_autocorr_max", "kurtosis_monthly_lower", "abs_return_autocorr_50",
                     "leverage_effect", "volume_abs_return_corr"):
            self.assertTrue(checks[fact][1], (fact, checks[fact][0]))

    def test_iid_gaussian_fails_clustering_and_tails(self):
        r = 0.01 * np.random.default_rng(4).standard_normal((252 * 20, 2))
        checks = SF.world_checks(SF.WorldSample(r, np.array([True, False])))
        self.assertFalse(checks["kurtosis_daily"][1])
        self.assertFalse(checks["abs_return_autocorr_50"][1])

    def test_gate_aggregation(self):
        res = [{"a": (1.0, True)}] * 8 + [{"a": (2.0, False)}] * 2
        res = [dict(r, tsmom_12m_sharpe=(0.5, True)) for r in res]
        g = SF.gate_pass_rate(res)
        self.assertTrue(g["a"]["passed"])
        self.assertTrue(g["tsmom_12m_sharpe"]["passed"])
        self.assertFalse(SF.gate_pass_rate([{"a": (1.0, False)}])["a"]["passed"])

    def test_dividend_yield_predictability(self):
        # log D/P mean-reverts and predicts returns: long horizon R² > short horizon R².
        rng = np.random.default_rng(5)
        T = 252 * 60
        dy = np.zeros(T)
        for t in range(1, T):
            dy[t] = 0.9995 * dy[t - 1] + 0.002 * rng.standard_normal()
        r = 0.0005 * dy + 0.01 * rng.standard_normal(T)
        self.assertGreater(SF.dividend_yield_r2(r, dy, 5 * 252), SF.dividend_yield_r2(r, dy, 21))


class BootstrapTest(unittest.TestCase):
    def test_block_lengths_and_sync(self):
        rng = np.random.default_rng(6)
        x = np.arange(1000 * 2, dtype=float).reshape(1000, 2)
        paths, idx = BS.bootstrap_paths(x, 5000, 2, mean_block=50, rng=rng)
        self.assertEqual(paths.shape, (2, 5000, 2))
        # Synchronous: both columns come from the same source row.
        np.testing.assert_array_equal(paths[..., 1] - paths[..., 0], np.ones((2, 5000)))
        breaks = np.sum(np.diff(idx, axis=1) != 1)
        mean_len = idx.size / (breaks + 2)
        self.assertTrue(35 < mean_len < 70, mean_len)

    def test_regime_conditioning(self):
        rng = np.random.default_rng(7)
        src_reg = np.repeat([0, 1, 0, 1], 250)
        x = np.column_stack([src_reg.astype(float), np.zeros(1000)])
        tgt = np.repeat([1, 0], [300, 200])
        paths, _ = BS.bootstrap_paths(x, 500, 3, 40, rng, src_reg, tgt)
        np.testing.assert_array_equal(paths[:, :, 0], np.tile(tgt.astype(float), (3, 1)))

    def test_nan_rows_dropped_and_errors(self):
        x = np.ones((50, 2)); x[10, 0] = np.nan
        paths, _ = BS.bootstrap_paths(x, 100, 1, 5, np.random.default_rng(8))
        self.assertTrue(np.isfinite(paths).all())
        with self.assertRaises(BS.BootstrapError):
            BS.draw_indices(10, 5, 2, np.random.default_rng(0), np.zeros(10), np.ones(5))


if __name__ == "__main__":
    unittest.main()
