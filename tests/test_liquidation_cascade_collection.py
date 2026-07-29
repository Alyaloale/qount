from __future__ import annotations

import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from qount.mini_trend.liquidation_cascade_collection import AppendOnlyGzipSegment
from qount.mini_trend.liquidation_cascade_collection import _CollectionRootLock
from qount.mini_trend.liquidation_cascade_collection import DEFAULT_SYMBOLS
from qount.mini_trend.liquidation_cascade_collection import DiskGuard
from qount.mini_trend.liquidation_cascade_collection import DiskSpaceExhausted
from qount.mini_trend.liquidation_cascade_collection import LiquidationCascadeCollectorConfig
from qount.mini_trend.liquidation_cascade_collection import RecentEventDeduper
from qount.mini_trend.liquidation_cascade_collection import build_collection_contract
from qount.mini_trend.liquidation_cascade_collection import build_force_order_stream_url
from qount.mini_trend.liquidation_cascade_collection import build_gap_record
from qount.mini_trend.liquidation_cascade_collection import build_segment_paths
from qount.mini_trend.liquidation_cascade_collection import build_snapshot_records
from qount.mini_trend.liquidation_cascade_collection import normalize_force_order_message
from qount.mini_trend.liquidation_cascade_collection import seal_closed_segment
from qount.mini_trend.liquidation_cascade_collection import write_or_verify_collection_contract


NOW = 1_700_000_123_456


class LiquidationCascadeCollectionTest(unittest.TestCase):
    def _config(self, root: Path, **overrides: object) -> LiquidationCascadeCollectorConfig:
        defaults: dict[str, object] = {
            "state_root": root,
            "symbols": DEFAULT_SYMBOLS,
            "min_free_disk_bytes": 0,
        }
        defaults.update(overrides)
        return LiquidationCascadeCollectorConfig(**defaults)

    def test_force_order_normalizes_direction_and_stable_dedup_id(self) -> None:
        source = {
            "stream": "btcusdt@forceOrder",
            "data": {
                "e": "forceOrder",
                "E": NOW,
                "o": {
                    "s": "BTCUSDT",
                    "S": "SELL",
                    "q": "0.5",
                    "p": "60000",
                    "ap": "59999",
                    "T": NOW - 5,
                    "X": "FILLED",
                },
            },
        }
        record = normalize_force_order_message(source, received_at_ms=NOW + 10)
        self.assertEqual(record["record_type"], "liquidation_event")
        self.assertEqual(record["liquidation_order_side"], "SELL")
        self.assertEqual(record["liquidated_position_side"], "long")
        self.assertEqual(record["transaction_time_ms"], NOW - 5)
        self.assertEqual(record["event_id"], normalize_force_order_message(source)["event_id"])

        deduper = RecentEventDeduper(max_items=2)
        self.assertTrue(deduper.add_if_new(record["event_id"]))
        self.assertFalse(deduper.add_if_new(record["event_id"]))

    def test_snapshot_records_preserve_partial_context_and_error(self) -> None:
        records = build_snapshot_records(
            kind="event_snapshot",
            symbol="ethusdt",
            snapshot_started_at_ms=NOW,
            recorded_at_ms=NOW + 20,
            source_payloads={"open_interest": {"openInterest": "12"}, "depth": {"lastUpdateId": 1}},
            source_errors={"premium_index": "HTTPError:451"},
            trigger_event_ids=("a" * 64,),
        )
        self.assertFalse(records[0]["complete"])
        self.assertEqual(records[0]["symbol"], "ETHUSDT")
        self.assertEqual(records[0]["trigger_event_ids"], ["a" * 64])
        self.assertEqual(records[1]["record_type"], "snapshot_error")
        self.assertEqual(records[1]["source"], "premium_index")

    def test_gap_record_never_hides_disconnect_duration(self) -> None:
        record = build_gap_record(started_at_ms=NOW, ended_at_ms=NOW + 1_250, reason="websocket_reconnect")
        self.assertEqual(record["record_type"], "collection_gap")
        self.assertEqual(record["gap_duration_ms"], 1_250)
        with self.assertRaises(ValueError):
            build_gap_record(started_at_ms=NOW, ended_at_ms=NOW - 1, reason="bad")

    def test_segment_paths_stay_under_root_and_are_utc_bucketed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            paths = build_segment_paths(
                root,
                recorded_at_ms=NOW,
                rotation_seconds=3600,
                session_id="test-session",
                sequence=7,
            )
            self.assertTrue(paths.relative_completed_path.startswith("raw/"))
            self.assertTrue(paths.completed_path.is_relative_to(root))
            self.assertTrue(paths.partial_path.name.endswith(".jsonl.gz.partial"))
            self.assertEqual(paths.bucket_ends_at_ms - paths.bucket_started_at_ms, 3_600_000)

    def test_disk_guard_fails_before_segment_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            guard = DiskGuard(root, min_free_bytes=2, interval_seconds=1)
            with patch("qount.mini_trend.liquidation_cascade_collection.shutil.disk_usage") as disk_usage:
                disk_usage.return_value.free = 1
                with self.assertRaises(DiskSpaceExhausted):
                    guard.check(force=True)

    def test_closed_segment_is_append_only_and_has_immutable_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            paths = build_segment_paths(
                root,
                recorded_at_ms=NOW,
                rotation_seconds=3600,
                session_id="test-session",
                sequence=1,
            )
            writer = AppendOnlyGzipSegment(paths, DiskGuard(root, min_free_bytes=0, interval_seconds=1))
            writer.write({"record_type": "collector_started", "recorded_at_ms": NOW})
            completed = writer.close()
            with gzip.open(completed, "rt", encoding="ascii") as handle:
                rows = [json.loads(line) for line in handle if line.strip()]
            self.assertEqual(rows[0]["record_type"], "collector_started")
            manifest = seal_closed_segment(root, completed)
            self.assertEqual(manifest["record_count"], 1)
            self.assertEqual(seal_closed_segment(root, completed), manifest)
            with self.assertRaises(FileExistsError):
                AppendOnlyGzipSegment(paths, DiskGuard(root, min_free_bytes=0, interval_seconds=1))

    def test_collection_contract_is_frozen_and_public_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            config = self._config(root)
            contract = build_collection_contract(config)
            self.assertEqual(contract["research_guards"]["independent_window_days"], 180)
            self.assertFalse(contract["research_guards"]["orders_authorized"])
            self.assertFalse(contract["research_guards"]["read_results_before_window"])
            self.assertIn("btcusdt@forceOrder", build_force_order_stream_url(config))
            self.assertEqual(write_or_verify_collection_contract(root, config), contract)
            changed = self._config(root, depth_limit=50)
            with self.assertRaisesRegex(ValueError, "collection_contract_mismatch"):
                write_or_verify_collection_contract(root, changed)

    def test_collection_root_lock_rejects_a_second_writer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            first = _CollectionRootLock(root)
            second = _CollectionRootLock(root)
            first.acquire()
            try:
                with self.assertRaisesRegex(ValueError, "collection_root_already_locked"):
                    second.acquire()
            finally:
                first.release()
            second.acquire()
            second.release()


if __name__ == "__main__":
    unittest.main()
