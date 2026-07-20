from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from qount.alpha_agents.historical_microstructure import HistoricalMicrostructureConfig
from qount.alpha_agents.historical_microstructure import archive_url
from qount.alpha_agents.historical_microstructure import build_historical_microstructure_coverage
from qount.alpha_agents.historical_microstructure import write_historical_microstructure_artifact
from qount.settings import Settings


def _checksum_for(url: str) -> bytes:
    filename = url.removesuffix(".CHECKSUM").rsplit("/", 1)[-1]
    return f"{'a' * 64}  {filename}\n".encode()


def _fake_fetch(url: str) -> bytes:
    if "/bookTicker/" in url and "/daily/" in url:
        raise FileNotFoundError(url)
    if "/bookDepth/" in url and "/monthly/" in url:
        raise AssertionError("bookDepth monthly must not be probed")
    return _checksum_for(url)


class HistoricalMicrostructureCoverageTest(unittest.TestCase):
    def test_archive_url(self) -> None:
        self.assertEqual(
            archive_url(
                dataset="aggTrades",
                symbol="BTCUSDT",
                cadence="monthly",
                period="2024-01",
            ),
            "https://data.binance.vision/data/futures/um/monthly/aggTrades/"
            "BTCUSDT/BTCUSDT-aggTrades-2024-01.zip",
        )

    def test_builds_coverage_without_downloading_archives(self) -> None:
        payload = build_historical_microstructure_coverage(
            HistoricalMicrostructureConfig(
                symbols=("BTCUSDT",),
                daily_dates=("2024-01-01",),
                monthly_months=("2024-01",),
                datasets=("aggTrades", "bookTicker", "bookDepth", "metrics", "forceOrder"),
            ),
            fetch=_fake_fetch,
        )
        self.assertEqual(payload["schema_version"], "alpha_agent_historical_microstructure_v0.1")
        self.assertEqual(payload["diagnostics"]["verdict"], "coverage_mapped")
        self.assertEqual(payload["diagnostics"]["status_counts"], {"available": 5, "missing": 1})
        self.assertEqual(payload["diagnostics"]["by_dataset"]["bookDepth"]["probe_count"], 1)
        self.assertEqual(payload["dataset_contracts"]["bookDepth"]["replaces_live_stream"], False)
        self.assertIn("no_pu_u_sequence", payload["dataset_contracts"]["bookDepth"]["replacement_blockers"])
        self.assertEqual(payload["diagnostics"]["live_only_or_external_source"][0], "forceOrder")
        self.assertTrue(all(probe["checksum_url"].endswith(".CHECKSUM") for probe in payload["probes"]))

    def test_network_error_is_fail_closed(self) -> None:
        def broken_fetch(url: str) -> bytes:
            raise TimeoutError(url)

        payload = build_historical_microstructure_coverage(
            HistoricalMicrostructureConfig(
                symbols=("BTCUSDT",),
                daily_dates=("2024-01-01",),
                monthly_months=(),
                datasets=("metrics",),
            ),
            fetch=broken_fetch,
        )
        self.assertEqual(payload["diagnostics"]["verdict"], "coverage_incomplete")
        self.assertEqual(payload["diagnostics"]["status_counts"], {"error": 1})

    def test_artifact_writer(self) -> None:
        payload = build_historical_microstructure_coverage(
            HistoricalMicrostructureConfig(
                symbols=("BTCUSDT",),
                daily_dates=("2024-01-01",),
                monthly_months=(),
                datasets=("metrics",),
            ),
            fetch=_fake_fetch,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "coverage.json"
            artifact = write_historical_microstructure_artifact(
                Settings.from_env(),
                payload,
                explicit_path=str(path),
            )
            self.assertTrue(path.exists())
            self.assertEqual(json.loads(path.read_text())["schema_version"], payload["schema_version"])
            self.assertEqual(artifact["artifact_path"], str(path))


if __name__ == "__main__":
    unittest.main()
