from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qount.certification import CertificationArtifactIncompleteError
from qount.certification import CertificationArtifactStoreError
from qount.certification import CertificationPlan
from qount.certification import CertificationRunner
from qount.certification import publish_certification_bundle
from qount.certification import read_certification_bundle
from qount.certification.gateway import LocalVenueGateway


_HASH = "a" * 64


def _plan() -> CertificationPlan:
    return CertificationPlan.create(
        certification_type="local_gateway",
        venue_semantic="real_ack_fill",
        symbol="BTCUSDT",
        action="certification_artifact_store_test",
        max_notional=120.0,
        max_fee=1.0,
        max_holding_time_seconds=120.0,
        owner_authorization_hash=_HASH,
        arm_token_hash=_HASH,
        expires_at="2026-12-31T23:59:59+00:00",
        preflight_snapshot_hash=_HASH,
        venue_capability_snapshot_hash=_HASH,
        zero_position_plan="market_reverse_to_close_then_verify_zero",
        failure_handling_path="manual_flatten_reconcile_and_halt",
        certification_status="local_sim",
    )


def _completed_runner(
    *, evidence_provenance: dict | None = None
) -> tuple[CertificationRunner, object]:
    gateway = LocalVenueGateway()
    runner = CertificationRunner(
        _plan(),
        gateway,
        source="local_gateway",
        evidence_provenance=evidence_provenance,
    )
    runner.start()
    runner.submit_order("cert-buy", "BTCUSDT", "BUY", 0.001)
    runner.submit_order("cert-sell", "BTCUSDT", "SELL", 0.001)
    return runner, runner.generate_result()


class CertificationArtifactStoreTest(unittest.TestCase):
    def test_publish_and_read_complete_bundle(self) -> None:
        runner, result = _completed_runner(
            evidence_provenance={
                "code_bundle_hash": "b" * 64,
                "dependency_manifest_hash": "c" * 64,
                "plan_hash": _plan().plan_hash,
                "arm_hash": "d" * 64,
            }
        )
        self.assertIsNotNone(runner.run)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / result.run_id
            published = publish_certification_bundle(
                directory,
                run=runner.run,
                result=result,
                member_payloads=runner.artifact_payloads,
            )
            self.assertEqual(published.member_count, 12)
            self.assertEqual(published.result.result_id, result.result_id)
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
            expected = {
                "manifest.json",
                "bundle_metadata.json",
                *(ref.file_name for ref in result.artifact_members),
            }
            self.assertEqual({path.name for path in directory.iterdir()}, expected)
            for path in directory.iterdir():
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            verified = read_certification_bundle(directory)
            self.assertEqual(verified.result.result_hash, result.result_hash)

    def test_manifest_missing_is_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / ("a" * 64)
            directory.mkdir(mode=0o700)
            with self.assertRaises(CertificationArtifactIncompleteError):
                read_certification_bundle(directory)

    def test_tamper_is_detected(self) -> None:
        runner, result = _completed_runner()
        self.assertIsNotNone(runner.run)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / result.run_id
            publish_certification_bundle(
                directory,
                run=runner.run,
                result=result,
                member_payloads=runner.artifact_payloads,
            )
            member = directory / result.artifact_members[0].file_name
            envelope = json.loads(member.read_text(encoding="ascii"))
            envelope["payload"]["tampered"] = True
            member.write_text(json.dumps(envelope), encoding="ascii")
            os.chmod(member, 0o600)
            with self.assertRaises(CertificationArtifactStoreError):
                read_certification_bundle(directory)

    def test_metadata_tamper_is_detected(self) -> None:
        runner, result = _completed_runner()
        self.assertIsNotNone(runner.run)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / result.run_id
            publish_certification_bundle(
                directory,
                run=runner.run,
                result=result,
                member_payloads=runner.artifact_payloads,
            )
            metadata_path = directory / "bundle_metadata.json"
            metadata = json.loads(metadata_path.read_text(encoding="ascii"))
            metadata["member_count"] = 11
            metadata_path.write_text(
                json.dumps(metadata),
                encoding="ascii",
            )
            os.chmod(metadata_path, 0o600)
            with self.assertRaises(CertificationArtifactStoreError):
                read_certification_bundle(directory)

    def test_duplicate_directory_is_rejected(self) -> None:
        runner, result = _completed_runner()
        self.assertIsNotNone(runner.run)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / result.run_id
            publish_certification_bundle(
                directory,
                run=runner.run,
                result=result,
                member_payloads=runner.artifact_payloads,
            )
            with self.assertRaises(CertificationArtifactStoreError):
                publish_certification_bundle(
                    directory,
                    run=runner.run,
                    result=result,
                    member_payloads=runner.artifact_payloads,
                )

    def test_missing_member_payload_is_rejected(self) -> None:
        runner, result = _completed_runner()
        self.assertIsNotNone(runner.run)
        payloads = runner.artifact_payloads
        payloads.pop("exchange_raw")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(CertificationArtifactStoreError):
                publish_certification_bundle(
                    Path(tmp) / result.run_id,
                    run=runner.run,
                    result=result,
                    member_payloads=payloads,
                )

    def test_sensitive_field_is_rejected(self) -> None:
        runner, result = _completed_runner(
            evidence_provenance={"api_secret": "must-not-persist"}
        )
        self.assertIsNotNone(runner.run)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(CertificationArtifactStoreError) as ctx:
                publish_certification_bundle(
                    Path(tmp) / result.run_id,
                    run=runner.run,
                    result=result,
                    member_payloads=runner.artifact_payloads,
                )
        self.assertIn("sensitive_field", str(ctx.exception))

    def test_manifest_write_failure_leaves_incomplete_bundle(self) -> None:
        runner, result = _completed_runner()
        self.assertIsNotNone(runner.run)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / result.run_id
            with patch(
                "qount.certification.artifact_store.write_immutable_artifact",
                side_effect=RuntimeError("injected_manifest_failure"),
            ):
                with self.assertRaises(RuntimeError):
                    publish_certification_bundle(
                        directory,
                        run=runner.run,
                        result=result,
                        member_payloads=runner.artifact_payloads,
                    )
            self.assertFalse((directory / "manifest.json").exists())
            with self.assertRaises(CertificationArtifactIncompleteError):
                read_certification_bundle(directory)


if __name__ == "__main__":
    unittest.main()
