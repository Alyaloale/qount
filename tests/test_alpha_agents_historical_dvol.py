from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs
from urllib.parse import urlparse

from qount.alpha_agents.historical_dvol import HISTORICAL_DVOL_VERSION
from qount.alpha_agents.historical_dvol import HOUR_MS
from qount.alpha_agents.historical_dvol import HistoricalDvolConfig
from qount.alpha_agents.historical_dvol import build_historical_dvol_dataset
from qount.alpha_agents.historical_dvol import parse_dvol_response


def _fake_fetch(url: str) -> bytes:
    query = parse_qs(urlparse(url).query)
    start_ms = int(query["start_timestamp"][0])
    end_ms = int(query["end_timestamp"][0])
    rows = []
    for ts_ms in range(start_ms, end_ms + HOUR_MS, HOUR_MS):
        base = 60.0 if query["currency"][0] == "BTC" else 70.0
        close = base + (ts_ms - start_ms) / HOUR_MS * 0.01
        rows.append([ts_ms, close - 0.1, close + 0.2, close - 0.2, close])
    return json.dumps({"result": {"data": rows, "continuation": None}}).encode()


class HistoricalDvolTest(unittest.TestCase):
    def test_parser_rejects_continuation_and_bad_ohlc(self) -> None:
        raw = json.dumps(
            {"result": {"data": [[0, 50, 49, 48, 50]], "continuation": None}}
        ).encode()
        with self.assertRaisesRegex(ValueError, "OHLC"):
            parse_dvol_response(raw, currency="BTC", start_ms=0, end_exclusive_ms=HOUR_MS)
        continuation = json.dumps(
            {"result": {"data": [], "continuation": 1}}
        ).encode()
        with self.assertRaisesRegex(ValueError, "continuation"):
            parse_dvol_response(
                continuation, currency="BTC", start_ms=0, end_exclusive_ms=HOUR_MS
            )

    def test_builds_complete_aligned_dataset_and_reuses_raw_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache"
            config = HistoricalDvolConfig(
                start_date="2024-01-01",
                end_date="2024-01-02",
                cache_dir=str(cache),
                min_coverage_ratio=1.0,
            )
            first = build_historical_dvol_dataset(config, fetch=_fake_fetch)

            def no_network(url: str) -> bytes:
                raise AssertionError(url)

            second = build_historical_dvol_dataset(config, fetch=no_network)
        self.assertEqual(first["schema_version"], HISTORICAL_DVOL_VERSION)
        self.assertEqual(first["diagnostics"]["verdict"], "pass_dataset")
        self.assertEqual(first["diagnostics"]["expected_hour_count"], 48)
        self.assertEqual(first["diagnostics"]["aligned_complete_hour_count"], 48)
        self.assertEqual(first["diagnostics"]["request_count"], 2)
        self.assertEqual(first["diagnostics"]["by_currency"]["BTC"]["coverage_ratio"], 1.0)
        self.assertTrue(second["source_requests"][0]["cache_hit"])
        self.assertEqual(first["meta"]["data_hash"], second["meta"]["data_hash"])
        self.assertEqual(first["hourly_features"][0]["decision_ts_ms"], first["hourly_features"][0]["ts_ms"] + HOUR_MS)
        self.assertAlmostEqual(first["hourly_features"][0]["eth_minus_btc_dvol_close"], 10.0)


if __name__ == "__main__":
    unittest.main()
