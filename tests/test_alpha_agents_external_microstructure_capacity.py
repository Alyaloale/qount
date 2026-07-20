from __future__ import annotations

import gzip
import json
import unittest
from urllib.parse import parse_qs
from urllib.parse import urlparse

from qount.alpha_agents.external_microstructure_capacity import EXTERNAL_MICROSTRUCTURE_CAPACITY_VERSION
from qount.alpha_agents.external_microstructure_capacity import ExternalMicrostructureCapacityConfig
from qount.alpha_agents.external_microstructure_capacity import _decode_response_body
from qount.alpha_agents.external_microstructure_capacity import build_external_microstructure_capacity
from qount.alpha_agents.external_microstructure_capacity import parse_tardis_raw_feed


def _line(receive_time: str, stream: str, data: dict) -> bytes:
    return f"{receive_time} {json.dumps({'stream': stream, 'data': data}, separators=(',', ':'))}\n".encode()


def _fake_fetch(url: str) -> tuple[int, dict[str, str], bytes]:
    if "/exchanges/" in url:
        symbols = []
        for symbol in ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"):
            symbols.append(
                {
                    "id": symbol,
                    "availableSince": "2020-01-01T00:00:00Z",
                    "availableTo": "2026-01-01T00:00:00Z",
                    "dataTypes": ["incremental_book_L2", "liquidations"],
                }
            )
        payload = {
            "id": "binance-futures",
            "name": "Binance USDS-M Futures",
            "datasets": {
                "exportedFrom": "2019-11-17T00:00:00Z",
                "exportedUntil": "2026-01-01T00:00:00Z",
                "formats": ["csv"],
                "symbols": symbols,
            },
        }
        return 200, {}, json.dumps(payload).encode()
    query = parse_qs(urlparse(url).query)
    filters = json.loads(query["filters"][0])
    channel = filters[0]["channel"]
    if channel == "depth":
        raw = b"".join(
            (
                _line(
                    "2024-01-01T00:00:00.0000000Z",
                    "btcusdt@depth@0ms",
                    {"e": "depthUpdate", "s": "BTCUSDT", "U": 1, "u": 2, "pu": 0, "b": [], "a": []},
                ),
                _line(
                    "2024-01-01T00:00:01.0000000Z",
                    "btcusdt@depth@0ms",
                    {"e": "depthUpdate", "s": "BTCUSDT", "U": 3, "u": 4, "pu": 2, "b": [], "a": []},
                ),
            )
        )
        return 200, {"x-slice-size": "1"}, raw
    raw = _line(
        "2024-01-01T00:00:33.0000000Z",
        "solusdt@forceOrder",
        {"e": "forceOrder", "o": {"s": "SOLUSDT", "q": "2", "p": "100"}},
    )
    return 200, {"x-slice-size": "1"}, raw


class ExternalMicrostructureCapacityTest(unittest.TestCase):
    def test_gzip_feed_body_is_decoded_before_parsing(self) -> None:
        raw = _line(
            "2024-01-01T00:00:33.0000000Z",
            "solusdt@forceOrder",
            {"e": "forceOrder", "o": {"s": "SOLUSDT"}},
        )
        self.assertEqual(
            _decode_response_body(gzip.compress(raw), {"content-encoding": "gzip"}),
            raw,
        )

    def test_parser_checks_depth_sequence(self) -> None:
        status, _headers, raw = _fake_fetch(
            "https://api.tardis.dev/v1/data-feeds/binance-futures?filters="
            + "%5B%7B%22channel%22%3A%22depth%22%7D%5D"
        )
        self.assertEqual(status, 200)
        parsed = parse_tardis_raw_feed(raw)
        self.assertEqual(parsed["event_counts"]["depthUpdate"], 2)
        self.assertEqual(parsed["depth_sequence_break_count"], 0)

    def test_blocks_unlicensed_truncated_history_and_l2_budget(self) -> None:
        payload = build_external_microstructure_capacity(
            ExternalMicrostructureCapacityConfig(maximum_source_cache_budget_bytes=1_000),
            fetch=_fake_fetch,
        )
        diagnostics = payload["diagnostics"]
        self.assertEqual(payload["schema_version"], EXTERNAL_MICROSTRUCTURE_CAPACITY_VERSION)
        self.assertEqual(diagnostics["verdict"], "block_g0_access_capacity")
        self.assertTrue(diagnostics["provider_metadata_complete"])
        self.assertTrue(diagnostics["replayable_l2_sample_pass"])
        self.assertTrue(diagnostics["liquidation_sample_pass"])
        self.assertFalse(diagnostics["anonymous_full_horizon_access"])
        self.assertFalse(diagnostics["l2_within_cache_budget"])
        self.assertTrue(diagnostics["liquidation_preferred_if_access_authorized"])
        self.assertFalse(diagnostics["preregistration_allowed"])
        self.assertIn("licensed_full_history_access_not_authorized", diagnostics["blockers"])

    def test_full_horizon_access_uses_provider_slice_size(self) -> None:
        def licensed_fetch(url: str) -> tuple[int, dict[str, str], bytes]:
            status, headers, raw = _fake_fetch(url)
            if "/data-feeds/" in url:
                query = parse_qs(urlparse(url).query)
                start = query["from"][0]
                end = query["to"][0]
                if start == "2024-01-01T00:00:00Z" and end == "2024-01-02T00:00:00Z":
                    headers = {**headers, "x-slice-size": "1440"}
            return status, headers, raw

        payload = build_external_microstructure_capacity(
            ExternalMicrostructureCapacityConfig(maximum_source_cache_budget_bytes=10**12),
            fetch=licensed_fetch,
        )
        self.assertTrue(payload["diagnostics"]["anonymous_full_horizon_access"])
        self.assertEqual(payload["diagnostics"]["verdict"], "eligible_g0")

    def test_missing_symbol_metadata_fails_closed(self) -> None:
        def missing_metadata(url: str) -> tuple[int, dict[str, str], bytes]:
            status, headers, raw = _fake_fetch(url)
            if "/exchanges/" in url:
                payload = json.loads(raw)
                payload["datasets"]["symbols"] = payload["datasets"]["symbols"][:-1]
                raw = json.dumps(payload).encode()
            return status, headers, raw

        payload = build_external_microstructure_capacity(fetch=missing_metadata)
        self.assertIn("provider_metadata_incomplete", payload["diagnostics"]["blockers"])


if __name__ == "__main__":
    unittest.main()
