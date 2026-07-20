from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from qount.mini_trend.forward import TOP3
from qount.mini_trend.futures_funding_veto import FUTURES_FUNDING_VETO_PROTOCOL
from qount.mini_trend.futures_funding_veto_attribution import (
    FUNDING_VETO_ATTRIBUTION_REPORT_VERSION,
)
from qount.mini_trend.futures_funding_veto_attribution import (
    FUNDING_VETO_ATTRIBUTION_PROTOCOL,
)
from qount.mini_trend.futures_funding_veto_report import FUNDING_VETO_REPORT_VERSION
from qount.mini_trend.futures_funding_veto_state_decay import (
    FUNDING_VETO_STATE_DECAY_PROTOCOL,
)
from qount.mini_trend.futures_funding_veto_state_decay import _event_decay_rows
from qount.mini_trend.futures_funding_veto_state_decay import _spell_rows
from qount.mini_trend.futures_funding_veto_state_decay import (
    build_funding_veto_state_decay_preregistration,
)
from qount.mini_trend.futures_funding_veto_state_decay import compare_execution_states
from qount.mini_trend.futures_recovery import selected_um_rules
from qount.mini_trend.futures_risk_tier import file_sha256


def _state(*, stage: str = "boosted", weight: float = 0.2) -> dict:
    return {
        "decision_risk_stage": stage,
        "active_vol_target": 0.02,
        "target_weights": {"BTCUSDT": weight},
        "trail_high": {"BTCUSDT": 100.0},
        "cooldown_remaining": {"BTCUSDT": 0},
        "selector_state": {"boost_latched": False},
    }


def _rows(count: int) -> list[dict]:
    return [
        {
            "decision_date": f"2024-01-{index + 1:02d}",
            "outcome_date": f"2024-01-{index + 2:02d}",
        }
        for index in range(count)
    ]


def _rules() -> dict:
    return {
        "market": "um",
        "source_type": "runtime_exchange_info",
        "rules": [
            {"symbol": symbol, "status": "TRADING", "min_qty": "0.001", "min_notional": "5"}
            for symbol in TOP3
        ],
    }


def _source_historical(path: Path, rules_hash: str) -> None:
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
                    "candidate": metric
                    | {
                        "funding_veto_activity": {
                            "events": [{"decision_date": "2024-01-01"}]
                        }
                    },
                },
            }
        ),
        encoding="utf-8",
    )


def _attribution(path: Path, source_sha: str) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": FUNDING_VETO_ATTRIBUTION_REPORT_VERSION,
                "artifact_type": (
                    "mini_trend_um_funding_veto_attribution_historical_diagnostic"
                ),
                "contract_hash": FUNDING_VETO_ATTRIBUTION_PROTOCOL.contract_hash,
                "protocol_hash": FUNDING_VETO_ATTRIBUTION_PROTOCOL.protocol_hash,
                "source_historical_sha256": source_sha,
                "diagnostics": {"verdict": "historical_cost_veto_mechanism_supported"},
                "accounting": {
                    "observation_count": 10,
                    "divergent_bar_count": 4,
                    "downstream_divergent_bar_count": 3,
                },
            }
        ),
        encoding="utf-8",
    )


class MiniTrendFuturesFundingVetoStateDecayTest(unittest.TestCase):
    def test_state_comparison_uses_tolerance_and_facets(self) -> None:
        reference = _state()
        within_tolerance = _state(weight=0.2 + 5e-13)
        self.assertFalse(compare_execution_states(reference, within_tolerance)["divergent"])
        candidate = _state(stage="funding_veto", weight=0.19)
        comparison = compare_execution_states(reference, candidate)
        self.assertTrue(comparison["divergent"])
        self.assertTrue(comparison["facets"]["risk_stage"])
        self.assertTrue(comparison["facets"]["target_weights"])
        self.assertAlmostEqual(comparison["maximum_target_weight_delta"], 0.01)

    def test_spell_rows_find_maximal_contiguous_runs(self) -> None:
        rows = _rows(7)
        flags = [False, True, True, False, True, True, True]
        comparisons = [
            {
                "maximum_target_weight_delta": float(index) / 100.0,
                "facets": {"target_weights": flag},
            }
            for index, flag in enumerate(flags)
        ]
        spells = _spell_rows(flags, rows, {"2024-01-02"}, comparisons)
        self.assertEqual([row["bar_count"] for row in spells], [2, 3])
        self.assertEqual(spells[0]["event_dates"], ["2024-01-02"])
        self.assertAlmostEqual(spells[1]["maximum_target_weight_delta"], 0.06)

    def test_event_decay_reports_first_and_stable_sync(self) -> None:
        rows = _rows(7)
        flags = [False, True, True, False, True, False, False]
        event_dates = ["2024-01-02", "2024-01-05"]
        spells = _spell_rows(flags, rows, set(event_dates))
        events = _event_decay_rows(rows, flags, event_dates, spells)
        self.assertEqual(events[0]["bars_to_first_sync"], 2)
        self.assertEqual(events[0]["bars_to_stable_sync_before_next_veto"], 2)
        self.assertFalse(events[0]["later_veto_before_first_sync"])
        self.assertEqual(events[1]["bars_to_first_sync"], 1)
        self.assertEqual(events[1]["bars_to_stable_sync_before_next_veto"], 1)

    def test_preregistration_binds_attribution_and_state_fields(self) -> None:
        _, rules_hash = selected_um_rules(_rules())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            historical = root / "historical.json"
            attribution = root / "attribution.json"
            _source_historical(historical, rules_hash)
            _attribution(attribution, file_sha256(historical))
            preregistration = build_funding_veto_state_decay_preregistration(
                _rules(), historical, attribution
            )
        self.assertFalse(preregistration["meta"]["state_decay_results_evaluated"])
        self.assertEqual(preregistration["source_attribution"]["divergent_bar_count"], 4)
        self.assertFalse(
            preregistration["decision_contract"]["execution_state_snapshot"][
                "account_equity_included"
            ]
        )
        self.assertEqual(
            preregistration["decision_contract"]["contract_hash"],
            FUNDING_VETO_STATE_DECAY_PROTOCOL.contract_hash,
        )


if __name__ == "__main__":
    unittest.main()
