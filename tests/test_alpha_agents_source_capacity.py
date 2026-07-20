from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from qount.alpha_agents.source_capacity import FROZEN_OPTIONS_DVOL_CONTRACT
from qount.alpha_agents.source_capacity import SOURCE_CAPACITY_VERSION
from qount.alpha_agents.source_capacity import SourceCapacityConfig
from qount.alpha_agents.source_capacity import build_options_dvol_preregistration
from qount.alpha_agents.source_capacity import build_source_capacity_matrix


def _fake_fetch(method: str, url: str, body: bytes | None) -> bytes:
    if "get_volatility_index_data" in url:
        start_ms = int(url.split("start_timestamp=", 1)[1].split("&", 1)[0])
        rows = [[start_ms + index * 3_600_000, 50.0, 51.0, 49.0, 50.5] for index in range(25)]
        return json.dumps({"result": {"data": rows, "continuation": None}}).encode()
    if "hyperliquid" in url:
        request = json.loads(body or b"{}")
        start_ms = int(request["startTime"])
        rows = [
            {
                "coin": request["coin"],
                "fundingRate": "0.0001",
                "premium": "0.001",
                "time": start_ms + index * 3_600_000,
            }
            for index in range(24)
        ]
        return json.dumps(rows).encode()
    if "/forceOrder/" in url or "/depth/" in url:
        raise FileNotFoundError(url)
    if "/bookDepth/" in url:
        filename = url.removesuffix(".CHECKSUM").rsplit("/", 1)[-1]
        return f"{'a' * 64}  {filename}\n".encode()
    raise AssertionError(url)


class SourceCapacityTest(unittest.TestCase):
    def test_matrix_selects_options_and_keeps_missing_history_failures(self) -> None:
        payload = build_source_capacity_matrix(fetch=_fake_fetch)
        self.assertEqual(payload["schema_version"], SOURCE_CAPACITY_VERSION)
        self.assertEqual(payload["diagnostics"]["verdict"], "select_single_g0_candidate")
        self.assertEqual(
            payload["diagnostics"]["selected_candidate_id"],
            "deribit_options_dvol_relative_stress",
        )
        by_id = {row["candidate_id"]: row for row in payload["candidates"]}
        self.assertEqual(by_id["binance_liquidation_force_order"]["status"], "forward_only")
        self.assertFalse(by_id["binance_replayable_l2_queue"]["historical_discovery_ready"])
        self.assertTrue(by_id["binance_replayable_l2_queue"]["aggregate_book_depth_available"])
        self.assertEqual(by_id["deribit_options_dvol_relative_stress"]["blockers"], [])
        self.assertFalse(payload["diagnostics"]["strategy_results_evaluated"])

    def test_preregistration_binds_capacity_and_freezes_forward_holdout(self) -> None:
        capacity = build_source_capacity_matrix(fetch=_fake_fetch)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "capacity.json"
            path.write_text(json.dumps(capacity), encoding="utf-8")
            preregistration = build_options_dvol_preregistration(path)
        self.assertEqual(preregistration["diagnostics"]["verdict"], "preregistered_g0")
        self.assertEqual(
            preregistration["contract"]["contract_hash"],
            FROZEN_OPTIONS_DVOL_CONTRACT.contract_hash,
        )
        self.assertEqual(preregistration["protocol"]["selection_trials"], 1)
        self.assertEqual(preregistration["protocol"]["price_interval"], "1h")
        self.assertEqual(preregistration["protocol"]["minimum_symbol_rank_ic"], 0.02)
        self.assertEqual(preregistration["protocol"]["minimum_feature_coverage"], 0.999)
        self.assertEqual(preregistration["protocol"]["minimum_price_coverage"], 0.999)
        self.assertEqual(preregistration["contract"]["beta_lookback_hours"], 720)
        self.assertEqual(preregistration["contract"]["minimum_entry_count_per_symbol"], 20)
        self.assertEqual(
            preregistration["protocol"]["reserved_forward_holdout_role"],
            "forward_validation_v1_once_only",
        )
        self.assertFalse(preregistration["diagnostics"]["reserved_forward_oos_consumed"])
        self.assertFalse(preregistration["diagnostics"]["promotion_allowed"])

    def test_preregistration_rejects_tampered_selection(self) -> None:
        capacity = build_source_capacity_matrix(fetch=_fake_fetch)
        capacity["diagnostics"]["selected_candidate_id"] = "binance_liquidation_force_order"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "capacity.json"
            path.write_text(json.dumps(capacity), encoding="utf-8")
            with self.assertRaises(ValueError):
                build_options_dvol_preregistration(path)

    def test_deribit_probe_failure_blocks_selection(self) -> None:
        def broken_fetch(method: str, url: str, body: bytes | None) -> bytes:
            if "get_volatility_index_data" in url:
                raise TimeoutError(url)
            return _fake_fetch(method, url, body)

        payload = build_source_capacity_matrix(
            SourceCapacityConfig(request_retries=0), fetch=broken_fetch
        )
        self.assertEqual(payload["diagnostics"]["verdict"], "capacity_incomplete")
        self.assertIsNone(payload["diagnostics"]["selected_candidate_id"])


if __name__ == "__main__":
    unittest.main()
