from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qount.alpha_agents.metrics import build_beta_residual_metrics
from qount.alpha_agents.metrics import load_return_rows
from qount.alpha_agents.promotion import evaluate_promotion_scorecard
from qount.alpha_agents.validation import ValidationConfig
from qount.alpha_agents.validation import assert_validation_matches_feature
from qount.alpha_agents.validation import build_validation_from_tradeflow_experiments
from qount.alpha_agents.validation import evaluate_validation_matrix
from qount.alpha_agents.validation import validation_meta
from qount.alpha_agents.validation import write_validation_artifact
from qount.settings import Settings


def _matrix(*, negative: bool = False) -> dict:
    start = dt.datetime(2024, 1, 1, 12, tzinfo=dt.UTC)
    count = 120
    labels = [((index % 17) - 8) / 10.0 for index in range(count)]
    timestamps = [str(int((start + dt.timedelta(days=index)).timestamp() * 1000)) for index in range(count)]
    daily = [(start + dt.timedelta(days=index)).strftime("%Y-%m-%d") for index in range(count)]
    robust_returns = [(-0.20 if negative else 0.20) + (0.04 if index % 2 else -0.04) for index in range(count)]
    candidates = [
        {
            "candidate_id": "robust",
            "strategy_returns_pct": robust_returns,
            "ic_feature_values": labels,
        },
        {
            "candidate_id": "inverse",
            "strategy_returns_pct": [-0.10 + (0.03 if index % 2 else -0.03) for index in range(count)],
            "ic_feature_values": [-value for value in labels],
        },
        {
            "candidate_id": "alternating",
            "strategy_returns_pct": [0.03 if index % 2 else -0.03 for index in range(count)],
            "ic_feature_values": [float(index % 2) for index in range(count)],
        },
        {
            "candidate_id": "weak",
            "strategy_returns_pct": [0.02 + (0.02 if index % 3 else -0.02) for index in range(count)],
            "ic_feature_values": [labels[(index + 11) % count] for index in range(count)],
        },
    ]
    if negative:
        for candidate in candidates[1:]:
            candidate["strategy_returns_pct"] = [
                -abs(value) - 0.01 for value in candidate["strategy_returns_pct"]
            ]
    return {
        "selection_metric": "rank_ic",
        "source_selected_candidate_id": "robust",
        "daily_timestamps": daily,
        "btc_returns_pct": [0.0] * count,
        "ic_timestamps": timestamps,
        "ic_residual_forward_returns_pct": labels,
        "candidates": candidates,
    }


class AlphaAgentsValidationTest(unittest.TestCase):
    def test_single_frozen_tradeflow_validation_is_pbo_blocking(self) -> None:
        contract = {"contract_id": "frozen", "contract_hash": "abc123"}

        def experiment(role: str, start: dt.datetime, count: int) -> dict:
            return {
                "schema_version": "alpha_agent_tradeflow_experiment_v0.1",
                "decision_contract": contract,
                "diagnostics": {"holdout_role": role},
                "periods": [
                    {
                        "ts": str(int((start + dt.timedelta(days=index)).timestamp() * 1000)),
                        "strategy_return_pct": 0.2,
                        "btc_return_pct": 0.05 if index % 2 else -0.05,
                    }
                    for index in range(count)
                ],
            }

        with tempfile.TemporaryDirectory() as tmp:
            discovery_path = Path(tmp) / "discovery.json"
            oos_path = Path(tmp) / "oos.json"
            discovery_path.write_text(
                json.dumps(experiment("discovery", dt.datetime(2024, 1, 1, tzinfo=dt.UTC), 30)),
                encoding="utf-8",
            )
            oos_path.write_text(
                json.dumps(experiment("historical_oos", dt.datetime(2024, 2, 1, tzinfo=dt.UTC), 10)),
                encoding="utf-8",
            )
            result = build_validation_from_tradeflow_experiments(
                discovery_path,
                oos_path,
                ValidationConfig(),
            )
        self.assertEqual(result["validation"]["pbo"], 1.0)
        self.assertTrue(result["validation"]["purged_cv_pass"])
        self.assertTrue(result["replay_candidate_parity"])
        self.assertEqual(result["diagnostics"]["contract_hash"], "abc123")
        self.assertEqual(
            result["diagnostics"]["pbo"]["method"],
            "not_identifiable_single_pre_registered_candidate",
        )

    def test_robust_matrix_passes_validation_fields(self) -> None:
        result = evaluate_validation_matrix(_matrix(), ValidationConfig())
        validation = result["validation"]
        self.assertGreater(validation["deflated_sharpe_ratio"], 0.95)
        self.assertLess(validation["pbo"], 0.5)
        self.assertTrue(validation["purged_cv_pass"])
        self.assertTrue(validation["embargo_applied"])
        self.assertGreater(validation["largest_contributor_removed_return_pct"], 0.0)

    def test_negative_matrix_stays_blocking(self) -> None:
        result = evaluate_validation_matrix(_matrix(negative=True), ValidationConfig())
        validation = result["validation"]
        self.assertFalse(validation["purged_cv_pass"])
        self.assertLessEqual(validation["largest_contributor_removed_return_pct"], 0.0)

    def test_validation_meta_can_fill_g4_without_filling_paper(self) -> None:
        result = evaluate_validation_matrix(_matrix(), ValidationConfig())
        payload = {
            "artifact_path": "/tmp/validation.json",
            "source_feature_experiment_path": "/tmp/feature.json",
            **result,
        }
        rows, meta, data_hash = load_return_rows("tests/fixtures/alpha_agent_returns.json")
        meta.update(validation_meta(payload))
        metrics = build_beta_residual_metrics(
            rows,
            source_label="validated-fixture",
            data_hash=data_hash,
            holdout_role="discovery",
            meta=meta,
        )
        scorecard = evaluate_promotion_scorecard(metrics, target="paper")
        blocked = {gate["gate_id"] for gate in scorecard["gates"] if gate["status"] == "block"}
        self.assertNotIn("G4", blocked)
        self.assertIn("G6", blocked)
        self.assertEqual(metrics["validation"]["artifact_path"], "/tmp/validation.json")

    def test_validation_source_must_match_feature(self) -> None:
        payload = {"source_feature_experiment_path": "/tmp/feature-a.json"}
        with self.assertRaises(ValueError):
            assert_validation_matches_feature(payload, "/tmp/feature-b.json")

    def test_validation_artifact_writer(self) -> None:
        evaluated = evaluate_validation_matrix(_matrix(), ValidationConfig())
        payload = {
            "schema_version": "alpha_agent_validation_v0.1",
            "source_feature_experiment_path": "/tmp/feature.json",
            **evaluated,
        }
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"QOUNT_PROJECT_ROOT": tmp}, clear=False
        ):
            artifact = write_validation_artifact(Settings.from_env(), payload)
            path = Path(artifact["artifact_path"])
            self.assertTrue(path.exists())
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["schema_version"], "alpha_agent_validation_v0.1")


if __name__ == "__main__":
    unittest.main()
