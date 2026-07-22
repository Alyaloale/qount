from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from qount.shadow_accounting import FetchResult
from qount.shadow_accounting import QueryMetadata
from qount.shadow_accounting import ShadowRun
from qount.shadow_accounting import WatermarkContract
from qount.shadow_accounting import archive_json
from qount.shadow_accounting import archive_raw_responses
from qount.shadow_accounting import archive_shadow_run
from qount.shadow_accounting import verify_archive


def _make_query_metadata(endpoint: str = "fetch_my_trades", symbol: str = "BTCUSDT") -> QueryMetadata:
    return QueryMetadata.create(
        endpoint=endpoint,
        symbol=symbol,
        query_start_ms=0,
        query_end_ms=1000,
        observed_at="2026-07-23T00:00:00+00:00",
        page_count=1,
        retry_count=0,
        result_count=1,
        source_hash="abc123def456",
        coverage_complete=True,
    )


def _make_fetch_result(
    data_type: str = "trades",
    records: list | None = None,
) -> FetchResult:
    if records is None:
        records = [
            {"symbol": "BTCUSDT", "side": "BUY", "price": "100000",
             "qty": "0.001", "commission": "0.04", "realizedPnl": "0",
             "time": 1000},
        ]
    return FetchResult.create(
        data_type=data_type,
        records=records,
        queries=[_make_query_metadata()],
    )


class ArchiveRawResponsesTest(unittest.TestCase):
    def test_archive_creates_files_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run1"
            fetch_results = [
                _make_fetch_result("trades"),
                _make_fetch_result("income_history", [
                    {"symbol": "BTCUSDT", "incomeType": "COMMISSION",
                     "income": "-0.04", "asset": "USDT", "time": 1000},
                ]),
            ]
            manifest = archive_raw_responses(fetch_results, run_dir=run_dir)
            self.assertIn("files", manifest)
            self.assertIn("trades.jsonl", manifest["files"])
            self.assertIn("income_history.jsonl", manifest["files"])
            self.assertTrue((run_dir / "raw" / "trades.jsonl").is_file())
            self.assertTrue((run_dir / "raw" / "income_history.jsonl").is_file())
            self.assertTrue((run_dir / "archive_manifest.json").is_file())

    def test_verify_archive_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run1"
            fetch_results = [_make_fetch_result("trades")]
            archive_raw_responses(fetch_results, run_dir=run_dir)
            manifest = verify_archive(run_dir)
            self.assertIn("files", manifest)

    def test_verify_archive_detects_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run1"
            fetch_results = [_make_fetch_result("trades")]
            archive_raw_responses(fetch_results, run_dir=run_dir)
            trades_file = run_dir / "raw" / "trades.jsonl"
            original = trades_file.read_text(encoding="ascii")
            trades_file.write_text(original + '{"tampered": true}\n', encoding="ascii")
            with self.assertRaises(ValueError) as ctx:
                verify_archive(run_dir)
            self.assertIn("hash_mismatch", str(ctx.exception))

    def test_verify_archive_detects_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run1"
            fetch_results = [_make_fetch_result("trades")]
            archive_raw_responses(fetch_results, run_dir=run_dir)
            (run_dir / "raw" / "trades.jsonl").unlink()
            with self.assertRaises(ValueError) as ctx:
                verify_archive(run_dir)
            self.assertIn("file_missing", str(ctx.exception))

    def test_duplicate_archive_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run1"
            fetch_results = [_make_fetch_result("trades")]
            archive_raw_responses(fetch_results, run_dir=run_dir)
            with self.assertRaises(FileExistsError):
                archive_raw_responses(fetch_results, run_dir=run_dir)

    def test_empty_fetch_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run1"
            manifest = archive_raw_responses([], run_dir=run_dir)
            self.assertEqual(manifest["files"], {})
            self.assertTrue((run_dir / "archive_manifest.json").is_file())


class ArchiveShadowRunTest(unittest.TestCase):
    def test_archive_shadow_run_creates_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run1"
            run_dir.mkdir(parents=True)
            watermark = WatermarkContract.create(
                live_cycle_completed_at="2026-07-23T00:00:00+00:00",
                shadow_fetch_started_at="2026-07-23T00:01:00+00:00",
                min_delay_seconds=60.0,
                delay_satisfied=True,
                shadow_coverage_start="2026-07-22T00:00:00+00:00",
                shadow_coverage_end="2026-07-23T00:00:00+00:00",
            )
            shadow_run = ShadowRun.create(
                observed_at="2026-07-23T00:01:00+00:00",
                venue="binance_usdm",
                symbols=["BTCUSDT", "ETHUSDT"],
                fetch_results=[_make_fetch_result("trades")],
                position_hashes=["hash1"],
                nav_hash="navhash",
                coverage_window_hash="covhash",
                unknown_income_count=0,
                diff_hashes=["diff1"],
                has_blocking_diff=False,
                watermark=watermark,
            )
            file_hash = archive_shadow_run(shadow_run, run_dir=run_dir)
            self.assertTrue(file_hash)
            run_file = run_dir / "shadow_run.json"
            self.assertTrue(run_file.is_file())
            data = json.loads(run_file.read_text(encoding="ascii"))
            self.assertEqual(data["run_id"], shadow_run.run_id)
            self.assertEqual(data["venue"], "binance_usdm")

    def test_archive_json_arbitrary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run1"
            run_dir.mkdir(parents=True)
            file_hash = archive_json(
                {"key": "value", "num": 42},
                file_name="custom.json",
                run_dir=run_dir,
            )
            self.assertTrue(file_hash)
            self.assertTrue((run_dir / "custom.json").is_file())


class WatermarkContractTest(unittest.TestCase):
    def test_validate_passes(self) -> None:
        wm = WatermarkContract.create(
            live_cycle_completed_at="2026-07-23T00:00:00+00:00",
            shadow_fetch_started_at="2026-07-23T00:01:00+00:00",
            min_delay_seconds=60.0,
            delay_satisfied=True,
            shadow_coverage_start="2026-07-22T00:00:00+00:00",
            shadow_coverage_end="2026-07-23T00:00:00+00:00",
        )
        errors = wm.validate()
        self.assertEqual(errors, ())

    def test_negative_delay_fails(self) -> None:
        wm = WatermarkContract.create(
            live_cycle_completed_at="2026-07-23T00:00:00+00:00",
            shadow_fetch_started_at="2026-07-23T00:01:00+00:00",
            min_delay_seconds=-1.0,
            delay_satisfied=False,
            shadow_coverage_start="2026-07-22T00:00:00+00:00",
            shadow_coverage_end="2026-07-23T00:00:00+00:00",
        )
        errors = wm.validate()
        self.assertIn("watermark_min_delay_negative", errors)


class ShadowRunTest(unittest.TestCase):
    def test_create_and_validate(self) -> None:
        watermark = WatermarkContract.create(
            live_cycle_completed_at="2026-07-23T00:00:00+00:00",
            shadow_fetch_started_at="2026-07-23T00:01:00+00:00",
            min_delay_seconds=60.0,
            delay_satisfied=True,
            shadow_coverage_start="2026-07-22T00:00:00+00:00",
            shadow_coverage_end="2026-07-23T00:00:00+00:00",
        )
        shadow_run = ShadowRun.create(
            observed_at="2026-07-23T00:01:00+00:00",
            venue="binance_usdm",
            symbols=["BTCUSDT"],
            fetch_results=[_make_fetch_result("trades")],
            position_hashes=["poshash1"],
            nav_hash="navhash",
            coverage_window_hash="covhash",
            unknown_income_count=0,
            diff_hashes=["diffhash1"],
            has_blocking_diff=False,
            watermark=watermark,
        )
        errors = shadow_run.validate()
        self.assertEqual(errors, ())
        self.assertTrue(shadow_run.run_id)
        self.assertTrue(shadow_run.run_hash)


if __name__ == "__main__":
    unittest.main()
