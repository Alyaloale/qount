from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from qount.contracts import canonical_hash
from qount.governance import StrategyRegistration
from qount.governance import StrategyRegistry
from qount.ledger import build_runtime_ledger_snapshot
from qount.notifications import SYSTEM_COMPONENTS
from qount.notifications import SystemComponentObservation
from qount.notifications import SystemHealthContractError
from qount.notifications import SystemHealthSnapshot
from qount.reporting import build_dashboard_v1
from tests.test_ledger_dashboard_bridge import CAPTURED_AT
from tests.test_ledger_dashboard_bridge import _ledger_with_accounting


def _hash(name: str) -> str:
    return canonical_hash({"system_health_fixture": name})


def _health_snapshot(
    *,
    status_by_component: dict[str, str] | None = None,
    manual_arm: bool | None = None,
    live_timer_state: str | None = None,
) -> SystemHealthSnapshot:
    statuses = status_by_component or {}
    observed_at = "2026-07-20T00:07:05+00:00"
    metrics = {
        "clock": {"drift_seconds": 0.015},
        "disk": {"free_bytes": 40_000_000_000, "total_bytes": 80_000_000_000},
        "service": {"service_name": "qount-publisher.service", "active_state": "active"},
        "backup": {
            "last_success_at": "2026-07-20T00:00:00+00:00",
            "age_seconds": 425,
        },
        "operations": {
            "checks": [
                {
                    "check_id": "observer_contract",
                    "status": "pass",
                    "detail": "fixture_healthy",
                    "impact_scopes": [
                        "delivery",
                        "execution",
                        "intelligence",
                        "observation",
                    ],
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
    if manual_arm is not None:
        metrics["operations"]["checks"].append(
            {
                "check_id": "trading:manual_arm",
                "status": "pass",
                "detail": "arm_present" if manual_arm else "arm_absent_disarmed",
                "impact_scopes": ["execution"],
                "blocks_execution": False,
                "observed_value": manual_arm,
            }
        )
    if live_timer_state is not None:
        metrics["operations"]["checks"].append(
            {
                "check_id": "service:mini_trend_live",
                "status": "pass",
                "detail": (
                    "service_state_expected:"
                    f"qount-mini-trend-live.timer:{live_timer_state}"
                ),
                "impact_scopes": ["execution"],
                "blocks_execution": True,
                "observed_value": live_timer_state,
            }
        )
    metrics["operations"]["checks"].sort(key=lambda row: row["check_id"])
    observations = []
    for component in SYSTEM_COMPONENTS:
        status = statuses.get(component, "healthy")
        component_metrics = dict(metrics[component])
        if component == "service" and status != "healthy":
            component_metrics["active_state"] = "failed"
        if component == "operations" and status != "healthy":
            component_metrics["checks"][0]["status"] = (
                "warn" if status == "degraded" else "block"
            )
            component_metrics["checks"][0]["blocks_execution"] = (
                status == "unavailable"
            )
            component_metrics["scope_status"]["execution"] = (
                "degraded" if status == "degraded" else "unavailable"
            )
        observations.append(
            SystemComponentObservation.create(
                component=component,
                status=status,
                observed_at=observed_at,
                detail_codes=(
                    () if status == "healthy" else (f"{component}_{status}",)
                ),
                metrics=component_metrics,
                source_id=_hash(f"{component}-source-id"),
                source_hash=_hash(f"{component}-source"),
            )
        )
    return SystemHealthSnapshot.create(
        observations,
        captured_at="2026-07-20T00:07:15+00:00",
    )


class SystemHealthContractTest(unittest.TestCase):
    def test_requires_exact_structured_component_set(self) -> None:
        snapshot = _health_snapshot()
        snapshot.validate()
        self.assertEqual(
            tuple(row["component"] for row in snapshot.observations),
            SYSTEM_COMPONENTS,
        )
        self.assertEqual(snapshot.status, "healthy")

        observations = [
            SystemComponentObservation.from_dict(row)
            for row in snapshot.observations[:-1]
        ]
        with self.assertRaisesRegex(
            SystemHealthContractError, "components_incomplete"
        ):
            SystemHealthSnapshot.create(
                observations,
                captured_at="2026-07-20T00:07:15+00:00",
            )

    def test_component_and_snapshot_tamper_fail_closed(self) -> None:
        snapshot = _health_snapshot()
        clock = dict(snapshot.observations[0])
        clock["metrics"] = {"drift_seconds": 99.0}
        tampered_observations = (clock, *snapshot.observations[1:])
        tampered = replace(snapshot, observations=tampered_observations)
        with self.assertRaisesRegex(SystemHealthContractError, "hash_invalid"):
            tampered.validate()

    def test_backup_age_is_bound_to_observation_time(self) -> None:
        with self.assertRaisesRegex(SystemHealthContractError, "age_mismatch"):
            SystemComponentObservation.create(
                component="backup",
                status="healthy",
                observed_at="2026-07-20T00:07:05+00:00",
                detail_codes=(),
                metrics={
                    "last_success_at": "2026-07-20T00:00:00+00:00",
                    "age_seconds": 1,
                },
                source_id=_hash("backup-source-id"),
                source_hash=_hash("backup-source"),
            )

    def test_unavailable_clock_and_disk_do_not_require_fabricated_values(self) -> None:
        clock = SystemComponentObservation.create(
            component="clock",
            status="unavailable",
            observed_at="2026-07-20T00:07:05+00:00",
            detail_codes=("clock_probe_failed",),
            metrics={"drift_seconds": None},
            source_id=_hash("clock-unavailable-id"),
            source_hash=_hash("clock-unavailable-source"),
        )
        disk = SystemComponentObservation.create(
            component="disk",
            status="unavailable",
            observed_at="2026-07-20T00:07:05+00:00",
            detail_codes=("disk_probe_failed",),
            metrics={"free_bytes": None, "total_bytes": None},
            source_id=_hash("disk-unavailable-id"),
            source_hash=_hash("disk-unavailable-source"),
        )
        self.assertIsNone(clock.metrics["drift_seconds"])
        self.assertIsNone(disk.metrics["free_bytes"])
        with self.assertRaisesRegex(
            SystemHealthContractError, "clock_availability_mismatch"
        ):
            SystemComponentObservation.create(
                component="clock",
                status="degraded",
                observed_at="2026-07-20T00:07:05+00:00",
                detail_codes=("clock_probe_failed",),
                metrics={"drift_seconds": None},
                source_id=_hash("clock-invalid-id"),
                source_hash=_hash("clock-invalid-source"),
            )

    def test_dashboard_health_has_independent_freshness_and_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ledger, batch, registry = _ledger_with_accounting(Path(temporary))
            ledger_snapshot = build_runtime_ledger_snapshot(
                ledger, batch, captured_at=CAPTURED_AT
            )
            health = _health_snapshot()
            models = build_dashboard_v1(
                batch,
                registry,
                generated_at=CAPTURED_AT,
                evaluated_at="2026-07-20T00:08:15+00:00",
                stale_after_seconds=900,
                system_stale_after_seconds=60,
                ledger_snapshot=ledger_snapshot,
                system_health=health,
            )

        self.assertEqual(models.overview.freshness["status"], "fresh")
        self.assertEqual(models.system.freshness["status"], "stale")
        self.assertEqual(models.strategies.freshness["status"], "stale")
        self.assertEqual(
            models.strategies.freshness["source_updated_at"],
            "2026-07-20T00:07:05+00:00",
        )
        self.assertEqual(models.readiness.payload["status"], "stale")
        self.assertEqual(
            set(models.system.freshness["sources"]), {"ops_observer"}
        )
        self.assertEqual(models.system.payload["summary"]["status"], "healthy")
        self.assertEqual(
            set(models.system.source_hashes),
            {
                "decision_batch_manifest",
                "strategy_registry",
                "runtime_ledger",
                "system_health",
            },
        )

    def test_new_blocked_observation_cannot_mask_stale_execution_health(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, batch, registry = _ledger_with_accounting(Path(temporary))
            health = _health_snapshot()
            core = {
                "status": "blocked",
                "live_orders_allowed": False,
                "runtime_ledger_created": False,
                "strategy_id": "test_strategy",
                "blockers": ["preflight:no_unmanaged_positions"],
                "observed_at": "2026-07-20T00:08:00+00:00",
            }
            observation = core | {"observation_hash": canonical_hash(core)}
            models = build_dashboard_v1(
                batch,
                registry,
                generated_at="2026-07-20T00:08:10+00:00",
                evaluated_at="2026-07-20T00:08:15+00:00",
                stale_after_seconds=300,
                system_stale_after_seconds=60,
                system_health=health,
                blocked_runtime_observation=observation,
            )

        self.assertEqual(models.overview.freshness["status"], "fresh")
        self.assertEqual(models.strategies.freshness["status"], "stale")
        self.assertEqual(models.readiness.payload["status"], "stale")
        self.assertEqual(
            models.strategies.freshness["source_updated_at"],
            "2026-07-20T00:07:05+00:00",
        )

    def test_armed_requires_live_registry_arm_and_active_live_timer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ledger, batch, registry = _ledger_with_accounting(Path(temporary))
            snapshot = build_runtime_ledger_snapshot(
                ledger, batch, captured_at=CAPTURED_AT
            )
            entry = registry.entries[0]
            live_entry = StrategyRegistration.create(
                strategy_id=entry.strategy_id,
                strategy_version=entry.strategy_version,
                strategy_kind=entry.strategy_kind,
                promotion_status="minimal_live",
                strategy_contract_hash=entry.strategy_contract_hash,
                code_hash=entry.code_hash,
                config_hash=entry.config_hash,
                promotion_artifact_hash=entry.promotion_artifact_hash,
                owner_authorization_hash="e" * 64,
                maximum_stress_loss_fraction=entry.maximum_stress_loss_fraction,
                maximum_gross=entry.maximum_gross,
                registered_at=entry.registered_at,
            )
            live_registry = StrategyRegistry.create(
                (live_entry,), created_at=registry.created_at
            )
            armed = build_dashboard_v1(
                batch,
                live_registry,
                generated_at=CAPTURED_AT,
                stale_after_seconds=300,
                ledger_snapshot=snapshot,
                system_health=_health_snapshot(
                    manual_arm=True, live_timer_state="active"
                ),
            )
            inactive = build_dashboard_v1(
                batch,
                live_registry,
                generated_at=CAPTURED_AT,
                stale_after_seconds=300,
                ledger_snapshot=snapshot,
                system_health=_health_snapshot(
                    manual_arm=True, live_timer_state="inactive"
                ),
            )

        armed_strategy = armed.strategies.payload["strategies"][0]
        self.assertEqual(armed_strategy["execution_status"], "armed")
        self.assertEqual(armed_strategy["execution_blockers"], [])
        self.assertFalse(armed_strategy["live_orders_allowed"])
        self.assertEqual(
            armed.readiness.payload["axes"]["trading_authority"]["status"],
            "armed",
        )
        inactive_strategy = inactive.strategies.payload["strategies"][0]
        self.assertEqual(inactive_strategy["execution_status"], "disarmed")
        self.assertIn(
            "live_timer_inactive", inactive_strategy["execution_blockers"]
        )

    def test_system_freshness_does_not_inherit_runtime_ledger_window(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ledger, batch, registry = _ledger_with_accounting(Path(temporary))
            ledger_snapshot = build_runtime_ledger_snapshot(
                ledger, batch, captured_at=CAPTURED_AT
            )
            models = build_dashboard_v1(
                batch,
                registry,
                generated_at=CAPTURED_AT,
                evaluated_at="2026-07-20T00:08:15+00:00",
                stale_after_seconds=60,
                system_stale_after_seconds=120,
                ledger_snapshot=ledger_snapshot,
                system_health=_health_snapshot(),
            )

        self.assertEqual(models.overview.freshness["status"], "stale")
        self.assertEqual(models.system.freshness["status"], "fresh")
        self.assertEqual(
            set(models.system.freshness["sources"]), {"ops_observer"}
        )

    def test_unavailable_component_requires_halt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ledger, batch, registry = _ledger_with_accounting(Path(temporary))
            ledger_snapshot = build_runtime_ledger_snapshot(
                ledger, batch, captured_at=CAPTURED_AT
            )
            models = build_dashboard_v1(
                batch,
                registry,
                generated_at=CAPTURED_AT,
                ledger_snapshot=ledger_snapshot,
                system_health=_health_snapshot(
                    status_by_component={"service": "unavailable"}
                ),
            )

        self.assertEqual(
            models.system.payload["summary"]["status"], "halt_required"
        )
        self.assertIn(
            "health_service_unavailable",
            models.system.payload["summary"]["reason_codes"],
        )


if __name__ == "__main__":
    unittest.main()
