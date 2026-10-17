from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from qount.binance_assets import (
    asset_by_execution_symbol,
    asset_mapping_payload,
    execution_to_signal_map,
    load_binance_assets,
)


class TestBinanceAssets(unittest.TestCase):
    def test_repository_mapping_is_unique_and_usdm_only(self) -> None:
        assets = load_binance_assets()
        self.assertEqual(len(assets), 10)
        self.assertTrue(all(asset.venue == "binance_usdm" for asset in assets))
        self.assertEqual(asset_by_execution_symbol("spyusdt").signal_symbol, "SPY")
        self.assertEqual(execution_to_signal_map()["CLUSDT"], "USO")

    def test_invalid_mapping_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "assets.json"
            payload = asset_mapping_payload()
            payload["assets"][1]["execution_symbol"] = payload["assets"][0]["execution_symbol"]
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate:execution_symbol"):
                load_binance_assets(path)

    def test_api_payload_exposes_execution_and_signal_identity(self) -> None:
        payload = asset_mapping_payload()
        self.assertEqual(payload["venue"], "binance_usdm")
        self.assertEqual(
            {row["execution_symbol"] for row in payload["assets"]},
            {asset.execution_symbol for asset in load_binance_assets()},
        )


if __name__ == "__main__":
    unittest.main()
