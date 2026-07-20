from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from qount.alpha_agents.binance_returns import BinanceReturnsConfig
from qount.alpha_agents.binance_returns import build_binance_returns_dataset
from qount.alpha_agents.exchange_rules import build_exchange_rules_report
from qount.alpha_agents.exchange_rules import load_symbol_rules
from qount.alpha_agents.exchange_rules import rules_from_exchange_info
from qount.alpha_agents.exchange_rules import validate_market_notional


def _zip_csv(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("data.csv", text)
    return buf.getvalue()


def _kline_csv(symbol: str) -> str:
    base = {"BTCUSDT": 100.0, "ETHUSDT": 50.0, "BNBUSDT": 20.0}[symbol]
    rows = []
    for day in range(1, 12):
        ts = 1704067200000 + (day - 1) * 86_400_000
        close = base + day
        rows.append(f"{ts},{close - 0.5},{close + 1},{close - 1},{close},100,{ts + 1}")
    return "\n".join(rows)


def _exchange_info() -> dict:
    return {
        "symbols": [
            {
                "symbol": "ETHUSDT",
                "status": "TRADING",
                "baseAsset": "ETH",
                "quoteAsset": "USDT",
                "filters": [
                    {"filterType": "PRICE_FILTER", "minPrice": "0.01", "maxPrice": "1000000", "tickSize": "0.01"},
                    {"filterType": "LOT_SIZE", "minQty": "0.001", "maxQty": "100000", "stepSize": "0.001"},
                    {"filterType": "MARKET_LOT_SIZE", "minQty": "0.001", "maxQty": "100000", "stepSize": "0.001"},
                    {"filterType": "MIN_NOTIONAL", "notional": "5"},
                ],
            }
        ]
    }


def _fake_fetch(url: str) -> bytes:
    if "fundingRate" in url:
        rows = [
            "1704412800000,8,0.00010000",
            "1704499200000,8,0.00010000",
        ]
        return _zip_csv("\n".join(rows))
    for symbol in ("BTCUSDT", "ETHUSDT", "BNBUSDT"):
        if f"/{symbol}/" in url:
            return _zip_csv(_kline_csv(symbol))
    raise AssertionError(f"unexpected url {url}")


class AlphaAgentsExchangeRulesTest(unittest.TestCase):
    def test_spot_report_uses_public_market_data_domain(self) -> None:
        report = build_exchange_rules_report(_exchange_info(), market="spot", symbols=("ETHUSDT",))
        self.assertEqual(
            report["source_url"],
            "https://data-api.binance.vision/api/v3/exchangeInfo",
        )

    def test_validates_market_notional_against_runtime_rules(self) -> None:
        rules = rules_from_exchange_info(_exchange_info(), market="um")
        ok = validate_market_notional(rules, symbol="ETHUSDT", price=2000, target_notional=400)
        too_small = validate_market_notional(rules, symbol="ETHUSDT", price=2000, target_notional=1)
        self.assertTrue(ok.ok)
        self.assertFalse(too_small.ok)
        self.assertIn("notional_below_min_notional", too_small.reasons)

    def test_rules_artifact_roundtrip(self) -> None:
        report = build_exchange_rules_report(_exchange_info(), market="um", symbols=("ETHUSDT",))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rules.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            rules = load_symbol_rules(path, market="um")
        self.assertIn("ETHUSDT", rules)
        self.assertEqual(str(rules["ETHUSDT"].min_notional), "5")

    def test_binance_returns_records_filter_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = BinanceReturnsConfig(
                start_month="2024-01",
                end_month="2024-01",
                fast_window=2,
                slow_window=3,
                cache_dir=str(Path(tmp) / "klines"),
                funding_cache_dir=str(Path(tmp) / "funding"),
            )
            dataset = build_binance_returns_dataset(config, fetch=_fake_fetch, exchange_info=_exchange_info())
        self.assertEqual(dataset["meta"]["exchange_rules_source"], "runtime_exchange_info")
        self.assertTrue(dataset["meta"]["filter_validator_reused"])
        self.assertEqual(dataset["meta"]["min_notional_coverage"], 1.0)
        self.assertGreater(dataset["diagnostics"]["filter_diagnostics"]["order_count"], 0)

    def test_binance_returns_can_include_funding_cashflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = BinanceReturnsConfig(
                start_month="2024-01",
                end_month="2024-01",
                fast_window=2,
                slow_window=3,
                include_funding=True,
                cache_dir=str(Path(tmp) / "klines"),
                funding_cache_dir=str(Path(tmp) / "funding"),
            )
            dataset = build_binance_returns_dataset(config, fetch=_fake_fetch)
        self.assertTrue(dataset["meta"]["funding_included"])
        self.assertGreater(dataset["diagnostics"]["funding_settlement_count"], 0)
        self.assertLess(dataset["diagnostics"]["total_funding_return_pct"], 0.0)


if __name__ == "__main__":
    unittest.main()
