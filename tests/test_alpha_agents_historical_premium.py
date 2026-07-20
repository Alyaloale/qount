from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from qount.alpha_agents.historical_premium import HISTORICAL_PREMIUM_VERSION
from qount.alpha_agents.historical_premium import HistoricalPremiumConfig
from qount.alpha_agents.historical_premium import build_historical_premium_dataset
from qount.alpha_agents.historical_premium import parse_premium_kline_csv


START_MS = 1_704_067_200_000


def _archive(dataset: str) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        lines = [
            "open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore"
        ]
        for index in range(288):
            ts_ms = START_MS + index * 300_000
            if dataset == "premiumIndexKlines":
                close = 0.001 + index * 0.000001
            elif dataset == "markPriceKlines":
                close = 2_002.0 + index * 0.01
            else:
                close = 2_000.0 + index * 0.01
            lines.append(
                f"{ts_ms},{close},{close},{close},{close},0,{ts_ms + 299999},0,1,0,0,0"
            )
        archive.writestr("sample.csv", "\n".join(lines))
    return output.getvalue()


class HistoricalPremiumTest(unittest.TestCase):
    def test_strict_parser_rejects_malformed_schema(self) -> None:
        with self.assertRaisesRegex(ValueError, "column count"):
            parse_premium_kline_csv("1704067200000,1,1,1,1,0")

    def test_builds_checksum_verified_three_source_dataset(self) -> None:
        blobs = {dataset: _archive(dataset) for dataset in (
            "premiumIndexKlines",
            "markPriceKlines",
            "indexPriceKlines",
        )}

        def fetch(url: str) -> bytes:
            dataset = next(name for name in blobs if f"/{name}/" in url)
            if url.endswith(".CHECKSUM"):
                filename = url.removesuffix(".CHECKSUM").rsplit("/", 1)[-1]
                digest = hashlib.sha256(blobs[dataset]).hexdigest()
                return f"{digest}  {filename}\n".encode()
            return blobs[dataset]

        with tempfile.TemporaryDirectory() as tmp:
            artifact = build_historical_premium_dataset(
                HistoricalPremiumConfig(
                    symbols=("ETHUSDT",),
                    start_date="2024-01-01",
                    end_date="2024-01-01",
                    cache_dir=str(Path(tmp) / "cache"),
                ),
                fetch=fetch,
            )
        self.assertEqual(artifact["schema_version"], HISTORICAL_PREMIUM_VERSION)
        self.assertEqual(artifact["diagnostics"]["verdict"], "pass_data_smoke")
        self.assertEqual(artifact["diagnostics"]["loaded_archive_count"], 3)
        self.assertEqual(artifact["diagnostics"]["complete_row_count"], 288)
        self.assertEqual(artifact["diagnostics"]["by_symbol"]["ETHUSDT"]["complete_coverage_ratio"], 1.0)
        first = artifact["five_minute_features"][0]
        self.assertAlmostEqual(first["mark_index_basis"], 0.001)
        self.assertAlmostEqual(first["premium_minus_mark_index_basis"], 0.0)


if __name__ == "__main__":
    unittest.main()
