from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from qount.contracts import canonical_hash
from qount.mini_trend.live_pilot import LIVE_PILOT_CONTRACT
from qount.mini_trend.pilot_dispatcher import PILOT_DISPATCH_SNAPSHOT_VERSION
from qount.mini_trend.pilot_projection import PILOT_PROJECTION_VERSION
from qount.operations.authority_writer import AuthorityWriterConfig
from qount.operations.authority_writer import write_order_free_authority_bundle
from qount.operations.health_probes import CommandResult
from qount.operations.health_probes import HealthProbeDependencies
from qount.risk import legacy_dispatch_plan_hash
from qount.reporting import read_vps_authority_bundle
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


class AuthorityWriterTest(unittest.TestCase):
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
            self.assertEqual(bundle.ledger_snapshot.positions, {})
            self.assertFalse(bundle.ledger_snapshot.reconciliation["passed"])
            self.assertEqual(bundle.registry.entries[0].promotion_status, "research")
            self.assertEqual(bundle.system_health.status, "unavailable")

    def test_systemd_unit_has_no_network_or_runtime_authority(self) -> None:
        unit = (
            Path(__file__).parents[1]
            / "deploy/systemd/qount-dashboard-authority.service"
        ).read_text()
        self.assertIn("PrivateNetwork=true", unit)
        self.assertIn("SuccessExitStatus=75", unit)
        self.assertIn("QOUNT_LIVE_ENABLE=false", unit)
        self.assertIn("QOUNT_MINI_TREND_LIVE_ENABLE=false", unit)
        self.assertIn("UnsetEnvironment=", unit)
        self.assertIn("BINANCE_API_KEY", unit)
        self.assertNotIn("WantedBy=", unit)


if __name__ == "__main__":
    unittest.main()
