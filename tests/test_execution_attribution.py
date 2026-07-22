from __future__ import annotations

import json
import math
import unittest

from qount.certification import UNAVAILABLE
from qount.certification import ExecutionAttributionReport
from qount.persistence import ArtifactCodecError
from qount.persistence import dump_artifact
from qount.persistence import load_artifact

_HASH_A = "a" * 64


class ExecutionAttributionUnavailableTest(unittest.TestCase):
    def test_create_unavailable(self):
        report = ExecutionAttributionReport.create_unavailable(
            attribution_source_hash=_HASH_A
        )
        self.assertEqual(report.attribution_source, UNAVAILABLE)
        self.assertIsNone(report.run_id)
        for field_name in (
            "decision_to_submit_ms",
            "submit_to_ack_ms",
            "ack_to_fill_ms",
            "planned_vs_filled_qty",
            "arrival_mid",
            "fee",
            "funding",
        ):
            self.assertEqual(getattr(report, field_name), UNAVAILABLE)
        self.assertFalse(report.validate())

    def test_create_unavailable_with_run_id(self):
        report = ExecutionAttributionReport.create_unavailable(
            run_id="b" * 64,
            attribution_source_hash=_HASH_A,
        )
        self.assertEqual(report.run_id, "b" * 64)

    def test_invalid_source_hash_rejected(self):
        with self.assertRaises(ValueError):
            ExecutionAttributionReport.create_unavailable(
                attribution_source_hash="not-a-hash"
            )

    def test_deterministic_hash(self):
        r1 = ExecutionAttributionReport.create_unavailable(
            attribution_source_hash=_HASH_A
        )
        r2 = ExecutionAttributionReport.create_unavailable(
            attribution_source_hash=_HASH_A
        )
        self.assertEqual(r1.report_hash, r2.report_hash)
        self.assertEqual(r1.report_id, r2.report_id)

    def test_round_trip(self):
        report = ExecutionAttributionReport.create_unavailable(
            attribution_source_hash=_HASH_A
        )
        raw = dump_artifact(report)
        restored = load_artifact(
            raw, expected_artifact_type="execution_attribution_report"
        )
        self.assertEqual(restored.report_id, report.report_id)
        self.assertEqual(restored.attribution_source, UNAVAILABLE)


class ExecutionAttributionRealFillTest(unittest.TestCase):
    def _make_real_fill(self, **overrides):
        params: dict = dict(
            run_id="b" * 64,
            decision_to_submit_ms=10.0,
            submit_to_ack_ms=50.0,
            ack_to_fill_ms=100.0,
            planned_vs_filled_qty=1.0,
            partial_fill_count=0,
            cancel_replace_count=0,
            arrival_mid=100000.5,
            bid_ask_spread=0.5,
            fill_vwap=100000.8,
            adverse_slippage=0.3,
            maker_or_taker="taker",
            fee=0.04,
            funding=0.0,
            unfilled_exposure_time=0.0,
            protection_order_latency=200.0,
            stop_gap=500.0,
            attribution_source_hash=_HASH_A,
        )
        params.update(overrides)
        return ExecutionAttributionReport.create_real_fill(**params)

    def test_create_real_fill(self):
        report = self._make_real_fill()
        self.assertEqual(report.attribution_source, "real_fill")
        self.assertEqual(report.maker_or_taker, "taker")
        self.assertFalse(report.validate())

    def test_string_numeric_field_rejected(self):
        with self.assertRaises(ValueError):
            self._make_real_fill(decision_to_submit_ms="10.0")

    def test_non_finite_numeric_rejected(self):
        with self.assertRaises(ValueError):
            self._make_real_fill(fee=float("nan"))
        with self.assertRaises(ValueError):
            self._make_real_fill(funding=float("inf"))

    def test_invalid_maker_or_taker_rejected(self):
        with self.assertRaises(ValueError):
            self._make_real_fill(maker_or_taker="invalid")

    def test_round_trip(self):
        report = self._make_real_fill()
        raw = dump_artifact(report)
        restored = load_artifact(
            raw, expected_artifact_type="execution_attribution_report"
        )
        self.assertEqual(restored.report_id, report.report_id)
        self.assertEqual(restored.attribution_source, "real_fill")
        self.assertAlmostEqual(restored.fee, report.fee)

    def test_tampered_payload_detected(self):
        report = self._make_real_fill()
        raw = json.loads(dump_artifact(report))
        raw["payload"]["fee"] = 999.0
        with self.assertRaises(ArtifactCodecError) as cm:
            load_artifact(
                json.dumps(raw, sort_keys=True).encode("ascii") + b"\n"
            )
        self.assertIn("payload_hash_mismatch", str(cm.exception))

    def test_deterministic_hash(self):
        r1 = self._make_real_fill()
        r2 = self._make_real_fill()
        self.assertEqual(r1.report_hash, r2.report_hash)


if __name__ == "__main__":
    unittest.main()
