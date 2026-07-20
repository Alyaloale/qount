from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from qount.mini_trend.pilot_readiness_evidence import (
    runtime_evidence_from_artifacts,
)


def _write(root: Path, name: str, payload: dict) -> Path:
    path = root / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _preflight() -> dict:
    return {
        "artifact_type": "mini_trend_um_pilot_account_preflight",
        "meta": {
            "read_only": True,
            "private_api_order_attempted": False,
            "mutating_account_method_attempted": False,
            "live_orders_allowed": False,
        },
        "evidence": {
            "configured_exchange_route_ok": True,
            "public_api_ok": True,
            "credentials_ok": False,
            "api_key_reading_enabled": True,
            "api_key_spot_margin_disabled": True,
            "unmanaged_position_count": None,
            "open_order_count": None,
        },
    }


def _paper() -> dict:
    return {
        "artifact_type": "mini_trend_um_pilot_paper_runtime",
        "meta": {
            "paper_only": True,
            "orders_allowed": False,
            "private_api_order_attempted": False,
            "live_orders_allowed": False,
        },
        "data": {"complete_prefix_pair_count": 2},
        "evaluation": {"paper_days": 2, "active_bars": 1},
        "journal": {"row_count": 2, "final_chain_hash": "a" * 64},
    }


def _inputs() -> dict:
    return {
        "artifact_type": "mini_trend_um_shadow_input_refresh",
        "meta": {
            "public_data_only": True,
            "orders_allowed": False,
            "live_orders_allowed": False,
        },
        "diagnostics": {"current_month_funding_complete": True},
    }


class MiniTrendPilotReadinessEvidenceTest(unittest.TestCase):
    def test_extracts_order_free_runtime_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = runtime_evidence_from_artifacts(
                preflight_path=_write(root, "preflight.json", _preflight()),
                paper_path=_write(root, "paper.json", _paper()),
                shadow_input_path=_write(root, "inputs.json", _inputs()),
                legacy_production_cron_disabled=True,
                legacy_live_guard_disarmed=True,
                rollback_documented=True,
            )
        self.assertEqual(result.evidence.forward_pairs, 2)
        self.assertEqual(result.evidence.paper_days, 2)
        self.assertEqual(result.evidence.paper_schema_error_count, 0)
        self.assertTrue(result.evidence.complete_funding_journal)
        self.assertTrue(result.evidence.public_api_ok)
        self.assertFalse(result.evidence.credentials_ok)
        self.assertTrue(result.evidence.api_key_reading_enabled)
        self.assertTrue(result.evidence.api_key_spot_margin_disabled)
        self.assertTrue(all(source["valid"] for source in result.sources.values()))

    def test_order_capable_paper_artifact_fails_closed(self) -> None:
        paper = _paper()
        paper["meta"]["orders_allowed"] = True
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = runtime_evidence_from_artifacts(
                preflight_path=_write(root, "preflight.json", _preflight()),
                paper_path=_write(root, "paper.json", paper),
                shadow_input_path=_write(root, "inputs.json", _inputs()),
            )
        self.assertEqual(result.evidence.paper_days, 0)
        self.assertGreater(result.evidence.paper_schema_error_count, 0)
        self.assertFalse(result.evidence.complete_funding_journal)
        self.assertFalse(result.sources["paper"]["valid"])


if __name__ == "__main__":
    unittest.main()
