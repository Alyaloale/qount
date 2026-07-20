from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from qount.mini_trend.forward import TOP3
from qount.mini_trend.futures_funding_veto import FUTURES_FUNDING_VETO_PROTOCOL
from qount.mini_trend.futures_funding_veto_attribution import ATTRIBUTION_GROUPS
from qount.mini_trend.futures_funding_veto_attribution import (
    FUNDING_VETO_ATTRIBUTION_PROTOCOL,
)
from qount.mini_trend.futures_funding_veto_attribution import _component_rows
from qount.mini_trend.futures_funding_veto_attribution import (
    build_funding_veto_attribution_preregistration,
)
from qount.mini_trend.futures_funding_veto_attribution import (
    exact_shapley_terminal_attribution,
)
from qount.mini_trend.futures_funding_veto_attribution import (
    validate_funding_veto_attribution_registration,
)
from qount.mini_trend.futures_funding_veto_report import FUNDING_VETO_REPORT_VERSION
from qount.mini_trend.futures_funding_veto_robustness import (
    FUNDING_VETO_ROBUSTNESS_REPORT_VERSION,
)
from qount.mini_trend.futures_funding_veto_robustness import (
    FUNDING_VETO_ROBUSTNESS_PROTOCOL,
)
from qount.mini_trend.futures_recovery import selected_um_rules
from qount.mini_trend.futures_recovery_backtest import VariantResult
from qount.mini_trend.futures_risk_tier import file_sha256


def _rules() -> dict:
    return {
        "market": "um",
        "source_type": "runtime_exchange_info",
        "rules": [
            {"symbol": symbol, "status": "TRADING", "min_qty": "0.001", "min_notional": "5"}
            for symbol in TOP3
        ],
    }


def _row(
    decision_date: str, gross: float, funding: float, trading_cost_return: float
) -> dict:
    return {
        "decision_date": decision_date,
        "outcome_date": decision_date,
        "gross_price_return": gross,
        "funding_return": funding,
        "trading_cost_return": trading_cost_return,
        "net_return": gross + funding + trading_cost_return,
    }


def _source_historical(path: Path, rules_hash: str) -> None:
    reference = {"return_pct": 1.0, "sharpe": 0.1, "max_drawdown_pct": 2.0}
    candidate = reference | {
        "funding_veto_activity": {"events": [{"decision_date": "2024-01-01"}]}
    }
    path.write_text(
        json.dumps(
            {
                "schema_version": FUNDING_VETO_REPORT_VERSION,
                "artifact_type": "mini_trend_um_funding_veto_historical_diagnostic",
                "contract_hash": FUTURES_FUNDING_VETO_PROTOCOL.contract_hash,
                "protocol_hash": FUTURES_FUNDING_VETO_PROTOCOL.protocol_hash,
                "exchange_rules_hash": rules_hash,
                "meta": {"holdout_role": "discovery_pool", "network_download_used": False},
                "diagnostics": {"verdict": "retain_historical_funding_veto_candidate"},
                "full_window": {
                    "data_hash": "fixed-data-hash",
                    "reference_stop_latch": reference,
                    "candidate": candidate,
                },
            }
        ),
        encoding="utf-8",
    )


def _robustness(path: Path, source_sha: str) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": FUNDING_VETO_ROBUSTNESS_REPORT_VERSION,
                "artifact_type": (
                    "mini_trend_um_funding_veto_robustness_historical_diagnostic"
                ),
                "contract_hash": FUNDING_VETO_ROBUSTNESS_PROTOCOL.contract_hash,
                "protocol_hash": FUNDING_VETO_ROBUSTNESS_PROTOCOL.protocol_hash,
                "source_historical_sha256": source_sha,
                "diagnostics": {
                    "verdict": "retain_historical_candidate_after_conditional_bootstrap"
                },
                "bootstrap": {"win_probabilities": {"return": 0.6}},
            }
        ),
        encoding="utf-8",
    )


class MiniTrendFuturesFundingVetoAttributionTest(unittest.TestCase):
    def test_exact_shapley_splits_compounding_interaction_and_closes(self) -> None:
        groups = {name: [0.0, 0.0] for name in ATTRIBUTION_GROUPS}
        groups["event_price_exposure"] = [0.10, 0.0]
        groups["event_funding"] = [0.0, 0.05]
        result = exact_shapley_terminal_attribution([0.0, 0.0], groups)
        contributions = result["group_contributions_percentage_points"]
        self.assertAlmostEqual(result["candidate_minus_reference_percentage_points"], 15.5)
        self.assertAlmostEqual(contributions["event_price_exposure"], 10.25)
        self.assertAlmostEqual(contributions["event_funding"], 5.25)
        self.assertAlmostEqual(result["closure_error_percentage_points"], 0.0)
        self.assertEqual(result["coalitions_evaluated"], 64)

    def test_component_rows_separate_event_and_downstream_deltas(self) -> None:
        reference = VariantResult(
            metrics={},
            equity=[
                _row("2024-01-01", 0.02, -0.003, -0.001),
                _row("2024-01-02", 0.01, -0.001, 0.0),
            ],
        )
        candidate = VariantResult(
            metrics={},
            equity=[
                _row("2024-01-01", 0.01, -0.002, -0.0015),
                _row("2024-01-02", 0.012, -0.0005, 0.0),
            ],
        )
        result = _component_rows(reference, candidate, ["2024-01-01"])
        self.assertAlmostEqual(result["groups"]["event_price_exposure"][0], -0.01)
        self.assertAlmostEqual(result["groups"]["event_funding"][0], 0.001)
        self.assertAlmostEqual(result["groups"]["downstream_price_exposure"][1], 0.002)
        self.assertAlmostEqual(result["groups"]["downstream_funding"][1], 0.0005)
        self.assertEqual(result["matched_event_count"], 1)
        self.assertEqual(result["downstream_divergent_bar_count"], 1)
        self.assertLess(result["maximum_daily_group_delta_closure_error"], 1e-15)

    def test_preregistration_binds_historical_and_robustness_artifacts(self) -> None:
        _, rules_hash = selected_um_rules(_rules())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            historical = root / "historical.json"
            robustness = root / "robustness.json"
            _source_historical(historical, rules_hash)
            _robustness(robustness, file_sha256(historical))
            preregistration = build_funding_veto_attribution_preregistration(
                _rules(), historical, robustness
            )
        self.assertFalse(preregistration["meta"]["attribution_results_evaluated"])
        self.assertEqual(preregistration["source_historical"]["event_count"], 1)
        self.assertEqual(
            preregistration["decision_contract"]["attribution"]["groups"],
            list(ATTRIBUTION_GROUPS),
        )
        self.assertEqual(
            preregistration["decision_contract"]["contract_hash"],
            FUNDING_VETO_ATTRIBUTION_PROTOCOL.contract_hash,
        )

    def test_registration_rejects_robustness_artifact_drift(self) -> None:
        _, rules_hash = selected_um_rules(_rules())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            historical = root / "historical.json"
            robustness = root / "robustness.json"
            _source_historical(historical, rules_hash)
            _robustness(robustness, file_sha256(historical))
            preregistration = build_funding_veto_attribution_preregistration(
                _rules(), historical, robustness
            )
            robustness.write_text(
                robustness.read_text(encoding="utf-8") + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "robustness hash mismatch"):
                validate_funding_veto_attribution_registration(
                    preregistration, _rules(), historical, robustness
                )


if __name__ == "__main__":
    unittest.main()
