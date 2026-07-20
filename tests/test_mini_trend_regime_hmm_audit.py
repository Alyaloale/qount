from __future__ import annotations

import datetime as dt
import unittest
from unittest.mock import patch

from qount.mini_trend.futures_recovery_backtest import VariantResult
from qount.mini_trend.regime_hmm_audit import HMMAuditConfig
from qount.mini_trend.regime_hmm_audit import build_hmm_economic_audit


def _predictions(count: int) -> list[dict]:
    start = dt.date(2023, 1, 1)
    rows = []
    for index in range(count):
        score = -0.8 + 1.6 * index / max(count - 1, 1)
        bull = 0.1 + 0.7 * index / max(count - 1, 1)
        bear = bull - score
        remaining = max(1.0 - bull - bear, 0.01)
        total = bull + bear + remaining
        bull, bear, range_probability = bull / total, bear / total, remaining / total
        forward_return = score * 0.08
        rows.append(
            {
                "decision_date": (start + dt.timedelta(days=index)).isoformat(),
                "test_year": 2023,
                "actual_label": "bull" if score > 0.2 else "bear" if score < -0.2 else "range",
                "causal_stage": "transition_range",
                "probabilities": {
                    "bear": bear,
                    "bull": bull,
                    "range": range_probability,
                },
                "p_bear": bear,
                "p_bull": bull,
                "p_range": range_probability,
                "risk_score": bull - bear,
                "forward_return_horizon": forward_return,
                "forward_path_max_drawdown": max(-forward_return, 0.0),
                "forward_max_adverse_return": min(forward_return, 0.0),
                "forward_max_favorable_return": max(forward_return, 0.0),
                "forward_realized_volatility": 0.02,
            }
        )
    return rows


def _base_result(count: int) -> VariantResult:
    start = dt.date(2023, 1, 1)
    equity = 400.0
    rows = []
    for index in range(count):
        net_return = -0.001 + 0.002 * index / max(count - 1, 1)
        equity *= 1.0 + net_return
        rows.append(
            {
                "decision_date": (start + dt.timedelta(days=index)).isoformat(),
                "outcome_date": (start + dt.timedelta(days=index + 1)).isoformat(),
                "equity": equity,
                "gross": 0.5,
                "gross_price_return": net_return,
                "funding_return": 0.0,
                "trading_cost_return": 0.0,
                "net_return": net_return,
            }
        )
    return VariantResult(metrics={"return_pct": 0.0}, equity=rows)


class MiniTrendRegimeHMMAuditTest(unittest.TestCase):
    def test_economic_audit_is_deterministic_and_research_only(self) -> None:
        predictions = _predictions(120)
        folds = [
            {
                "test_year": year,
                "train_rows": 100,
                "test_rows": 30,
                "purge_check_passed": True,
                "brier_improvement_vs_constant": 0.01,
                "log_loss_improvement_vs_constant": 0.01,
            }
            for year in (2023, 2024, 2025, 2026)
        ]
        dataset = {
            "contract": {"contract_hash": "contract"},
            "data_hash": "data",
        }
        config = HMMAuditConfig(
            probability_bins=5,
            economic_horizon_days=10,
            bootstrap_block_days=10,
            bootstrap_samples=100,
            seed=7,
        )
        with patch(
            "qount.mini_trend.regime_hmm_audit._hmm_prediction_rows",
            return_value=(predictions, folds),
        ):
            left = build_hmm_economic_audit(dataset, _base_result(140), config)
            right = build_hmm_economic_audit(dataset, _base_result(140), config)
        self.assertEqual(
            left["economic_conditioning"]["block_bootstrap"],
            right["economic_conditioning"]["block_bootstrap"],
        )
        self.assertGreater(left["economic_conditioning"]["high_minus_low_top3_return"], 0)
        self.assertEqual(left["sample"]["economically_aligned_rows"], 120)
        self.assertFalse(left["meta"]["paper_or_live_allowed"])
        self.assertFalse(left["diagnostics"]["paper_or_live_allowed"])


if __name__ == "__main__":
    unittest.main()
