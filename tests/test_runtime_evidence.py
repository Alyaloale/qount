from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

from qount.operations.runtime_evidence import probe_forward, probe_liquidation
from qount.research.forward_collector import PluginRegistry, PluginResult, run_once


NOW = dt.datetime(2026, 9, 23, 4, tzinfo=dt.timezone.utc)


class _Sources:
    name = "research_lines"

    def collect(self, context):
        return PluginResult("insufficient", {"sources": {
            "binance": {"status": "valid"},
            "l1_passive": {"status": "insufficient", "payload": {"secret": "never-publish"}},
        }})


class RuntimeEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def _forward(self):
        registry = PluginRegistry()
        registry.register(_Sources())
        run_once(state_root=self.root, symbols=("BTCUSDT",), plugin_names=("research_lines",),
                 registry=registry, observed_at=NOW)

    def _liquidation(self, **overrides):
        value = {
            "status": "running", "stopped_at_ms": None,
            "updated_at_ms": int(NOW.timestamp() * 1000),
            "last_stream_message_at_ms": int(NOW.timestamp() * 1000),
            "research_guards": dict.fromkeys(("orders_authorized", "private_api_used",
                                              "pnl_evaluated", "read_results_before_window"), False),
        } | overrides
        path = self.root / "metadata/current.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(value))

    def test_real_head_distinguishes_freshness_from_source_gaps(self):
        self._forward()
        checks = probe_forward(self.root, observed_at=NOW.isoformat())
        indexed = {r["check_id"]: r for r in checks}
        self.assertEqual(indexed["runtime:forward"]["status"], "pass")
        self.assertEqual(indexed["runtime:source_l1_passive"]["status"], "warn")
        self.assertNotIn("never-publish", json.dumps(checks))
        stale = probe_forward(self.root, observed_at=(NOW + dt.timedelta(minutes=31)).isoformat())
        self.assertEqual(stale[0]["detail"], "forward_head_stale")

    def test_tampered_record_and_path_escape_are_unavailable(self):
        self._forward()
        path = self.root / "records/2026/09/23/cycles.jsonl"
        path.write_text(path.read_text().replace('"research_only":true', '"research_only":false'))
        self.assertEqual(probe_forward(self.root, observed_at=NOW.isoformat())[0]["status"], "unavailable")
        head_path = self.root / "metadata/current.json"
        head = json.loads(head_path.read_bytes())
        head["last_record_path"] = "../private.json"
        head_path.write_text(json.dumps(head))
        self.assertEqual(probe_forward(self.root, observed_at=NOW.isoformat())[0]["status"], "unavailable")

    def test_published_head_survives_next_unpublished_complete_row(self):
        self._forward()
        head_path = self.root / "metadata/current.json"
        old = head_path.read_bytes()
        self._forward()
        head_path.write_bytes(old)
        self.assertEqual(probe_forward(self.root, observed_at=NOW.isoformat())[0]["status"], "pass")

    def test_live_heartbeat_checks_staleness_future_and_guards(self):
        self._liquidation()
        self.assertEqual(probe_liquidation(self.root, observed_at=NOW.isoformat())[0]["status"], "pass")
        later = (NOW + dt.timedelta(seconds=181)).isoformat()
        self.assertEqual(probe_liquidation(self.root, observed_at=later)[0]["status"], "warn")
        self._liquidation(last_stream_message_at_ms=int(NOW.timestamp() * 1000) + 60_000)
        self.assertEqual(probe_liquidation(self.root, observed_at=NOW.isoformat())[0]["status"], "unavailable")
        self._liquidation(research_guards={"orders_authorized": True})
        self.assertEqual(probe_liquidation(self.root, observed_at=NOW.isoformat())[0]["detail"],
                         "liquidation_guards_invalid")

    def test_missing_malformed_oversized_and_symlink_fail_closed(self):
        self.assertEqual(probe_liquidation(self.root, observed_at=NOW.isoformat())[0]["status"], "unavailable")
        path = self.root / "metadata/current.json"
        path.parent.mkdir()
        for raw in ('[]', '{"a":1,"a":2}', ' ' * (2 * 1024 * 1024 + 1)):
            path.write_text(raw)
            self.assertEqual(probe_liquidation(self.root, observed_at=NOW.isoformat())[0]["status"], "unavailable")
        path.unlink()
        path.symlink_to(self.root / "not-a-status")
        self.assertEqual(probe_liquidation(self.root, observed_at=NOW.isoformat())[0]["status"], "unavailable")
