from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from qount.venue import VenueCapabilitySnapshot
from qount.venue import extract_symbol_rules
from qount.venue import fetch_venue_data
from qount.venue import run_venue_snapshot


_EXCHANGE_INFO: dict[str, Any] = {
    "timezone": "UTC",
    "serverTime": 1721712000000,
    "symbols": [
        {
            "symbol": "BTCUSDT",
            "status": "TRADING",
            "baseAsset": "BTC",
            "quoteAsset": "USDT",
            "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
                {"filterType": "LOT_SIZE", "stepSize": "0.001",
                 "minQty": "0.001", "maxQty": "1000"},
                {"filterType": "MIN_NOTIONAL", "notional": "5.0"},
            ],
            "pricePrecision": 2,
            "quantityPrecision": 3,
        },
        {
            "symbol": "ETHUSDT",
            "status": "TRADING",
            "baseAsset": "ETH",
            "quoteAsset": "USDT",
            "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                {"filterType": "LOT_SIZE", "stepSize": "0.001",
                 "minQty": "0.001", "maxQty": "10000"},
                {"filterType": "MIN_NOTIONAL", "notional": "5.0"},
            ],
            "pricePrecision": 2,
            "quantityPrecision": 3,
        },
    ],
}

_CHANGELOG_BODY = "# Binance USD-M Futures Changelog\n## 2026-07-01\n- Updated API rate limits.\n"


class MockVenueDataFetcher:
    """Mock fetcher implementing VenueDataFetcher Protocol."""

    def __init__(
        self,
        exchange_info: dict[str, Any] | None = None,
        server_time_ms: int = 1721712000000,
        changelog_body: str = _CHANGELOG_BODY,
        changelog_observed_at: str = "2026-07-23T00:00:00+00:00",
    ) -> None:
        self._exchange_info = exchange_info or _EXCHANGE_INFO
        self._server_time_ms = server_time_ms
        self._changelog_body = changelog_body
        self._changelog_observed_at = changelog_observed_at

    def fetch_exchange_info(self) -> dict[str, Any]:
        return self._exchange_info

    def fetch_server_time_ms(self) -> int:
        return self._server_time_ms

    def fetch_changelog_body(self) -> tuple[str, str]:
        return self._changelog_body, self._changelog_observed_at


class FetchVenueDataTest(unittest.TestCase):
    def test_fetch_returns_all_data(self) -> None:
        fetcher = MockVenueDataFetcher()
        data = fetch_venue_data(fetcher)
        self.assertIn("symbols", data.exchange_info)
        self.assertEqual(data.server_time_ms, 1721712000000)
        self.assertEqual(data.changelog_body, _CHANGELOG_BODY)
        self.assertTrue(data.changelog_source_hash)

    def test_server_time_offset(self) -> None:
        fetcher = MockVenueDataFetcher(server_time_ms=1721712001000)
        data = fetch_venue_data(fetcher)
        offset = data.server_time_offset_ms
        self.assertIsInstance(offset, int)

    def test_changelog_hash_consistent(self) -> None:
        fetcher = MockVenueDataFetcher()
        data1 = fetch_venue_data(fetcher)
        data2 = fetch_venue_data(fetcher)
        self.assertEqual(
            data1.changelog_source_hash, data2.changelog_source_hash
        )


class ExtractSymbolRulesTest(unittest.TestCase):
    def test_extract_all_symbols(self) -> None:
        rules = extract_symbol_rules(_EXCHANGE_INFO)
        self.assertIn("BTCUSDT", rules)
        self.assertIn("ETHUSDT", rules)

    def test_extract_specific_symbols(self) -> None:
        rules = extract_symbol_rules(_EXCHANGE_INFO, ["BTCUSDT"])
        self.assertIn("BTCUSDT", rules)
        self.assertNotIn("ETHUSDT", rules)

    def test_extract_nonexistent_symbol(self) -> None:
        rules = extract_symbol_rules(_EXCHANGE_INFO, ["DOGEUSDT"])
        self.assertEqual(len(rules), 0)


class RunVenueSnapshotTest(unittest.TestCase):
    def test_first_snapshot_passes(self) -> None:
        fetcher = MockVenueDataFetcher()
        snapshot = run_venue_snapshot(
            fetcher=fetcher,
            symbols=["BTCUSDT", "ETHUSDT"],
        )
        self.assertEqual(snapshot.venue, "binance_usdm")
        self.assertEqual(snapshot.compatibility, "pass")
        self.assertEqual(snapshot.position_mode, "one_way")
        self.assertEqual(snapshot.margin_mode, "isolated")
        self.assertEqual(snapshot.leverage, 1)

    def test_blocked_on_wrong_position_mode(self) -> None:
        fetcher = MockVenueDataFetcher()
        snapshot = run_venue_snapshot(
            fetcher=fetcher,
            position_mode="hedge",
        )
        self.assertEqual(snapshot.compatibility, "blocked")
        self.assertIn("position_mode_not_one_way", snapshot.blockers)

    def test_review_required_on_exchange_info_change(self) -> None:
        fetcher1 = MockVenueDataFetcher()
        snap1 = run_venue_snapshot(fetcher=fetcher1)

        modified_info = json.loads(json.dumps(_EXCHANGE_INFO))
        modified_info["symbols"][0]["pricePrecision"] = 3
        fetcher2 = MockVenueDataFetcher(exchange_info=modified_info)
        snap2 = run_venue_snapshot(
            fetcher=fetcher2,
            previous_snapshot=snap1,
        )
        self.assertEqual(snap2.compatibility, "review_required")

    def test_review_required_on_changelog_change(self) -> None:
        fetcher1 = MockVenueDataFetcher()
        snap1 = run_venue_snapshot(fetcher=fetcher1)

        fetcher2 = MockVenueDataFetcher(
            changelog_body="# Updated changelog\n## 2026-07-22\n- New changes.\n",
        )
        snap2 = run_venue_snapshot(
            fetcher=fetcher2,
            previous_snapshot=snap1,
        )
        self.assertEqual(snap2.compatibility, "review_required")
        self.assertIn("changelog_text_changed", snap2.blockers)

    def test_pass_on_no_change(self) -> None:
        fetcher1 = MockVenueDataFetcher()
        snap1 = run_venue_snapshot(fetcher=fetcher1)

        fetcher2 = MockVenueDataFetcher()
        snap2 = run_venue_snapshot(
            fetcher=fetcher2,
            previous_snapshot=snap1,
        )
        self.assertEqual(snap2.compatibility, "pass")

    def test_archive_creates_file(self) -> None:
        fetcher = MockVenueDataFetcher()
        with tempfile.TemporaryDirectory() as tmp:
            archive_dir = Path(tmp) / "venue_snapshots"
            snapshot = run_venue_snapshot(
                fetcher=fetcher,
                archive_dir=str(archive_dir),
            )
            files = list(archive_dir.glob("*.json"))
            self.assertEqual(len(files), 1)
            data = json.loads(files[0].read_text(encoding="ascii"))
            self.assertEqual(data["snapshot_hash"], snapshot.snapshot_hash)
            self.assertEqual(data["compatibility"], "pass")


if __name__ == "__main__":
    unittest.main()
