from __future__ import annotations

import os
import stat
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from qount.contracts import ArtifactReference
from qount.contracts import DecisionBatchManifest
from qount.contracts import MarketSnapshot
from qount.contracts import OrderPlan
from qount.contracts import PortfolioTarget
from qount.contracts import RiskDecision
from qount.persistence import ArtifactCodecError
from qount.persistence import DecisionBatchError
from qount.persistence import DecisionBatchIncompleteError
from qount.persistence import artifact_envelope
from qount.persistence import build_decision_batch_manifest
from qount.persistence import dump_artifact
from qount.persistence import inspect_decision_batch
from qount.persistence import load_artifact
from qount.persistence import publish_decision_batch
from qount.persistence import read_decision_batch
from qount.persistence import resume_incomplete_decision_batch
from qount.persistence import write_immutable_artifact
from qount.persistence.batch_store import write_immutable_artifact as real_write
from tests.test_immutable_contract_artifacts import DECISION_TIME
from tests.test_immutable_contract_artifacts import _objects


MANIFEST_TIME = "2026-07-20T00:06:00+00:00"


def _trace() -> tuple[
    MarketSnapshot,
    tuple[object, ...],
    PortfolioTarget,
    RiskDecision,
    OrderPlan,
]:
    snapshot, intent, target, risk, plan = _objects()[:5]
    return snapshot, (intent,), target, risk, plan


def _manifest() -> DecisionBatchManifest:
    snapshot, intents, target, risk, plan = _trace()
    return build_decision_batch_manifest(
        snapshot=snapshot,
        intents=intents,
        target=target,
        risk=risk,
        plan=plan,
        created_at=MANIFEST_TIME,
    )


def _publish(root: Path):
    snapshot, intents, target, risk, plan = _trace()
    return publish_decision_batch(
        root / risk.batch_id,
        snapshot=snapshot,
        intents=intents,
        target=target,
        risk=risk,
        plan=plan,
        created_at=MANIFEST_TIME,
    )


def _risk(
    target: PortfolioTarget,
    original: RiskDecision,
    *,
    increase_allowed: bool,
    reduce_allowed: bool,
) -> RiskDecision:
    return RiskDecision.create(
        batch_id=original.batch_id,
        portfolio_target_id=target.portfolio_target_id,
        decision_time=original.decision_time,
        approved=True,
        input_target=target.target_weights,
        approved_target=target.target_weights,
        adjustments=(),
        violations=(),
        risk_state_hash=original.risk_state_hash,
        increase_risk_allowed=increase_allowed,
        reduce_risk_allowed=reduce_allowed,
    )


def _plan(
    target: PortfolioTarget,
    risk: RiskDecision,
    original: OrderPlan,
) -> OrderPlan:
    return OrderPlan.create(
        batch_id=risk.batch_id,
        risk_decision_id=risk.risk_decision_id,
        portfolio_target_id=target.portfolio_target_id,
        snapshot_id=original.snapshot_id,
        decision_ids=original.decision_ids,
        created_at=original.created_at,
        current_position_hash=original.current_position_hash,
        approved_target=risk.approved_target,
        orders=original.orders,
        cancellations=original.cancellations,
        retained_order_ids=original.retained_order_ids,
        expected_positions=original.expected_positions,
        reconciliation_tolerance=original.reconciliation_tolerance,
        blockers=original.blockers,
        executable=original.executable,
    )


class DecisionBatchArtifactTest(unittest.TestCase):
    def test_manifest_round_trips_and_never_authorizes_orders(self) -> None:
        first = _manifest()
        second = _manifest()

        self.assertEqual(first, second)
        self.assertEqual(first.validate(), ())
        self.assertFalse(first.orders_authorized)
        self.assertEqual(load_artifact(dump_artifact(first)), first)
        tampered = replace(first, orders_authorized=True)
        self.assertIn(
            "decision_batch_manifest_cannot_authorize_orders",
            tampered.validate(),
        )
        with self.assertRaisesRegex(ArtifactCodecError, "cannot_authorize_orders"):
            dump_artifact(tampered)

    def test_publish_is_manifest_last_with_strict_modes(self) -> None:
        calls: list[str] = []

        def recording_write(path: str | Path, value: object):
            calls.append(Path(path).name)
            return real_write(path, value)

        with tempfile.TemporaryDirectory() as temporary, patch(
            "qount.persistence.batch_store.write_immutable_artifact",
            side_effect=recording_write,
        ):
            batch = _publish(Path(temporary))
            directory = Path(temporary) / batch.manifest.batch_id

            self.assertEqual(calls[-1], "manifest.json")
            self.assertEqual(read_decision_batch(directory), batch)
            self.assertEqual(inspect_decision_batch(directory)["status"], "complete")
            self.assertEqual(stat.S_IMODE(os.stat(directory).st_mode), 0o700)
            for path in directory.iterdir():
                self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def test_two_independent_publishes_have_identical_golden_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = _publish(root / "first")
            second = _publish(root / "second")
            first_dir = root / "first" / first.manifest.batch_id
            second_dir = root / "second" / second.manifest.batch_id

            first_files = {
                path.name: path.read_bytes() for path in first_dir.iterdir()
            }
            second_files = {
                path.name: path.read_bytes() for path in second_dir.iterdir()
            }
            self.assertEqual(first_files, second_files)

    def test_partial_directory_requires_verified_resume_not_overwrite(self) -> None:
        snapshot, intents, target, risk, plan = _trace()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / risk.batch_id
            directory.mkdir(mode=0o700)
            write_immutable_artifact(directory / "market_snapshot.json", snapshot)

            self.assertEqual(inspect_decision_batch(directory)["status"], "incomplete")
            with self.assertRaisesRegex(
                DecisionBatchIncompleteError,
                "manifest_missing",
            ):
                read_decision_batch(directory)
            with self.assertRaises(FileExistsError):
                publish_decision_batch(
                    directory,
                    snapshot=snapshot,
                    intents=intents,
                    target=target,
                    risk=risk,
                    plan=plan,
                    created_at=MANIFEST_TIME,
                )
            self.assertFalse((directory / "manifest.json").exists())
            snapshot_bytes = (directory / "market_snapshot.json").read_bytes()
            resumed = resume_incomplete_decision_batch(
                directory,
                snapshot=snapshot,
                intents=intents,
                target=target,
                risk=risk,
                plan=plan,
                created_at=MANIFEST_TIME,
            )
            self.assertEqual(resumed.snapshot, snapshot)
            self.assertEqual(
                (directory / "market_snapshot.json").read_bytes(),
                snapshot_bytes,
            )
            self.assertEqual(inspect_decision_batch(directory)["status"], "complete")

    def test_resume_rejects_mismatched_existing_member_without_manifest(self) -> None:
        snapshot, intents, target, risk, plan = _trace()
        replacement = MarketSnapshot.create(
            decision_time=snapshot.decision_time,
            data_cutoff=snapshot.data_cutoff,
            prices={"BTCUSDT": 99_000.0, "ETHUSDT": 3_500.0},
            funding=snapshot.funding,
            features=snapshot.features,
            exchange_rules_hash=snapshot.exchange_rules_hash,
            account_snapshot_hash=snapshot.account_snapshot_hash,
            data_quality=snapshot.data_quality,
            source_hashes=snapshot.source_hashes,
        )
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / risk.batch_id
            directory.mkdir(mode=0o700)
            write_immutable_artifact(directory / "market_snapshot.json", replacement)
            with self.assertRaisesRegex(
                DecisionBatchError,
                "reference_.*_mismatch",
            ):
                resume_incomplete_decision_batch(
                    directory,
                    snapshot=snapshot,
                    intents=intents,
                    target=target,
                    risk=risk,
                    plan=plan,
                    created_at=MANIFEST_TIME,
                )
            self.assertFalse((directory / "manifest.json").exists())

    def test_missing_or_unexpected_member_invalidates_completed_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            batch = _publish(Path(temporary) / "missing")
            missing_dir = Path(temporary) / "missing" / batch.manifest.batch_id
            (missing_dir / "order_plan.json").unlink()
            with self.assertRaisesRegex(
                DecisionBatchIncompleteError,
                "files_mismatch",
            ):
                read_decision_batch(missing_dir)

            batch = _publish(Path(temporary) / "unexpected")
            unexpected_dir = Path(temporary) / "unexpected" / batch.manifest.batch_id
            (unexpected_dir / "unexpected.json").write_text("{}", encoding="ascii")
            with self.assertRaisesRegex(
                DecisionBatchIncompleteError,
                "files_mismatch",
            ):
                read_decision_batch(unexpected_dir)

    def test_tamper_and_valid_replacement_fail_reference_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            batch = _publish(Path(temporary) / "tampered")
            directory = Path(temporary) / "tampered" / batch.manifest.batch_id
            snapshot_path = directory / "market_snapshot.json"
            os.chmod(snapshot_path, 0o600)
            raw = snapshot_path.read_bytes()
            snapshot_path.write_bytes(raw.replace(b"100000.0", b"99000.00"))
            with self.assertRaises(ArtifactCodecError):
                read_decision_batch(directory)

            batch = _publish(Path(temporary) / "replacement")
            directory = Path(temporary) / "replacement" / batch.manifest.batch_id
            snapshot_path = directory / "market_snapshot.json"
            snapshot_path.unlink()
            replacement = MarketSnapshot.create(
                decision_time=batch.snapshot.decision_time,
                data_cutoff=batch.snapshot.data_cutoff,
                prices={"BTCUSDT": 99_000.0, "ETHUSDT": 3_500.0},
                funding=batch.snapshot.funding,
                features=batch.snapshot.features,
                exchange_rules_hash=batch.snapshot.exchange_rules_hash,
                account_snapshot_hash=batch.snapshot.account_snapshot_hash,
                data_quality=batch.snapshot.data_quality,
                source_hashes=batch.snapshot.source_hashes,
            )
            write_immutable_artifact(snapshot_path, replacement)
            with self.assertRaisesRegex(
                DecisionBatchError,
                "reference_.*_mismatch",
            ):
                read_decision_batch(directory)

    def test_cross_object_target_and_risk_mismatch_fails_before_publish(self) -> None:
        snapshot, intents, target, risk, plan = _trace()
        other_target = PortfolioTarget.create(
            snapshot_id=target.snapshot_id,
            decision_ids=target.decision_ids,
            decision_time=target.decision_time,
            proposed_target_weights={"BTCUSDT": 0.2},
            target_weights={"BTCUSDT": 0.2},
            sleeve_contributions={"test_strategy": {"BTCUSDT": 0.2}},
            blockers=(),
            allocatable=True,
            allocation_hash="9" * 64,
        )
        other_risk = _risk(
            other_target,
            risk,
            increase_allowed=True,
            reduce_allowed=True,
        )

        with self.assertRaisesRegex(
            DecisionBatchError,
            "risk_portfolio_target_mismatch",
        ):
            build_decision_batch_manifest(
                snapshot=snapshot,
                intents=intents,
                target=target,
                risk=other_risk,
                plan=plan,
                created_at=MANIFEST_TIME,
            )

        inconsistent_target = PortfolioTarget.create(
            snapshot_id=target.snapshot_id,
            decision_ids=target.decision_ids,
            decision_time=target.decision_time,
            proposed_target_weights={"BTCUSDT": 0.3},
            target_weights={"BTCUSDT": 0.3},
            sleeve_contributions={"test_strategy": {"BTCUSDT": 0.2}},
            blockers=(),
            allocatable=True,
            allocation_hash="8" * 64,
        )
        with self.assertRaisesRegex(
            DecisionBatchError,
            "target_sleeve_sum_mismatch",
        ):
            build_decision_batch_manifest(
                snapshot=snapshot,
                intents=intents,
                target=inconsistent_target,
                risk=risk,
                plan=plan,
                created_at=MANIFEST_TIME,
            )

    def test_risk_permissions_control_increase_and_reduction_actions(self) -> None:
        snapshot, intents, target, original_risk, original_plan = _trace()
        no_increase = _risk(
            target,
            original_risk,
            increase_allowed=False,
            reduce_allowed=True,
        )
        no_increase_plan = _plan(target, no_increase, original_plan)
        with self.assertRaisesRegex(
            DecisionBatchError,
            "increase_order_not_allowed",
        ):
            build_decision_batch_manifest(
                snapshot=snapshot,
                intents=intents,
                target=target,
                risk=no_increase,
                plan=no_increase_plan,
                created_at=MANIFEST_TIME,
            )

        no_reduction = _risk(
            target,
            original_risk,
            increase_allowed=True,
            reduce_allowed=False,
        )
        no_reduction_plan = _plan(target, no_reduction, original_plan)
        with self.assertRaisesRegex(
            DecisionBatchError,
            "reduction_action_not_allowed",
        ):
            build_decision_batch_manifest(
                snapshot=snapshot,
                intents=intents,
                target=target,
                risk=no_reduction,
                plan=no_reduction_plan,
                created_at=MANIFEST_TIME,
            )

    def test_manifest_time_directory_name_and_reference_path_fail_closed(self) -> None:
        snapshot, intents, target, risk, plan = _trace()
        with self.assertRaisesRegex(
            DecisionBatchError,
            "created_before_order_plan",
        ):
            build_decision_batch_manifest(
                snapshot=snapshot,
                intents=intents,
                target=target,
                risk=risk,
                plan=plan,
                created_at="2026-07-20T00:04:00+00:00",
            )
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(
                DecisionBatchError,
                "directory_name_mismatch",
            ):
                publish_decision_batch(
                    Path(temporary) / "wrong-batch-id",
                    snapshot=snapshot,
                    intents=intents,
                    target=target,
                    risk=risk,
                    plan=plan,
                    created_at=MANIFEST_TIME,
                )
        with self.assertRaisesRegex(ValueError, "file_name_invalid"):
            ArtifactReference.create(
                artifact_type="market_snapshot",
                object_id="1" * 64,
                payload_hash="2" * 64,
                artifact_hash="3" * 64,
                file_name="../snapshot.json",
            )

    def test_insecure_directory_or_artifact_mode_fails_readback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            batch = _publish(Path(temporary) / "directory-mode")
            directory = Path(temporary) / "directory-mode" / batch.manifest.batch_id
            os.chmod(directory, 0o755)
            with self.assertRaisesRegex(DecisionBatchError, "directory_mode_invalid"):
                read_decision_batch(directory)

            batch = _publish(Path(temporary) / "artifact-mode")
            directory = Path(temporary) / "artifact-mode" / batch.manifest.batch_id
            os.chmod(directory / "order_plan.json", 0o644)
            with self.assertRaisesRegex(DecisionBatchError, "artifact_mode_invalid"):
                read_decision_batch(directory)

    def test_manifest_hash_is_pinned(self) -> None:
        manifest = _manifest()
        self.assertEqual(
            artifact_envelope(manifest)["artifact_hash"],
            "1f03366dc88619bc912dd0feff7a55875e83f325f7b2568f8f408c22c57166e8",
        )


if __name__ == "__main__":
    unittest.main()
