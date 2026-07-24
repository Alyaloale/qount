"""Unit tests for R0-DATA lifecycle collection (no network)."""

from __future__ import annotations

import json
import unittest

from qount.research_data.lifecycle import EXCHANGE_INFO_URLS
from qount.research_data.lifecycle import VENUE_BY_MARKET
from qount.research_data.lifecycle import build_lifecycle_from_exchange_info
from qount.research_data.lifecycle import build_lifecycle_from_symbol
from qount.research_data.lifecycle import build_rules_dict
from qount.research_data.lifecycle import build_rules_hash
from qount.research_data.lifecycle import fetch_exchange_info
from qount.research_data.lifecycle import infer_spot_listing_date
from qount.research_data.lifecycle import parse_lifecycle_state
from qount.research_data.lifecycle import parse_valid_from
from qount.research_data.lifecycle import parse_valid_to
from qount.research_data.lifecycle import summarize_lifecycle_batch


# --- Fixtures ---

UM_SYMBOL_ACTIVE = {
    "symbol": "BTCUSDT",
    "status": "TRADING",
    "baseAsset": "BTC",
    "quoteAsset": "USDT",
    "onboardDate": 1569398400000,
    "contractType": "PERPETUAL",
    "filters": [
        {"filterType": "PRICE_FILTER", "tickSize": "0.10", "minPrice": "0.01", "maxPrice": "1000000"},
        {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001", "maxQty": "1000"},
        {"filterType": "MARKET_LOT_SIZE", "stepSize": "0.001"},
        {"filterType": "MIN_NOTIONAL", "notional": "100"},
    ],
}

UM_SYMBOL_DELISTED = {
    "symbol": "OLDUSDT",
    "status": "CLOSE",
    "baseAsset": "OLD",
    "quoteAsset": "USDT",
    "onboardDate": 1577836800000,
    "contractType": "PERPETUAL",
    "filters": [
        {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
        {"filterType": "LOT_SIZE", "stepSize": "0.01", "minQty": "0.01"},
    ],
}

CM_SYMBOL_QUARTERLY = {
    "symbol": "BTCUSD_250627",
    "pair": "BTCUSD",
    "status": "TRADING",
    "contractType": "CURRENT_QUARTER",
    "onboardDate": 1711900800000,
    "deliveryDate": 1750992000000,
    "filters": [
        {"filterType": "PRICE_FILTER", "tickSize": "0.50"},
        {"filterType": "LOT_SIZE", "stepSize": "1"},
    ],
}

SPOT_SYMBOL = {
    "symbol": "ETHUSDT",
    "status": "TRADING",
    "baseAsset": "ETH",
    "quoteAsset": "USDT",
    "filters": [
        {"filterType": "PRICE_FILTER", "tickSize": "0.01000000"},
        {"filterType": "LOT_SIZE", "stepSize": "0.00001000", "minQty": "0.00001000"},
    ],
}

UM_EXCHANGE_INFO = {
    "timezone": "UTC",
    "symbols": [UM_SYMBOL_ACTIVE, UM_SYMBOL_DELISTED],
}

CM_EXCHANGE_INFO = {
    "timezone": "UTC",
    "symbols": [CM_SYMBOL_QUARTERLY],
}

SPOT_EXCHANGE_INFO = {
    "timezone": "UTC",
    "symbols": [SPOT_SYMBOL],
}


def _make_fetcher(payload: dict) -> object:
    blob = json.dumps(payload).encode("utf-8")
    return lambda url: blob


class TestParseLifecycleState(unittest.TestCase):
    def test_trading_maps_to_active(self) -> None:
        self.assertEqual(parse_lifecycle_state({"status": "TRADING"}), "active")

    def test_close_maps_to_delisted(self) -> None:
        self.assertEqual(parse_lifecycle_state({"status": "CLOSE"}), "delisted")

    def test_expired_maps_to_delisted(self) -> None:
        self.assertEqual(parse_lifecycle_state({"status": "EXPIRED"}), "delisted")

    def test_break_maps_to_suspended(self) -> None:
        self.assertEqual(parse_lifecycle_state({"status": "BREAK"}), "suspended")

    def test_pending_trading_maps_to_suspended(self) -> None:
        self.assertEqual(parse_lifecycle_state({"status": "PENDING_TRADING"}), "suspended")

    def test_unknown_status_maps_to_unknown(self) -> None:
        self.assertEqual(parse_lifecycle_state({"status": "WEIRD"}), "unknown")

    def test_missing_status_maps_to_unknown(self) -> None:
        self.assertEqual(parse_lifecycle_state({}), "unknown")


class TestParseValidFrom(unittest.TestCase):
    def test_um_onboard_date(self) -> None:
        result = parse_valid_from(UM_SYMBOL_ACTIVE)
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("2019-09-25"))

    def test_spot_no_onboard_date_returns_none(self) -> None:
        self.assertIsNone(parse_valid_from(SPOT_SYMBOL))

    def test_zero_onboard_date_returns_none(self) -> None:
        self.assertIsNone(parse_valid_from({"onboardDate": 0}))

    def test_microsecond_normalization(self) -> None:
        # 1569398400000000 µs = 1569398400000 ms
        result = parse_valid_from({"onboardDate": 1569398400000000})
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("2019-09-25"))


class TestParseValidTo(unittest.TestCase):
    def test_cm_delivery_date(self) -> None:
        result = parse_valid_to(CM_SYMBOL_QUARTERLY)
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("2025-06-27"))

    def test_um_no_delivery_date_returns_none(self) -> None:
        self.assertIsNone(parse_valid_to(UM_SYMBOL_ACTIVE))


class TestRulesHash(unittest.TestCase):
    def test_rules_dict_is_sorted(self) -> None:
        rules = build_rules_dict(UM_SYMBOL_ACTIVE, market="um")
        keys = list(rules.keys())
        self.assertEqual(keys, sorted(keys))

    def test_rules_hash_stable(self) -> None:
        rules1 = build_rules_dict(UM_SYMBOL_ACTIVE, market="um")
        rules2 = build_rules_dict(UM_SYMBOL_ACTIVE, market="um")
        self.assertEqual(build_rules_hash(rules1), build_rules_hash(rules2))

    def test_rules_hash_changes_when_tick_size_changes(self) -> None:
        modified = dict(UM_SYMBOL_ACTIVE)
        modified["filters"] = [
            {"filterType": "PRICE_FILTER", "tickSize": "0.20", "minPrice": "0.01", "maxPrice": "1000000"},
        ] + UM_SYMBOL_ACTIVE["filters"][1:]
        hash1 = build_rules_hash(build_rules_dict(UM_SYMBOL_ACTIVE, market="um"))
        hash2 = build_rules_hash(build_rules_dict(modified, market="um"))
        self.assertNotEqual(hash1, hash2)

    def test_rules_hash_is_sha256(self) -> None:
        rules = build_rules_dict(UM_SYMBOL_ACTIVE, market="um")
        h = build_rules_hash(rules)
        self.assertEqual(len(h), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in h))


class TestBuildLifecycleFromSymbol(unittest.TestCase):
    def test_um_active_symbol(self) -> None:
        source_hash = "a" * 64
        record = build_lifecycle_from_symbol(UM_SYMBOL_ACTIVE, market="um", source_hash=source_hash)
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.symbol, "BTCUSDT")
        self.assertEqual(record.venue, "binance_um")
        self.assertEqual(record.state, "active")
        self.assertIsNone(record.valid_to)
        self.assertTrue(record.valid_from.startswith("2019-09-25"))
        self.assertEqual(record.source_hash, source_hash)
        self.assertIsNotNone(record.rules_hash)
        errors = record.validate()
        self.assertEqual(errors, ())

    def test_um_delisted_symbol(self) -> None:
        source_hash = "b" * 64
        record = build_lifecycle_from_symbol(UM_SYMBOL_DELISTED, market="um", source_hash=source_hash)
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.state, "delisted")
        self.assertIsNone(record.valid_to)
        errors = record.validate()
        self.assertEqual(errors, ())

    def test_cm_quarterly_with_delivery(self) -> None:
        source_hash = "c" * 64
        record = build_lifecycle_from_symbol(CM_SYMBOL_QUARTERLY, market="cm", source_hash=source_hash)
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.symbol, "BTCUSD_250627")
        self.assertEqual(record.venue, "binance_cm")
        self.assertEqual(record.state, "active")
        self.assertIsNotNone(record.valid_to)
        self.assertTrue(record.valid_to.startswith("2025-06-27"))
        errors = record.validate()
        self.assertEqual(errors, ())

    def test_spot_without_onboard_returns_none(self) -> None:
        source_hash = "d" * 64
        record = build_lifecycle_from_symbol(SPOT_SYMBOL, market="spot", source_hash=source_hash)
        self.assertIsNone(record)

    def test_spot_with_override(self) -> None:
        source_hash = "e" * 64
        record = build_lifecycle_from_symbol(
            SPOT_SYMBOL,
            market="spot",
            source_hash=source_hash,
            valid_from_override="2017-08-17T00:00:00+00:00",
        )
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.venue, "binance_spot")
        self.assertEqual(record.state, "active")
        errors = record.validate()
        self.assertEqual(errors, ())


class TestBuildLifecycleFromExchangeInfo(unittest.TestCase):
    def test_um_payload(self) -> None:
        source_hash = "f" * 64
        records = build_lifecycle_from_exchange_info(UM_EXCHANGE_INFO, market="um", source_hash=source_hash)
        self.assertEqual(len(records), 2)
        symbols = {r.symbol for r in records}
        self.assertEqual(symbols, {"BTCUSDT", "OLDUSDT"})
        for r in records:
            self.assertEqual(r.source_hash, source_hash)
            self.assertEqual(r.venue, "binance_um")
            self.assertEqual(r.validate(), ())

    def test_cm_payload(self) -> None:
        source_hash = "0" * 64
        records = build_lifecycle_from_exchange_info(CM_EXCHANGE_INFO, market="cm", source_hash=source_hash)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].symbol, "BTCUSD_250627")

    def test_spot_with_overrides(self) -> None:
        source_hash = "1" * 64
        overrides = {"ETHUSDT": "2017-08-17T00:00:00+00:00"}
        records = build_lifecycle_from_exchange_info(
            SPOT_EXCHANGE_INFO, market="spot", source_hash=source_hash,
            valid_from_overrides=overrides,
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].symbol, "ETHUSDT")
        self.assertEqual(records[0].venue, "binance_spot")

    def test_empty_symbols(self) -> None:
        source_hash = "2" * 64
        records = build_lifecycle_from_exchange_info({"symbols": []}, market="um", source_hash=source_hash)
        self.assertEqual(records, [])

    def test_invalid_payload_raises(self) -> None:
        with self.assertRaises(ValueError):
            build_lifecycle_from_exchange_info({"not_symbols": []}, market="um", source_hash="x" * 64)


class TestFetchExchangeInfo(unittest.TestCase):
    def test_fetch_um(self) -> None:
        payload, source_hash = fetch_exchange_info(market="um", fetch=_make_fetcher(UM_EXCHANGE_INFO))
        self.assertIsInstance(payload, dict)
        self.assertIn("symbols", payload)
        self.assertEqual(len(source_hash), 64)

    def test_fetch_spot(self) -> None:
        payload, source_hash = fetch_exchange_info(market="spot", fetch=_make_fetcher(SPOT_EXCHANGE_INFO))
        self.assertIsInstance(payload, dict)

    def test_fetch_cm(self) -> None:
        payload, source_hash = fetch_exchange_info(market="cm", fetch=_make_fetcher(CM_EXCHANGE_INFO))
        self.assertIsInstance(payload, dict)

    def test_invalid_market_raises(self) -> None:
        with self.assertRaises(ValueError):
            fetch_exchange_info(market="stock", fetch=lambda url: b"{}")

    def test_source_hash_stable(self) -> None:
        _, h1 = fetch_exchange_info(market="um", fetch=_make_fetcher(UM_EXCHANGE_INFO))
        _, h2 = fetch_exchange_info(market="um", fetch=_make_fetcher(UM_EXCHANGE_INFO))
        self.assertEqual(h1, h2)

    def test_source_hash_changes_with_payload(self) -> None:
        _, h1 = fetch_exchange_info(market="um", fetch=_make_fetcher(UM_EXCHANGE_INFO))
        modified = dict(UM_EXCHANGE_INFO)
        modified["extra"] = "changed"
        _, h2 = fetch_exchange_info(market="um", fetch=_make_fetcher(modified))
        self.assertNotEqual(h1, h2)

    def test_invalid_payload_raises(self) -> None:
        with self.assertRaises(ValueError):
            fetch_exchange_info(market="um", fetch=lambda url: b'{"not_symbols": []}')

    def test_exchange_info_urls_cover_all_markets(self) -> None:
        for market in ("spot", "um", "cm"):
            self.assertIn(market, EXCHANGE_INFO_URLS)
            self.assertTrue(EXCHANGE_INFO_URLS[market].startswith("https://"))

    def test_venue_by_market_covers_all_markets(self) -> None:
        for market in ("spot", "um", "cm"):
            self.assertIn(market, VENUE_BY_MARKET)
            self.assertTrue(VENUE_BY_MARKET[market].startswith("binance_"))


class TestSummarizeLifecycleBatch(unittest.TestCase):
    def test_summary(self) -> None:
        source_hash = "3" * 64
        records = build_lifecycle_from_exchange_info(UM_EXCHANGE_INFO, market="um", source_hash=source_hash)
        summary = summarize_lifecycle_batch(records, market="um", source_hash=source_hash, observed_at="2026-07-23T00:00:00+00:00")
        self.assertEqual(summary["total_symbols"], 2)
        self.assertEqual(summary["active_symbols"], 1)
        self.assertEqual(summary["delisted_symbols"], 1)
        self.assertEqual(summary["source_hash"], source_hash)


class TestInferSpotListingDate(unittest.TestCase):
    def test_finds_first_month(self) -> None:
        calls: list[str] = []

        def mock_fetch(url: str) -> bytes:
            calls.append(url)
            # Only 2019-01 has data.
            if "2019-01" in url:
                return b"fake_zip_data"
            raise Exception("404")

        result = infer_spot_listing_date("ETHUSDT", fetch=mock_fetch, earliest_year=2019)
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("2019-01-01"))

    def test_no_data_returns_none(self) -> None:
        def mock_fetch(url: str) -> bytes:
            raise Exception("404")

        result = infer_spot_listing_date("NOSUCH", fetch=mock_fetch, earliest_year=2024)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
