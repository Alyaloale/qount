from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from qount.alpha_agents.historical_derivatives import HistoricalDerivativesConfig
from qount.alpha_agents.historical_derivatives import build_historical_derivatives_dataset
from qount.alpha_agents.historical_derivatives import parse_historical_metrics_csv
from qount.alpha_agents.historical_derivatives import write_historical_derivatives_artifact
from qount.settings import Settings


HEADER = (
    "create_time,symbol,sum_open_interest,sum_open_interest_value,"
    "count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,"
    "count_long_short_ratio,sum_taker_long_short_vol_ratio"
)


def _metrics_zip(symbol: str, day: str) -> bytes:
    rows = [HEADER]
    for index in range(288):
        hour, minute = divmod((index + 1) * 5, 60)
        timestamp = f"{day} {hour % 24:02d}:{minute:02d}:00"
        rows.append(
            f"{timestamp},{symbol},{1000 + index},{200000 + index},1.1,1.2,1.3,{0.8 + index / 1000}"
        )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"{symbol}-metrics-{day}.csv", "\n".join(rows))
    return buffer.getvalue()


def _metrics_zip_with_gap(symbol: str, day: str) -> bytes:
    rows = [HEADER]
    for index in list(range(60)) + list(range(180, 288)):
        hour, minute = divmod((index + 1) * 5, 60)
        timestamp = f"{day} {hour % 24:02d}:{minute:02d}:00"
        rows.append(
            f"{timestamp},{symbol},{1000 + index},{200000 + index},1.1,1.2,1.3,{0.8 + index / 1000}"
        )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"{symbol}-metrics-{day}.csv", "\n".join(rows))
    return buffer.getvalue()


def _fake_fetch(url: str) -> bytes:
    filename = url.removesuffix(".CHECKSUM").rsplit("/", 1)[-1]
    symbol, _, day_zip = filename.partition("-metrics-")
    day = day_zip.removesuffix(".zip")
    blob = _metrics_zip(symbol, day)
    if url.endswith(".CHECKSUM"):
        return f"{hashlib.sha256(blob).hexdigest()}  {filename}\n".encode()
    return blob


class HistoricalDerivativesTest(unittest.TestCase):
    def test_parse_metrics_rows(self) -> None:
        text = "\n".join(
            [
                HEADER,
                "2024-01-01 00:05:00,BTCUSDT,1000,200000,1.1,1.2,1.3,0.9",
            ]
        )
        rows = parse_historical_metrics_csv(text)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].symbol, "BTCUSDT")
        self.assertEqual(rows[0].ts_ms, 1704067500000)
        self.assertAlmostEqual(rows[0].sum_taker_long_short_vol_ratio, 0.9)

    def test_builds_checksum_verified_compatible_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = build_historical_derivatives_dataset(
                HistoricalDerivativesConfig(
                    symbols=("BTCUSDT", "ETHUSDT"),
                    start_date="2024-01-01",
                    end_date="2024-01-02",
                    cache_dir=tmp,
                    max_workers=2,
                ),
                fetch=_fake_fetch,
            )
        self.assertEqual(payload["diagnostics"]["verdict"], "pass_data_smoke")
        self.assertEqual(payload["diagnostics"]["requested_archive_count"], 4)
        self.assertEqual(payload["diagnostics"]["loaded_archive_count"], 4)
        self.assertEqual(payload["diagnostics"]["row_count"], 1152)
        self.assertEqual(payload["diagnostics"]["by_symbol"]["BTCUSDT"]["coverage_ratio"], 1.0)
        self.assertTrue(payload["meta"]["checksum_verified"])
        self.assertEqual(len(payload["open_interest_hist"]), 1152)
        self.assertEqual(payload["taker_long_short"][0]["buy_vol"], None)
        self.assertIn("taker_ratio", payload["meta"]["supported_feature_families"])
        self.assertIn("taker_imbalance", payload["meta"]["unsupported_feature_families"])

    def test_checksum_mismatch_blocks_dataset(self) -> None:
        def bad_fetch(url: str) -> bytes:
            if url.endswith(".CHECKSUM"):
                filename = url.removesuffix(".CHECKSUM").rsplit("/", 1)[-1]
                return f"{'0' * 64}  {filename}\n".encode()
            return _fake_fetch(url)

        with tempfile.TemporaryDirectory() as tmp:
            payload = build_historical_derivatives_dataset(
                HistoricalDerivativesConfig(
                    symbols=("BTCUSDT",),
                    start_date="2024-01-01",
                    end_date="2024-01-01",
                    cache_dir=tmp,
                ),
                fetch=bad_fetch,
            )
        self.assertEqual(payload["diagnostics"]["verdict"], "block_data")
        self.assertIn("archive_fetch_or_parse_errors", payload["diagnostics"]["blockers"])

    def test_gap_creates_new_segment(self) -> None:
        def gap_fetch(url: str) -> bytes:
            filename = url.removesuffix(".CHECKSUM").rsplit("/", 1)[-1]
            symbol, _, day_zip = filename.partition("-metrics-")
            day = day_zip.removesuffix(".zip")
            blob = _metrics_zip_with_gap(symbol, day)
            if url.endswith(".CHECKSUM"):
                return f"{hashlib.sha256(blob).hexdigest()}  {filename}\n".encode()
            return blob

        with tempfile.TemporaryDirectory() as tmp:
            payload = build_historical_derivatives_dataset(
                HistoricalDerivativesConfig(
                    symbols=("BTCUSDT",),
                    start_date="2024-01-01",
                    end_date="2024-01-01",
                    cache_dir=tmp,
                    min_coverage_ratio=0.5,
                ),
                fetch=gap_fetch,
            )
        segments = {row["segment_id"] for row in payload["open_interest_hist"]}
        self.assertEqual(segments, {0, 1})
        self.assertEqual(payload["diagnostics"]["by_symbol"]["BTCUSDT"]["segment_count"], 2)

    def test_artifact_writer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = build_historical_derivatives_dataset(
                HistoricalDerivativesConfig(
                    symbols=("BTCUSDT",),
                    start_date="2024-01-01",
                    end_date="2024-01-01",
                    cache_dir=str(Path(tmp) / "cache"),
                ),
                fetch=_fake_fetch,
            )
            path = Path(tmp) / "historical.json"
            artifact = write_historical_derivatives_artifact(
                Settings.from_env(), payload, explicit_path=str(path)
            )
            self.assertTrue(path.exists())
            self.assertEqual(json.loads(path.read_text())["schema_version"], payload["schema_version"])
            self.assertEqual(artifact["artifact_path"], str(path))


if __name__ == "__main__":
    unittest.main()
