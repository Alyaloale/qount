from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

from qount.alpha_agents.residual_trend_model import FEATURE_NAMES
from qount.alpha_agents.residual_trend_model import RESIDUAL_TREND_MODEL_VERSION
from qount.alpha_agents.residual_trend_model import FROZEN_RESIDUAL_TREND_MODEL_CONTRACT
from qount.alpha_agents.residual_trend_model import _fit_model
from qount.alpha_agents.residual_trend_model import _predict
from qount.alpha_agents.residual_trend_model import _walk_forward_cv
from qount.alpha_agents.residual_trend_model import aggregate_depth_to_hourly
from qount.alpha_agents.residual_trend_model import build_residual_trend_model_preregistration
from qount.alpha_agents.residual_trend_model import build_residual_trend_model_report


START_MS = 1_704_067_200_000


def _depth_rows() -> list[dict]:
    rows = []
    for bucket in range(24):
        value = 0.2 if bucket < 12 else -0.2
        rows.append(
            {
                "symbol": "ETHUSDT",
                "ts_ms": START_MS + bucket * 300_000,
                "snapshot_count": 10,
                "depth_imbalance_1pct_mean": value,
                "depth_imbalance_1pct_std": 0.1,
                "depth_imbalance_5pct_mean": value / 2,
                "depth_imbalance_5pct_std": 0.05,
                "near_depth_share_mean": 2.0,
                "complete": True,
                "segment_id": 0,
            }
        )
    return rows


def _model_rows(count: int = 300) -> list[dict]:
    rows = []
    for index in range(count):
        signal = math.sin(index / 7.0)
        features = [signal, signal / 2, abs(signal), 2.0, signal / 100, 0.0, signal, signal, 0.5, 0.0]
        rows.append(
            {
                "decision_ts_ms": START_MS + index * 3_600_000,
                "feature_values": features,
                "target": int(signal > 0),
                "residual_forward_return_pct": signal,
            }
        )
    return rows


def _experiment(symbol: str, passed: bool) -> dict:
    return {
        "schema_version": RESIDUAL_TREND_MODEL_VERSION,
        "artifact_type": "model_experiment",
        "config": {"strategy_symbol": symbol},
        "decision_contract": {"contract_hash": FROZEN_RESIDUAL_TREND_MODEL_CONTRACT.contract_hash},
        "diagnostics": {
            "verdict": "advance_to_independent_oos" if passed else "block_discovery",
            "blockers": [] if passed else ["auc_below_frozen_gate"],
            "prediction": {"auc": 0.6 if passed else 0.5, "rank_ic": 0.05 if passed else 0.0, "brier_improvement": 0.01 if passed else -0.01},
            "score": {"net_residual_return_pct": 2.0 if passed else -1.0},
            "execution": {"entry_count": 12, "max_rolling_24h_turnover": 2.0},
            "filter_diagnostics": {"filter_coverage": 1.0},
            "walk_forward": {"positive_rank_ic_fold_fraction": 0.8 if passed else 0.2},
            "anti_overfit": {"deflated_sharpe_ratio": 0.9, "pbo": 1.0},
        },
    }


class ResidualTrendModelTest(unittest.TestCase):
    def test_hourly_depth_pooling_preserves_snapshot_weighting(self) -> None:
        hourly = aggregate_depth_to_hourly(_depth_rows(), symbol="ETHUSDT")
        self.assertEqual(len(hourly), 2)
        self.assertAlmostEqual(hourly[0]["depth_imbalance_1pct_mean"], 0.2)
        self.assertAlmostEqual(hourly[1]["depth_imbalance_1pct_mean"], -0.2)
        self.assertEqual(hourly[0]["snapshot_count"], 120)

    def test_fixed_logistic_model_and_walk_forward_are_predictive_on_synthetic_data(self) -> None:
        rows = _model_rows()
        scaler, model = _fit_model(rows[:200], contract=FROZEN_RESIDUAL_TREND_MODEL_CONTRACT)
        probabilities = _predict(scaler, model, rows[200:])
        self.assertGreater(probabilities[0], 0.5 if rows[200]["target"] else 0.0)
        cv = _walk_forward_cv(rows, contract=FROZEN_RESIDUAL_TREND_MODEL_CONTRACT)
        self.assertEqual(cv["fold_count"], 5)
        self.assertGreater(cv["mean_auc"], 0.9)

    def test_preregistration_and_report_keep_sequence_model_disabled(self) -> None:
        preregistration = build_residual_trend_model_preregistration()
        self.assertFalse(preregistration["diagnostics"]["a10_sequence_enabled"])
        self.assertEqual(tuple(preregistration["contract"]["feature_names"]), FEATURE_NAMES)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prereg = root / "prereg.json"
            prereg.write_text(json.dumps(preregistration), encoding="utf-8")
            paths = []
            for symbol, passed in (("ETHUSDT", True), ("BNBUSDT", True), ("SOLUSDT", False)):
                path = root / f"{symbol}.json"
                path.write_text(json.dumps(_experiment(symbol, passed)), encoding="utf-8")
                paths.append(path)
            report = build_residual_trend_model_report(
                preregistration_path=prereg,
                experiment_paths=paths,
            )
        self.assertEqual(report["diagnostics"]["verdict"], "advance_to_reserved_oos_preregistration")
        self.assertFalse(report["diagnostics"]["a10_sequence_enabled"])
        self.assertEqual(report["diagnostics"]["pbo"], 1.0)


if __name__ == "__main__":
    unittest.main()
