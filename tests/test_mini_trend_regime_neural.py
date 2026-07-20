from __future__ import annotations

import datetime as dt
import unittest

from qount.mini_trend.regime_ml import FEATURE_NAMES
from qount.mini_trend.regime_neural import RegimeGRUConfig, build_sequence_samples


class MiniTrendRegimeNeuralTest(unittest.TestCase):
    def test_sequence_samples_are_causal_and_contiguous(self) -> None:
        rows = []
        start = dt.date(2021, 1, 1)
        for index in range(80):
            rows.append(
                {
                    "decision_date": (start + dt.timedelta(days=index)).isoformat(),
                    "label_end_date": (start + dt.timedelta(days=index + 10)).isoformat(),
                    "label": ("bear", "bull", "range")[index % 3],
                    "features": {
                        name: float(index + feature_index)
                        for feature_index, name in enumerate(FEATURE_NAMES)
                    },
                }
            )
        samples = build_sequence_samples(rows, 60)
        self.assertEqual(len(samples), 21)
        self.assertEqual(samples[0]["decision_date"], "2021-03-01")
        self.assertEqual(samples[0]["values"].shape, (60, len(FEATURE_NAMES)))
        self.assertEqual(samples[0]["values"][-1, 0], 59.0)
        self.assertEqual(RegimeGRUConfig().trial_count, 1)


if __name__ == "__main__":
    unittest.main()
