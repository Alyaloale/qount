from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from qount.alpha_agents.live_collector import GzipJsonlWriter
from qount.alpha_agents.live_collector import LiveCollectorConfig
from qount.alpha_agents.live_collector import audit_event_file
from qount.alpha_agents.live_collector import audit_records
from qount.alpha_agents.live_collector import combined_stream_url
from qount.alpha_agents.live_collector import combined_stream_urls
from qount.alpha_agents.live_collector import fetch_depth_snapshots
from qount.alpha_agents.live_collector import iter_gzip_jsonl
from qount.alpha_agents.live_collector import normalize_stream_message
from qount.alpha_agents.live_collector import normalize_depth_snapshot_response
from qount.alpha_agents.live_collector import run_live_collector
from qount.alpha_agents.live_collector import run_live_collector_segments
from qount.alpha_agents.live_collector import stream_names
from qount.settings import Settings


NOW = 1_700_000_000_000


def _event(event_type: str, payload: dict, *, received: int = NOW + 20) -> dict:
    data = dict(payload)
    data.setdefault("e", event_type)
    data.setdefault("E", NOW)
    data.setdefault("s", "BTCUSDT")
    return normalize_stream_message(json.dumps({"stream": "btcusdt@test", "data": data}), received_at_ms=received)


def _good_records() -> list[dict]:
    return [
        {"record_type": "connection_open", "received_at_ms": NOW},
        {
            "record_type": "depth_snapshot",
            "symbol": "BTCUSDT",
            "snapshot_started_at_ms": NOW,
            "received_at_ms": NOW + 5,
            "payload": {"lastUpdateId": 100, "bids": [["99", "1"]], "asks": [["101", "2"]]},
        },
        _event("bookTicker", {"u": 10, "b": "100", "B": "1", "a": "101", "A": "2"}),
        _event("bookTicker", {"u": 11, "b": "100", "B": "1", "a": "101", "A": "2"}),
        _event("aggTrade", {"a": 50, "p": "100", "q": "1", "m": False}),
        _event("aggTrade", {"a": 51, "p": "100", "q": "1", "m": True}),
        _event("depthUpdate", {"U": 100, "u": 101, "pu": 99, "b": [["100", "3"]], "a": []}),
        _event("depthUpdate", {"U": 102, "u": 102, "pu": 101, "b": [], "a": []}),
        _event("forceOrder", {"o": {"s": "BTCUSDT", "S": "SELL", "q": "1", "p": "100", "T": NOW}}),
        {"record_type": "connection_close", "received_at_ms": NOW + 100},
    ]


class AlphaAgentsLiveCollectorTest(unittest.TestCase):
    def test_writer_disk_guard_fails_before_opening_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl.gz"
            with patch("qount.alpha_agents.live_collector.shutil.disk_usage") as disk_usage:
                disk_usage.return_value.free = 1
                with self.assertRaisesRegex(RuntimeError, "collector disk guard tripped"):
                    GzipJsonlWriter(path, min_free_disk_bytes=2)
            self.assertFalse(path.exists())

    def test_stream_names_and_combined_url(self) -> None:
        config = LiveCollectorConfig(symbols=("BTCUSDT",), duration_seconds=1)
        self.assertEqual(
            stream_names(config),
            (
                "btcusdt@bookTicker",
                "btcusdt@aggTrade",
                "btcusdt@depth@100ms",
                "btcusdt@forceOrder",
            ),
        )
        urls = dict(combined_stream_urls(config))
        self.assertIn("/public/stream?streams=btcusdt@bookTicker/", urls["public"])
        self.assertIn("/market/stream?streams=btcusdt@aggTrade/", urls["market"])

        public_only = LiveCollectorConfig(symbols=("BTCUSDT",), streams=("bookTicker", "depth"), duration_seconds=1)
        self.assertIn("/public/stream?streams=btcusdt@bookTicker/", combined_stream_url(public_only))
        with self.assertRaises(ValueError):
            combined_stream_url(config)

    def test_normalize_force_order_uses_nested_symbol_and_time(self) -> None:
        record = normalize_stream_message(
            json.dumps(
                {
                    "stream": "btcusdt@forceOrder",
                    "data": {"e": "forceOrder", "E": NOW, "o": {"s": "BTCUSDT", "T": NOW - 1}},
                }
            ),
            received_at_ms=NOW + 10,
        )
        self.assertEqual(record["symbol"], "BTCUSDT")
        self.assertEqual(record["transaction_time_ms"], NOW - 1)

    def test_normalize_websocket_depth_snapshot(self) -> None:
        record = normalize_depth_snapshot_response(
            {"id": "depth-0-btcusdt", "status": 200, "result": {"lastUpdateId": 100, "bids": [], "asks": []}},
            symbol="BTCUSDT",
            started_at_ms=NOW,
            received_at_ms=NOW + 10,
        )
        self.assertEqual(record["payload"]["lastUpdateId"], 100)

    def test_good_records_pass_data_smoke(self) -> None:
        config = LiveCollectorConfig(symbols=("BTCUSDT",), duration_seconds=1)
        audit = audit_records(_good_records(), config)
        self.assertEqual(audit["verdict"], "pass_data_smoke")
        self.assertEqual(audit["blockers"], [])
        self.assertEqual(audit["depth"]["sequence_breaks"], 0)
        self.assertEqual(audit["depth"]["replay_updates"], 2)
        self.assertEqual(audit["depth"]["crossed_books"], 0)
        self.assertEqual(audit["depth"]["final_top_by_symbol"]["BTCUSDT"]["bid"], ["100", "3"])
        self.assertEqual(audit["trades"]["missing_ids"], 0)

    def test_connection_continuation_is_valid_segment_evidence(self) -> None:
        records = _good_records()
        records[0] = {
            "record_type": "connection_continuation",
            "connection_id": "capture-public-1",
            "route": "public",
            "received_at_ms": NOW,
        }
        audit = audit_records(records, LiveCollectorConfig(symbols=("BTCUSDT",), duration_seconds=1))
        self.assertEqual(audit["verdict"], "pass_data_smoke")
        self.assertEqual(audit["connections"]["opens"], 0)
        self.assertEqual(audit["connections"]["continuations"], 1)

    def test_crossed_replayed_book_blocks_data(self) -> None:
        records = _good_records()
        records.insert(-1, _event("depthUpdate", {"U": 103, "u": 103, "pu": 102, "b": [["102", "1"]], "a": []}))
        audit = audit_records(records, LiveCollectorConfig(symbols=("BTCUSDT",), duration_seconds=1))
        self.assertEqual(audit["verdict"], "block_data")
        self.assertIn("depth_replay_crossed_book", audit["blockers"])

    def test_sequence_gaps_and_future_event_block(self) -> None:
        records = _good_records()
        records.insert(-1, _event("aggTrade", {"a": 55}, received=NOW - 2_000))
        records.insert(-1, _event("depthUpdate", {"U": 103, "u": 103, "pu": 99, "b": [], "a": []}))
        audit = audit_records(records, LiveCollectorConfig(symbols=("BTCUSDT",), duration_seconds=1))
        self.assertEqual(audit["verdict"], "block_data")
        self.assertIn("trade_gap_rate_above_threshold", audit["blockers"])
        self.assertIn("depth_sequence_breaks_above_threshold", audit["blockers"])
        self.assertIn("event_time_future", audit["blockers"])

    def test_replay_can_pass_with_a_recovered_snapshot_error_below_smoke_threshold(self) -> None:
        records = _good_records()
        records.insert(
            2,
            {
                "record_type": "snapshot_error",
                "symbol": "BTCUSDT",
                "received_at_ms": NOW + 6,
                "error_type": "SSLEOFError",
                "error": "transient",
            },
        )
        records.insert(
            3,
            {
                "record_type": "depth_snapshot",
                "symbol": "BTCUSDT",
                "snapshot_started_at_ms": NOW + 7,
                "received_at_ms": NOW + 8,
                "payload": {"lastUpdateId": 100, "bids": [["99", "1"]], "asks": [["101", "2"]]},
            },
        )
        config = LiveCollectorConfig(symbols=("BTCUSDT",), duration_seconds=1, max_snapshot_error_rate=0.5)
        audit = audit_records(records, config)
        self.assertEqual(audit["verdict"], "pass_data_smoke")
        self.assertAlmostEqual(audit["snapshots"]["error_rate"], 1 / 3)

    def test_snapshot_retry_is_audited_without_becoming_final_error(self) -> None:
        failure = {
            "record_type": "snapshot_error",
            "symbol": "BTCUSDT",
            "received_at_ms": NOW,
            "error_type": "SSLEOFError",
            "error": "transient",
        }
        success = {
            "record_type": "depth_snapshot",
            "symbol": "BTCUSDT",
            "snapshot_started_at_ms": NOW + 1,
            "received_at_ms": NOW + 2,
            "payload": {"lastUpdateId": 100, "bids": [], "asks": []},
        }
        config = LiveCollectorConfig(
            symbols=("BTCUSDT",),
            duration_seconds=1,
            snapshot_max_retries=1,
            snapshot_retry_delay_seconds=0,
        )
        with patch(
            "qount.alpha_agents.live_collector._fetch_depth_snapshots_once",
            side_effect=[[failure], [success]],
        ):
            records = fetch_depth_snapshots(config)
        self.assertEqual([record["record_type"] for record in records], ["snapshot_retry", "depth_snapshot"])
        audit = audit_records([*_good_records(), *records], config)
        self.assertEqual(audit["snapshots"]["retries"], 1)
        self.assertEqual(audit["snapshots"]["errors"], 0)
        self.assertEqual(audit["verdict"], "pass_data_smoke")

    def test_snapshot_retry_exhaustion_keeps_final_error(self) -> None:
        failure = {
            "record_type": "snapshot_error",
            "symbol": "BTCUSDT",
            "received_at_ms": NOW,
            "error_type": "SSLEOFError",
            "error": "persistent",
        }
        config = LiveCollectorConfig(
            symbols=("BTCUSDT",),
            duration_seconds=1,
            snapshot_max_retries=1,
            snapshot_retry_delay_seconds=0,
        )
        with patch(
            "qount.alpha_agents.live_collector._fetch_depth_snapshots_once",
            side_effect=[[failure], [failure]],
        ):
            records = fetch_depth_snapshots(config)
        self.assertEqual([record["record_type"] for record in records], ["snapshot_retry", "snapshot_error"])

    def test_gzip_round_trip_and_file_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl.gz"
            with GzipJsonlWriter(path) as writer:
                for record in _good_records():
                    writer.write(record)
            self.assertEqual(len(list(iter_gzip_jsonl(path))), len(_good_records()))
            audit = audit_event_file(path, LiveCollectorConfig(symbols=("BTCUSDT",), duration_seconds=1))
            self.assertEqual(audit["verdict"], "pass_data_smoke")

    def test_run_collector_atomically_closes_raw_and_summary(self) -> None:
        def fake_capture(config: LiveCollectorConfig, path: Path) -> dict:
            with GzipJsonlWriter(path) as writer:
                for record in _good_records():
                    writer.write(record)
            return {
                "started_at_ms": NOW,
                "ended_at_ms": NOW + 1_000,
                "market_events": 8,
                "connection_attempts": 1,
                "routes": [],
                "line_count": len(_good_records()),
                "stream_urls": {},
            }

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "collector"
            config = LiveCollectorConfig(symbols=("BTCUSDT",), duration_seconds=1)
            with patch("qount.alpha_agents.live_collector.capture_market_streams", side_effect=fake_capture):
                result = run_live_collector(Settings.from_env(), config, explicit_output_dir=str(output_dir))
            self.assertTrue(Path(result["raw_event_path"]).is_file())
            self.assertTrue(Path(result["artifact_path"]).is_file())
            self.assertFalse((output_dir / "events.jsonl.gz.partial").exists())
            self.assertEqual(result["audit"]["verdict"], "pass_data_smoke")

    def test_continuous_segments_rotate_writers_without_reconnecting(self) -> None:
        class FakeWebSocket:
            def __init__(self, route: str) -> None:
                self.route = route
                self.update_id = 100

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

            def recv(self, timeout: float):
                time.sleep(0.005)
                self.update_id += 1
                now = int(time.time() * 1000)
                if self.route == "public":
                    data = {
                        "e": "bookTicker",
                        "E": now,
                        "s": "BTCUSDT",
                        "u": self.update_id,
                        "b": "100",
                        "B": "1",
                        "a": "101",
                        "A": "1",
                    }
                    stream = "btcusdt@bookTicker"
                else:
                    data = {
                        "e": "aggTrade",
                        "E": now,
                        "s": "BTCUSDT",
                        "a": self.update_id,
                        "p": "100",
                        "q": "1",
                        "m": False,
                    }
                    stream = "btcusdt@aggTrade"
                return json.dumps({"stream": stream, "data": data})

        connect_calls: list[str] = []

        def fake_connect(uri: str, **kwargs):
            connect_calls.append(uri)
            return FakeWebSocket("public" if "/public/" in uri else "market")

        with tempfile.TemporaryDirectory() as tmp:
            config = LiveCollectorConfig(
                symbols=("BTCUSDT",),
                streams=("bookTicker", "aggTrade"),
                duration_seconds=1,
            )
            segments = [
                (config, str(Path(tmp) / "segment-0")),
                (config, str(Path(tmp) / "segment-1")),
            ]
            with patch("websockets.sync.client.connect", side_effect=fake_connect):
                results = run_live_collector_segments(Settings.from_env(), segments)

            self.assertEqual(len(connect_calls), 2)
            self.assertEqual(len(results), 2)
            self.assertEqual([result["audit"]["verdict"] for result in results], ["pass_data_smoke"] * 2)
            first_connections = results[0]["capture"]["connection_ids_at_end"]
            second_connections = results[1]["capture"]["connection_ids_at_start"]
            self.assertEqual(first_connections, second_connections)
            second_records = list(iter_gzip_jsonl(Path(results[1]["raw_event_path"])))
            self.assertEqual(
                {record.get("route") for record in second_records if record["record_type"] == "connection_continuation"},
                {"public", "market"},
            )

    def test_config_rejects_unknown_stream(self) -> None:
        config = LiveCollectorConfig(symbols=("BTCUSDT",), streams=("unknown",), duration_seconds=1)
        with self.assertRaises(ValueError):
            config.validate()


if __name__ == "__main__":
    unittest.main()
