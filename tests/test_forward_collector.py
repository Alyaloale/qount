from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

from qount.research.forward_collector import CollectionContext
from qount.research.forward_collector import PluginRegistry
from qount.research.forward_collector import PluginResult
from qount.research.forward_collector import default_registry
from qount.research.forward_collector import load_source_config
from qount.research.forward_collector import run_once


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
                "cta_r",
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
