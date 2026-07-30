from __future__ import annotations

import datetime as dt
import io
import json
import tempfile
import unittest
import urllib.parse
import zipfile
from pathlib import Path

from qount.research_data.market_data import Funding
from qount.mini_trend.futures_shadow_inputs import (
    _copy_seed,
    canonical_funding_settlement_timestamp,
    parse_completed_daily_kline_api_response,
    load_funding_snapshots,
    merge_funding,
    parse_funding_api_response,
    refresh_shadow_inputs,
)


def _zip(name: str, text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, text)
    return buffer.getvalue()


def _kline(timestamp: int = 1_767_225_600_000) -> bytes:
    return _zip(
        "row.csv",
        f"{timestamp},100,101,99,100,10,{timestamp + 86_399_999},1000,5,5,500,0\n",
    )


def _funding(timestamp: int = 1_767_254_400_000) -> bytes:
    return _zip("row.csv", f"{timestamp},8,0.0001\n")


def _rest_kline(day: dt.date) -> bytes:
    open_ms = int(dt.datetime.combine(day, dt.time(), dt.UTC).timestamp() * 1000)
    return json.dumps(
        [[open_ms, "100", "101", "99", "100", "10", open_ms + 86_399_999,
          "1000", 5, "5", "500", "0"]]
    ).encode()


def _complete_funding_response(url: str, last_day: dt.date) -> bytes:
    symbol = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["symbol"][0]
    rows = []
    day = last_day.replace(day=1)
    while day <= last_day:
        start_ms = int(dt.datetime.combine(day, dt.time(), dt.UTC).timestamp() * 1000)
        for offset_hours in (8, 16, 24):
            rows.append(
                {
                    "symbol": symbol,
                    "fundingTime": start_ms + offset_hours * 3_600_000,
                    "fundingRate": "0.0001",
                }
            )
        day += dt.timedelta(days=1)
    return json.dumps(rows).encode()


class MiniTrendFuturesShadowInputsTest(unittest.TestCase):
    def test_latest_daily_archive_uses_completed_public_rest_fallback(self) -> None:
        retrieved_at = dt.datetime(2026, 2, 3, 3, tzinfo=dt.UTC)
        fallback_day = dt.date(2026, 2, 2)

        def vision_fetch(url: str) -> bytes:
            if "2026-02-02" in url:
                raise RuntimeError("daily archive not published")
            return _kline()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = refresh_shadow_inputs(
                cache_dir=root / "cache",
                funding_snapshot_root=root / "snapshots",
                start_month="2026-02",
                end_date=fallback_day.isoformat(),
                retrieved_at=retrieved_at,
                vision_fetch=vision_fetch,
                kline_fetch=lambda _: _rest_kline(fallback_day),
                funding_fetch=lambda url: _complete_funding_response(url, fallback_day),
            )
        self.assertEqual(report["diagnostics"]["verdict"], "shadow_inputs_refreshed")
        fallback = [
            row for row in report["files"]
            if row.get("source") == "binance_public_um_rest"
        ]
        self.assertEqual(len(fallback), 3)

    def test_kline_rest_fallback_rejects_uncompleted_row(self) -> None:
        day = dt.date(2026, 2, 2)
        with self.assertRaisesRegex(ValueError, "not yet completed"):
            parse_completed_daily_kline_api_response(
                _rest_kline(day),
                symbol="BTCUSDT",
                day=day,
                retrieved_at=dt.datetime(2026, 2, 2, 12, tzinfo=dt.UTC),
            )

    def test_existing_canonical_cache_ignores_later_seed_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target.zip"
            source = root / "seed.zip"
            target.write_bytes(b"canonical")
            source.write_bytes(b"stale")
            seeded = _copy_seed(target, source)
            persisted = target.read_bytes()
        self.assertFalse(seeded)
        self.assertEqual(persisted, b"canonical")

    def test_small_exchange_timestamp_jitter_is_canonicalized(self) -> None:
        boundary = 28_800_000
        self.assertEqual(
            canonical_funding_settlement_timestamp(boundary + 13), boundary
        )
        self.assertEqual(
            canonical_funding_settlement_timestamp(boundary + 1_001),
            boundary + 1_001,
        )

    def test_parse_funding_api_response_is_bounded_and_deduplicated(self) -> None:
        raw = json.dumps(
            [
                {"symbol": "BTCUSDT", "fundingTime": 2000, "fundingRate": "0.0001"},
                {"symbol": "BTCUSDT", "fundingTime": 1000, "fundingRate": "-0.0002"},
                {"symbol": "BTCUSDT", "fundingTime": 2000, "fundingRate": "0.0001"},
            ]
        ).encode()
        rows = parse_funding_api_response(
            raw, symbol="BTCUSDT", start_ms=1000, end_ms=2000
        )
        self.assertEqual(rows, [Funding(1000, -0.0002), Funding(2000, 0.0001)])

    def test_snapshot_merge_rejects_conflicting_rates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = {
                "schema_version": "mini_trend_um_funding_snapshot_v0.1",
                "symbol": "BTCUSDT",
                "rows": [{"ts_ms": 1000, "rate": 0.0001}],
            }
            second = first | {"rows": [{"ts_ms": 1000, "rate": 0.0002}]}
            (root / "a.json").write_text(json.dumps(first), encoding="utf-8")
            (root / "b.json").write_text(json.dumps(second), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "conflicting funding snapshots"):
                load_funding_snapshots(root)

    def test_merge_funding_accepts_identical_archive_overlap(self) -> None:
        archived = {"BTCUSDT": [Funding(1000, 0.0001)]}
        snapshots = {"BTCUSDT": [Funding(1000, 0.0001), Funding(2000, 0.0002)]}
        merged = merge_funding(archived, snapshots)
        self.assertEqual(merged["BTCUSDT"], [Funding(1000, 0.0001), Funding(2000, 0.0002)])

    def test_empty_funding_response_is_not_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = refresh_shadow_inputs(
                cache_dir=root / "cache",
                funding_snapshot_root=root / "snapshots",
                start_month="2026-02",
                end_date="2026-02-01",
                retrieved_at=dt.datetime(2026, 2, 2, 12, tzinfo=dt.UTC),
                vision_fetch=lambda _: _kline(),
                funding_fetch=lambda _: b"[]",
            )
        self.assertEqual(
            report["diagnostics"]["verdict"],
            "await_complete_shadow_input_transport",
        )
        self.assertFalse(report["diagnostics"]["current_month_funding_complete"])
        self.assertEqual(len(report["funding_api"]["failed_symbols"]), 3)

    def test_refresh_writes_only_public_immutable_inputs(self) -> None:
        retrieved_at = dt.datetime(2026, 2, 3, 12, tzinfo=dt.UTC)
        api_rows = {
            symbol: json.dumps(
                [
                    {
                        "symbol": symbol,
                        "fundingTime": timestamp,
                        "fundingRate": "0.0001",
                    }
                    for timestamp in (
                        1_769_932_800_000,
                        1_769_961_600_000,
                        1_769_990_400_000,
                        1_770_019_200_000,
                        1_770_048_000_000,
                        1_770_076_800_000,
                    )
                ]
            ).encode()
            for symbol in ("BTCUSDT", "ETHUSDT", "BNBUSDT")
        }

        def vision_fetch(url: str) -> bytes:
            if "fundingRate" in url:
                return _funding()
            return _kline()

        def funding_fetch(url: str) -> bytes:
            funding_urls.append(url)
            symbol = next(symbol for symbol in api_rows if f"symbol={symbol}" in url)
            return api_rows[symbol]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            funding_urls: list[str] = []
            report = refresh_shadow_inputs(
                cache_dir=root / "cache",
                funding_snapshot_root=root / "snapshots",
                start_month="2026-01",
                end_date="2026-02-02",
                retrieved_at=retrieved_at,
                vision_fetch=vision_fetch,
                funding_fetch=funding_fetch,
            )
            snapshots = load_funding_snapshots(root / "snapshots")
        self.assertEqual(report["diagnostics"]["verdict"], "shadow_inputs_refreshed")
        self.assertFalse(report["meta"]["private_exchange_data"])
        self.assertEqual(len(report["data_hash"]), 64)
        self.assertEqual(len(report["funding_api"]["complete_symbols"]), 3)
        self.assertTrue(all(len(rows) == 6 for rows in snapshots.values()))
        expected_end_ms = int(
            dt.datetime(2026, 2, 3, tzinfo=dt.UTC).timestamp() * 1000
        ) + 60_000
        self.assertTrue(
            all(
                int(urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["endTime"][0])
                == expected_end_ms
                for url in funding_urls
            )
        )


if __name__ == "__main__":
    unittest.main()
