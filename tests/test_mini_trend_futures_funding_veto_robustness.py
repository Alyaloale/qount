from __future__ import annotations

import json
import random
import tempfile
import unittest
from pathlib import Path

from qount.mini_trend.forward import TOP3
from qount.mini_trend.futures_funding_veto import FUNDING_VETO_PREREG_VERSION
from qount.mini_trend.futures_funding_veto import FUTURES_FUNDING_VETO_PROTOCOL
from qount.mini_trend.futures_funding_veto_report import FUNDING_VETO_REPORT_VERSION
from qount.mini_trend.futures_funding_veto_robustness import (
    FUNDING_VETO_ROBUSTNESS_PROTOCOL,
)
from qount.mini_trend.futures_funding_veto_robustness import (
    build_funding_veto_robustness_preregistration,
)
from qount.mini_trend.futures_funding_veto_robustness import circular_moving_block_indices
from qount.mini_trend.futures_funding_veto_robustness import paired_moving_block_bootstrap
from qount.mini_trend.futures_funding_veto_robustness import (
    validate_funding_veto_robustness_registration,
)


def _rules() -> dict:
    return {
        "market": "um",
        "source_type": "runtime_exchange_info",
        "rules": [
            {"symbol": symbol, "status": "TRADING", "min_qty": "0.001", "min_notional": "5"}
            for symbol in TOP3
        ],
    }


def _parent(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": FUNDING_VETO_PREREG_VERSION,
                "decision_contract": {"contract_hash": FUTURES_FUNDING_VETO_PROTOCOL.contract_hash},
                "protocol": {"protocol_hash": FUTURES_FUNDING_VETO_PROTOCOL.protocol_hash},
            }
        ),
        encoding="utf-8",
    )


def _historical(path: Path, rules_hash: str) -> None:
    metric = {"return_pct": 1.0, "sharpe": 0.1, "max_drawdown_pct": 2.0}
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
                    "reference_stop_latch": metric,
                    "candidate": metric,
                    "funding_veto_event_audit": {"event_count": 17},
                },
            }
        ),
        encoding="utf-8",
    )


class MiniTrendFuturesFundingVetoRobustnessTest(unittest.TestCase):
    def test_circular_blocks_preserve_local_order_and_length(self) -> None:
        indices = circular_moving_block_indices(random.Random(7), 7, 3)
        self.assertEqual(len(indices), 7)
        for offset in (0, 1, 3, 4):
            self.assertEqual(indices[offset + 1], (indices[offset] + 1) % 7)

    def test_paired_bootstrap_is_deterministic(self) -> None:
        reference = [0.01, -0.02, 0.005, 0.0, 0.008] * 5
        candidate = [0.011, -0.015, 0.006, 0.0, 0.009] * 5
        kwargs = {
            "block_length": 5,
            "samples": 100,
            "seed": 42,
            "periods_per_year": 365.0,
        }
        first = paired_moving_block_bootstrap(reference, candidate, **kwargs)
        second = paired_moving_block_bootstrap(reference, candidate, **kwargs)
        self.assertEqual(first, second)
        self.assertEqual(first["sample_count"], 100)
        self.assertEqual(
            first["win_probabilities"]["candidate_terminal_return_above_reference"], 1.0
        )
        self.assertGreater(
            first["delta_distributions"]["terminal_return_percentage_points"]["median"], 0.0
        )

    def test_identical_sequences_do_not_count_ties_as_wins(self) -> None:
        returns = [0.01, -0.005, 0.0, 0.002] * 5
        report = paired_moving_block_bootstrap(
            returns,
            returns,
            block_length=4,
            samples=20,
            seed=3,
            periods_per_year=365.0,
        )
        self.assertEqual(
            report["win_probabilities"],
            {
                "candidate_terminal_return_above_reference": 0.0,
                "candidate_sharpe_above_reference": 0.0,
                "candidate_max_drawdown_below_reference": 0.0,
            },
        )

    def test_preregistration_binds_source_artifacts_before_bootstrap(self) -> None:
        from qount.mini_trend.futures_recovery import selected_um_rules

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent = root / "parent.json"
            historical = root / "historical.json"
            _parent(parent)
            _, rules_hash = selected_um_rules(_rules())
            _historical(historical, rules_hash)
            preregistration = build_funding_veto_robustness_preregistration(
                _rules(), parent, historical
            )
        self.assertFalse(preregistration["meta"]["bootstrap_results_evaluated"])
        self.assertTrue(preregistration["meta"]["source_historical_results_consumed"])
        self.assertEqual(
            preregistration["decision_contract"]["bootstrap"]["block_length_completed_days"],
            20,
        )
        self.assertEqual(
            preregistration["decision_contract"]["bootstrap"]["bootstrap_samples"],
            5_000,
        )
        self.assertEqual(
            preregistration["decision_contract"]["contract_hash"],
            FUNDING_VETO_ROBUSTNESS_PROTOCOL.contract_hash,
        )

    def test_registration_rejects_source_artifact_drift(self) -> None:
        from qount.mini_trend.futures_recovery import selected_um_rules

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent = root / "parent.json"
            historical = root / "historical.json"
            _parent(parent)
            _, rules_hash = selected_um_rules(_rules())
            _historical(historical, rules_hash)
            preregistration = build_funding_veto_robustness_preregistration(
                _rules(), parent, historical
            )
            historical.write_text(historical.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "source historical hash mismatch"):
                validate_funding_veto_robustness_registration(
                    preregistration, _rules(), parent, historical
                )


if __name__ == "__main__":
    unittest.main()
