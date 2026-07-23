from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from qount.certification import ExecutionAttributionReport
from qount.operations import BaseStandardProductionError
from qount.operations import read_base_standard_production_status
from qount.operations import record_base_standard_production_cycle
from qount.operations.authority_writer import AuthorityWriterConfig
from qount.operations.authority_writer import write_order_free_authority_bundle
from qount.reporting import read_vps_authority_bundle
from tests.test_authority_writer import _fake_health
from tests.test_authority_writer import _live_standard_plan
from tests.test_authority_writer import _source_run


OBSERVED_AT = "2026-08-02T00:20:00+00:00"
RELEASE = {
    "git_commit": "a" * 40,
    "version": "0.2.15",
    "source_tree_hash": "b" * 64,
    "provenance_hash": "c" * 64,
}


def _inputs(root: Path):
    run, _ = _source_run(root, blocked=False)
    config = AuthorityWriterConfig(
        repo_root=Path(__file__).parents[1],
        source_root=root / "state/mini_trend/forward/latest",
        authority_root=root / "authority",
        runtime_root=root / "runtime",
        backup_root=root / "backups",
        dashboard_root=root / "dashboard",
        lock_path=root / "lock/publisher.lock",
    )
    written = write_order_free_authority_bundle(
        config,
        captured_at="2026-08-02T00:10:00+00:00",
        health_dependencies=_fake_health(),
    )
    if written.status != "written":
        raise AssertionError(written)
    bundle = read_vps_authority_bundle(root / "authority")
    plan, registry = _live_standard_plan(bundle, run)
    return bundle, plan, registry


def _real_report() -> dict:
    report = ExecutionAttributionReport.create_real_fill(
        run_id="d" * 64,
        decision_to_submit_ms=10.0,
        submit_to_ack_ms=20.0,
        ack_to_fill_ms=30.0,
        planned_vs_filled_qty=1.0,
        partial_fill_count=0,
        cancel_replace_count=0,
        arrival_mid=100.0,
        bid_ask_spread=0.1,
        fill_vwap=100.02,
        adverse_slippage=2.0,
        maker_or_taker="taker",
        fee=0.04,
        funding=0.0,
        unfilled_exposure_time=50.0,
        protection_order_latency=40.0,
        stop_gap=500.0,
        attribution_source_hash="e" * 64,
    )
    return asdict(report)


class BaseStandardProductionTest(unittest.TestCase):
    def test_zero_order_cycle_arms_observer_without_fabricating_sample(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle, plan, registry = _inputs(root)
            production_root = root / "standard-production"
            status = record_base_standard_production_cycle(
                production_root,
                batch=bundle.batch,
                ledger_snapshot=bundle.ledger_snapshot,
                registry=registry,
                plan=plan,
                dispatch={
                    "status": "completed",
                    "exchange_mutation_attempted": False,
                    "responses": [],
                    "execution_attribution_reports": [],
                },
                release_identity=RELEASE,
                observed_at=OBSERVED_AT,
            )

            self.assertEqual(
                status["first_fill_observation"], "awaiting_natural_fill"
            )
            self.assertEqual(status["sample_count"], 0)
            self.assertIsNone(status["first_sample_id"])
            self.assertFalse(status["latest_cycle"]["orders_forced_for_sampling"])
            self.assertEqual(
                status["latest_authority"]["batch_id"],
                bundle.batch.manifest.batch_id,
            )
            self.assertEqual(
                stat.S_IMODE(production_root.stat().st_mode), 0o700
            )
            for path in production_root.rglob("*"):
                self.assertEqual(
                    stat.S_IMODE(path.stat().st_mode),
                    0o700 if path.is_dir() else 0o600,
                )

    def test_first_natural_fill_is_immutable_and_survives_later_wait_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle, plan, registry = _inputs(root)
            production_root = root / "standard-production"
            report = _real_report()
            raw_evidence = {
                "submit_response": {"id": "exchange-order-1"},
                "confirmed_order": {"status": "closed"},
                "trades": [{"id": "trade-1"}],
                "authorization": "[REDACTED]",
                "source_hash": "f" * 64,
            }
            first = record_base_standard_production_cycle(
                production_root,
                batch=bundle.batch,
                ledger_snapshot=bundle.ledger_snapshot,
                registry=registry,
                plan=plan,
                dispatch={
                    "status": "completed",
                    "exchange_mutation_attempted": True,
                    "execution_attribution_reports": [report],
                    "responses": [
                        {
                            "execution_attribution": report,
                            "raw_exchange_evidence": raw_evidence,
                        }
                    ],
                },
                release_identity=RELEASE,
                observed_at=OBSERVED_AT,
            )
            first_id = first["first_sample_id"]
            sample_path = production_root / "samples" / f"{first_id}.json"
            sample_bytes = sample_path.read_bytes()

            second = record_base_standard_production_cycle(
                production_root,
                batch=bundle.batch,
                ledger_snapshot=bundle.ledger_snapshot,
                registry=registry,
                plan=plan,
                dispatch={
                    "status": "completed",
                    "exchange_mutation_attempted": False,
                    "execution_attribution_reports": [],
                    "responses": [],
                },
                release_identity=RELEASE,
                observed_at="2026-08-03T00:20:00+00:00",
            )

            self.assertEqual(second["first_fill_observation"], "captured")
            self.assertEqual(second["first_sample_id"], first_id)
            self.assertEqual(second["sample_count"], 1)
            self.assertEqual(sample_path.read_bytes(), sample_bytes)
            self.assertEqual(
                read_base_standard_production_status(production_root), second
            )

    def test_tamper_and_unsanitized_exchange_secret_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle, plan, registry = _inputs(root)
            production_root = root / "standard-production"
            status = record_base_standard_production_cycle(
                production_root,
                batch=bundle.batch,
                ledger_snapshot=bundle.ledger_snapshot,
                registry=registry,
                plan=plan,
                dispatch={
                    "status": "completed",
                    "exchange_mutation_attempted": False,
                    "execution_attribution_reports": [],
                    "responses": [],
                },
                release_identity=RELEASE,
                observed_at=OBSERVED_AT,
            )
            status_path = production_root / "status.json"
            tampered = json.loads(status_path.read_text(encoding="ascii"))
            tampered["sample_count"] = 1
            status_path.write_text(json.dumps(tampered) + "\n", encoding="ascii")
            os.chmod(status_path, 0o600)
            with self.assertRaisesRegex(
                BaseStandardProductionError, "status_hash_invalid"
            ):
                read_base_standard_production_status(production_root)
            self.assertEqual(status["sample_count"], 0)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle, plan, registry = _inputs(root)
            report = _real_report()
            with self.assertRaisesRegex(
                BaseStandardProductionError, "sensitive_field"
            ):
                record_base_standard_production_cycle(
                    root / "standard-production",
                    batch=bundle.batch,
                    ledger_snapshot=bundle.ledger_snapshot,
                    registry=registry,
                    plan=plan,
                    dispatch={
                        "status": "completed",
                        "exchange_mutation_attempted": True,
                        "execution_attribution_reports": [report],
                        "responses": [
                            {
                                "execution_attribution": report,
                                "raw_exchange_evidence": {
                                    "api_key": "plaintext-forbidden",
                                    "source_hash": "f" * 64,
                                },
                            }
                        ],
                    },
                    release_identity=RELEASE,
                    observed_at=OBSERVED_AT,
                )


if __name__ == "__main__":
    unittest.main()
