import importlib.util
from pathlib import Path
import unittest

import numpy as np

_path = Path(__file__).resolve().parents[1] / "scripts/research/study_position_flow.py"
_spec = importlib.util.spec_from_file_location("position_flow", _path)
study = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(study)


class PositionFlowTest(unittest.TestCase):
    def test_metric_join_enforces_publication_lag_and_staleness(self):
        def row(minute, value):
            return dict(create_time=f"1970-01-01 00:{minute:02d}:00", sum_open_interest=str(value),
                        sum_toptrader_long_short_ratio="1", count_toptrader_long_short_ratio="1",
                        count_long_short_ratio="1")
        x, coverage = study.asof_metrics([row(54, ""), row(55, 100), row(56, 999)], np.array([0, study.HOUR]))
        self.assertEqual(x[0, 0], 100)
        self.assertTrue(np.isnan(x[1, 0]))
        self.assertEqual(coverage["hourly_missing"], 1)
        self.assertEqual(coverage["invalid_rows"], 1)

    def test_event_execution_delay_funding_boundary_and_cooldown(self):
        times = np.arange(280) * study.HOUR
        future = np.zeros((280, 12)); future[:, 1] = 100
        signal = np.ones(280)
        funding = [dict(fundingTime=i * study.HOUR, fundingRate=".001", markPrice="100")
                   for i in (202, 203, 226)]
        events = study.event_study("BTCUSDT", times, future, {"test":signal}, np.ones(280), funding)
        self.assertEqual(events[0]["entry_ms"], 202 * study.HOUR)
        self.assertEqual(events[0]["signal_ms"], 201 * study.HOUR)
        self.assertAlmostEqual(events[0]["funding_6h_bp"], -10)
        self.assertAlmostEqual(events[0]["funding_24h_bp"], -20)
        self.assertGreaterEqual(events[1]["entry_ms"] - events[0]["entry_ms"], 24 * study.HOUR)

    def test_evaluation_window_excludes_warmup_entries_and_late_exits(self):
        times = np.arange(280) * study.HOUR
        future = np.zeros((280, 12)); future[:, 1] = 100
        events = study.event_study("BTCUSDT", times, future, {"test":np.ones(280)},
                    np.ones(280), [], entry_start_ms=220 * study.HOUR, end_ms=245 * study.HOUR)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["entry_ms"], 220 * study.HOUR)

    def test_position_signals_do_not_use_future_rows(self):
        rng = np.random.default_rng(27)
        f = np.ones((600, 12)); s = f.copy()
        f[:, 4] = 100 * np.exp(np.cumsum(rng.normal(0, .01, 600)))
        s[:, 4] = f[:, 4]
        s[:, 7] = rng.uniform(1e6, 2e6, 600)
        s[:, 10] = s[:, 7] * rng.uniform(.3, .7, 600)
        metrics = np.exp(np.cumsum(rng.normal(0, .01, (600, 4)), axis=0))
        btc = rng.normal(0, .01, 600)
        full, beta = study.signal_set(f, s, metrics, btc)
        short, short_beta = study.signal_set(f[:500], s[:500], metrics[:500], btc[:500])
        for key in full:
            np.testing.assert_array_equal(full[key][:500], short[key])
        np.testing.assert_allclose(beta[:500], short_beta, equal_nan=True)


if __name__ == "__main__":
    unittest.main()
