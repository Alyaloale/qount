from __future__ import annotations

import datetime as dt
import unittest

from qount.grid.data import Bar, Funding
from qount.mini_trend.forward import TOP3
from qount.mini_trend.regime_ml import FEATURE_NAMES
from qount.mini_trend.regime_ml import RegimeMLConfig
from qount.mini_trend.regime_ml import _blend_probabilities
from qount.mini_trend.regime_ml import _causal_hmm_filter
from qount.mini_trend.regime_ml import build_regime_ml_dataset
from qount.mini_trend.regime_ml import run_regime_ml_walk_forward


_DAY = 86_400_000
_T0 = int(dt.datetime(2021, 1, 1, tzinfo=dt.UTC).timestamp() * 1000)


def _bars(count: int, drift: float) -> list[Bar]:
    rows = []
    close = 100.0
    for index in range(count):
        close *= 1.0 + drift + (0.002 if index % 9 == 0 else -0.0002)
        rows.append(Bar(_T0 + index * _DAY, close, close * 1.01, close * 0.99, close, 1000.0))
    return rows


def _funding(count: int) -> list[Funding]:
    rows = []
    for index in range(count):
        open_ms = _T0 + index * _DAY
        rows.extend(
            [
                Funding(open_ms + 8 * 3_600_000, 0.00001),
                Funding(open_ms + 16 * 3_600_000, 0.00001),
                Funding(open_ms + _DAY, 0.00001),
            ]
        )
    return rows


class MiniTrendRegimeMLTest(unittest.TestCase):
    def test_probability_blend_is_fixed_and_normalized(self) -> None:
        blended = _blend_probabilities(
            [[0.6, 0.3, 0.1], [0.2, 0.3, 0.5]],
            [[0.2, 0.3, 0.5], [0.4, 0.4, 0.2]],
            left_weight=0.5,
        )
        expected = [[0.4, 0.3, 0.3], [0.3, 0.35, 0.35]]
        for actual_row, expected_row in zip(blended, expected):
            for actual, expected_value in zip(actual_row, expected_row):
                self.assertAlmostEqual(actual, expected_value)
        self.assertTrue(all(abs(sum(row) - 1.0) < 1e-12 for row in blended))

    def test_hmm_filter_is_causal_and_normalized(self) -> None:
        common = {
            "start_probability": [0.6, 0.3, 0.1],
            "transition_matrix": [
                [0.8, 0.1, 0.1],
                [0.1, 0.8, 0.1],
                [0.1, 0.1, 0.8],
            ],
            "means": [[-1.0], [0.0], [1.0]],
            "diagonal_covariances": [[0.5], [0.5], [0.5]],
        }
        left = _causal_hmm_filter([[-0.8], [0.1], [0.9]], **common)
        right = _causal_hmm_filter([[-0.8], [0.1], [-4.0]], **common)
        self.assertEqual(left[:2].tolist(), right[:2].tolist())
        self.assertTrue(all(abs(sum(row) - 1.0) < 1e-12 for row in left))

    def test_dataset_has_causal_features_and_triple_barrier_labels(self) -> None:
        count = 900
        bars = {symbol: _bars(count, 0.001 if symbol != "BNBUSDT" else 0.0008) for symbol in TOP3}
        funding = {symbol: _funding(count) for symbol in TOP3}
        dataset = build_regime_ml_dataset(
            bars,
            funding,
            RegimeMLConfig(start_date="2021-07-20", end_date="2023-05-01"),
        )
        self.assertGreater(dataset["summary"]["row_count"], 400)
        self.assertEqual(tuple(dataset["features"]), FEATURE_NAMES)
        self.assertEqual(sum(dataset["summary"]["label_counts"].values()), len(dataset["rows"]))
        self.assertTrue(set(row["label"] for row in dataset["rows"]).issubset({"bear", "range", "bull"}))
        self.assertTrue(all(row["label_end_date"] > row["decision_date"] for row in dataset["rows"]))
        self.assertTrue(all(row["horizon_end_date"] > row["decision_date"] for row in dataset["rows"]))
        self.assertTrue(
            all(0.0 <= row["forward_path_max_drawdown"] < 1.0 for row in dataset["rows"])
        )
        self.assertTrue(
            all(
                row["forward_max_adverse_return"] <= row["forward_max_favorable_return"]
                for row in dataset["rows"]
            )
        )

    def test_future_change_does_not_change_decision_features(self) -> None:
        count = 700
        original = {symbol: _bars(count, 0.0005) for symbol in TOP3}
        changed = {symbol: list(rows) for symbol, rows in original.items()}
        for symbol in TOP3:
            for index in range(500, count):
                prior = changed[symbol][index]
                changed[symbol][index] = Bar(
                    prior.ts_ms,
                    prior.open * 1.5,
                    prior.high * 1.5,
                    prior.low * 1.5,
                    prior.close * 1.5,
                    prior.volume,
                )
        funding = {symbol: _funding(count) for symbol in TOP3}
        config = RegimeMLConfig(start_date="2021-07-20", end_date="2022-03-01")
        left = build_regime_ml_dataset(original, funding, config)
        right = build_regime_ml_dataset(changed, funding, config)
        left_row = next(row for row in left["rows"] if row["decision_date"] == "2022-02-01")
        right_row = next(row for row in right["rows"] if row["decision_date"] == "2022-02-01")
        self.assertEqual(left_row["features"], right_row["features"])
        self.assertEqual(left_row["causal_stage"], right_row["causal_stage"])

    def test_walk_forward_purges_overlapping_training_labels(self) -> None:
        config = RegimeMLConfig()
        rows = []
        current = dt.date(2021, 7, 20)
        end = dt.date(2026, 5, 1)
        index = 0
        while current <= end:
            label = ("bear", "range", "bull")[index % 3]
            rows.append(
                {
                    "decision_date": current.isoformat(),
                    "label_end_date": (current + dt.timedelta(days=10)).isoformat(),
                    "label": label,
                    "causal_stage": {
                        "bear": "bear_cash",
                        "range": "transition_range",
                        "bull": "strong_bull",
                    }[label],
                    "features": {
                        name: float((index * (feature_index + 1)) % 17) / 17.0
                        for feature_index, name in enumerate(FEATURE_NAMES)
                    },
                }
            )
            current += dt.timedelta(days=1)
            index += 1
        dataset = {
            "contract": {**vars(config), "contract_hash": config.contract_hash},
            "data_hash": "synthetic",
            "rows": rows,
        }
        result = run_regime_ml_walk_forward(
            dataset,
            model_names=("logistic", "logistic_unweighted", "hist_gb"),
            model_trial_count=2,
        )
        self.assertEqual(result["diagnostics"]["verdict"], "discovery_models_evaluated")
        self.assertEqual(result["diagnostics"]["model_trial_count"], 2)
        self.assertTrue(result["diagnostics"]["all_purge_checks_passed"])
        self.assertGreaterEqual(len(result["folds"]), 2)
        self.assertTrue(
            all(fold["train_last_label_end_date"] < fold["test_first_date"] for fold in result["folds"])
        )


if __name__ == "__main__":
    unittest.main()
