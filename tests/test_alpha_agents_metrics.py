from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qount.alpha_agents.metrics import build_beta_residual_metrics
from qount.alpha_agents.metrics import load_return_rows
from qount.alpha_agents.metrics import write_beta_metrics_artifact
from qount.alpha_agents.promotion import evaluate_promotion_scorecard
from qount.settings import Settings


class AlphaAgentsMetricsTest(unittest.TestCase):
    def test_load_return_rows_and_build_beta_metrics(self) -> None:
        rows, meta, data_hash = load_return_rows("tests/fixtures/alpha_agent_returns.json")
        metrics = build_beta_residual_metrics(
            rows,
            source_label="fixture",
            data_hash=data_hash,
            holdout_role="discovery",
            meta=meta,
        )
        self.assertEqual(metrics["performance"]["period_count"], 3)
        self.assertGreater(metrics["performance"]["net_residual_return_pct"], 0.0)
        self.assertLess(metrics["performance"]["beta_to_btc"], 1.0)
        self.assertTrue(metrics["benchmarks"]["beats_btc_buy_hold"])
        self.assertTrue(metrics["cost"]["costs_included"])

    def test_metrics_default_missing_validation_blocks_promotion(self) -> None:
        rows, meta, data_hash = load_return_rows("tests/fixtures/alpha_agent_returns.json")
        metrics = build_beta_residual_metrics(
            rows,
            source_label="fixture",
            data_hash=data_hash,
            holdout_role="discovery",
            meta=meta,
        )
        scorecard = evaluate_promotion_scorecard(metrics, target="paper")
        blocked = {gate["gate_id"]: gate for gate in scorecard["gates"] if gate["status"] == "block"}
        self.assertIn("G4", blocked)
        self.assertIn("G6", blocked)
        self.assertIn("dsr_below_threshold", blocked["G4"]["reasons"])
        self.assertIn("paper_not_validation_v1", blocked["G6"]["reasons"])

    def test_csv_input_and_artifact_writer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "returns.csv"
            csv_path.write_text(
                "ts,strategy_return_pct,btc_return_pct,top3_equal_weight_return_pct,current_live_baseline_return_pct\n"
                "a,1,0,0,0\n"
                "b,1,0,0,0\n",
                encoding="utf-8",
            )
            rows, meta, data_hash = load_return_rows(csv_path)
            metrics = build_beta_residual_metrics(
                rows,
                source_label="csv",
                data_hash=data_hash,
                holdout_role="unknown",
                meta=meta,
            )
            with patch.dict(os.environ, {"QOUNT_PROJECT_ROOT": tmp}, clear=False):
                artifact = write_beta_metrics_artifact(Settings.from_env(), metrics)
            path = Path(artifact["artifact_path"])
            self.assertTrue(path.exists())
            path.relative_to(root / "state" / "research_runs")
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["schema_version"], "alpha_agent_beta_metrics_v0.1")


if __name__ == "__main__":
    unittest.main()
