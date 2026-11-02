"""Targeted checks for the independent offline factor experiment."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

_path = Path(__file__).resolve().parents[1] / "scripts/research/study_independent_crypto_factors.py"
_spec = importlib.util.spec_from_file_location("independent_factors", _path)
study = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(study)


def panel(days=8):
    return dict(times=np.arange(days) * study.DAY,
                dates=np.arange(np.datetime64("2021-01-01", "D"), np.datetime64("2021-01-01", "D") + np.timedelta64(days, "D")).astype(str),
                open=np.full((days, 7), 100.), beta=np.ones((days, 7)),
                funding_value=np.zeros((days, 7)))


class IndependentFactorTest(unittest.TestCase):
    def test_full_day_signal_delay(self):
        p = panel()
        p["open"][3:, -1] = 110.
        p["open"][4:, -1] = 120.
        score = np.tile(np.arange(7.), (8, 1))
        changed = score.copy()
        changed[1] *= -1
        a = study.simulate(p, score, start="2021-01-03", cadence=1, cost_bp=0)
        b = study.simulate(p, changed, start="2021-01-03", cadence=1, cost_bp=0)
        self.assertAlmostEqual(a["returns"][0], b["returns"][0])
        self.assertNotAlmostEqual(a["returns"][1], b["returns"][1])

    def test_fixed_quantity_cost_and_funding_ledger(self):
        p = panel(4)
        p["funding_value"][2, -1] = 1.  # rate * actual settlement mark, per contract
        score = np.tile(np.arange(7.), (4, 1))
        r = study.simulate(p, score, start="2021-01-03", cost_bp=10)
        self.assertAlmostEqual(r["funding_pnl"][0], -25.)
        self.assertAlmostEqual(r["costs"][0], 20.)  # entry plus final liquidation
        self.assertAlmostEqual(r["nav"][-1], .9955)

    def test_beta_projection_constraints_and_gross(self):
        beta = np.array([1., 1.2, 1.8, .8, 1.5, .9, 1.3])
        w = study.factor_weights(np.arange(7.), beta)
        self.assertAlmostEqual(w.sum(), 0.)
        self.assertAlmostEqual(w @ beta, 0.)
        self.assertAlmostEqual(np.abs(w).sum(), 1.)

    def test_features_do_not_change_when_future_is_appended(self):
        rng = np.random.default_rng(17)
        p = dict(close=100 * np.exp(np.cumsum(rng.normal(0, .01, (150, 7)), axis=0)),
                 quote=rng.uniform(1e6, 2e6, (150, 7)), daily_rate=rng.normal(0, .0001, (150, 7)))
        p["taker"] = p["quote"] * rng.uniform(.35, .65, (150, 7))
        a, beta_a = study.make_factors(p)
        b, beta_b = study.make_factors({k: v[:120] for k, v in p.items()})
        np.testing.assert_allclose(beta_a[:120], beta_b, equal_nan=True)
        for k in a:
            np.testing.assert_allclose(a[k][:120], b[k], equal_nan=True)

    def test_funding_boundary_uses_old_position_interval(self):
        data = {}
        for symbol in study.SYMBOLS:
            data[symbol + "_klines"] = [[d * study.DAY, 100, 101, 99, 100, 1,
                    (d + 1) * study.DAY - 1, 100, 1, .5, 50, 0] for d in range(3)]
            data[symbol + "_funding"] = [dict(fundingTime=h * 3_600_000,
                    fundingRate="0.01", markPrice=str(100 + h)) for h in range(0, 72, 8)]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "panel.json"
            path.write_text(json.dumps(dict(data=data, cutoff="1970-01-04T00:00:00Z", downloaded_at="test")))
            p = study.load_panel(path)
        # Entry at 00:00 excludes h=0, includes h=8,16 and following h=24.
        np.testing.assert_allclose(p["funding_value"][0], .01 * (108 + 116 + 124))
        np.testing.assert_allclose(p["daily_rate"][0], .03)

    def test_online_training_uses_only_mature_labels(self):
        rng = np.random.default_rng(19)
        p = panel(620)
        p["close"] = p["open"] = 100 * np.exp(np.cumsum(rng.normal(0, .01, (620, 7)), axis=0))
        p["quote"] = rng.uniform(1e6, 2e6, (620, 7))
        p["taker"] = p["quote"] * rng.uniform(.35, .65, (620, 7))
        p["daily_rate"] = rng.normal(0, .0001, (620, 7))
        f, b = study.make_factors(p)
        full, gate_full, fits = study.online_ridge_scores(p, f, b)
        short, gate_short, _ = study.online_ridge_scores({k: v[:580] for k, v in p.items()},
                                                {k: v[:580] for k, v in f.items()}, b[:580])
        np.testing.assert_allclose(full[:580], short)
        np.testing.assert_allclose(gate_full[:580], gate_short)
        for fit in fits:
            self.assertLessEqual(fit["last_training_outcome"], fit["signal_date"])


if __name__ == "__main__":
    unittest.main()
