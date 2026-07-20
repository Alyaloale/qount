from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs
from urllib.parse import urlparse

from qount.alpha_agents.derivatives_state import DerivativesStateConfig
from qount.alpha_agents.derivatives_state import build_derivatives_state_dataset
from qount.alpha_agents.derivatives_state import fetch_open_interest_hist
from qount.alpha_agents.derivatives_state import fetch_taker_long_short_ratio
from qount.alpha_agents.derivatives_state import write_derivatives_state_artifact
from qount.settings import Settings


NOW_MS = 1704153600000
START_MS = NOW_MS - 24 * 60 * 60_000


def _fake_fetch(url: str) -> bytes:
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    symbol = params.get("symbol", ["ETHUSDT"])[0]
    if parsed.path.endswith("/openInterestHist"):
        rows = [
            {
                "symbol": symbol,
                "sumOpenInterest": "100.0",
                "sumOpenInterestValue": "200000.0",
                "timestamp": START_MS,
            },
            {
                "symbol": symbol,
                "sumOpenInterest": "101.0",
                "sumOpenInterestValue": "202000.0",
                "timestamp": START_MS + 300_000,
            },
        ]
        return json.dumps(rows).encode("utf-8")
    if parsed.path.endswith("/takerlongshortRatio"):
        rows = [
            {
                "buySellRatio": "1.25",
                "buyVol": "500.0",
                "sellVol": "400.0",
                "timestamp": START_MS,
            },
            {
                "buySellRatio": "0.80",
                "buyVol": "320.0",
                "sellVol": "400.0",
                "timestamp": START_MS + 300_000,
            },
        ]
        return json.dumps(rows).encode("utf-8")
    if parsed.path.endswith("/openInterest"):
        return json.dumps({"symbol": symbol, "openInterest": "123.45", "time": NOW_MS}).encode("utf-8")
    raise AssertionError(f"unexpected url {url}")


class AlphaAgentsDerivativesStateTest(unittest.TestCase):
    def test_fetch_open_interest_hist_parses_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rows = fetch_open_interest_hist(
                "ETHUSDT",
                period="5m",
                start_ms=START_MS,
                end_ms=START_MS + 300_000,
                limit=500,
                cache_dir=tmp,
                fetch=_fake_fetch,
            )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].symbol, "ETHUSDT")
        self.assertAlmostEqual(rows[1].sum_open_interest, 101.0)

    def test_fetch_taker_long_short_parses_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rows = fetch_taker_long_short_ratio(
                "ETHUSDT",
                period="5m",
                start_ms=START_MS,
                end_ms=START_MS + 300_000,
                limit=500,
                cache_dir=tmp,
                fetch=_fake_fetch,
            )
        self.assertEqual(len(rows), 2)
        self.assertAlmostEqual(rows[0].buy_sell_ratio, 1.25)
        self.assertAlmostEqual(rows[1].sell_vol, 400.0)

    def test_build_derivatives_state_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = DerivativesStateConfig(symbols=("ETHUSDT",), days=1, cache_dir=tmp)
            payload = build_derivatives_state_dataset(config, fetch=_fake_fetch, now_ms=NOW_MS)
        self.assertEqual(payload["schema_version"], "alpha_agent_derivatives_state_v0.1")
        self.assertEqual(payload["meta"]["history_limit"], "latest_30_days_official_limit")
        self.assertEqual(payload["diagnostics"]["open_interest_hist_count"], 2)
        self.assertEqual(payload["diagnostics"]["taker_long_short_count"], 2)
        self.assertEqual(payload["diagnostics"]["current_open_interest_count"], 1)
        self.assertEqual(payload["diagnostics"]["errors"], [])
        by_symbol = payload["diagnostics"]["by_symbol"]["ETHUSDT"]
        self.assertEqual(by_symbol["open_interest_hist"]["row_count"], 2)

    def test_rejects_windows_beyond_official_recent_limit(self) -> None:
        config = DerivativesStateConfig(symbols=("ETHUSDT",), days=31)
        with self.assertRaises(ValueError):
            build_derivatives_state_dataset(config, fetch=_fake_fetch, now_ms=NOW_MS)

    def test_artifact_writer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings.from_env()
            output_path = Path(tmp) / "alpha_agent_derivatives_state.json"
            payload = build_derivatives_state_dataset(
                DerivativesStateConfig(symbols=("ETHUSDT",), days=1, cache_dir=str(Path(tmp) / "cache")),
                fetch=_fake_fetch,
                now_ms=NOW_MS,
            )
            artifact = write_derivatives_state_artifact(settings, payload, explicit_path=str(output_path))
            path = Path(artifact["artifact_path"])
            self.assertTrue(path.exists())
            self.assertEqual(json.loads(path.read_text())["schema_version"], "alpha_agent_derivatives_state_v0.1")


if __name__ == "__main__":
    unittest.main()
