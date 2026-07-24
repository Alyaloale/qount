from __future__ import annotations

import json
import unittest
from pathlib import Path

from qount.mini_trend.liquid_trend import LIQUID_TREND_UNIVERSE
from scripts.research.build_pit_exchange_rules import build_pit_exchange_rules


def _mock_fetch(url: str) -> bytes:
    symbols = []
    for i, sym in enumerate(LIQUID_TREND_UNIVERSE):
        symbols.append({
            "symbol": sym,
            "status": "TRADING",
            "onboardDate": 1577836800000 + i * 86400000 * 30,
            "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
                {"filterType": "MIN_NOTIONAL", "notional": "5.0"},
            ],
        })
    return json.dumps({"symbols": symbols}).encode("utf-8")


class PitExchangeRulesTests(unittest.TestCase):
    def test_builds_rules_for_all_10_symbols(self) -> None:
        report = build_pit_exchange_rules(
            market="um", fetch=_mock_fetch, observed_at="2026-07-25T00:00:00+00:00",
        )
        self.assertEqual(report["universe_size"], 10)
        self.assertEqual(report["rules_present"], 10)
        self.assertEqual(report["rules_trading"], 10)
        self.assertEqual(report["coverage"], 1.0)
        self.assertEqual(len(report["rules"]), 10)

    def test_marks_pit_revision_as_not_available(self) -> None:
        report = build_pit_exchange_rules(
            market="um", fetch=_mock_fetch, observed_at="2026-07-25T00:00:00+00:00",
        )
        self.assertFalse(report["pit_revision_available"])
        self.assertIn("append-only", report["pit_revision_note"])

    def test_extracts_min_notional_and_onboard(self) -> None:
        report = build_pit_exchange_rules(
            market="um", fetch=_mock_fetch, observed_at="2026-07-25T00:00:00+00:00",
        )
        btc_rule = next(r for r in report["rules"] if r["symbol"] == "BTCUSDT")
        self.assertTrue(btc_rule["present"])
        self.assertTrue(btc_rule["trading"])
        self.assertEqual(btc_rule["status"], "TRADING")
        self.assertEqual(btc_rule["min_notional"], "5.0")
        self.assertIsNotNone(btc_rule["onboard_date"])
        self.assertIsNotNone(btc_rule["rules_hash"])

    def test_missing_symbol_marked_absent(self) -> None:
        def partial_fetch(url: str) -> bytes:
            return json.dumps({"symbols": [
                {"symbol": "BTCUSDT", "status": "TRADING", "onboardDate": 1577836800000, "filters": []},
            ]}).encode("utf-8")

        report = build_pit_exchange_rules(
            market="um", fetch=partial_fetch, observed_at="2026-07-25T00:00:00+00:00",
        )
        btc = next(r for r in report["rules"] if r["symbol"] == "BTCUSDT")
        eth = next(r for r in report["rules"] if r["symbol"] == "ETHUSDT")
        self.assertTrue(btc["present"])
        self.assertFalse(eth["present"])
        self.assertEqual(report["coverage"], 0.1)

    def test_orders_not_authorized(self) -> None:
        report = build_pit_exchange_rules(
            market="um", fetch=_mock_fetch, observed_at="2026-07-25T00:00:00+00:00",
        )
        self.assertFalse(report["orders_authorized"])


if __name__ == "__main__":
    unittest.main()
