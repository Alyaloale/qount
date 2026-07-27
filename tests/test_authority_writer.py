from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from qount.contracts import canonical_hash
from qount.governance import StrategyRegistry
from qount.mini_trend.live_pilot import LIVE_PILOT_CONTRACT
from qount.mini_trend.pilot_dispatcher import build_manual_arm
from qount.mini_trend.pilot_dispatcher import PILOT_DISPATCH_SNAPSHOT_VERSION
from qount.mini_trend.pilot_dispatcher import _bind_standard_authority
from qount.mini_trend.pilot_dispatcher import _finalize_plan
from qount.mini_trend.pilot_dispatcher import run_pilot_dispatch
from qount.mini_trend.pilot_dispatcher import verify_dispatch_journal
from qount.mini_trend.pilot_projection import PILOT_PROJECTION_VERSION
from qount.operations.authority_writer import AuthorityWriterConfig
from qount.operations.authority_writer import AuthorityWriterBlocked
from qount.operations.authority_writer import authorize_minimal_live_authority_bundle
from qount.operations.authority_writer import refresh_authority_bundle_from_runtime
from qount.operations.authority_writer import write_order_free_authority_bundle
from qount.operations.authority_writer import read_blocked_runtime_observation
from qount.operations.health_probes import CommandResult
from qount.operations.health_probes import HealthProbeDependencies
from qount.notifications import SystemComponentObservation
from qount.notifications import SystemHealthSnapshot
from qount.ledger import RuntimeLedger
from qount.risk import legacy_dispatch_plan_hash
from qount.reporting import read_vps_authority_bundle
from qount.strategies import base_strategy_registration
from tests.test_legacy_dispatch_replay import _artifacts
from tests.test_mini_trend_pilot_dispatcher import _plan
from tests.test_mini_trend_pilot_dispatcher import _preflight
from tests.test_mini_trend_pilot_dispatcher import _readiness
from tests.test_mini_trend_pilot_dispatcher import _snapshot


def _bytes(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=True, indent=2).encode("ascii")


def _write(path: Path, value: dict) -> str:
    raw = _bytes(value)
    path.write_bytes(raw)
    os.chmod(path, 0o600)
    return hashlib.sha256(raw).hexdigest()


def _fake_health() -> HealthProbeDependencies:
    def command(argv: tuple[str, ...]) -> CommandResult:
        if argv[0] == "timedatectl" and "NTPSynchronized" in argv:
            return CommandResult(0, "yes\n")
        if argv[0] == "timedatectl":
            return CommandResult(0, "0 us\n")
        if argv[0] == "systemctl":
            return CommandResult(0, "active\n")
        raise AssertionError(argv)

    class Usage:
        total = 100_000_000_000
        used = 10_000_000_000
        free = 90_000_000_000

    return HealthProbeDependencies(command_runner=command, disk_usage=lambda _: Usage())


def _healthy_snapshot(observed_at: str) -> SystemHealthSnapshot:
    metrics = {
        "clock": {"drift_seconds": 0.0},
        "disk": {"free_bytes": 90_000_000_000, "total_bytes": 100_000_000_000},
        "service": {
            "service_name": "qount-dashboard-publisher.timer",
            "active_state": "active",
        },
        "backup": {"last_success_at": observed_at, "age_seconds": 0},
        "operations": {
            "checks": [
                {
                    "check_id": "observer_contract",
                    "status": "pass",
                    "detail": "fixture_healthy",
                    "impact_scopes": (
                        "delivery",
                        "execution",
                        "intelligence",
                        "observation",
                    ),
                    "blocks_execution": False,
                    "observed_value": True,
                }
            ],
            "scope_status": {
                "delivery": "pass",
                "execution": "pass",
                "intelligence": "pass",
                "observation": "pass",
            },
        },
    }
    observations = tuple(
        SystemComponentObservation.create(
            component=component,
            status="healthy",
            observed_at=observed_at,
            detail_codes=(),
            metrics=metrics[component],
            source_id=canonical_hash({"healthy_source_id": component}),
            source_hash=canonical_hash(
                {"healthy_source_hash": component, "observed_at": observed_at}
            ),
        )
        for component in ("clock", "disk", "service", "backup", "operations")
    )
    return SystemHealthSnapshot.create(observations, captured_at=observed_at)


def _source_run(root: Path, *, blocked: bool) -> tuple[Path, dict[str, str]]:
    runs = root / "state" / "mini_trend" / "forward" / "runs"
    run = runs / "20260802T000000Z"
    run.mkdir(parents=True, mode=0o700)
    os.chmod(run, 0o700)
    projection, dispatch = _artifacts()
    preflight = _preflight()
    snapshot = _snapshot()
    snapshot["created_at"] = "2026-08-02T00:01:00+00:00"
    snapshot["balance"] = {
        "margin_balance": 300.0,
        "quote_free": 300.0,
        "quote_used": 0.0,
        "wallet_balance": 300.0,
    }
    snapshot["snapshot_hash"] = canonical_hash(
        {
            "contract_hash": snapshot["contract_hash"],
            "balance": snapshot["balance"],
            "prices": snapshot["prices"],
            "positions": snapshot["positions"],
            "regular_open_orders": snapshot["regular_open_orders"],
            "conditional_open_orders": snapshot["conditional_open_orders"],
            "position_mode": snapshot["position_mode"],
            "resolved_symbols": snapshot["resolved_symbols"],
        }
    )
    preflight["diagnostics"] = {
        "blockers": [],
        "verdict": "account_preflight_pass",
    }
    preflight["evidence"]["account_flat"] = True
    dispatch = copy.deepcopy(dispatch)
    dispatch["account_snapshot"] = snapshot
    dispatch["created_at"] = "2026-08-02T00:02:00+00:00"
    projection["schema_version"] = PILOT_PROJECTION_VERSION
    projection["contract"]["strategy"] = LIVE_PILOT_CONTRACT.strategy
    projection["contract"]["capital_usdt"] = 100.0
    dispatch["capital_usdt"] = 100.0
    projection["diagnostics"] = {"projection_ready": not blocked}
    if blocked:
        dispatch["decision"] = None
        dispatch["diagnostics"] = {
            "blockers": ["latest_completed_decision_unavailable"],
            "dry_evidence_valid": False,
            "verdict": "await_dispatch_decision",
        }
        preflight["diagnostics"] = {"blockers": ["account_flat"], "verdict": "blocked_account_preflight"}
        preflight["evidence"]["account_flat"] = False
    hashes = {
        "account_preflight": _write(run / "account_preflight.json", preflight),
        "dry_dispatch": _write(run / "dry_dispatch.json", dispatch),
        "exchange_rules": _write(run / "exchange_rules.json", {"rules": []}),
        "latest_projection": _write(run / "latest_projection.json", projection),
    }
    readiness = _readiness(preflight_hash=hashes["account_preflight"])
    readiness["created_at"] = "2026-08-02T00:01:30+00:00"
    hashes["dispatch_readiness"] = _write(
        run / "dispatch_readiness.json", readiness
    )
    final_readiness = copy.deepcopy(readiness)
    final_readiness["created_at"] = "2026-08-02T00:03:00+00:00"
    hashes["live_readiness"] = _write(
        run / "live_readiness.json", final_readiness
    )
    if not blocked:
        dispatch["source_hashes"] = {
            "projection": hashes["latest_projection"],
            "preflight": hashes["account_preflight"],
            "readiness": hashes["dispatch_readiness"],
            "exchange_rules": hashes["exchange_rules"],
        }
        dispatch["plan_hash"] = legacy_dispatch_plan_hash(dispatch)
        hashes["dry_dispatch"] = _write(run / "dry_dispatch.json", dispatch)
    (run.parent.parent / "latest").symlink_to(Path("runs") / run.name)
    return run, hashes


def _live_standard_plan(bundle, run: Path) -> tuple[dict, StrategyRegistry]:
    plan = json.loads((run / "dry_dispatch.json").read_text())
    plan["meta"] = {
        **plan["meta"],
        "mode": "live",
        "orders_allowed": True,
        "live_orders_allowed": True,
    }
    plan["diagnostics"] = {
        **plan["diagnostics"],
        "blockers": [],
        "verdict": "live_dispatch_ready",
        "live_authorized": True,
    }
    source = {
        "batch_id": bundle.batch.manifest.batch_id,
        "ledger_snapshot_hash": bundle.ledger_snapshot.snapshot_hash,
        "reconciliation_hash": bundle.ledger_snapshot.reconciliation["report_hash"],
    }
    plan["standard_authority"] = source
    authority_readiness = {
        "evidence": {
            "authority_batch_id": source["batch_id"],
            "runtime_ledger_snapshot_hash": source["ledger_snapshot_hash"],
            "pre_dispatch_reconciliation_hash": source["reconciliation_hash"],
        }
    }
    ready_readiness = _readiness()
    arm = build_manual_arm(
        ready_readiness,
        readiness_artifact_sha256="r",
        confirmed_readiness_hash=ready_readiness["readiness_hash"],
        arm_token="test-arm-token-long",
    )
    registry = StrategyRegistry.create(
        (
            base_strategy_registration(
                promotion_status="minimal_live",
                code_hash=bundle.registry.entries[0].code_hash,
                config_hash=bundle.registry.entries[0].config_hash,
                promotion_artifact_hash="a" * 64,
                owner_authorization_hash=arm["owner_authorization_hash"],
                maximum_stress_loss_fraction=0.01,
                maximum_gross=1.0,
                registered_at="2026-08-02T00:11:00+00:00",
            ),
        ),
        created_at="2026-08-02T00:11:00+00:00",
    )
    _bind_standard_authority(
        plan,
        authority_readiness,
        bundle.batch,
        bundle.ledger_snapshot,
        registry,
        arm,
    )
    return _finalize_plan(plan), registry


class AuthorityWriterTest(unittest.TestCase):
    def test_account_safety_block_writes_non_executable_observation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = root / "state/mini_trend/forward/runs/20260802T000000Z"
            run.mkdir(parents=True, mode=0o700)
            os.chmod(run, 0o700)
            common_meta = {
                "orders_allowed": False,
                "live_orders_allowed": False,
                "private_api_order_attempted": False,
                "mutating_account_method_attempted": False,
            }
            values = {
                "account_preflight.json": {
                    "created_at": "2026-08-02T00:01:00+00:00",
                    "meta": common_meta | {"read_only": True},
                },
                "dispatch_readiness.json": {
                    "created_at": "2026-08-02T00:01:10+00:00",
                    "meta": common_meta,
                },
                "dry_dispatch.json": {
                    "created_at": "2026-08-02T00:01:20+00:00",
                    "meta": common_meta,
                    "diagnostics": {"verdict": "blocked_dispatch"},
                },
                "exchange_rules.json": {"created_at": "2026-08-02T00:00:50+00:00"},
                "latest_projection.json": {
                    "created_at": "2026-08-02T00:01:15+00:00",
                    "meta": common_meta,
                    "decision": {"decision_id": "a" * 64},
                    "contract": {"strategy": "MiniTrend-UM-Base-v0.2"},
                    "diagnostics": {"projection_ready": True},
                },
            }
            for name, value in values.items():
                _write(run / name, value)
            config = AuthorityWriterConfig(
                repo_root=Path(__file__).parents[1],
                source_root=root / "state/mini_trend/forward/latest",
                authority_root=root / "authority",
                runtime_root=root / "runtime",
                backup_root=root / "backups",
                dashboard_root=root / "dashboard",
                lock_path=root / "lock/publisher.lock",
            )
            blocked = AuthorityWriterBlocked(
                (
                    "dispatch:critical_account_preflight_blocked",
                    "dispatch:unmanaged_or_duplicate_conditional_order",
                    "preflight:no_unmanaged_positions",
                    "account_snapshot_unmanaged_conditional_order",
                ),
                run_dir=run,
            )
            with mock.patch(
                "qount.operations.authority_writer._validate_sources",
                side_effect=blocked,
            ):
                result = write_order_free_authority_bundle(
                    config, captured_at="2026-08-02T00:02:00+00:00"
                )
            observation = read_blocked_runtime_observation(
                root / "blocked_runtime_observation.json"
            )

        self.assertEqual(result.status, "blocked_observation_written")
        self.assertIsNotNone(observation)
        self.assertFalse(observation["live_orders_allowed"])
        self.assertFalse(observation["runtime_ledger_created"])
        self.assertEqual(observation["strategy_id"], "MiniTrend-UM-Base-v0.2")
        self.assertFalse((root / "runtime/runtime.sqlite3").exists())

    def test_legacy_run_without_preserved_dispatch_readiness_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _source_run(root, blocked=True)
            (root / "state/mini_trend/forward/latest/dispatch_readiness.json").unlink()
            config = AuthorityWriterConfig(
                repo_root=Path(__file__).parents[1],
                source_root=root / "state/mini_trend/forward/latest",
                authority_root=root / "authority",
                runtime_root=root / "runtime",
                backup_root=root / "backups",
                dashboard_root=root / "dashboard",
                lock_path=root / "lock/publisher.lock",
            )
            result = write_order_free_authority_bundle(
                config,
                captured_at="2026-08-02T00:10:00+00:00",
            )
            self.assertEqual(result.status, "blocked")
            self.assertEqual(
                result.blockers, ("dispatch_readiness_source_missing",)
            )

    def test_missing_completed_decision_blocks_without_touching_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run, _ = _source_run(root, blocked=True)
            authority = root / "authority"
            authority.mkdir(mode=0o700)
            marker = authority / "untouched"
            marker.write_text("keep")
            config = AuthorityWriterConfig(
                repo_root=Path(__file__).parents[1],
                source_root=root / "state/mini_trend/forward/latest",
                authority_root=authority,
                runtime_root=root / "runtime",
                backup_root=root / "backups",
                dashboard_root=root / "dashboard",
                lock_path=root / "lock/publisher.lock",
            )
            result = write_order_free_authority_bundle(
                config,
                captured_at="2026-08-02T00:10:00+00:00",
            )
            self.assertEqual(result.status, "blocked")
            self.assertIn(
                "dispatch:latest_completed_decision_unavailable", result.blockers
            )
            self.assertTrue(marker.exists())
            self.assertFalse((root / "runtime").exists())
            self.assertEqual(run.name, Path(result.run_dir).name)

    def test_complete_flat_run_writes_importable_standard_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _source_run(root, blocked=False)
            config = AuthorityWriterConfig(
                repo_root=Path(__file__).parents[1],
                source_root=root / "state/mini_trend/forward/latest",
                authority_root=root / "authority",
                runtime_root=root / "runtime",
                backup_root=root / "backups",
                dashboard_root=root / "dashboard",
                lock_path=root / "lock/publisher.lock",
            )
            result = write_order_free_authority_bundle(
                config,
                captured_at="2026-08-02T00:10:00+00:00",
                health_dependencies=_fake_health(),
            )
            self.assertEqual(result.status, "written")
            bundle = read_vps_authority_bundle(root / "authority")
            self.assertFalse(bundle.batch.manifest.orders_authorized)
            self.assertEqual(
                bundle.ledger_snapshot.positions,
                {"BNBUSDT": 0.0, "BTCUSDT": 0.0, "ETHUSDT": 0.0},
            )
            self.assertEqual(
                bundle.ledger_snapshot.reconciliation["phase"], "pre_dispatch"
            )
            self.assertTrue(bundle.ledger_snapshot.reconciliation["passed"])
            self.assertEqual(bundle.registry.entries[0].promotion_status, "research")
            self.assertEqual(bundle.system_health.status, "unavailable")

    def test_systemd_unit_has_no_network_or_runtime_authority(self) -> None:
        unit = (
            Path(__file__).parents[1]
            / "deploy/systemd/qount-dashboard-authority.service"
        ).read_text()
        self.assertIn("PrivateNetwork=true", unit)
        self.assertIn("ReadWritePaths=-/run/chrony", unit)
        self.assertIn("CapabilityBoundingSet=CAP_DAC_OVERRIDE", unit)
        self.assertNotIn("CAP_NET_", unit)
        self.assertIn("SuccessExitStatus=75", unit)
        self.assertIn("QOUNT_LIVE_ENABLE=false", unit)
        self.assertIn("QOUNT_MINI_TREND_LIVE_ENABLE=false", unit)
        self.assertIn("UnsetEnvironment=", unit)
        self.assertIn("BINANCE_API_KEY", unit)
        self.assertNotIn("WantedBy=", unit)

    def test_manual_arm_atomically_promotes_matching_authority_to_minimal_live(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _source_run(root, blocked=False)
            config = AuthorityWriterConfig(
                repo_root=Path(__file__).parents[1],
                source_root=root / "state/mini_trend/forward/latest",
                authority_root=root / "authority",
                runtime_root=root / "runtime",
                backup_root=root / "backups",
                dashboard_root=root / "dashboard",
                lock_path=root / "lock/publisher.lock",
            )
            write_order_free_authority_bundle(
                config,
                captured_at="2026-08-02T00:10:00+00:00",
                health_dependencies=_fake_health(),
            )
            bundle = read_vps_authority_bundle(root / "authority")
            readiness = _readiness()
            readiness["evidence"] = {
                **readiness["evidence"],
                "authority_batch_id": bundle.batch.manifest.batch_id,
                "runtime_ledger_snapshot_hash": bundle.ledger_snapshot.snapshot_hash,
                "pre_dispatch_reconciliation_hash": bundle.ledger_snapshot.reconciliation[
                    "report_hash"
                ],
            }
            readiness["readiness_hash"] = canonical_hash(
                {
                    "contract_hash": readiness["contract"]["contract_hash"],
                    "request": {
                        key: readiness["request"].get(key)
                        for key in (
                            "owner_requested_one_month_live",
                            "capital_usdt",
                            "start_date",
                            "duration_days",
                        )
                    },
                    "evidence": readiness["evidence"],
                    "gates": readiness["gates"],
                    "observations": readiness["observations"],
                }
            )
            arm = build_manual_arm(
                readiness,
                readiness_artifact_sha256="f" * 64,
                confirmed_readiness_hash=readiness["readiness_hash"],
                arm_token="test-arm-token-long",
            )
            promoted = authorize_minimal_live_authority_bundle(
                config,
                arm=arm,
                arm_artifact_hash="a" * 64,
                captured_at="2026-08-02T00:11:00+00:00",
                health_dependencies=_fake_health(),
            )
            self.assertEqual(promoted.status, "written")
            updated = read_vps_authority_bundle(root / "authority")
            self.assertEqual(
                updated.ledger_snapshot.snapshot_hash,
                bundle.ledger_snapshot.snapshot_hash,
            )
            self.assertEqual(updated.registry.entries[0].promotion_status, "minimal_live")
            self.assertEqual(
                updated.registry.entries[0].owner_authorization_hash,
                arm["owner_authorization_hash"],
            )
            self.assertGreater(
                dt.datetime.fromisoformat(updated.registry.created_at),
                dt.datetime.fromisoformat(updated.batch.manifest.created_at),
            )
            updated.daily_brief.validate()

    def test_manual_arm_recaptures_quiet_monitoring_without_synthetic_alert(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _source_run(root, blocked=False)
            config = AuthorityWriterConfig(
                repo_root=Path(__file__).parents[1],
                source_root=root / "state/mini_trend/forward/latest",
                authority_root=root / "authority",
                runtime_root=root / "runtime",
                backup_root=root / "backups",
                dashboard_root=root / "dashboard",
                lock_path=root / "lock/publisher.lock",
            )
            first_health = _healthy_snapshot("2026-08-02T00:10:00+00:00")
            second_health = _healthy_snapshot("2026-08-02T00:12:00+00:00")
            with mock.patch(
                "qount.operations.authority_writer._health",
                side_effect=(first_health, second_health),
            ):
                write_order_free_authority_bundle(
                    config,
                    captured_at="2026-08-02T00:10:00+00:00",
                )
                bundle = read_vps_authority_bundle(root / "authority")
                readiness = _readiness()
                readiness["evidence"] = {
                    **readiness["evidence"],
                    "authority_batch_id": bundle.batch.manifest.batch_id,
                    "runtime_ledger_snapshot_hash": bundle.ledger_snapshot.snapshot_hash,
                    "pre_dispatch_reconciliation_hash": bundle.ledger_snapshot.reconciliation[
                        "report_hash"
                    ],
                }
                readiness["readiness_hash"] = canonical_hash(
                    {
                        "contract_hash": readiness["contract"]["contract_hash"],
                        "request": {
                            key: readiness["request"].get(key)
                            for key in (
                                "owner_requested_one_month_live",
                                "capital_usdt",
                                "start_date",
                                "duration_days",
                            )
                        },
                        "evidence": readiness["evidence"],
                        "gates": readiness["gates"],
                        "observations": readiness["observations"],
                    }
                )
                arm = build_manual_arm(
                    readiness,
                    readiness_artifact_sha256="f" * 64,
                    confirmed_readiness_hash=readiness["readiness_hash"],
                    arm_token="test-arm-token-long",
                )
                promoted = authorize_minimal_live_authority_bundle(
                    config,
                    arm=arm,
                    arm_artifact_hash="a" * 64,
                    captured_at="2026-08-02T00:12:00+00:00",
                )
            updated = read_vps_authority_bundle(root / "authority")

            self.assertEqual(promoted.status, "written")
            self.assertEqual(updated.registry.entries[0].promotion_status, "minimal_live")
            self.assertEqual(updated.notification_snapshot.alerts, ())
            self.assertEqual(updated.notification_snapshot.open_alert_count, 0)
            self.assertEqual(updated.notification_snapshot.audit_row_count, 0)
            self.assertEqual(
                updated.notification_snapshot.observed_at,
                "2026-08-02T00:12:00+00:00",
            )

    def test_next_order_free_batch_preserves_matching_minimal_live_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
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
            write_order_free_authority_bundle(
                config,
                captured_at="2026-08-02T00:10:00+00:00",
                health_dependencies=_fake_health(),
            )
            initial = read_vps_authority_bundle(root / "authority")
            readiness = _readiness()
            readiness["evidence"] = {
                **readiness["evidence"],
                "authority_batch_id": initial.batch.manifest.batch_id,
                "runtime_ledger_snapshot_hash": initial.ledger_snapshot.snapshot_hash,
                "pre_dispatch_reconciliation_hash": initial.ledger_snapshot.reconciliation[
                    "report_hash"
                ],
            }
            readiness["readiness_hash"] = canonical_hash(
                {
                    "contract_hash": readiness["contract"]["contract_hash"],
                    "request": {
                        key: readiness["request"].get(key)
                        for key in (
                            "owner_requested_one_month_live",
                            "capital_usdt",
                            "start_date",
                            "duration_days",
                        )
                    },
                    "evidence": readiness["evidence"],
                    "gates": readiness["gates"],
                    "observations": readiness["observations"],
                }
            )
            arm = build_manual_arm(
                readiness,
                readiness_artifact_sha256="f" * 64,
                confirmed_readiness_hash=readiness["readiness_hash"],
                arm_token="test-arm-token-long",
            )
            authorize_minimal_live_authority_bundle(
                config,
                arm=arm,
                arm_artifact_hash="a" * 64,
                captured_at="2026-08-02T00:11:00+00:00",
                health_dependencies=_fake_health(),
            )
            promoted = read_vps_authority_bundle(root / "authority")

            projection = json.loads((run / "latest_projection.json").read_text())
            dispatch = json.loads((run / "dry_dispatch.json").read_text())
            projection["decision"]["decision_date"] = "2026-08-02"
            dispatch["decision"]["decision_date"] = "2026-08-02"
            next_decision_id = canonical_hash({"next_decision": dispatch["decision"]})
            projection["decision"]["decision_id"] = next_decision_id
            dispatch["decision"]["decision_id"] = next_decision_id
            projection_hash = _write(run / "latest_projection.json", projection)
            dispatch["source_hashes"]["projection"] = projection_hash
            dispatch["created_at"] = "2026-08-03T00:02:00+00:00"
            dispatch["account_snapshot"]["created_at"] = (
                "2026-08-03T00:01:00+00:00"
            )
            dispatch["plan_hash"] = legacy_dispatch_plan_hash(dispatch)
            _write(run / "dry_dispatch.json", dispatch)

            next_result = write_order_free_authority_bundle(
                config,
                captured_at="2026-08-03T00:10:00+00:00",
                health_dependencies=_fake_health(),
            )
            self.assertEqual(next_result.status, "written")
            next_bundle = read_vps_authority_bundle(root / "authority")
            next_entry = next_bundle.registry.entries[0]
            previous_entry = promoted.registry.entries[0]
            self.assertNotEqual(
                next_bundle.batch.manifest.batch_id,
                promoted.batch.manifest.batch_id,
            )
            self.assertEqual(next_entry.promotion_status, "minimal_live")
            self.assertEqual(
                next_entry.promotion_artifact_hash,
                previous_entry.promotion_artifact_hash,
            )
            self.assertEqual(
                next_entry.owner_authorization_hash,
                previous_entry.owner_authorization_hash,
            )
            self.assertEqual(
                next_entry.supersedes_entry_id,
                previous_entry.registry_entry_id,
            )

    def test_live_dispatch_uses_standard_ids_and_updates_runtime_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
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
            self.assertEqual(written.status, "written")
            bundle = read_vps_authority_bundle(root / "authority")
            ledger = RuntimeLedger(root / "runtime/runtime.sqlite3")
            plan, minimal_registry = _live_standard_plan(bundle, run)
            self.assertEqual(plan["diagnostics"]["blockers"], [])
            self.assertTrue(
                all(
                    row["client_order_id"].startswith(("q-i-", "q-r-"))
                    for row in plan["market_orders"]
                )
            )
            self.assertTrue(
                all(
                    row["client_order_id"].startswith("q-p-")
                    for row in plan["stop_orders"]
                )
            )

            post = copy.deepcopy(plan["account_snapshot"])
            post["created_at"] = "2026-08-02T00:20:15.500000+00:00"
            post["positions"] = [
                {
                    "data_symbol": order["symbol"],
                    "symbol": order["ccxt_symbol"],
                    "side": "long",
                    "contracts": order["quantity"],
                    "notional_usdt": order["notional_usdt"],
                    "average_cost": post["prices"][order["symbol"]],
                }
                for order in plan["market_orders"]
            ]
            post["conditional_open_orders"] = [
                {
                    "id": f"stop-{index}",
                    "data_symbol": order["symbol"],
                    "symbol": order["ccxt_symbol"],
                    "side": "sell",
                    "client_order_id": order["client_order_id"],
                    "close_position": True,
                    "reduce_only": False,
                    "status": "open",
                }
                for index, order in enumerate(plan["stop_orders"], 1)
            ]
            post["snapshot_hash"] = canonical_hash(
                {
                    "contract_hash": post["contract_hash"],
                    "balance": post["balance"],
                    "prices": post["prices"],
                    "positions": post["positions"],
                    "regular_open_orders": post["regular_open_orders"],
                    "conditional_open_orders": post["conditional_open_orders"],
                    "position_mode": post["position_mode"],
                    "resolved_symbols": post["resolved_symbols"],
                }
            )

            class Exchange:
                def __init__(self):
                    self.calls = []
                    self.market_orders = {}

                def create_order(self, symbol, type_, side, amount, price, params):
                    self.calls.append((symbol, type_, side, amount, price, params))
                    if type_ == "market":
                        response = {
                            "id": f"market-{len(self.calls)}",
                            "clientOrderId": params["newClientOrderId"],
                            "symbol": symbol,
                            "type": type_,
                            "side": side,
                            "status": "closed",
                            "filled": amount,
                            "average": post["prices"][
                                next(
                                    order["symbol"]
                                    for order in plan["market_orders"]
                                    if order["ccxt_symbol"] == symbol
                                )
                            ],
                            "fee": {"cost": 0.01, "currency": "USDT"},
                        }
                        self.market_orders[response["id"]] = response
                        return response
                    return {
                        "id": f"stop-{len(self.calls)}",
                        "clientOrderId": params["newClientOrderId"],
                        "symbol": symbol,
                        "type": type_,
                        "side": side,
                        "status": "open",
                    }

                def cancel_order(self, *args, **kwargs):
                    self.calls.append(("cancel", args, kwargs))

                def fetch_order(self, order_id, symbol):
                    return self.market_orders[order_id]

                def fetch_order_trades(self, order_id, symbol):
                    order = self.market_orders[order_id]
                    return [
                        {
                            "id": f"trade-{order_id}",
                            "order": order_id,
                            "clientOrderId": order["clientOrderId"],
                            "amount": order["filled"],
                            "price": order["average"],
                            "fee": {"cost": 0.01, "currency": "USDT"},
                            "datetime": "2026-08-02T00:20:10+00:00",
                        }
                    ]

                def fetch_ledger(self, currency, since, limit):
                    if currency != "USDT" or limit != 1000:
                        raise AssertionError("unexpected ledger query")
                    return []

            clock = iter(
                dt.datetime(2026, 8, 2, 0, 20, second, tzinfo=dt.timezone.utc)
                for second in range(40)
            )
            journal = root / "live-dispatch.jsonl"
            with mock.patch(
                "qount.mini_trend.pilot_dispatcher.utc_now",
                side_effect=lambda: next(clock),
            ), mock.patch(
                "qount.mini_trend.pilot_dispatcher.fetch_pilot_dispatch_snapshot",
                return_value=post,
            ):
                result = run_pilot_dispatch(
                    mock.Mock(),
                    plan,
                    journal,
                    exchange=Exchange(),
                    halt_path=root / "HALT",
                    standard_batch=bundle.batch,
                    runtime_ledger=ledger,
                    pre_dispatch_ledger_snapshot=bundle.ledger_snapshot,
                    standard_registry=minimal_registry,
                )
            self.assertEqual(result["status"], "completed", result)
            self.assertEqual(
                len(result["execution_attribution_reports"]),
                len(plan["market_orders"]),
            )
            for report in result["execution_attribution_reports"]:
                self.assertEqual(report["attribution_source"], "real_fill")
                self.assertEqual(
                    report["field_evidence"]["fee"]["status"],
                    "available",
                )
                self.assertEqual(report["arrival_mid"], "unavailable")
                self.assertEqual(
                    report["field_evidence"]["arrival_mid"]["missing_reason"],
                    "order_book_query_unavailable",
                )
            market_responses = [
                response
                for response in result["responses"]
                if response.get("type") == "market"
            ]
            self.assertTrue(
                all("raw_exchange_evidence" in response for response in market_responses)
            )
            self.assertFalse((root / "HALT").exists())
            self.assertEqual(
                verify_dispatch_journal(journal)["executed_decision_ids"],
                [plan["decision"]["decision_id"]],
            )
            self.assertTrue(ledger.risk_increase_allowed())
            for order in bundle.batch.plan.orders:
                expected = "ACKNOWLEDGED" if order.phase == "protective" else "FILLED"
                self.assertEqual(ledger.get_order(order.client_order_id)["status"], expected)
            refreshed = refresh_authority_bundle_from_runtime(
                config,
                captured_at="2026-08-02T00:25:00+00:00",
                health_dependencies=_fake_health(),
            )
            self.assertEqual(refreshed.status, "written")
            post_bundle = read_vps_authority_bundle(root / "authority")
            self.assertEqual(
                post_bundle.ledger_snapshot.reconciliation["phase"],
                "post_dispatch",
            )
            self.assertTrue(post_bundle.ledger_snapshot.reconciliation["passed"])
            self.assertEqual(post_bundle.ledger_snapshot.unresolved_order_ids, ())

    def test_market_timeout_is_unknown_halted_and_not_retried(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
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
            self.assertEqual(written.status, "written")
            bundle = read_vps_authority_bundle(root / "authority")
            ledger = RuntimeLedger(root / "runtime/runtime.sqlite3")
            plan, registry = _live_standard_plan(bundle, run)

            class Exchange:
                def __init__(self):
                    self.calls = []

                def create_order(self, symbol, type_, side, amount, price, params):
                    self.calls.append((symbol, type_, side, amount, price, params))
                    raise TimeoutError("exchange result unknown")

            exchange = Exchange()
            journal = root / "live-timeout.jsonl"
            halt = root / "HALT"
            clock = iter(
                dt.datetime(2026, 8, 2, 0, 20, second, tzinfo=dt.timezone.utc)
                for second in range(40)
            )
            with mock.patch(
                "qount.mini_trend.pilot_dispatcher.utc_now",
                side_effect=lambda: next(clock),
            ):
                result = run_pilot_dispatch(
                    mock.Mock(),
                    plan,
                    journal,
                    exchange=exchange,
                    halt_path=halt,
                    standard_batch=bundle.batch,
                    runtime_ledger=ledger,
                    pre_dispatch_ledger_snapshot=bundle.ledger_snapshot,
                    standard_registry=registry,
                )

            self.assertEqual(result["status"], "halted_uncertain")
            self.assertTrue(halt.exists())
            self.assertEqual(len(exchange.calls), 1)
            market_orders = [
                order for order in bundle.batch.plan.orders if order.phase != "protective"
            ]
            first = ledger.get_order(market_orders[0].client_order_id)
            self.assertEqual(first["status"], "UNKNOWN")
            self.assertEqual(
                [row["to_status"] for row in ledger.list_order_events(first["client_order_id"])],
                ["SUBMITTING", "UNKNOWN"],
            )
            self.assertTrue(
                all(
                    ledger.get_order(order.client_order_id)["status"] == "PLANNED"
                    for order in bundle.batch.plan.orders
                    if order.client_order_id != first["client_order_id"]
                )
            )
            self.assertEqual(
                verify_dispatch_journal(journal)["locked_live_decision_ids"],
                [plan["decision"]["decision_id"]],
            )
            self.assertIsNotNone(result["runtime_ledger_snapshot_hash"])
            refreshed = refresh_authority_bundle_from_runtime(
                config,
                captured_at="2026-08-02T00:25:00+00:00",
                health_dependencies=_fake_health(),
            )
            self.assertEqual(refreshed.status, "written")
            halted_bundle = read_vps_authority_bundle(root / "authority")
            self.assertEqual(
                halted_bundle.registry.entries[0].promotion_status, "halted"
            )
            self.assertIn(
                first["client_order_id"],
                halted_bundle.ledger_snapshot.unresolved_order_ids,
            )


if __name__ == "__main__":
    unittest.main()
