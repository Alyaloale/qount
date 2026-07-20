from __future__ import annotations

import datetime as dt
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from qount.mini_trend.equity_mapping_collection import (
    EQUITY_MAPPING_COLLECTION_VERSION,
)
from qount.mini_trend.equity_mapping_collection import (
    build_equity_mapping_collection_batch,
)
from qount.mini_trend.equity_mapping_collection import (
    build_equity_mapping_collection_readiness,
)
from qount.mini_trend.equity_mapping_collection import collection_source_hashes
from qount.mini_trend.equity_mapping_collection import (
    load_verified_equity_mapping_collection_manifest,
)
from qount.mini_trend.equity_mapping_collection import (
    seal_equity_mapping_collection_batch,
)


_ROLES = (
    ("instrument_mapping", "NVDA"),
    ("mapped_quote", "NVDA"),
    ("cash_premarket_quote", "NVDA"),
    ("corporate_action", "NVDA"),
    ("event_context", "NVDA"),
    ("usdt_usd_quote", "GLOBAL"),
    ("cash_calendar", "GLOBAL"),
    ("stress_scenario", "GLOBAL"),
)


def _payload(root: Path) -> dict[str, object]:
    captures = []
    quote_times = {
        "mapped_quote": "2026-07-20T13:24:55+00:00",
        "cash_premarket_quote": "2026-07-20T13:24:56+00:00",
        "usdt_usd_quote": "2026-07-20T13:24:57+00:00",
    }
    for index, (role, asset_key) in enumerate(_ROLES):
        path = root / f"source-{index}.json"
        path.write_text(json.dumps({"role": role, "value": index}), encoding="utf-8")
        quote_time = quote_times.get(role)
        captures.append(
            {
                "role": role,
                "asset_key": asset_key,
                "source_id": f"fixture-{role}",
                "source_url": f"https://data.example.test/{role}",
                "content_type": "application/json",
                "raw_scope": "response_body_only",
                "source_event_at": quote_time,
                "observed_at": quote_time or "2026-07-20T12:00:00+00:00",
                "available_at": quote_time or "2026-07-20T12:00:01+00:00",
                "path": path.name,
            }
        )
    return {
        "schema_version": EQUITY_MAPPING_COLLECTION_VERSION,
        "dataset_role": "synthetic_fixture",
        "cash_trading_date": "2026-07-20",
        "source_allowlist": ["data.example.test"],
        "captures": captures,
    }


class EquityMappingCollectionTests(unittest.TestCase):
    def test_readiness_uses_new_york_dst_and_never_claims_market_evidence(self) -> None:
        readiness = build_equity_mapping_collection_readiness(
            "2026-07-20",
            as_of=dt.datetime(2026, 7, 19, 5, 0, tzinfo=dt.UTC),
        )
        self.assertEqual(readiness["reference_window_start"], "2026-07-20T13:24:30+00:00")
        self.assertEqual(readiness["decision_time"], "2026-07-20T13:25:00+00:00")
        self.assertEqual(readiness["status"], "await_collection_window")
        self.assertFalse(readiness["meta"]["market_evidence_present"])
        self.assertFalse(readiness["meta"]["orders_allowed"])

    def test_valid_batch_is_content_addressed_and_linkable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report, _ = build_equity_mapping_collection_batch(
                _payload(root), base_dir=root
            )
        self.assertEqual(report["verdict"], "ready_to_seal_raw_collection")
        self.assertEqual(report["capture_count"], 8)
        self.assertEqual(report["asset_count"], 1)
        self.assertEqual(report["batch"]["actual_cross_leg_skew_seconds"], 2.0)
        self.assertEqual(collection_source_hashes((report,)), set(report["source_hashes"]))
        self.assertFalse(report["meta"]["pnl_evaluated"])

    def test_seal_is_idempotent_and_never_overwrites_raw_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = _payload(root)
            raw_root = root / "raw-store"
            first = seal_equity_mapping_collection_batch(
                payload, input_base_dir=root, raw_root=raw_root
            )
            second = seal_equity_mapping_collection_batch(
                payload, input_base_dir=root, raw_root=raw_root
            )
            self.assertFalse(first["idempotent_existing_bundle"])
            self.assertTrue(second["idempotent_existing_bundle"])
            self.assertEqual(first["bundle_path"], second["bundle_path"])
            manifest_path = Path(first["bundle_path"]) / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["verdict"], "sealed_raw_collection")
            verified = load_verified_equity_mapping_collection_manifest(manifest_path)
            self.assertTrue(verified["verification"]["raw_readback_verified"])
            capture = manifest["batch"]["captures"][0]
            sealed = Path(first["bundle_path"]) / "raw" / capture["stored_filename"]
            self.assertEqual(hashlib.sha256(sealed.read_bytes()).hexdigest(), capture["sha256"])

            source = root / "source-0.json"
            source.write_text('{"revised":true}', encoding="utf-8")
            revised = seal_equity_mapping_collection_batch(
                payload, input_base_dir=root, raw_root=raw_root
            )
            self.assertNotEqual(first["bundle_path"], revised["bundle_path"])
            self.assertEqual(hashlib.sha256(sealed.read_bytes()).hexdigest(), capture["sha256"])

            sealed.write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "raw_hash_mismatch"):
                load_verified_equity_mapping_collection_manifest(manifest_path)

    def test_missing_asset_role_blocks_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = _payload(root)
            payload["captures"] = [
                row for row in payload["captures"] if row["role"] != "corporate_action"
            ]
            with self.assertRaisesRegex(ValueError, "asset_role_coverage_incomplete"):
                build_equity_mapping_collection_batch(payload, base_dir=root)

    def test_secret_query_and_cross_leg_skew_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = _payload(root)
            payload["captures"][0]["source_url"] = (
                "https://data.example.test/mapping?api_key=secret"
            )
            with self.assertRaisesRegex(ValueError, "source_url_contains_secret"):
                build_equity_mapping_collection_batch(payload, base_dir=root)

            payload = _payload(root)
            payload["source_allowlist"] = ["127.0.0.1"]
            payload["captures"][0]["source_url"] = "https://127.0.0.1/mapping"
            with self.assertRaisesRegex(ValueError, "ip_literal_forbidden"):
                build_equity_mapping_collection_batch(payload, base_dir=root)

            payload = _payload(root)
            for row in payload["captures"]:
                if row["role"] == "cash_premarket_quote":
                    row["source_event_at"] = "2026-07-20T13:24:49+00:00"
                    row["observed_at"] = "2026-07-20T13:24:49+00:00"
                    row["available_at"] = "2026-07-20T13:24:50+00:00"
            with self.assertRaisesRegex(ValueError, "cross_leg_skew_exceeded"):
                build_equity_mapping_collection_batch(payload, base_dir=root)


if __name__ == "__main__":
    unittest.main()
