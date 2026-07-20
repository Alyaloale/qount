from __future__ import annotations

import datetime as dt
import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from qount.mini_trend.equity_mapping_sources import SourceResponse
from qount.mini_trend.equity_mapping_sources import audit_nasdaq_cash_quote
from qount.mini_trend.equity_mapping_sources import audit_nasdaq_earnings_context
from qount.mini_trend.equity_mapping_sources import (
    build_equity_mapping_source_capacity,
)
from qount.mini_trend.equity_mapping_sources import parse_binance_book_ticker
from qount.mini_trend.equity_mapping_sources import (
    parse_binance_instrument_mapping,
)
from qount.mini_trend.equity_mapping_sources import parse_bitstamp_usdtusd_book
from qount.mini_trend.equity_mapping_sources import (
    parse_nasdaq_explicit_corporate_action,
)
from qount.mini_trend.equity_mapping_sources import parse_nasdaq_market_session
from qount.mini_trend.equity_mapping_sources import (
    write_equity_mapping_source_capacity_artifact,
)
from qount.settings import Settings


_AVAILABLE = "2026-07-20T13:24:59+00:00"


def _response(source_id: str, role: str, payload: object) -> SourceResponse:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return SourceResponse(
        source_id=source_id,
        role=role,
        source_url=f"https://data.example.test/{source_id}",
        final_url=f"https://data.example.test/{source_id}",
        observed_at="2026-07-20T13:24:58+00:00",
        available_at=_AVAILABLE,
        status_code=200,
        content_type="application/json",
        body=raw,
    )


class EquityMappingSourceTests(unittest.TestCase):
    def test_binance_mapping_and_book_ticker_preserve_server_time(self) -> None:
        mapping_response = _response(
            "binance_exchange_info",
            "instrument_mapping",
            {
                "symbols": [
                    {
                        "symbol": "NVDAUSDT",
                        "status": "TRADING",
                        "contractType": "PERPETUAL",
                        "underlyingType": "TRADIFI",
                        "quoteAsset": "USDT",
                        "baseAsset": "NVDA",
                    }
                ]
            },
        )
        instrument = parse_binance_instrument_mapping(
            mapping_response,
            venue_symbol="NVDAUSDT",
            cash_quote_venue="nasdaq",
            stablecoin_quote_venue="bitstamp",
        )
        self.assertEqual(instrument.cash_symbol, "NVDA")
        self.assertEqual(instrument.mapping_source_hash, mapping_response.source_hash)

        event_ms = int(
            dt.datetime(2026, 7, 20, 13, 24, 57, tzinfo=dt.UTC).timestamp()
            * 1000
        )
        quote = parse_binance_book_ticker(
            _response(
                "binance_mapped_book",
                "mapped_quote",
                {
                    "symbol": "NVDAUSDT",
                    "bidPrice": "199.90",
                    "askPrice": "200.10",
                    "time": event_ms,
                },
            ),
            venue_symbol="NVDAUSDT",
        )
        self.assertEqual(quote.quote_at, "2026-07-20T13:24:57+00:00")
        self.assertEqual(quote.bid, 199.9)
        self.assertEqual(quote.validate(), ())

    def test_bitstamp_book_is_a_timestamped_usdtusd_quote(self) -> None:
        event = dt.datetime(2026, 7, 20, 13, 24, 57, tzinfo=dt.UTC)
        quote = parse_bitstamp_usdtusd_book(
            _response(
                "bitstamp_usdtusd_book",
                "usdt_usd_quote",
                {
                    "microtimestamp": str(int(event.timestamp() * 1_000_000)),
                    "bids": [["0.9998", "1000"]],
                    "asks": [["1.0002", "1200"]],
                },
            )
        )
        self.assertEqual(quote.symbol, "USDTUSD")
        self.assertEqual(quote.quote_at, event.isoformat())
        self.assertEqual(quote.validate(), ())

    def test_nasdaq_market_info_builds_the_cash_session(self) -> None:
        session = parse_nasdaq_market_session(
            _response(
                "nasdaq_market_info",
                "cash_calendar",
                {
                    "data": {
                        "nextTradeDate": "Jul 20, 2026",
                        "marketOpeningTime": "Jul 20, 2026 09:30 AM ET",
                        "marketClosingTime": "Jul 20, 2026 04:00 PM ET",
                    }
                },
            ),
            cash_trading_date="2026-07-20",
        )
        self.assertTrue(session.is_trading_day)
        self.assertEqual(session.regular_close_time_local, "16:00:00")
        self.assertEqual(session.validate(), ())

    def test_nasdaq_delayed_quote_cannot_supply_the_cash_leg(self) -> None:
        audit = audit_nasdaq_cash_quote(
            _response(
                "nasdaq_cash_quote",
                "cash_premarket_quote",
                {
                    "data": {
                        "symbol": "NVDA",
                        "marketStatus": "Closed",
                        "primaryData": {
                            "isRealTime": False,
                            "bidPrice": "N/A",
                            "askPrice": "N/A",
                            "lastTradeTimestamp": "Jul 16, 2026",
                        },
                    }
                },
            ),
            cash_symbol="NVDA",
        )
        self.assertFalse(audit["semantic_ready"])
        self.assertIn("cash_quote_not_realtime", audit["reasons"])
        self.assertIn("cash_quote_bid_ask_missing", audit["reasons"])
        self.assertIn("cash_quote_source_event_timestamp_missing", audit["reasons"])

    def test_nasdaq_quote_timestamp_must_precede_availability(self) -> None:
        audit = audit_nasdaq_cash_quote(
            _response(
                "nasdaq_cash_quote",
                "cash_premarket_quote",
                {
                    "data": {
                        "symbol": "NVDA",
                        "primaryData": {
                            "isRealTime": True,
                            "bidPrice": "$199.90",
                            "askPrice": "$200.10",
                            "quoteTimestamp": "2026-07-20T13:25:01+00:00",
                        },
                    }
                },
            ),
            cash_symbol="NVDA",
        )
        self.assertFalse(audit["semantic_ready"])
        self.assertIn(
            "cash_quote_source_event_timestamp_after_availability",
            audit["reasons"],
        )

    def test_nasdaq_split_absence_and_earnings_date_fail_closed(self) -> None:
        splits = _response(
            "nasdaq_splits",
            "corporate_action",
            {
                "data": {
                    "rows": [
                        {
                            "symbol": "OTHER",
                            "ratio": "2 : 1",
                            "executionDate": "7/21/2026",
                        }
                    ]
                }
            },
        )
        with self.assertRaisesRegex(ValueError, "not_scoped_to_requested_date"):
            parse_nasdaq_explicit_corporate_action(
                splits,
                cash_symbol="NVDA",
                cash_trading_date="2026-07-20",
            )
        earnings = audit_nasdaq_earnings_context(
            _response(
                "nasdaq_earnings",
                "event_context",
                {"data": {"rows": [{"symbol": "NVDA", "time": "pre-market"}]}},
            ),
            cash_symbol="NVDA",
            cash_trading_date="2026-07-20",
        )
        self.assertFalse(earnings["semantic_ready"])
        self.assertIn("earnings_event_date_not_bound_in_rows", earnings["reasons"])

        empty_earnings = audit_nasdaq_earnings_context(
            _response(
                "nasdaq_earnings",
                "event_context",
                {"data": {"rows": []}},
            ),
            cash_symbol="NVDA",
            cash_trading_date="2026-07-20",
        )
        self.assertFalse(empty_earnings["semantic_ready"])
        self.assertIn(
            "earnings_event_date_not_bound_in_rows",
            empty_earnings["reasons"],
        )

    def test_capacity_report_blocks_missing_roles_without_market_event(self) -> None:
        def fetch(probe):
            if probe.source_id == "nasdaq_cash_quote":
                return _response(
                    probe.source_id,
                    probe.role,
                    {
                        "data": {
                            "symbol": "NVDA",
                            "primaryData": {
                                "isRealTime": False,
                                "bidPrice": "N/A",
                                "askPrice": "N/A",
                            },
                        }
                    },
                )
            return SourceResponse(
                source_id=probe.source_id,
                role=probe.role,
                source_url=probe.url,
                final_url=None,
                observed_at="2026-07-19T06:00:00+00:00",
                available_at="2026-07-19T06:00:01+00:00",
                status_code=None,
                content_type=None,
                body=b"",
                error="transport_unavailable",
            )

        report, raw = build_equity_mapping_source_capacity(
            cash_trading_date="2026-07-20",
            fetch=fetch,
        )
        self.assertEqual(report["verdict"], "block_equity_mapping_source_capacity")
        self.assertIn("cash_premarket_quote", report["blockers"])
        self.assertEqual(report["meta"]["trial_count"], 0)
        self.assertFalse(report["meta"]["market_event_created"])
        self.assertEqual(set(raw), {"nasdaq_cash_quote"})
        unavailable = next(
            probe
            for probe in report["probes"]
            if probe["source_id"] == "coinbase_usdtusd_book"
        )
        self.assertEqual(unavailable["audit"]["reasons"], ["transport_unavailable"])

    def test_artifact_writer_hashes_raw_readback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            settings = replace(Settings.from_env(), state_dir=Path(temporary))
            payload = {"verdict": "block", "probes": []}
            result = write_equity_mapping_source_capacity_artifact(
                settings, payload, {"source": b"raw-body"}
            )
            artifact_path = Path(result["artifact_path"])
            self.assertTrue(artifact_path.is_file())
            raw_path = artifact_path.parent / "raw" / "source.bin"
            self.assertEqual(raw_path.read_bytes(), b"raw-body")
            self.assertEqual(
                result["raw_manifest"]["files"][0]["sha256"],
                hashlib.sha256(b"raw-body").hexdigest(),
            )


if __name__ == "__main__":
    unittest.main()
