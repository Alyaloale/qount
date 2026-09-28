from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

from qount.research.forward_collector import CollectionContext
from qount.research.forward_collector import LiquidationStatusPlugin
from qount.research.forward_collector import PluginRegistry
from qount.research.forward_collector import PluginResult
from qount.research.forward_collector import default_registry
from qount.research.forward_collector import load_source_config
from qount.research.forward_collector import run_once
from qount.research.cta_r_inputs import CTA_R_ETF_SYMBOLS
from qount.research.cta_r_inputs import inspect_seed_zip
from qount.research.cta_r_inputs import write_seed_zip


class _TestPlugin:
    name = "test_plugin"

    def collect(self, context: CollectionContext) -> PluginResult:
        return PluginResult("valid", {"symbol_count": len(context.symbols)})


class _FailingPlugin:
    name = "failing_plugin"

    def collect(self, context: CollectionContext) -> PluginResult:
        raise RuntimeError("network unavailable")


class _SecondPlugin:
    name = "second_plugin"

    def collect(self, context: CollectionContext) -> PluginResult:
        return PluginResult("valid", {})


class ForwardCollectorTests(unittest.TestCase):
    def test_cta_r_seed_is_research_only_and_validates_freshness(self) -> None:
        observed_at = dt.datetime(2026, 9, 27, 12, 0, tzinfo=dt.UTC)
        series = {
            symbol: [("2026-09-25", 100.0), ("2026-09-26", 101.0)]
            for symbol in CTA_R_ETF_SYMBOLS
        }
        with tempfile.TemporaryDirectory() as directory:
            path = write_seed_zip(
                Path(directory) / "etf_data.zip", series,
                start_date="2026-01-01", end_date="2026-09-27",
            )
            result = inspect_seed_zip(path, observed_at=observed_at)
            self.assertEqual(result["status"], "valid")
            self.assertFalse(result["strategy_results_evaluated"])
            self.assertEqual(result["adjustment"], "qfq")
            self.assertFalse(result.get("api_key_used", False))

            stale = {
                symbol: [("2026-09-01", 100.0)] for symbol in CTA_R_ETF_SYMBOLS
            }
            stale_path = write_seed_zip(
                Path(directory) / "stale.zip", stale,
                start_date="2026-01-01", end_date="2026-09-27",
            )
            stale_result = inspect_seed_zip(stale_path, observed_at=observed_at)
            self.assertEqual(stale_result["status"], "insufficient")
            self.assertIn("series_stale", stale_result["reason_codes"])

    def test_cta_r_source_plugin_records_seed_status_without_key(self) -> None:
        observed_at = dt.datetime(2026, 9, 27, 12, 0, tzinfo=dt.UTC)
        series = {
            symbol: [("2026-09-25", 100.0)] for symbol in CTA_R_ETF_SYMBOLS
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            seed = write_seed_zip(
                root / "etf_data.zip", series,
                start_date="2026-01-01", end_date="2026-09-27",
            )
            config_path = root / "sources.json"
            config_path.write_text(json.dumps({
                "schema_version": "research_forward_sources_v0.1",
                "sources": {"cta": {"kind": "cta_r_akshare", "seed_path": str(seed)}},
                "research_lines": [{"id": "cta", "sources": ["cta"]}],
            }), encoding="ascii")
            source_config = load_source_config(config_path, repo_root=root)
            record = run_once(
                state_root=root / "state",
                symbols=("BTCUSDT",),
                plugin_names=("research_lines",),
                registry=default_registry(
                    liquidation_state_root=root / "missing-liquidation",
                    source_config=source_config,
                    repo_root=root,
                ),
                observed_at=observed_at,
                source_config_hash=source_config["source_config_hash"],
            )
            payload = record["plugins"]["research_lines"]["payload"]
            self.assertEqual(payload["sources"]["cta"]["status"], "valid")
            self.assertFalse(payload["sources"]["cta"]["payload"]["api_key_used"])

    @staticmethod
    def _liquidation_status(observed_at: dt.datetime, **overrides: object) -> dict[str, object]:
        observed_at_ms = int(observed_at.timestamp() * 1000)
        status: dict[str, object] = {
            "status": "running",
            "stopped_at_ms": None,
            "updated_at_ms": observed_at_ms - 30_000,
            "last_stream_message_at_ms": observed_at_ms - 1_000,
            "research_guards": {
                "orders_authorized": False,
                "private_api_used": False,
                "pnl_evaluated": False,
            },
        }
        status.update(overrides)
        return status

    def test_liquidation_status_requires_fresh_stream_heartbeat(self) -> None:
        observed_at = dt.datetime(2026, 8, 18, 6, 30, tzinfo=dt.UTC)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = root / "metadata"
            metadata.mkdir()
            status_path = metadata / "current.json"
            status_path.write_text(
                json.dumps(self._liquidation_status(observed_at)), encoding="ascii"
            )
            context = CollectionContext(
                observed_at=observed_at,
                symbols=("BTCUSDT",),
                fetch_json=lambda _: {},
                config={},
            )
            fresh = LiquidationStatusPlugin(root).collect(context)
            self.assertEqual(fresh.status, "valid")
            self.assertEqual(fresh.payload["stream_health"]["reason_codes"], [])

            bulky = self._liquidation_status(observed_at, recent_event_ids=["a" * 64] * 4096,
                                            counters={"events": 123}, session_id="session-1")
            status_path.write_text(json.dumps(bulky), encoding="ascii")
            compact = LiquidationStatusPlugin(root).collect(context)
            self.assertNotIn("recent_event_ids", compact.payload["status"])
            self.assertEqual(compact.payload["status"]["counters"], {"events": 123})
            self.assertEqual(compact.payload["status"]["session_id"], "session-1")
            self.assertLess(len(json.dumps(compact.as_dict())), 2000)
            self.assertEqual(json.loads(status_path.read_text()), bulky)

            status_path.write_text(
                json.dumps(
                    self._liquidation_status(
                        observed_at,
                        last_stream_message_at_ms=None,
                    )
                ),
                encoding="ascii",
            )
            missing = LiquidationStatusPlugin(root).collect(context)
            self.assertEqual(missing.status, "insufficient")
            self.assertIn(
                "last_stream_message_at_ms_missing",
                missing.payload["stream_health"]["reason_codes"],
            )

    def test_liquidation_status_rejects_stale_or_unsafe_state(self) -> None:
        observed_at = dt.datetime(2026, 8, 18, 6, 30, tzinfo=dt.UTC)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = root / "metadata"
            metadata.mkdir()
            stale_at_ms = int((observed_at - dt.timedelta(minutes=5)).timestamp() * 1000)
            (metadata / "current.json").write_text(
                json.dumps(
                    self._liquidation_status(
                        observed_at,
                        updated_at_ms=stale_at_ms,
                        last_stream_message_at_ms=stale_at_ms,
                        research_guards={
                            "orders_authorized": True,
                            "private_api_used": False,
                            "pnl_evaluated": False,
                        },
                    )
                ),
                encoding="ascii",
            )
            context = CollectionContext(
                observed_at=observed_at,
                symbols=("BTCUSDT",),
                fetch_json=lambda _: {},
                config={},
            )
            result = LiquidationStatusPlugin(root).collect(context)
            self.assertEqual(result.status, "insufficient")
            reasons = result.payload["stream_health"]["reason_codes"]
            self.assertIn("updated_at_ms_stale", reasons)
            self.assertIn("last_stream_message_at_ms_stale", reasons)
            self.assertIn("research_guards_invalid", reasons)

    def test_source_config_registers_all_research_lines(self) -> None:
        root = Path(__file__).resolve().parents[1]
        config = load_source_config(
            root / "deploy/research/forward-sources.json", repo_root=root
        )
        registry = default_registry(
            liquidation_state_root=Path("/missing/liquidation"),
            source_config=config,
            repo_root=root,
        )
        self.assertIn("research_lines", registry.names())
        self.assertEqual(
            {line["id"] for line in config["research_lines"]},
            {
                "mini_trend_base",
                "funding_veto",
                "vol_crisis",
                "fomc",
                "l1_passive",
                "liquidation_cascade",
            },
        )

    def test_custom_plugin_is_recorded_and_hash_chain_is_append_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = PluginRegistry()
            registry.register(_TestPlugin())
            first_time = dt.datetime(2026, 7, 30, 1, 0, tzinfo=dt.UTC)
            second_time = first_time + dt.timedelta(minutes=15)
            first = run_once(
                state_root=Path(directory),
                symbols=("BTCUSDT",),
                plugin_names=("test_plugin",),
                registry=registry,
                observed_at=first_time,
            )
            second = run_once(
                state_root=Path(directory),
                symbols=("BTCUSDT",),
                plugin_names=("test_plugin",),
                registry=registry,
                observed_at=second_time,
            )
            self.assertEqual(second["previous_record_hash"], first["record_hash"])
            self.assertNotEqual(second["record_hash"], first["record_hash"])
            record_path = Path(directory) / "records/2026/07/30/cycles.jsonl"
            rows = [json.loads(line) for line in record_path.read_text().splitlines()]
            self.assertEqual(len(rows), 2)
            self.assertFalse(rows[0]["orders_authorized"])
            self.assertEqual(rows[1]["plugins"]["test_plugin"]["status"], "valid")

    def test_plugin_exception_is_recorded_as_insufficient_without_aborting_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = PluginRegistry()
            registry.register(_FailingPlugin())
            record = run_once(
                state_root=Path(directory),
                symbols=("BTCUSDT",),
                plugin_names=("failing_plugin",),
                registry=registry,
                observed_at=dt.datetime(2026, 7, 30, tzinfo=dt.UTC),
            )
            result = record["plugins"]["failing_plugin"]
            self.assertEqual(result["status"], "insufficient")
            self.assertEqual(result["payload"]["error"], "RuntimeError")

    def test_contract_rejects_plugin_set_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = PluginRegistry()
            registry.register(_TestPlugin())
            registry.register(_SecondPlugin())
            run_once(
                state_root=Path(directory),
                symbols=("BTCUSDT",),
                plugin_names=("test_plugin",),
                registry=registry,
                observed_at=dt.datetime(2026, 7, 30, tzinfo=dt.UTC),
            )
            with self.assertRaisesRegex(ValueError, "forward_contract_mismatch"):
                run_once(
                    state_root=Path(directory),
                    symbols=("BTCUSDT",),
                    plugin_names=("test_plugin", "second_plugin"),
                    registry=registry,
                    observed_at=dt.datetime(2026, 7, 30, 0, 15, tzinfo=dt.UTC),
                )


if __name__ == "__main__":
    unittest.main()
