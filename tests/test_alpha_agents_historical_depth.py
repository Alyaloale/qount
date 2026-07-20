from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from qount.alpha_agents.historical_depth import HISTORICAL_DEPTH_VERSION
from qount.alpha_agents.historical_depth import HistoricalDepthConfig
from qount.alpha_agents.historical_depth import build_historical_depth_dataset
from qount.alpha_agents.historical_depth import parse_depth_csv


def _csv() -> str:
    lines = ["timestamp,percentage,depth,notional"]
    for bucket in range(288):
        minute = bucket * 5
        hour, minute = divmod(minute, 60)
        stamp = f"2024-01-01 {hour:02d}:{minute:02d}:10"
        for percentage in (-5, -4, -3, -2, -1, 1, 2, 3, 4, 5):
            notional = 1000.0 * (6 - abs(percentage)) * (1.2 if percentage < 0 else 0.8)
            lines.append(f"{stamp},{percentage},{abs(notional) / 100},{notional}")
    return "\n".join(lines)


def _zip(text: str) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("depth.csv", text)
    return output.getvalue()


class HistoricalDepthTest(unittest.TestCase):
    def test_parser_requires_all_percentage_levels(self) -> None:
        malformed = "timestamp,percentage,depth,notional\n2024-01-01 00:00:10,-1,1,1\n"
        with self.assertRaisesRegex(ValueError, "exact"):
            parse_depth_csv(malformed)

    def test_builds_checksum_verified_five_minute_dataset(self) -> None:
        blob = _zip(_csv())

        def fetch(url: str) -> bytes:
            if url.endswith(".CHECKSUM"):
                filename = url.removesuffix(".CHECKSUM").rsplit("/", 1)[-1]
                return f"{hashlib.sha256(blob).hexdigest()}  {filename}\n".encode()
            return blob

        with tempfile.TemporaryDirectory() as tmp:
            artifact = build_historical_depth_dataset(
                HistoricalDepthConfig(
                    symbols=("ETHUSDT",),
                    start_date="2024-01-01",
                    end_date="2024-01-01",
                    cache_dir=str(Path(tmp) / "cache"),
                ),
                fetch=fetch,
            )
        self.assertEqual(artifact["schema_version"], HISTORICAL_DEPTH_VERSION)
        self.assertEqual(artifact["diagnostics"]["verdict"], "pass_data_smoke")
        self.assertEqual(artifact["diagnostics"]["complete_row_count"], 288)
        self.assertFalse(artifact["meta"]["replayable_l2"])
        first = artifact["five_minute_features"][0]
        self.assertAlmostEqual(first["depth_imbalance_1pct_mean"], 0.2)
        self.assertAlmostEqual(first["depth_imbalance_5pct_mean"], 0.2)
        self.assertAlmostEqual(first["near_depth_share_mean"], 5.0)


if __name__ == "__main__":
    unittest.main()
