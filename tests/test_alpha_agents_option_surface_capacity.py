from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs
from urllib.parse import urlparse

from qount.alpha_agents.option_surface_capacity import OPTION_SURFACE_CAPACITY_VERSION
from qount.alpha_agents.option_surface_capacity import OptionSurfaceCapacityConfig
from qount.alpha_agents.option_surface_capacity import build_option_surface_capacity
from qount.alpha_agents.option_surface_capacity import write_option_surface_capacity_artifact
from qount.settings import Settings


def _fake_fetch(url: str) -> bytes:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    method = parsed.path.rsplit("/", 1)[-1]
    if method == "get_instrument":
        name = query["instrument_name"][0]
        return json.dumps(
            {
                "result": {
                    "instrument_name": name,
                    "creation_timestamp": 1,
                    "expiration_timestamp": 2,
                    "strike": 40_000,
                    "option_type": "call",
                }
            }
        ).encode()
    if method == "get_tradingview_chart_data":
        return json.dumps(
            {
                "result": {
                    "status": "ok",
                    "ticks": [1, 2],
                    "open": [0.1, 0.2],
                    "high": [0.1, 0.2],
                    "low": [0.1, 0.2],
                    "close": [0.1, 0.2],
                    "volume": [1.0, 0.0],
                    "cost": [0.1, 0.0],
                }
            }
        ).encode()
    if method == "get_last_trades_by_currency_and_time":
        return json.dumps({"result": {"trades": [], "has_more": False}}).encode()
    if method == "get_instruments":
        return json.dumps(
            {
                "result": [
                    {
                        "instrument_name": "BTC-16JUL26-60000-C",
                        "expiration_timestamp": 1_784_188_800_000,
                    }
                ]
            }
        ).encode()
    if method == "get_book_summary_by_currency":
        return json.dumps(
            {
                "result": [
                    {
                        "instrument_name": "BTC-31JUL26-60000-C",
                        "mark_iv": 50.0,
                        "bid_iv": None,
                        "ask_iv": None,
                        "mark_price": 0.1,
                        "underlying_price": 65_000.0,
                    }
                ]
            }
        ).encode()
    raise AssertionError(url)


class OptionSurfaceCapacityTest(unittest.TestCase):
    def test_blocks_price_only_history_without_chain_or_historical_iv(self) -> None:
        payload = build_option_surface_capacity(fetch=_fake_fetch)
        diagnostics = payload["diagnostics"]
        self.assertEqual(payload["schema_version"], OPTION_SURFACE_CAPACITY_VERSION)
        self.assertEqual(diagnostics["verdict"], "block_g0")
        self.assertTrue(diagnostics["metadata_complete"])
        self.assertTrue(diagnostics["historical_price_charts_complete"])
        self.assertTrue(diagnostics["current_surface_available"])
        self.assertFalse(diagnostics["historical_chain_enumerable"])
        self.assertFalse(diagnostics["historical_trade_iv_available"])
        self.assertFalse(diagnostics["charts_have_direct_iv_index_mark"])
        self.assertFalse(diagnostics["preregistration_allowed"])
        self.assertIn("official_historical_instrument_chain_not_enumerable", diagnostics["blockers"])

    def test_network_failure_is_fail_closed(self) -> None:
        def broken_fetch(url: str) -> bytes:
            if "get_instrument?" in url:
                raise TimeoutError(url)
            return _fake_fetch(url)

        payload = build_option_surface_capacity(fetch=broken_fetch)
        self.assertEqual(payload["diagnostics"]["verdict"], "block_g0")
        self.assertIn("official_probe_incomplete", payload["diagnostics"]["blockers"])

    def test_artifact_writer(self) -> None:
        payload = build_option_surface_capacity(fetch=_fake_fetch)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "capacity.json"
            artifact = write_option_surface_capacity_artifact(
                Settings.from_env(), payload, explicit_path=str(path)
            )
            self.assertTrue(path.exists())
            self.assertEqual(artifact["artifact_path"], str(path))


if __name__ == "__main__":
    unittest.main()
