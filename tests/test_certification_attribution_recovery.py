from __future__ import annotations

import unittest
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from qount.certification import build_recovered_attribution
from qount.persistence import read_immutable_artifact
from qount.shadow_accounting import FetchResult
from qount.shadow_accounting import QueryMetadata
from qount.shadow_accounting import archive_raw_responses


class CertificationAttributionRecoveryTest(unittest.TestCase):
    def test_recovers_only_fields_present_in_read_only_evidence(self) -> None:
        report = build_recovered_attribution(
            run_id="a" * 64,
            trades=[
                {
                    "amount": 0.001,
                    "price": 65394.0,
                    "takerOrMaker": "taker",
                    "fee": {"cost": 0.0327, "currency": "USDT"},
                },
                {
                    "amount": 0.001,
                    "price": 65396.0,
                    "takerOrMaker": "taker",
                    "fee": {"cost": 0.0327, "currency": "USDT"},
                },
            ],
            income=[],
            planned_quantity=0.002,
            source_metadata={"source": "phase_b_raw_archive"},
        )
        self.assertAlmostEqual(report.fill_vwap, 65395.0)
        self.assertAlmostEqual(report.fee, 0.0654)
        self.assertEqual(report.maker_or_taker, "taker")
        self.assertEqual(report.planned_vs_filled_qty, 1.0)
        self.assertEqual(report.arrival_mid, "unavailable")
        self.assertEqual(
            report.field_evidence["arrival_mid"]["missing_reason"],
            "not_captured_at_event_time",
        )
        self.assertFalse(report.validate())

    def test_funding_zero_requires_income_window_evidence(self) -> None:
        without_income = build_recovered_attribution(
            run_id="a" * 64,
            trades=[],
            income=[],
        )
        self.assertEqual(without_income.funding, "unavailable")
        with_income = build_recovered_attribution(
            run_id="a" * 64,
            trades=[],
            income=[
                {
                    "incomeType": "COMMISSION",
                    "income": "-0.01",
                }
            ],
        )
        self.assertEqual(with_income.funding, 0.0)
        self.assertEqual(
            with_income.field_evidence["funding"]["status"], "available"
        )

    def test_cli_reads_verified_phase_b_archive_without_exchange_access(self) -> None:
        query = QueryMetadata.create(
            endpoint="fetch_my_trades",
            symbol="BTCUSDT",
            query_start_ms=0,
            query_end_ms=2_000,
            observed_at="2026-07-23T00:00:00+00:00",
            page_count=1,
            retry_count=0,
            result_count=1,
            source_hash="fixture-source",
            coverage_complete=True,
        )
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "phase-b-run"
            archive_raw_responses(
                (
                    FetchResult.create(
                        data_type="trades",
                        records=(
                            {
                                "symbol": "BTCUSDT",
                                "qty": "0.002",
                                "price": "65000",
                                "commission": "0.0654",
                                "maker": False,
                                "orderId": "cert-order-1",
                                "time": 1_000,
                            },
                        ),
                        queries=(query,),
                    ),
                    FetchResult.create(
                        data_type="income_history",
                        records=(
                            {
                                "symbol": "BTCUSDT",
                                "incomeType": "COMMISSION",
                                "income": "-0.0654",
                                "time": 1_000,
                            },
                        ),
                        queries=(query,),
                    ),
                ),
                run_dir=run_dir,
            )
            output = Path(tmp) / "recovered.json"
            root = Path(__file__).resolve().parents[1]
            env = dict(os.environ, PYTHONPATH=str(root / "src"))
            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/operations/phase_d_real_run.py",
                    "backfill-attribution",
                    "--run-id",
                    "a" * 64,
                    "--source-path",
                    str(run_dir),
                    "--symbol",
                    "BTCUSDT",
                    "--order-id",
                    "cert-order-1",
                    "--planned-quantity",
                    "0.002",
                    "--output-path",
                    str(output),
                ],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = read_immutable_artifact(
                output,
                expected_artifact_type="execution_attribution_report",
            )
            self.assertAlmostEqual(report.fee, 0.0654)
            self.assertEqual(report.maker_or_taker, "taker")


if __name__ == "__main__":
    unittest.main()
