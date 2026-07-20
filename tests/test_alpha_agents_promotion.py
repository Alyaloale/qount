from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qount.alpha_agents.promotion import evaluate_promotion_scorecard
from qount.alpha_agents.promotion import load_metrics
from qount.alpha_agents.promotion import write_promotion_scorecard_artifact
from qount.settings import Settings


def passing_metrics() -> dict:
    return {
        "proposal": {
            "label_spec": "beta residual next-bar net return",
            "benchmark_spec": "cash/BTC/TOP3/current live",
            "data_spec": "point-in-time Binance futures panel",
            "cost_spec": "taker+spread+funding+min-notional",
            "kill_line": "block on negative residual OOS",
            "beta_residual_target": True,
        },
        "data": {
            "point_in_time": True,
            "as_of_join": True,
            "replayable": True,
            "data_hash": "data-sha",
            "code_version": "git-sha",
            "config_hash": "cfg-sha",
            "holdout_role": "validation_v1",
            "trial_count": 12,
            "exchange_rules_source": "runtime_exchange_info",
            "filter_validator_reused": True,
        },
        "performance": {
            "net_residual_return_pct": 1.2,
            "beta_to_btc": 0.2,
        },
        "benchmarks": {
            "beats_cash": True,
            "beats_btc_buy_hold": True,
            "beats_top3_equal_weight": True,
            "beats_current_live_baseline": True,
        },
        "cost": {
            "net_after_cost_pct": 1.1,
            "worst_case_cost_net_pct": 0.2,
            "min_notional_coverage": 1.0,
            "required_maker_fill_ratio": 0.0,
            "actual_maker_fill_ratio": 0.0,
            "funding_included": True,
        },
        "validation": {
            "deflated_sharpe_ratio": 0.96,
            "pbo": 0.2,
            "purged_cv_pass": True,
            "largest_contributor_removed_return_pct": 0.1,
            "embargo_applied": True,
        },
        "breadth": {
            "effective_breadth": 2.5,
            "claims_cross_sectional_edge": True,
            "correlation_stress_pass": True,
            "capacity_checked": True,
        },
        "paper": {
            "holdout_role": "validation_v1",
            "forward_days": 30,
            "schema_errors": 0,
            "unmanaged_positions": 0,
            "unknown_price_filter_events": 0,
            "orders_replayable": True,
        },
        "live": {
            "dry_run_days": 7,
            "pilot_cap_usdt": 200.0,
            "withdrawal_disabled": True,
            "one_way_position_mode": True,
            "isolated_margin": True,
            "rollback_written": True,
        },
        "llm": {
            "used_for_orders": False,
            "used_for_target_weights": False,
            "used_for_risk_override": False,
        },
    }


class AlphaAgentsPromotionTest(unittest.TestCase):
    def test_passing_metrics_pass_paper_gate(self) -> None:
        scorecard = evaluate_promotion_scorecard(passing_metrics(), target="paper")
        self.assertEqual(scorecard["verdict"], "pass")
        self.assertEqual(scorecard["blocked_gate_count"], 0)

    def test_missing_beta_and_cost_blocks(self) -> None:
        metrics = passing_metrics()
        metrics["proposal"]["beta_residual_target"] = False
        metrics["cost"]["net_after_cost_pct"] = -0.1
        scorecard = evaluate_promotion_scorecard(metrics, target="paper")
        blocked = {gate["gate_id"]: gate for gate in scorecard["gates"] if gate["status"] == "block"}
        self.assertIn("G0", blocked)
        self.assertIn("G3", blocked)
        self.assertIn("missing_beta_residual_target", blocked["G0"]["reasons"])
        self.assertIn("net_after_cost_not_positive", blocked["G3"]["reasons"])

    def test_llm_usage_blocks_even_when_metrics_pass(self) -> None:
        metrics = passing_metrics()
        metrics["llm"]["used_for_orders"] = True
        scorecard = evaluate_promotion_scorecard(metrics, target="paper")
        blocked = {gate["gate_id"]: gate for gate in scorecard["gates"] if gate["status"] == "block"}
        self.assertIn("GX", blocked)
        self.assertIn("llm_used_for_orders", blocked["GX"]["reasons"])

    def test_live_gate_requires_dry_run_and_small_pilot(self) -> None:
        metrics = passing_metrics()
        metrics["live"]["dry_run_days"] = 3
        metrics["live"]["pilot_cap_usdt"] = 400.0
        scorecard = evaluate_promotion_scorecard(metrics, target="live_pilot")
        blocked = {gate["gate_id"]: gate for gate in scorecard["gates"] if gate["status"] == "block"}
        self.assertIn("G7", blocked)
        self.assertIn("dry_run_days_below_threshold", blocked["G7"]["reasons"])
        self.assertIn("pilot_cap_above_threshold", blocked["G7"]["reasons"])

    def test_metrics_loader_and_artifact_writer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            metrics_path = root / "metrics.json"
            metrics_path.write_text(json.dumps(passing_metrics()), encoding="utf-8")
            metrics = load_metrics(metrics_path)
            scorecard = evaluate_promotion_scorecard(metrics, target="paper")
            with patch.dict(os.environ, {"QOUNT_PROJECT_ROOT": tmp}, clear=False):
                artifact = write_promotion_scorecard_artifact(Settings.from_env(), scorecard)
            artifact_path = Path(artifact["artifact_path"])
            self.assertTrue(artifact_path.exists())
            artifact_path.relative_to(root / "state" / "research_runs")


if __name__ == "__main__":
    unittest.main()
