from __future__ import annotations

import errno
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qount.contracts import MarketSnapshot
from qount.contracts import OrderPlan
from qount.contracts import PlannedCancellation
from qount.contracts import PlannedOrder
from qount.contracts import PortfolioTarget
from qount.contracts import RiskDecision
from qount.contracts import StrategyIntent
from qount.contracts import canonical_hash
from qount.contracts import trace_id
from qount.governance import DeploymentManifest
from qount.governance import StrategyRegistration
from qount.governance import StrategyRegistry
from qount.persistence import ArtifactCodecError
from qount.persistence import artifact_envelope
from qount.persistence import dump_artifact
from qount.persistence import load_artifact
from qount.persistence import read_immutable_artifact
from qount.persistence import write_immutable_artifact


DECISION_TIME = "2026-07-20T00:05:00+00:00"
DATA_CUTOFF = "2026-07-20T00:00:00+00:00"


def _objects() -> tuple[object, ...]:
    snapshot = MarketSnapshot.create(
        decision_time=DECISION_TIME,
        data_cutoff=DATA_CUTOFF,
        prices={"BTCUSDT": 100_000.0, "ETHUSDT": 3_500.0},
        funding={"BTCUSDT": 0.0001, "ETHUSDT": -0.00005},
        features={"BTCUSDT_ABOVE_SMA200": True},
        exchange_rules_hash="a" * 64,
        account_snapshot_hash="b" * 64,
        data_quality={
            "complete": True,
            "blockers": [],
            "account_snapshot_linked": True,
        },
        source_hashes={"market_data": "c" * 64, "funding": "d" * 64},
    )
    intent = StrategyIntent.create(
        strategy_id="test_strategy",
        strategy_version="1.2.3",
        snapshot_id=snapshot.snapshot_id,
        decision_time=DECISION_TIME,
        data_cutoff=DATA_CUTOFF,
        target_weights={"BTCUSDT": 0.4, "ETHUSDT": 0.2},
        expected_holding_bars=1,
        target_stress_loss_fraction=0.01,
        reason_codes=("BASE_MASTER_GATE_ACTIVE", "BTCUSDT_TARGET_LONG"),
        evidence_hash="e" * 64,
        state_hash="f" * 64,
    )
    target = PortfolioTarget.create(
        snapshot_id=snapshot.snapshot_id,
        decision_ids=(intent.decision_id,),
        decision_time=DECISION_TIME,
        proposed_target_weights=intent.target_weights,
        target_weights=intent.target_weights,
        sleeve_contributions={intent.strategy_id: intent.target_weights},
        blockers=(),
        allocatable=True,
        allocation_hash=canonical_hash({"allocation": "fixture"}),
    )
    batch_id = trace_id(
        "decision_batch",
        {
            "snapshot_id": snapshot.snapshot_id,
            "portfolio_target_id": target.portfolio_target_id,
        },
    )
    risk = RiskDecision.create(
        batch_id=batch_id,
        portfolio_target_id=target.portfolio_target_id,
        decision_time=DECISION_TIME,
        approved=True,
        input_target=target.target_weights,
        approved_target=target.target_weights,
        adjustments=(),
        violations=(),
        risk_state_hash=canonical_hash({"healthy": True, "gross": 0.6}),
        increase_risk_allowed=True,
        reduce_risk_allowed=True,
    )
    orders = (
        PlannedOrder.create(
            batch_id=batch_id,
            decision_ids=target.decision_ids,
            symbol="ETHUSDT",
            side="sell",
            quantity=0.01,
            reduce_only=True,
            phase="reduce",
            sequence=1,
        ),
        PlannedOrder.create(
            batch_id=batch_id,
            decision_ids=target.decision_ids,
            symbol="BTCUSDT",
            side="buy",
            quantity=0.001,
            reduce_only=False,
            phase="increase",
            sequence=2,
        ),
        PlannedOrder.create(
            batch_id=batch_id,
            decision_ids=target.decision_ids,
            symbol="BTCUSDT",
            side="sell",
            quantity=None,
            reduce_only=True,
            phase="protective",
            sequence=4,
            order_type="stop_market",
            close_position=True,
            stop_price=90_000.0,
        ),
    )
    cancellations = (
        PlannedCancellation.create(
            batch_id=batch_id,
            decision_ids=target.decision_ids,
            symbol="BTCUSDT",
            target_exchange_order_id="existing-stop-1",
            target_client_order_id=None,
            sequence=3,
            reason="replace_protective_order",
        ),
    )
    plan = OrderPlan.create(
        batch_id=batch_id,
        risk_decision_id=risk.risk_decision_id,
        portfolio_target_id=target.portfolio_target_id,
        snapshot_id=snapshot.snapshot_id,
        decision_ids=target.decision_ids,
        created_at=DECISION_TIME,
        current_position_hash=canonical_hash({"BTCUSDT": 0.0, "ETHUSDT": 0.02}),
        approved_target=risk.approved_target,
        orders=orders,
        cancellations=cancellations,
        retained_order_ids=("retained-stop-1",),
        expected_positions={"BTCUSDT": 0.001, "ETHUSDT": 0.01},
        reconciliation_tolerance={"BTCUSDT": 0.000001, "ETHUSDT": 0.0001},
        blockers=(),
        executable=True,
    )
    registration = StrategyRegistration.create(
        strategy_id=intent.strategy_id,
        strategy_version=intent.strategy_version,
        strategy_kind="continuous",
        promotion_status="shadow",
        strategy_contract_hash="1" * 64,
        code_hash="2" * 64,
        config_hash="3" * 64,
        promotion_artifact_hash="4" * 64,
        owner_authorization_hash=None,
        maximum_stress_loss_fraction=0.01,
        maximum_gross=0.60,
        registered_at="2026-07-19T23:50:00+00:00",
    )
    registry = StrategyRegistry.create(
        (registration,),
        created_at="2026-07-19T23:55:00+00:00",
    )
    manifest = DeploymentManifest.create(
        registry,
        strategy_entry_ids=(registration.registry_entry_id,),
        environment="shadow",
        git_commit="5" * 40,
        dirty=True,
        code_tree_hash="6" * 64,
        dependency_lock_hash="7" * 64,
        config_hash="8" * 64,
        deployed_at="2026-07-19T23:59:00+00:00",
        deployed_by="local-artifact-test",
        rollback_target=None,
    )
    return snapshot, intent, target, risk, plan, registration, registry, manifest


def _encoded_envelope(value: dict[str, object]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii") + b"\n"


def _rehash_envelope(envelope: dict[str, object]) -> None:
    payload = envelope["payload"]
    if not isinstance(payload, dict):
        raise TypeError("fixture payload must be a mapping")
    envelope["payload_hash"] = canonical_hash(payload)
    core = {key: value for key, value in envelope.items() if key != "artifact_hash"}
    envelope["artifact_hash"] = canonical_hash(core)


class ImmutableContractArtifactTest(unittest.TestCase):
    def test_all_supported_objects_round_trip_exactly(self) -> None:
        for value in _objects():
            with self.subTest(value=type(value).__name__):
                self.assertEqual(load_artifact(dump_artifact(value)), value)

    def test_serialized_bytes_and_hashes_are_deterministic(self) -> None:
        for value, rebuilt in zip(_objects(), _objects(), strict=True):
            with self.subTest(value=type(value).__name__):
                self.assertEqual(value, rebuilt)
                self.assertEqual(dump_artifact(value), dump_artifact(rebuilt))
                self.assertEqual(
                    artifact_envelope(value)["artifact_hash"],
                    artifact_envelope(rebuilt)["artifact_hash"],
                )

    def test_tampered_payload_fails_before_reconstruction(self) -> None:
        snapshot = _objects()[0]
        envelope = json.loads(dump_artifact(snapshot))
        envelope["payload"]["prices"]["BTCUSDT"] = 99_000.0

        with self.assertRaisesRegex(ArtifactCodecError, "payload_hash_mismatch"):
            load_artifact(_encoded_envelope(envelope))

    def test_tampered_internal_identity_fails_with_new_envelope_hashes(self) -> None:
        snapshot = _objects()[0]
        envelope = json.loads(dump_artifact(snapshot))
        envelope["payload"]["snapshot_id"] = "9" * 64
        _rehash_envelope(envelope)

        with self.assertRaisesRegex(ArtifactCodecError, "identity_or_hash_mismatch"):
            load_artifact(_encoded_envelope(envelope))

    def test_tampered_envelope_object_id_fails(self) -> None:
        snapshot = _objects()[0]
        envelope = json.loads(dump_artifact(snapshot))
        envelope["object_id"] = "9" * 64
        _rehash_envelope(envelope)

        with self.assertRaisesRegex(ArtifactCodecError, "object_id_mismatch"):
            load_artifact(_encoded_envelope(envelope))

    def test_unknown_type_schema_and_duplicate_key_fail_closed(self) -> None:
        snapshot = _objects()[0]
        envelope = json.loads(dump_artifact(snapshot))
        envelope["artifact_schema_version"] = 2
        _rehash_envelope(envelope)
        with self.assertRaisesRegex(ArtifactCodecError, "schema_version_unsupported"):
            load_artifact(_encoded_envelope(envelope))

        envelope = json.loads(dump_artifact(snapshot))
        envelope["artifact_type"] = "unknown"
        _rehash_envelope(envelope)
        with self.assertRaisesRegex(ArtifactCodecError, "artifact_type_unknown"):
            load_artifact(_encoded_envelope(envelope))

        with self.assertRaisesRegex(ArtifactCodecError, "duplicate_key"):
            load_artifact(b'{"artifact_schema_version":1,"artifact_schema_version":1}')
        with self.assertRaisesRegex(ArtifactCodecError, "artifact_type_mismatch"):
            load_artifact(
                dump_artifact(snapshot),
                expected_artifact_type="strategy_registry",
            )

    def test_write_is_no_overwrite_mode_0600_and_readback_verified(self) -> None:
        snapshot = _objects()[0]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "snapshot.json"
            receipt = write_immutable_artifact(path, snapshot)

            self.assertEqual(receipt["object"], snapshot)
            self.assertEqual(read_immutable_artifact(path), snapshot)
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
            with self.assertRaises(FileExistsError):
                write_immutable_artifact(path, snapshot)
            self.assertEqual(read_immutable_artifact(path), snapshot)
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    def test_write_falls_back_to_exclusive_create_without_hard_link_support(self) -> None:
        snapshot = _objects()[0]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "snapshot.json"
            with patch(
                "qount.persistence.immutable_json.os.link",
                side_effect=OSError(errno.EPERM, "hard links unsupported"),
            ):
                receipt = write_immutable_artifact(path, snapshot)

            self.assertEqual(receipt["object"], snapshot)
            self.assertEqual(read_immutable_artifact(path), snapshot)
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
            with self.assertRaises(FileExistsError):
                write_immutable_artifact(path, snapshot)
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    def test_temporary_or_partial_paths_are_not_completed_artifacts(self) -> None:
        snapshot = _objects()[0]
        with tempfile.TemporaryDirectory() as temporary:
            partial = Path(temporary) / "snapshot.json.partial"
            partial.write_bytes(dump_artifact(snapshot))
            with self.assertRaisesRegex(ValueError, "path_is_temporary"):
                read_immutable_artifact(partial)
            with self.assertRaisesRegex(ValueError, "path_is_temporary"):
                write_immutable_artifact(
                    Path(temporary) / "snapshot.json.tmp",
                    snapshot,
                )

            truncated = Path(temporary) / "snapshot.json"
            truncated.write_bytes(dump_artifact(snapshot)[:40])
            with self.assertRaisesRegex(ArtifactCodecError, "artifact_json_invalid"):
                read_immutable_artifact(truncated)

    def test_order_plan_preserves_execution_and_reconciliation_fields(self) -> None:
        plan = _objects()[4]
        restored = load_artifact(dump_artifact(plan))

        self.assertEqual(restored.cancellations, plan.cancellations)
        self.assertEqual(restored.retained_order_ids, plan.retained_order_ids)
        self.assertEqual(restored.expected_positions, plan.expected_positions)
        self.assertEqual(
            restored.reconciliation_tolerance,
            plan.reconciliation_tolerance,
        )

    def test_registry_and_shadow_manifest_remain_linked(self) -> None:
        registry = _objects()[6]
        manifest = _objects()[7]
        restored_registry = load_artifact(dump_artifact(registry))
        restored_manifest = load_artifact(dump_artifact(manifest))

        self.assertEqual(
            restored_manifest.validate_against_registry(restored_registry),
            (),
        )
        self.assertFalse(restored_manifest.orders_authorized)

    def test_golden_snapshot_envelope_hash_is_pinned(self) -> None:
        snapshot = _objects()[0]
        self.assertEqual(
            artifact_envelope(snapshot)["artifact_hash"],
            "7bb07f556a82e8b57cc2a44253072fb5be1963e4d2c16a478b40e6e2ee2a2968",
        )


if __name__ == "__main__":
    unittest.main()
