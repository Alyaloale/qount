from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
import zipfile
import datetime as dt
from pathlib import Path

from qount.alpha_agents.historical_tradeflow import AGG_TRADE_COLUMNS
from qount.alpha_agents.historical_tradeflow import BOOK_TICKER_COLUMNS
from qount.alpha_agents.historical_tradeflow import HistoricalTradeFlowConfig
from qount.alpha_agents.historical_tradeflow import archive_url
from qount.alpha_agents.historical_tradeflow import build_historical_tradeflow_dataset
from qount.alpha_agents.historical_tradeflow import parse_agg_trades_csv
from qount.alpha_agents.historical_tradeflow import parse_book_ticker_csv
from qount.alpha_agents.historical_tradeflow import write_historical_tradeflow_artifact
from qount.settings import Settings


def _zip_csv(filename: str, rows: list[str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(filename, "\n".join(rows))
    return buffer.getvalue()


def _agg_zip(symbol: str, period: str, *, gap: bool = False) -> bytes:
    rows = [",".join(AGG_TRADE_COLUMNS)]
    day_offset = (dt.date.fromisoformat(period) - dt.date(2024, 1, 1)).days
    start = 1_704_067_200_000 + day_offset * 86_400_000
    trade_id = 100 + day_offset * 576
    for bucket in range(288):
        if gap and bucket == 100:
            continue
        ts_ms = start + bucket * 300_000 + 10
        rows.append(f"{trade_id},100,2,{trade_id},{trade_id},{ts_ms},false")
        trade_id += 1
        rows.append(f"{trade_id},100,1,{trade_id},{trade_id},{ts_ms + 10},true")
        trade_id += 1
    return _zip_csv(f"{symbol}-aggTrades-{period}.csv", rows)


def _book_zip(symbol: str, period: str) -> bytes:
    rows = [",".join(BOOK_TICKER_COLUMNS)]
    day_offset = (dt.date.fromisoformat(period) - dt.date(2024, 1, 1)).days
    start = 1_704_067_200_000 + day_offset * 86_400_000
    update_id = 1_000 + day_offset * 288 * 7
    for bucket in range(288):
        ts_ms = start + bucket * 300_000 + 20
        rows.append(f"{update_id},99,3,101,1,{ts_ms - 2},{ts_ms}")
        update_id += 7
    return _zip_csv(f"{symbol}-bookTicker-{period}.csv", rows)


def _fetch_factory(*, gap: bool = False, bad_checksum: bool = False):
    def fetch(url: str) -> bytes:
        filename = url.removesuffix(".CHECKSUM").rsplit("/", 1)[-1]
        symbol = filename.split("-", 1)[0]
        dataset = "aggTrades" if "-aggTrades-" in filename else "bookTicker"
        period = filename.removesuffix(".zip").split(f"-{dataset}-", 1)[1]
        blob = _agg_zip(symbol, period, gap=gap) if dataset == "aggTrades" else _book_zip(symbol, period)
        if url.endswith(".CHECKSUM"):
            digest = "0" * 64 if bad_checksum else hashlib.sha256(blob).hexdigest()
            return f"{digest}  {filename}\n".encode()
        return blob

    return fetch


class HistoricalTradeFlowTest(unittest.TestCase):
    def test_real_archive_schema_parsers(self) -> None:
        agg = parse_agg_trades_csv(
            "agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker\n"
            "1965151407,42313.9,0.046,4426785111,4426785111,1704067200038,true\n"
        )
        self.assertEqual(agg[0].agg_trade_id, 1_965_151_407)
        self.assertTrue(agg[0].is_buyer_maker)
        book = parse_book_ticker_csv(
            "update_id,best_bid_price,best_bid_qty,best_ask_price,best_ask_qty,transaction_time,event_time\n"
            "3751155539277,42313.9,10.756,42314.0,2.906,1704067200005,1704067200011\n"
        )
        self.assertEqual(book[0].event_time_ms, 1_704_067_200_011)
        self.assertAlmostEqual(book[0].best_ask_qty, 2.906)

    def test_schema_mismatch_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "unexpected CSV schema"):
            parse_agg_trades_csv("price,quantity\n100,1\n")

    def test_archive_url(self) -> None:
        self.assertEqual(
            archive_url(dataset="bookTicker", symbol="BTCUSDT", cadence="daily", period="2024-01-01"),
            "https://data.binance.vision/data/futures/um/daily/bookTicker/"
            "BTCUSDT/BTCUSDT-bookTicker-2024-01-01.zip",
        )

    def test_checksum_verified_five_minute_aggregation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = build_historical_tradeflow_dataset(
                HistoricalTradeFlowConfig(
                    symbols=("BTCUSDT",),
                    start_date="2024-01-01",
                    end_date="2024-01-01",
                    datasets=("aggTrades", "bookTicker"),
                    cadence="daily",
                    cache_dir=tmp,
                ),
                fetch=_fetch_factory(),
            )
        self.assertEqual(payload["diagnostics"]["verdict"], "pass_data_smoke")
        self.assertEqual(payload["diagnostics"]["loaded_archive_count"], 2)
        self.assertEqual(payload["diagnostics"]["row_count"], 288)
        self.assertTrue(payload["meta"]["checksum_verified"])
        row = payload["five_minute_features"][0]
        self.assertAlmostEqual(row["agg_trade_imbalance"], 1 / 3)
        self.assertEqual(row["agg_trade_count"], 2)
        self.assertEqual(row["book_ticker_event_count"], 1)
        self.assertAlmostEqual(row["book_last_top_imbalance"], 0.5)
        self.assertTrue(row["complete"])
        archive = next(item for item in payload["diagnostics"]["archives"] if item["dataset"] == "bookTicker")
        self.assertEqual(archive["update_id_regression_count"], 0)
        self.assertIn("not_a_gap_signal", archive["update_id_gap_semantics"])

    def test_missing_bucket_blocks_and_segments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = build_historical_tradeflow_dataset(
                HistoricalTradeFlowConfig(
                    symbols=("BTCUSDT",),
                    start_date="2024-01-01",
                    end_date="2024-01-01",
                    datasets=("aggTrades",),
                    cadence="daily",
                    cache_dir=tmp,
                    min_coverage_ratio=0.999,
                ),
                fetch=_fetch_factory(gap=True),
            )
        self.assertEqual(payload["diagnostics"]["verdict"], "block_data")
        self.assertIn("coverage_below_threshold", payload["diagnostics"]["blockers"])
        self.assertEqual(payload["diagnostics"]["by_symbol"]["BTCUSDT"]["segment_count"], 2)

    def test_cross_archive_sequence_is_audited(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = build_historical_tradeflow_dataset(
                HistoricalTradeFlowConfig(
                    symbols=("BTCUSDT",),
                    start_date="2024-01-01",
                    end_date="2024-01-02",
                    datasets=("aggTrades",),
                    cadence="daily",
                    cache_dir=tmp,
                ),
                fetch=_fetch_factory(),
            )
        audit = payload["diagnostics"]["cross_archive_sequence"][0]
        self.assertEqual(audit["archive_count"], 2)
        self.assertEqual(audit["id_gap_count"], 0)
        self.assertEqual(audit["id_regression_count"], 0)

    def test_checksum_mismatch_blocks_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = build_historical_tradeflow_dataset(
                HistoricalTradeFlowConfig(
                    symbols=("BTCUSDT",),
                    start_date="2024-01-01",
                    end_date="2024-01-01",
                    datasets=("aggTrades",),
                    cadence="daily",
                    cache_dir=tmp,
                ),
                fetch=_fetch_factory(bad_checksum=True),
            )
        self.assertEqual(payload["diagnostics"]["verdict"], "block_data")
        self.assertIn("archive_fetch_or_parse_errors", payload["diagnostics"]["blockers"])

    def test_artifact_writer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = build_historical_tradeflow_dataset(
                HistoricalTradeFlowConfig(
                    symbols=("BTCUSDT",),
                    start_date="2024-01-01",
                    end_date="2024-01-01",
                    datasets=("aggTrades",),
                    cadence="daily",
                    cache_dir=str(Path(tmp) / "cache"),
                ),
                fetch=_fetch_factory(),
            )
            path = Path(tmp) / "tradeflow.json"
            artifact = write_historical_tradeflow_artifact(Settings.from_env(), payload, explicit_path=str(path))
            self.assertTrue(path.exists())
            self.assertEqual(json.loads(path.read_text())["schema_version"], payload["schema_version"])
            self.assertEqual(artifact["artifact_path"], str(path))


if __name__ == "__main__":
    unittest.main()
