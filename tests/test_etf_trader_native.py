import datetime as dt
import json
import unittest
from pathlib import Path

import numpy as np

from qount.research.etf_trader.generator import native
from qount.research.etf_trader.generator import stylized as SF
from qount.research.etf_trader.generator import targets as TG
from qount.research.etf_trader.generator.calibration import DEFAULT_TARGETS, calibration_report
from qount.research.etf_trader.generator.params import sample_world
from qount.research.etf_trader.generator.specs import ACCOUNT_SPECS
from qount.research.etf_trader.generator.structural import simulate_world


def _fields(w):
    d = w.data
    return dict(close_adj=d.close_adj, close=d.close, open=d.open, adv=d.adv, sigma=d.sigma, spread=d.spread,
                cash=d.cash_return, valuation=w.valuation, tv=w.traded_value, mu=w.truth.mu, var=w.truth.var,
                regime=w.truth.regime, pe=w.truth.pe, rate=w.truth.rate, erp=w.truth.erp, quota=w.truth.quota,
                drought=w.truth.drought, fx=w.truth.fx_log)


@unittest.skipUnless(native.available(), "no C++ compiler: native kernel not built")
class NativeKernelTest(unittest.TestCase):
    def test_matches_numpy_reference(self):
        # Same draws, same expression order, no FMA / fast-math: agreement to rounding
        # (bitwise on the Mac toolchain; the tolerance covers other libm builds).
        for acct in ("us", "cn"):
            for seed in (0, 7, 21):
                p = sample_world(acct, np.random.default_rng(seed))
                a = _fields(simulate_world(ACCOUNT_SPECS[acct], p, years=12.0, warmup_years=4.0, backend="numpy"))
                b = _fields(simulate_world(ACCOUNT_SPECS[acct], p, years=12.0, warmup_years=4.0, backend="native"))
                for k in a:
                    np.testing.assert_allclose(np.asarray(b[k], float), np.asarray(a[k], float),
                                               rtol=1e-9, atol=1e-14, equal_nan=True, err_msg=f"{acct}/{seed}/{k}")

    def test_abi_matches_loader(self):
        self.assertEqual(native.load().qount_kernel_abi(), native.ABI)

    def test_helpers_match_numpy(self):
        rng = np.random.default_rng(3)
        z = rng.standard_normal((500, 4))
        ar = native.ar1(z, 0.97, 0.1)
        ref = np.zeros_like(z)
        for t in range(1, 500):
            ref[t] = 0.97 * ref[t - 1] + 0.1 * z[t]
        np.testing.assert_allclose(ar, ref, rtol=1e-12, atol=1e-15)

    def test_unknown_backend_rejected(self):
        p = sample_world("us", np.random.default_rng(0))
        with self.assertRaises(ValueError):
            simulate_world(ACCOUNT_SPECS["us"], p, years=1.0, warmup_years=1.0, backend="gpu")


class TargetsTest(unittest.TestCase):
    def _series(self, T=1500, seed=0, phi=0.0):
        rng = np.random.default_rng(seed)
        e = 0.01 * rng.standard_normal(T)
        r = np.empty(T)
        r[0] = e[0]
        for t in range(1, T):
            r[t] = phi * r[t - 1] + e[t]
        days = [(dt.date(2005, 1, 3) + dt.timedelta(days=i)).isoformat() for i in range(T + 1)]
        close = 1000 * np.exp(np.r_[0, np.cumsum(r)])
        return list(zip(days, close.tolist()))

    def test_bootstrap_se_near_iid_for_iid_series(self):
        r = 0.01 * np.random.default_rng(1).standard_normal(2500)
        se = TG.stationary_bootstrap_se(r, draws=300)
        np.testing.assert_allclose(se, TG.iid_autocorr_se(2500), rtol=0.25)

    def test_build_round_trip_and_gate(self):
        series = {code: self._series(seed=i, phi=0.1 if code == "sz399006" else 0.0)
                  for i, (_, code) in enumerate(TG.CN_INDEX_FOR_COLUMN.values())}
        tg = TG.build_cn_targets(series, draws=200)
        again = TG.CalibrationTargets.from_json(tg.to_json())
        self.assertEqual(again, tg)
        chinext = next(a for a in tg.autocorr if a.index == "sz399006")
        self.assertGreater(chinext.rho[0], 0.04)
        # a world drawn from the same process passes its cells; a world with the wrong sign fails lag 1
        n = ACCOUNT_SPECS["cn"].n
        same = np.zeros((1500, n))
        flip = np.zeros((1500, n))
        for k, (_, code) in TG.CN_INDEX_FOR_COLUMN.items():
            x = np.diff(np.log([c for _, c in self._series(seed=50 + k, phi=0.1 if code == "sz399006" else 0.0)]))
            same[:, k] = x
            flip[:, k] = np.diff(np.log([c for _, c in self._series(seed=50 + k, phi=-0.1 if code == "sz399006" else 0.0)]))
        cells_same = TG.autocorr_cells(same, tg)
        cells_flip = TG.autocorr_cells(flip, tg)
        self.assertTrue(cells_same["autocorr:159915:lag1"][1])
        self.assertFalse(cells_flip["autocorr:159915:lag1"][1])

    def test_fetch_pages_and_filters_window(self):
        calls = []

        def getter(url):
            calls.append(url)
            start = url.split(",day,")[1].split(",")[0]
            day0 = dt.date.fromisoformat(start)
            rows = [[(day0 + dt.timedelta(days=i)).isoformat(), "1", str(100 + i), "1", "1", "1"] for i in range(400)]
            return json.dumps({"data": {"sh000300": {"day": rows}}}).encode()

        rows = TG.fetch_tencent_index(getter, "sh000300", dt.date(2005, 1, 1), dt.date(2014, 12, 31))
        self.assertGreater(len(calls), 1)
        self.assertTrue(all("2005-01-01" <= d <= "2014-12-31" for d, _ in rows))
        self.assertEqual([d for d, _ in rows], sorted(d for d, _ in rows))

    def test_committed_targets_load(self):
        tg = TG.CalibrationTargets.from_json(Path(DEFAULT_TARGETS["cn"]).read_text())
        self.assertEqual(tg.account, "cn")
        self.assertEqual({a.etf for a in tg.autocorr}, {"510300", "510500", "159915", "510050"})
        self.assertIsNone(tg.dy_r2_5y)
        self.assertTrue(all(a.last_day <= "2014-12-31" for a in tg.autocorr))  # never touches the §9 test window

    def test_dy_r2_pending_without_target(self):
        r = 0.01 * np.random.default_rng(2).standard_t(4, (252 * 12, 2))
        dy = np.cumsum(0.001 * np.random.default_rng(3).standard_normal((252 * 12, 1)), axis=0)
        checks = SF.world_checks(SF.WorldSample(r, np.array([True, False]), log_dividend_yield=dy))
        self.assertEqual(checks["dy_r2_5y"][1], SF.PENDING)
        gates = SF.gate_pass_rate([checks, checks])
        self.assertTrue(gates["dy_r2_5y"]["needs_calibration"])
        self.assertFalse(gates["dy_r2_5y"]["passed"])

    def test_report_uses_targets_and_is_worker_invariant(self):
        a = calibration_report("cn", 3, seed=5, plausibility_years=30.0, stylized_years=12.0, workers=1)
        b = calibration_report("cn", 3, seed=5, plausibility_years=30.0, stylized_years=12.0, workers=2)
        self.assertIsNotNone(a["targets_sha256"])
        self.assertIn("autocorr_calibrated", a["stylized"])
        self.assertIn("dy_r2_5y", a["stylized_undecided"])
        self.assertEqual(json.dumps(a["stylized"], sort_keys=True), json.dumps(b["stylized"], sort_keys=True))


if __name__ == "__main__":
    unittest.main()
