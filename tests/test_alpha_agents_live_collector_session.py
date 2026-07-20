from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from datetime import datetime
from datetime import timezone
from pathlib import Path
from unittest.mock import patch

from qount.alpha_agents.live_collector import _live_collector_result
from qount.alpha_agents.live_collector import GzipJsonlWriter
from qount.alpha_agents.live_collector import LiveCollectorConfig
from qount.alpha_agents.live_collector import normalize_stream_message
from qount.alpha_agents.live_collector_offload import _receipt_id
from qount.alpha_agents.live_collector_offload import remote_ack_segment
from qount.alpha_agents.live_collector_offload import verify_offload_segment
from qount.alpha_agents.live_collector_session import LiveCollectorSessionConfig
from qount.alpha_agents.live_collector_session import _boundary_gap
from qount.alpha_agents.live_collector_session import _new_manifest
from qount.alpha_agents.live_collector_session import _segment_entry
from qount.alpha_agents.live_collector_session import _segment_duration_seconds
from qount.alpha_agents.live_collector_session import _write_manifest
from qount.alpha_agents.live_collector_session import mark_live_collector_session_superseded
from qount.alpha_agents.live_collector_session import resume_live_collector_session
from qount.alpha_agents.live_collector_session import run_live_collector_session
from qount.alpha_agents.live_collector_session import verify_live_collector_session
from qount.settings import Settings


NOW = 1_700_000_000_000


def _market_event(event_type: str, payload: dict, *, received_at_ms: int = NOW + 20) -> dict:
    data = dict(payload)
    data.setdefault("e", event_type)
    data.setdefault("E", NOW)
    data.setdefault("s", "BTCUSDT")
    return normalize_stream_message(
        json.dumps({"stream": f"btcusdt@{event_type}", "data": data}),
        received_at_ms=received_at_ms,
    )


def _verified_session_fixture(root: Path) -> Path:
    session_dir = root / "session"
    segment_dir = session_dir / "segments" / "0000-fixture"
    segment_dir.mkdir(parents=True)
    raw_path = segment_dir / "events.jsonl.gz"
    records = [
        {"record_type": "collector_start", "received_at_ms": NOW},
        {
            "record_type": "connection_open",
            "connection_id": "fixture-public-1",
            "route": "public",
            "received_at_ms": NOW,
        },
        {
            "record_type": "connection_open",
            "connection_id": "fixture-market-1",
            "route": "market",
            "received_at_ms": NOW,
        },
        {
            "record_type": "depth_snapshot",
            "symbol": "BTCUSDT",
            "snapshot_started_at_ms": NOW,
            "received_at_ms": NOW + 5,
            "payload": {"lastUpdateId": 100, "bids": [["99", "1"]], "asks": [["101", "2"]]},
        },
        _market_event("bookTicker", {"u": 10, "b": "100", "B": "1", "a": "101", "A": "2"}),
        _market_event("aggTrade", {"a": 50, "p": "100", "q": "1", "m": False}),
        _market_event("depthUpdate", {"U": 100, "u": 101, "pu": 99, "b": [["100", "3"]], "a": []}),
        _market_event("forceOrder", {"o": {"s": "BTCUSDT", "S": "SELL", "q": "1", "p": "100", "T": NOW}}),
        {
            "record_type": "connection_close",
            "connection_id": "fixture-public-1",
            "route": "public",
            "received_at_ms": NOW + 1_000,
        },
        {
            "record_type": "connection_close",
            "connection_id": "fixture-market-1",
            "route": "market",
            "received_at_ms": NOW + 1_000,
        },
        {"record_type": "collector_stop", "received_at_ms": NOW + 1_000},
    ]
    with GzipJsonlWriter(raw_path) as writer:
        for record in records:
            writer.write(record)

    config = LiveCollectorConfig(symbols=("BTCUSDT",), duration_seconds=1)
    capture = {
        "started_at_ms": NOW,
        "ended_at_ms": NOW + 1_000,
        "market_events": 4,
        "connection_attempts": 2,
        "routes": [
            {
                "route": "public",
                "first_market_event_at_ms": NOW + 20,
                "last_market_event_at_ms": NOW + 20,
                "sequence_boundaries": {
                    "trades": {},
                    "book_ticker": {"BTCUSDT": {"first": 10, "last": 10}},
                    "depth": {
                        "BTCUSDT": {
                            "first": {
                                "first_update_id": 100,
                                "final_update_id": 101,
                                "previous_final_update_id": 99,
                            },
                            "last": {
                                "first_update_id": 100,
                                "final_update_id": 101,
                                "previous_final_update_id": 99,
                            },
                        }
                    },
                },
            },
            {
                "route": "market",
                "first_market_event_at_ms": NOW + 20,
                "last_market_event_at_ms": NOW + 20,
                "sequence_boundaries": {
                    "trades": {"BTCUSDT:aggTrade": {"first": 50, "last": 50}},
                    "book_ticker": {},
                    "depth": {},
                },
            },
        ],
        "market_event_started_at_ms": NOW + 20,
        "market_event_ended_at_ms": NOW + 20,
        "line_count": len(records),
        "stream_urls": {},
        "connection_ids_at_start": {},
        "connection_ids_at_end": {},
        "segment_connection_mode": "continuous_in_stream_rotation",
        "writer_generation": 1,
    }
    result = _live_collector_result(config, segment_dir, raw_path, capture)
    session_config = LiveCollectorSessionConfig(total_duration_seconds=1, segment_duration_seconds=1)
    manifest = _new_manifest(session_dir, config, session_config)
    entry = _segment_entry(result, 1, 0, session_dir=session_dir)
    entry.update(
        {
            "boundary_gap_ms": 0,
            "boundary_gap_by_route_ms": {},
            "boundary_market_inter_event_ms": 0,
            "boundary_market_inter_event_by_route_ms": {},
            "connection_restarted_routes": [],
            "boundary_sequence_breaks": {"trades": [], "book_ticker": [], "depth": []},
        }
    )
    manifest["segments"].append(entry)
    manifest["session"]["status"] = "complete"
    _write_manifest(manifest, session_dir)
    return session_dir


def _passing_audit() -> dict:
    return {
        "verdict": "pass_data_smoke",
        "blockers": [],
        "counts": {},
        "connections": {"opens": 2, "errors": 0},
        "snapshots": {"retries": 0, "errors": 0},
        "trades": {"missing_ids": 0},
        "book_ticker": {"out_of_order": 0},
        "depth": {
            "sequence_breaks": 0,
            "replay_updates": 2,
            "invalid_levels": 0,
            "empty_books": 0,
            "crossed_books": 0,
        },
        "event_time": {"missing": 0, "future": 0, "stale": 0},
    }


class FakeSegmentRunner:
    def __init__(self) -> None:
        self.calls = 0

    def run_segment(
        self,
        settings: Settings,
        config: LiveCollectorConfig,
        *,
        explicit_output_dir: str,
        connection_id: str,
    ) -> dict:
        index = self.calls
        self.calls += 1
        output_dir = Path(explicit_output_dir)
        raw_path = output_dir / "events.jsonl.gz"
        artifact_path = output_dir / "alpha_agent_live_collector.json"
        raw = f"segment-{index}".encode("ascii")
        raw_path.write_bytes(raw)
        started_at_ms = NOW + index * 2_000
        result = {
            "artifact_path": str(artifact_path),
            "raw_event_path": str(raw_path),
            "meta": {
                "config_hash": hashlib.sha256(str(config.to_dict()).encode("utf-8")).hexdigest(),
                "raw_sha256": hashlib.sha256(raw).hexdigest(),
                "raw_bytes": len(raw),
            },
            "capture": {
                "started_at_ms": started_at_ms,
                "ended_at_ms": started_at_ms + 1_000,
                "market_events": 10 + index,
                "routes": [],
                "connection_ids_at_start": {"public": connection_id, "market": connection_id},
                "connection_ids_at_end": {"public": connection_id, "market": connection_id},
                "segment_connection_mode": "continuous_in_stream_rotation",
            },
            "audit": _passing_audit(),
        }
        artifact_path.write_text(json.dumps(result), encoding="utf-8")
        return result


class FakeBatchRunner:
    def __init__(self, segment_runner: FakeSegmentRunner) -> None:
        self.segment_runner = segment_runner
        self.calls = 0

    def __call__(self, settings: Settings, segments, *, on_segment_complete=None) -> list[dict]:
        connection_id = f"batch-{self.calls}"
        self.calls += 1
        results = []
        for config, output_dir in segments:
            result = self.segment_runner.run_segment(
                settings,
                config,
                explicit_output_dir=output_dir,
                connection_id=connection_id,
            )
            results.append(result)
            if on_segment_complete is not None:
                on_segment_complete(result)
        return results


class AlphaAgentsLiveCollectorSessionTest(unittest.TestCase):
    def test_session_verifier_passes_closed_replayable_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _verified_session_fixture(Path(tmp))
            verification = verify_live_collector_session(
                session_dir,
                minimum_duration_seconds=1,
                required_symbols=("BTCUSDT",),
            )
        self.assertEqual(verification["verdict"], "pass_data_gate")
        self.assertEqual(verification["blockers"], [])
        self.assertTrue(verification["segments"][0]["deep_replay_match"])

    def test_session_verifier_passes_after_archive_relocation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = _verified_session_fixture(root)
            relocated = root / "relocated-session"
            shutil.copytree(source, relocated)
            verification = verify_live_collector_session(
                relocated,
                minimum_duration_seconds=1,
                required_symbols=("BTCUSDT",),
            )
        self.assertEqual(verification["verdict"], "pass_data_gate")
        self.assertEqual(verification["blockers"], [])

    def test_offload_verifies_then_remote_ack_deletes_only_raw(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _verified_session_fixture(Path(tmp))
            manifest = json.loads(
                (session_dir / "alpha_agent_live_collector_session.json").read_text(encoding="utf-8")
            )
            verification = verify_offload_segment(session_dir, manifest, 0)
            segment = manifest["segments"][0]
            receipt_id = _receipt_id(manifest["session_id"], 0, segment["raw_sha256"])
            result = remote_ack_segment(session_dir, 0, segment["raw_sha256"], receipt_id)
            repeated = remote_ack_segment(session_dir, 0, segment["raw_sha256"], receipt_id)
            raw_path = session_dir / segment["raw_event_path"]
            artifact_path = session_dir / segment["artifact_path"]
            raw_exists = raw_path.exists()
            artifact_exists = artifact_path.exists()
        self.assertEqual(verification["verdict"], "pass_offload")
        self.assertEqual(result["status"], "deleted")
        self.assertEqual(repeated["status"], "already_deleted")
        self.assertFalse(raw_exists)
        self.assertTrue(artifact_exists)

    def test_session_verifier_reports_running_manifest_as_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp) / "session"
            session_dir.mkdir()
            config = LiveCollectorConfig(symbols=("BTCUSDT",), duration_seconds=1)
            manifest = _new_manifest(
                session_dir,
                config,
                LiveCollectorSessionConfig(total_duration_seconds=1, segment_duration_seconds=1),
            )
            _write_manifest(manifest, session_dir)
            verification = verify_live_collector_session(
                session_dir,
                minimum_duration_seconds=1,
                required_symbols=("BTCUSDT",),
            )
        self.assertEqual(verification["verdict"], "incomplete")
        self.assertIn("session_not_complete", verification["blockers"])
        self.assertIn("session_segments_missing", verification["blockers"])

    def test_superseded_session_remains_incomplete_without_corruption_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp) / "session"
            session_dir.mkdir()
            config = LiveCollectorConfig(symbols=("BTCUSDT",), duration_seconds=1)
            manifest = _new_manifest(
                session_dir,
                config,
                LiveCollectorSessionConfig(total_duration_seconds=1, segment_duration_seconds=1),
            )
            _write_manifest(manifest, session_dir)
            marked = mark_live_collector_session_superseded(session_dir, "replacement-vps-session")
            verification = verify_live_collector_session(
                session_dir,
                minimum_duration_seconds=1,
                required_symbols=("BTCUSDT",),
            )
        self.assertEqual(marked["session"]["status"], "superseded")
        self.assertEqual(marked["supersession"]["replacement_session_id"], "replacement-vps-session")
        self.assertEqual(verification["verdict"], "incomplete")
        self.assertIn("session_superseded", verification["blockers"])
        self.assertNotIn("session_declared_blockers", verification["blockers"])

    def test_session_verifier_does_not_hide_running_contract_corruption_as_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp) / "session"
            session_dir.mkdir()
            config = LiveCollectorConfig(symbols=("BTCUSDT",), duration_seconds=1)
            manifest = _new_manifest(
                session_dir,
                config,
                LiveCollectorSessionConfig(total_duration_seconds=1, segment_duration_seconds=1),
            )
            manifest["contract_hash"] = "tampered"
            _write_manifest(manifest, session_dir)
            verification = verify_live_collector_session(
                session_dir,
                minimum_duration_seconds=1,
                required_symbols=("BTCUSDT",),
            )
        self.assertEqual(verification["verdict"], "block_data")
        self.assertIn("session_contract_hash_mismatch", verification["blockers"])

    def test_session_verifier_blocks_tampered_raw(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _verified_session_fixture(Path(tmp))
            manifest = json.loads(
                (session_dir / "alpha_agent_live_collector_session.json").read_text(encoding="utf-8")
            )
            (session_dir / manifest["segments"][0]["raw_event_path"]).write_bytes(b"tampered")
            verification = verify_live_collector_session(
                session_dir,
                minimum_duration_seconds=1,
                required_symbols=("BTCUSDT",),
            )
        self.assertEqual(verification["verdict"], "block_data")
        self.assertIn("segment_0_raw_sha256_mismatch", verification["blockers"])
        self.assertIn("segment_0_deep_replay_failed", verification["blockers"])

    def test_session_verifier_fails_closed_on_malformed_numeric_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _verified_session_fixture(Path(tmp))
            manifest_path = session_dir / "alpha_agent_live_collector_session.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["segments"][0]["wall_duration_seconds"] = "invalid"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            verification = verify_live_collector_session(
                session_dir,
                minimum_duration_seconds=1,
                required_symbols=("BTCUSDT",),
            )
        self.assertEqual(verification["verdict"], "block_data")
        self.assertIn("segment_0_capture_numeric_fields_invalid", verification["blockers"])

    def test_session_verifier_blocks_paths_outside_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = _verified_session_fixture(root)
            manifest_path = session_dir / "alpha_agent_live_collector_session.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["segments"][0]["raw_event_path"] = str(root / "outside.jsonl.gz")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            verification = verify_live_collector_session(
                session_dir,
                minimum_duration_seconds=1,
                required_symbols=("BTCUSDT",),
            )
        self.assertEqual(verification["verdict"], "block_data")
        self.assertIn("segment_0_raw_path_outside_session", verification["blockers"])

    def test_session_verifier_blocks_missing_boundary_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _verified_session_fixture(Path(tmp))
            manifest_path = session_dir / "alpha_agent_live_collector_session.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            del manifest["segments"][0]["sequence_boundaries"]["market"]["trades"]["BTCUSDT:aggTrade"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            verification = verify_live_collector_session(
                session_dir,
                minimum_duration_seconds=1,
                required_symbols=("BTCUSDT",),
            )
        self.assertEqual(verification["verdict"], "block_data")
        self.assertIn("segment_0_boundary_agg_trade_missing_BTCUSDT", verification["blockers"])

    def test_segment_duration_clips_at_utc_midnight(self) -> None:
        timestamp = int(datetime(2026, 7, 14, 23, 59, 58, 500_000, tzinfo=timezone.utc).timestamp() * 1000)
        self.assertEqual(_segment_duration_seconds(60, 60, timestamp), 2)

    def test_boundary_gap_uses_each_route_market_coverage(self) -> None:
        previous = {
            "ended_at_ms": 1_000,
            "route_coverage": {
                "public": {"last_market_event_at_ms": 900},
                "market": {"last_market_event_at_ms": 950},
            },
        }
        current = {
            "started_at_ms": 1_100,
            "route_coverage": {
                "public": {"first_market_event_at_ms": 1_050},
                "market": {"first_market_event_at_ms": 1_000},
            },
        }
        gap, by_route = _boundary_gap(previous, current)
        self.assertEqual(gap, 150)
        self.assertEqual(by_route, {"market": 50, "public": 150})

    def test_continuous_connection_boundary_has_zero_connection_gap(self) -> None:
        previous = {
            "connection_ids_at_end": {"public": "run-public-1", "market": "run-market-1"},
            "sequence_boundaries": {},
        }
        current = {
            "connection_ids_at_start": {"public": "run-public-1", "market": "run-market-1"},
            "sequence_boundaries": {},
        }
        from qount.alpha_agents.live_collector_session import _boundary_connection_restarts

        self.assertEqual(_boundary_connection_restarts(previous, current), [])

    def test_session_pauses_and_resumes_from_frozen_manifest(self) -> None:
        runner = FakeSegmentRunner()
        batch_runner = FakeBatchRunner(runner)
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp) / "session"
            collector = LiveCollectorConfig(symbols=("BTCUSDT",), duration_seconds=99)
            session = LiveCollectorSessionConfig(total_duration_seconds=3, segment_duration_seconds=1)
            with patch(
                "qount.alpha_agents.live_collector_session.run_live_collector_segments",
                side_effect=batch_runner,
            ):
                paused = run_live_collector_session(
                    Settings.from_env(),
                    collector,
                    session,
                    explicit_output_dir=str(session_dir),
                    max_segments=1,
                )
                completed = resume_live_collector_session(Settings.from_env(), str(session_dir))

            self.assertEqual(paused["session"]["status"], "paused")
            self.assertEqual(paused["session"]["remaining_duration_seconds"], 2)
            self.assertEqual(completed["session"]["status"], "complete")
            self.assertEqual(completed["session"]["verdict"], "block_data")
            self.assertIn("boundary_gap_present", completed["session"]["blockers"])
            self.assertFalse(completed["session"]["continuous_gate_eligible"])
            self.assertEqual(completed["session"]["resume_count"], 1)
            self.assertEqual(completed["aggregate"]["segment_count"], 3)
            self.assertEqual(completed["aggregate"]["connection_restart_count"], 1)
            self.assertEqual(completed["aggregate"]["boundary_gap_max_ms"], 1_000)
            self.assertEqual([item["index"] for item in completed["segments"]], [0, 1, 2])
            self.assertTrue((session_dir / completed["days"][0]["artifact_path"]).is_file())
            self.assertFalse((session_dir / ".collector-session.lock").exists())
            self.assertFalse(list(session_dir.rglob("*.tmp")))

    def test_failed_segment_is_preserved_as_orphan_and_can_resume(self) -> None:
        runner = FakeSegmentRunner()
        batch_runner = FakeBatchRunner(runner)

        def fail_after_partial(settings: Settings, segments, *, on_segment_complete=None) -> list[dict]:
            output_dir = Path(segments[0][1])
            (output_dir / "events.jsonl.gz.partial").write_bytes(b"partial")
            raise RuntimeError("simulated interruption")

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp) / "session"
            collector = LiveCollectorConfig(symbols=("BTCUSDT",), duration_seconds=99)
            session = LiveCollectorSessionConfig(total_duration_seconds=1, segment_duration_seconds=1)
            with patch(
                "qount.alpha_agents.live_collector_session.run_live_collector_segments",
                side_effect=fail_after_partial,
            ):
                with self.assertRaisesRegex(RuntimeError, "simulated interruption"):
                    run_live_collector_session(
                        Settings.from_env(),
                        collector,
                        session,
                        explicit_output_dir=str(session_dir),
                    )
            error_manifest = json.loads(
                (session_dir / "alpha_agent_live_collector_session.json").read_text(encoding="utf-8")
            )
            self.assertEqual(error_manifest["session"]["status"], "error")
            self.assertEqual(len(error_manifest["orphan_files"]), 1)

            with patch(
                "qount.alpha_agents.live_collector_session.run_live_collector_segments",
                side_effect=batch_runner,
            ):
                completed = resume_live_collector_session(Settings.from_env(), str(session_dir))
            self.assertEqual(completed["session"]["status"], "complete")
            self.assertEqual(completed["session"]["verdict"], "block_data")
            self.assertIn("orphan_files_present", completed["session"]["blockers"])
            self.assertEqual(completed["aggregate"]["segment_count"], 1)
            self.assertEqual(len(completed["orphan_files"]), 1)


if __name__ == "__main__":
    unittest.main()
