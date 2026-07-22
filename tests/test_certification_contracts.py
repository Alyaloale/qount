from __future__ import annotations

import json
import unittest

from qount.certification import CERTIFICATION_SCHEMA_VERSION
from qount.certification import CertificationEvent
from qount.certification import CertificationPlan
from qount.certification import CertificationResult
from qount.certification import CertificationRun
from qount.contracts import ArtifactReference
from qount.contracts import canonical_hash
from qount.persistence import ArtifactCodecError
from qount.persistence import dump_artifact
from qount.persistence import load_artifact

_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64
_HASH_D = "d" * 64
_HASH_E = "e" * 64
_HASH_0 = "0" * 64
_HASH_1 = "1" * 64
_HASH_2 = "2" * 64

_EXPIRES = "2026-08-01T00:00:00+00:00"
_STARTED = "2026-07-23T10:00:00+00:00"


def _make_plan(**overrides) -> CertificationPlan:
    params: dict = dict(
        certification_type="local_gateway",
        venue_semantic="client_id_idempotency",
        symbol="BTCUSDT",
        action="market_buy_then_cancel",
        max_notional=100.0,
        max_fee=1.0,
        max_holding_time_seconds=3600.0,
        owner_authorization_hash=_HASH_A,
        arm_token_hash=_HASH_B,
        expires_at=_EXPIRES,
        preflight_snapshot_hash=_HASH_C,
        venue_capability_snapshot_hash=_HASH_D,
        zero_position_plan="market sell to close, then verify 0 position",
        failure_handling_path="manual flatten + halt if sell fails",
    )
    params.update(overrides)
    return CertificationPlan.create(**params)


def _make_run(plan: CertificationPlan | None = None, **overrides) -> CertificationRun:
    if plan is None:
        plan = _make_plan()
    params: dict = dict(
        plan_id=plan.plan_id,
        certification_type="local_gateway",
        started_at=_STARTED,
    )
    params.update(overrides)
    return CertificationRun.create(**params)


def _make_event(run: CertificationRun | None = None, **overrides) -> CertificationEvent:
    if run is None:
        run = _make_run()
    params: dict = dict(
        run_id=run.run_id,
        event_type="submit",
        client_order_id="qmt-cert-001",
        timestamp="2026-07-23T10:00:01+00:00",
        observed_state="SUBMITTING",
        raw_response_hash=_HASH_E,
        source="local_gateway",
    )
    params.update(overrides)
    return CertificationEvent.create(**params)


def _make_member_refs() -> tuple[ArtifactReference, ...]:
    members = [
        "authorization",
        "venue_capability_snapshot",
        "certification_preflight",
        "certification_plan",
        "certification_order_events",
        "exchange_raw",
        "query_coverage",
        "runtime_ledger_snapshot",
        "shadow_accountant_snapshot",
        "reconciliation_diff",
        "operational_cost",
        "zero_position_proof",
    ]
    return tuple(
        ArtifactReference.create(
            artifact_type=mt,
            object_id=_HASH_A,
            payload_hash=_HASH_B,
            artifact_hash=_HASH_C,
            file_name=f"{mt}.json",
        )
        for mt in members
    )


def _make_result(
    run: CertificationRun | None = None,
    *,
    final_position_is_zero: bool = True,
    members: tuple[ArtifactReference, ...] | None = None,
) -> CertificationResult:
    if run is None:
        run = _make_run()
    return CertificationResult.create(
        run_id=run.run_id,
        artifact_members=members if members is not None else _make_member_refs(),
        final_zero_position_proof_hash=_HASH_0,
        reconciliation_diff_hash=_HASH_1,
        operational_cost_hash=_HASH_2,
        final_position_is_zero=final_position_is_zero,
    )


def _encoded_envelope(value: dict) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii") + b"\n"


def _rehash_envelope(envelope: dict) -> None:
    payload = envelope["payload"]
    envelope["payload_hash"] = canonical_hash(payload)
    core = {k: v for k, v in envelope.items() if k != "artifact_hash"}
    envelope["artifact_hash"] = canonical_hash(core)


class CertificationPlanTest(unittest.TestCase):
    def test_create_produces_valid_plan(self):
        plan = _make_plan()
        self.assertEqual(plan.schema_version, CERTIFICATION_SCHEMA_VERSION)
        self.assertFalse(plan.orders_authorized)
        self.assertIsNone(plan.strategy_id)
        self.assertEqual(plan.batch_type, "venue_certification")
        self.assertEqual(plan.pnl_attribution, "operational_certification_cost")
        self.assertEqual(plan.portfolio_nav, "excluded")
        self.assertEqual(plan.certification_status, "draft")
        self.assertFalse(plan.validate())

    def test_orders_authorized_always_false(self):
        plan = _make_plan()
        self.assertFalse(plan.orders_authorized)

    def test_invalid_certification_type_rejected(self):
        with self.assertRaises(ValueError):
            _make_plan(certification_type="invalid_type")

    def test_invalid_venue_semantic_rejected(self):
        with self.assertRaises(ValueError):
            _make_plan(venue_semantic="invalid_semantic")

    def test_invalid_symbol_rejected(self):
        with self.assertRaises(ValueError):
            _make_plan(symbol="invalid")

    def test_invalid_action_rejected(self):
        with self.assertRaises(ValueError):
            _make_plan(action="")

    def test_non_finite_max_notional_rejected(self):
        with self.assertRaises(ValueError):
            _make_plan(max_notional=float("nan"))
        with self.assertRaises(ValueError):
            _make_plan(max_notional=float("inf"))

    def test_negative_max_fee_rejected(self):
        with self.assertRaises(ValueError):
            _make_plan(max_fee=-1.0)

    def test_non_positive_max_holding_time_rejected(self):
        with self.assertRaises(ValueError):
            _make_plan(max_holding_time_seconds=0.0)
        with self.assertRaises(ValueError):
            _make_plan(max_holding_time_seconds=-1.0)

    def test_invalid_hash_fields_rejected(self):
        with self.assertRaises(ValueError):
            _make_plan(owner_authorization_hash="not-a-hash")
        with self.assertRaises(ValueError):
            _make_plan(arm_token_hash="short")

    def test_invalid_expires_at_rejected(self):
        with self.assertRaises(ValueError):
            _make_plan(expires_at="not-a-datetime")
        with self.assertRaises(ValueError):
            _make_plan(expires_at="2026-08-01T00:00:00")

    def test_empty_zero_position_plan_rejected(self):
        with self.assertRaises(ValueError):
            _make_plan(zero_position_plan="")

    def test_empty_failure_handling_path_rejected(self):
        with self.assertRaises(ValueError):
            _make_plan(failure_handling_path="")

    def test_invalid_certification_status_rejected(self):
        with self.assertRaises(ValueError):
            _make_plan(certification_status="invalid_status")

    def test_deterministic_hash(self):
        plan1 = _make_plan()
        plan2 = _make_plan()
        self.assertEqual(plan1.plan_hash, plan2.plan_hash)
        self.assertEqual(plan1.plan_id, plan2.plan_id)

    def test_round_trip(self):
        plan = _make_plan()
        raw = dump_artifact(plan)
        restored = load_artifact(raw, expected_artifact_type="certification_plan")
        self.assertEqual(restored.plan_id, plan.plan_id)
        self.assertEqual(restored.plan_hash, plan.plan_hash)
        self.assertFalse(restored.orders_authorized)

    def test_tampered_payload_detected(self):
        plan = _make_plan()
        raw = json.loads(dump_artifact(plan))
        raw["payload"]["symbol"] = "ETHUSDT"
        with self.assertRaises(ArtifactCodecError) as cm:
            load_artifact(json.dumps(raw, sort_keys=True).encode("ascii"))
        self.assertIn("payload_hash_mismatch", str(cm.exception))

    def test_tampered_envelope_object_id_detected(self):
        plan = _make_plan()
        envelope = json.loads(dump_artifact(plan))
        envelope["object_id"] = _HASH_E
        _rehash_envelope(envelope)
        with self.assertRaises(ArtifactCodecError) as cm:
            load_artifact(_encoded_envelope(envelope))
        self.assertIn("object_id_mismatch", str(cm.exception))

    def test_unknown_field_rejected(self):
        plan = _make_plan()
        raw = json.loads(dump_artifact(plan))
        raw["payload"]["unknown_field"] = "bad"
        with self.assertRaises(ArtifactCodecError):
            load_artifact(json.dumps(raw, sort_keys=True).encode("ascii"))

    def test_duplicate_json_key_rejected(self):
        plan = _make_plan()
        raw = dump_artifact(plan).decode("ascii")
        raw = raw.replace(
            '"symbol":"BTCUSDT"',
            '"symbol":"BTCUSDT","symbol":"ETHUSDT"',
        )
        with self.assertRaises(ArtifactCodecError) as cm:
            load_artifact(raw.encode("ascii"))
        self.assertIn("duplicate_key", str(cm.exception))


class CertificationRunTest(unittest.TestCase):
    def test_create_produces_valid_run(self):
        run = _make_run()
        self.assertEqual(run.schema_version, CERTIFICATION_SCHEMA_VERSION)
        self.assertEqual(run.status, "running")
        self.assertFalse(run.orders_authorized)
        self.assertIsNone(run.completed_at)
        self.assertFalse(run.validate())

    def test_completed_before_started_rejected(self):
        with self.assertRaises(ValueError):
            _make_run(
                started_at="2026-07-23T10:00:00+00:00",
                completed_at="2026-07-23T09:00:00+00:00",
                status="completed",
            )

    def test_invalid_status_rejected(self):
        with self.assertRaises(ValueError):
            _make_run(status="invalid")

    def test_round_trip(self):
        run = _make_run(
            completed_at="2026-07-23T11:00:00+00:00",
            status="completed",
        )
        raw = dump_artifact(run)
        restored = load_artifact(raw, expected_artifact_type="certification_run")
        self.assertEqual(restored.run_id, run.run_id)
        self.assertEqual(restored.status, "completed")


class CertificationEventTest(unittest.TestCase):
    def test_create_produces_valid_event(self):
        event = _make_event()
        self.assertEqual(event.event_type, "submit")
        self.assertEqual(event.observed_state, "SUBMITTING")
        self.assertFalse(event.validate())

    def test_invalid_event_type_rejected(self):
        with self.assertRaises(ValueError):
            _make_event(event_type="invalid")

    def test_invalid_observed_state_rejected(self):
        with self.assertRaises(ValueError):
            _make_event(observed_state="INVALID_STATE")

    def test_invalid_source_rejected(self):
        with self.assertRaises(ValueError):
            _make_event(source="invalid_source")

    def test_empty_client_order_id_rejected(self):
        with self.assertRaises(ValueError):
            _make_event(client_order_id="")

    def test_round_trip(self):
        event = _make_event(exchange_order_id="12345")
        raw = dump_artifact(event)
        restored = load_artifact(raw, expected_artifact_type="certification_event")
        self.assertEqual(restored.event_id, event.event_id)
        self.assertEqual(restored.exchange_order_id, "12345")


class CertificationResultTest(unittest.TestCase):
    def test_complete_result(self):
        result = _make_result(final_position_is_zero=True)
        self.assertTrue(result.completed)
        self.assertFalse(result.validate())

    def test_incomplete_result_missing_members(self):
        result = _make_result(members=(), final_position_is_zero=False)
        self.assertFalse(result.completed)

    def test_incomplete_result_non_zero_position(self):
        result = _make_result(final_position_is_zero=False)
        self.assertFalse(result.completed)

    def test_completed_false_when_position_not_zero(self):
        result = _make_result(final_position_is_zero=False)
        self.assertFalse(result.completed)

    def test_members_sorted_by_artifact_type(self):
        refs = tuple(reversed(_make_member_refs()))
        result = _make_result(members=refs)
        types = [ref.artifact_type for ref in result.artifact_members]
        self.assertEqual(types, sorted(types))

    def test_round_trip_complete(self):
        result = _make_result(final_position_is_zero=True)
        raw = dump_artifact(result)
        restored = load_artifact(raw, expected_artifact_type="certification_result")
        self.assertEqual(restored.result_id, result.result_id)
        self.assertTrue(restored.completed)

    def test_round_trip_incomplete(self):
        result = _make_result(members=(), final_position_is_zero=False)
        raw = dump_artifact(result)
        restored = load_artifact(raw, expected_artifact_type="certification_result")
        self.assertEqual(restored.result_id, result.result_id)
        self.assertFalse(restored.completed)

    def test_tampered_completed_flag_detected(self):
        result = _make_result(final_position_is_zero=True)
        raw = json.loads(dump_artifact(result))
        self.assertTrue(raw["payload"]["completed"])
        raw["payload"]["final_position_is_zero"] = False
        with self.assertRaises(ArtifactCodecError) as cm:
            load_artifact(json.dumps(raw, sort_keys=True).encode("ascii"))
        self.assertIn("mismatch", str(cm.exception).lower())


class CertificationArtifactImmutableTest(unittest.TestCase):
    def test_all_certification_types_round_trip(self):
        plan = _make_plan()
        run = _make_run(plan)
        event = _make_event(run)
        result = _make_result(run)
        for obj, expected_type in [
            (plan, "certification_plan"),
            (run, "certification_run"),
            (event, "certification_event"),
            (result, "certification_result"),
        ]:
            raw = dump_artifact(obj)
            restored = load_artifact(raw, expected_artifact_type=expected_type)
            self.assertEqual(
                restored.__class__, obj.__class__,
                f"round-trip class mismatch for {expected_type}",
            )

    def test_serialized_bytes_deterministic(self):
        plan = _make_plan()
        raw1 = dump_artifact(plan)
        raw2 = dump_artifact(plan)
        self.assertEqual(raw1, raw2)

    def test_type_mismatch_detected(self):
        plan = _make_plan()
        raw = dump_artifact(plan)
        with self.assertRaises(ArtifactCodecError) as cm:
            load_artifact(raw, expected_artifact_type="certification_run")
        self.assertIn("artifact_type_mismatch", str(cm.exception))

    def test_unknown_artifact_type_detected(self):
        plan = _make_plan()
        raw = json.loads(dump_artifact(plan))
        raw["artifact_type"] = "unknown_type"
        with self.assertRaises(ArtifactCodecError) as cm:
            load_artifact(json.dumps(raw, sort_keys=True).encode("ascii"))
        self.assertIn("artifact_type_unknown", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
