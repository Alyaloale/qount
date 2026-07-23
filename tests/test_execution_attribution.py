from __future__ import annotations

import json
import math
import unittest

from qount.certification import UNAVAILABLE
from qount.certification import ExecutionAttributionReport
from qount.certification import build_event_time_attribution
from qount.certification import capture_arrival_quote
from qount.certification import exchange_evidence_envelope
from qount.persistence import ArtifactCodecError
from qount.persistence import dump_artifact
from qount.persistence import load_artifact
from qount.contracts.hashing import canonical_hash
from qount.contracts.trace import trace_id

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

    def test_partial_real_fill_preserves_missing_reason(self):
        evidence = {
            field: {
                "status": "unavailable",
                "missing_reason": "not_captured_at_event_time",
                "source_hash": _HASH_A,
            }
            for field in (
                "decision_to_submit_ms",
                "submit_to_ack_ms",
                "ack_to_fill_ms",
                "planned_vs_filled_qty",
                "partial_fill_count",
                "cancel_replace_count",
                "arrival_mid",
                "bid_ask_spread",
                "fill_vwap",
                "adverse_slippage",
                "maker_or_taker",
                "fee",
                "funding",
                "unfilled_exposure_time",
                "protection_order_latency",
                "stop_gap",
            )
        }
        for field in ("planned_vs_filled_qty", "fill_vwap", "fee"):
            evidence[field] = {
                "status": "available",
                "missing_reason": None,
                "source_hash": _HASH_A,
            }
        evidence["maker_or_taker"] = {
            "status": "available",
            "missing_reason": None,
            "source_hash": _HASH_A,
        }
        report = ExecutionAttributionReport.create_partial_real_fill(
            run_id="b" * 64,
            values={
                "planned_vs_filled_qty": 1.0,
                "fill_vwap": 65394.0,
                "fee": 0.0654,
            },
            maker_or_taker="taker",
            field_evidence=evidence,
            attribution_source_hash=_HASH_A,
        )
        self.assertEqual(report.arrival_mid, "unavailable")
        self.assertEqual(
            report.field_evidence["arrival_mid"]["missing_reason"],
            "not_captured_at_event_time",
        )
        self.assertEqual(report.fee, 0.0654)
        self.assertFalse(report.validate())
        restored = load_artifact(
            dump_artifact(report),
            expected_artifact_type="execution_attribution_report",
        )
        self.assertEqual(restored.field_evidence, report.field_evidence)

    def test_partial_available_field_requires_numeric_value(self):
        unavailable = {
            field: {
                "status": "unavailable",
                "missing_reason": "not_captured_at_event_time",
                "source_hash": _HASH_A,
            }
            for field in (
                "decision_to_submit_ms",
                "submit_to_ack_ms",
                "ack_to_fill_ms",
                "planned_vs_filled_qty",
                "partial_fill_count",
                "cancel_replace_count",
                "arrival_mid",
                "bid_ask_spread",
                "fill_vwap",
                "adverse_slippage",
                "maker_or_taker",
                "fee",
                "funding",
                "unfilled_exposure_time",
                "protection_order_latency",
                "stop_gap",
            )
        }
        unavailable["fee"] = {
            "status": "available",
            "missing_reason": None,
            "source_hash": _HASH_A,
        }
        with self.assertRaises(ValueError):
            ExecutionAttributionReport.create_partial_real_fill(
                run_id="b" * 64,
                values={},
                field_evidence=unavailable,
                attribution_source_hash=_HASH_A,
            )

    def test_schema_v1_artifact_remains_readable(self):
        core = {
            "schema_version": 1,
            "run_id": "b" * 64,
            "attribution_source": "real_fill",
            "decision_to_submit_ms": 10.0,
            "submit_to_ack_ms": 20.0,
            "ack_to_fill_ms": 30.0,
            "planned_vs_filled_qty": 1.0,
            "partial_fill_count": 0,
            "cancel_replace_count": 0,
            "arrival_mid": 100.0,
            "bid_ask_spread": 1.0,
            "fill_vwap": 100.5,
            "adverse_slippage": 0.5,
            "fee": 0.04,
            "funding": 0.0,
            "unfilled_exposure_time": 0.0,
            "protection_order_latency": 0.0,
            "stop_gap": 0.0,
            "maker_or_taker": "taker",
            "attribution_source_hash": _HASH_A,
        }
        report_hash = canonical_hash(core)
        payload = core | {
            "report_id": trace_id(
                "execution_attribution_report",
                {"report_hash": report_hash},
            ),
            "report_hash": report_hash,
        }
        envelope_core = {
            "artifact_schema_version": 1,
            "artifact_type": "execution_attribution_report",
            "object_id": payload["report_id"],
            "payload": payload,
            "payload_hash": canonical_hash(payload),
        }
        raw = json.dumps(
            envelope_core
            | {"artifact_hash": canonical_hash(envelope_core)},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii") + b"\n"
        restored = load_artifact(
            raw,
            expected_artifact_type="execution_attribution_report",
        )
        self.assertEqual(restored.schema_version, 1)
        self.assertEqual(restored.field_evidence, {})

    def test_event_time_capture_builds_partial_real_report(self):
        class Exchange:
            def fetch_order_book(self, symbol, limit):
                self.call = (symbol, limit)
                return {
                    "bids": [[99.0, 2.0]],
                    "asks": [[101.0, 3.0]],
                    "apiKey": "must-not-persist",
                }

        exchange = Exchange()
        arrival = capture_arrival_quote(
            exchange,
            symbol="BTC/USDT:USDT",
            observed_at="2026-07-23T00:00:00+00:00",
        )
        raw = exchange_evidence_envelope(
            submit_response={"id": "order-1", "secret": "redact"},
            confirmed_order={"id": "order-1", "status": "closed"},
            trades=(
                {
                    "id": "trade-1",
                    "takerOrMaker": "taker",
                    "api_key": "redact",
                },
            ),
        )
        report = build_event_time_attribution(
            run_id="b" * 64,
            decision_time="2026-07-23T00:00:00+00:00",
            submitted_at="2026-07-23T00:00:01+00:00",
            acknowledged_at="2026-07-23T00:00:01.050000+00:00",
            planned_quantity=2.0,
            side="buy",
            arrival_quote=arrival,
            fills=(
                {
                    "quantity": 1.0,
                    "price": 100.0,
                    "fee": 0.04,
                    "occurred_at": "2026-07-23T00:00:01.100000+00:00",
                },
                {
                    "quantity": 1.0,
                    "price": 101.0,
                    "fee": 0.04,
                    "occurred_at": "2026-07-23T00:00:01.200000+00:00",
                },
            ),
            raw_trades=(
                {"id": "trade-1", "takerOrMaker": "taker"},
                {"id": "trade-2", "takerOrMaker": "taker"},
            ),
            raw_exchange_evidence=raw,
            protection_acknowledged_at="2026-07-23T00:00:01.400000+00:00",
            stop_price=95.0,
        )
        self.assertEqual(exchange.call, ("BTC/USDT:USDT", 5))
        self.assertEqual(arrival["mid"], 100.0)
        self.assertEqual(report.submit_to_ack_ms, 50.0)
        self.assertEqual(report.partial_fill_count, 1)
        self.assertEqual(report.fill_vwap, 100.5)
        self.assertEqual(report.maker_or_taker, "taker")
        self.assertEqual(report.funding, UNAVAILABLE)
        self.assertEqual(
            report.field_evidence["funding"]["missing_reason"],
            "not_attributable_to_single_order",
        )
        self.assertEqual(raw["submit_response"]["secret"], "[REDACTED]")
        self.assertEqual(raw["trades"][0]["api_key"], "[REDACTED]")
        self.assertFalse(report.validate())

    def test_missing_order_book_does_not_block_fill_fields(self):
        arrival = capture_arrival_quote(
            object(),
            symbol="BTC/USDT:USDT",
            observed_at="2026-07-23T00:00:00+00:00",
        )
        raw = exchange_evidence_envelope(submit_response={"id": "order-1"})
        report = build_event_time_attribution(
            run_id="b" * 64,
            decision_time="2026-07-23T00:00:00+00:00",
            submitted_at="2026-07-23T00:00:01+00:00",
            acknowledged_at="2026-07-23T00:00:01.050000+00:00",
            planned_quantity=1.0,
            side="buy",
            arrival_quote=arrival,
            fills=(
                {
                    "quantity": 1.0,
                    "price": 100.0,
                    "fee": 0.04,
                    "occurred_at": "2026-07-23T00:00:01.100000+00:00",
                },
            ),
            raw_trades=(),
            raw_exchange_evidence=raw,
            protection_acknowledged_at=None,
            stop_price=None,
        )
        self.assertEqual(report.arrival_mid, UNAVAILABLE)
        self.assertEqual(report.fill_vwap, 100.0)
        self.assertEqual(report.fee, 0.04)
        self.assertEqual(
            report.field_evidence["arrival_mid"]["missing_reason"],
            "order_book_query_unavailable",
        )


if __name__ == "__main__":
    unittest.main()
