from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from qount.mini_trend.pilot_runtime import (
    build_pilot_runtime_proof,
    validate_pilot_runtime_proof,
)


ROOT = Path(__file__).resolve().parents[1]


class MiniTrendPilotRuntimeTest(unittest.TestCase):
    def test_forward_cycle_scopes_dispatch_journal_to_contract_hash(self) -> None:
        cycle = (
            ROOT / "scripts" / "desktop" / "mini_trend_um_forward_cycle.sh"
        ).read_text(encoding="ascii")

        self.assertIn("LIVE_PILOT_CONTRACT.contract_hash", cycle)
        self.assertIn(
            'DISPATCH_JOURNAL_PATH="$DRY_ROOT/contracts/'
            '$DISPATCH_CONTRACT_HASH/dispatcher.jsonl"',
            cycle,
        )
        self.assertNotIn(
            'DISPATCH_JOURNAL_PATH="$DRY_ROOT/dispatcher.jsonl"', cycle
        )

    def test_systemd_order_free_runtime_is_verified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cycle = root / "cycle.sh"
            unit = root / "service.service"
            cycle.write_text("#!/bin/sh\n", encoding="ascii")
            cycle.chmod(0o700)
            unit.write_text("[Service]\n", encoding="ascii")
            proof = build_pilot_runtime_proof(
                cycle_path=cycle,
                service_unit_path=unit,
                environment={
                    "INVOCATION_ID": "test-invocation",
                    "QOUNT_LIVE_ENABLE": "false",
                    "QOUNT_X4_LIVE_ENABLE": "false",
                    "QOUNT_RV_LIVE_ENABLE": "false",
                    "QOUNT_CXD_CARRY_ENABLE": "false",
                    "QOUNT_MINI_TREND_LIVE_ENABLE": "false",
                },
            )
        self.assertEqual(
            proof["diagnostics"]["verdict"], "independent_runtime_verified"
        )
        self.assertTrue(validate_pilot_runtime_proof(proof))
        self.assertNotIn("test-invocation", str(proof))

    def test_live_cycle_and_systemd_unit_keep_single_strategy_fail_closed(self) -> None:
        cycle = (
            ROOT / "scripts" / "desktop" / "mini_trend_um_live_cycle.sh"
        ).read_text(encoding="ascii")
        service = (
            ROOT / "deploy" / "systemd" / "qount-mini-trend-live.service"
        ).read_text(encoding="ascii")
        timer = (
            ROOT / "deploy" / "systemd" / "qount-mini-trend-live.timer"
        ).read_text(encoding="ascii")

        self.assertIn("mini_trend_um_forward_cycle.sh", cycle)
        self.assertIn("--mode live", cycle)
        self.assertIn("--arm-path", cycle)
        self.assertIn("QOUNT_MINI_TREND_LIVE_ENABLE", cycle)
        self.assertIn("QOUNT_MINI_TREND_LIVE_CONFIRMATION", cycle)
        self.assertIn("QOUNT_MINI_TREND_ARM_TOKEN", cycle)
        self.assertIn("blocked_live_env_permissions", cycle)
        self.assertIn("blocked_arm_permissions", cycle)
        self.assertIn("blocked_legacy_live_switch", cycle)
        self.assertIn("executed_count", cycle)
        self.assertIn("duplicate_decision_noop", cycle)
        self.assertIn("blocked_unresolved_live_intent", cycle)
        self.assertNotIn("x4_live", cycle)
        self.assertNotIn("cxd_live", cycle)
        self.assertIn(
            "EnvironmentFile=/root/.config/qount/mini-trend-live.env", service
        )
        self.assertIn("ConditionPathExists=!/root/qount/state/mini_trend/HALT", service)
        self.assertIn("QOUNT_LIVE_ENABLE=false", service)
        self.assertIn("QOUNT_X4_LIVE_ENABLE=false", service)
        self.assertIn("QOUNT_RV_LIVE_ENABLE=false", service)
        self.assertIn("QOUNT_CXD_CARRY_ENABLE=false", service)
        self.assertNotIn("QOUNT_MINI_TREND_LIVE_ENABLE=true", service)
        self.assertIn("Unit=qount-mini-trend-live.service", timer)

    def test_live_cycle_stops_before_refresh_when_unarmed(self) -> None:
        cycle = ROOT / "scripts" / "desktop" / "mini_trend_um_live_cycle.sh"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = os.environ.copy()
            env.update(
                {
                    "QOUNT_PROJECT_ROOT": str(ROOT),
                    "QOUNT_PYTHON_BIN": str(ROOT / ".venv" / "bin" / "python"),
                    "QOUNT_MINI_TREND_STATE_ROOT": str(root / "state"),
                    "QOUNT_MINI_TREND_LIVE_ENABLE": "false",
                }
            )
            result = subprocess.run(
                ["/bin/bash", str(cycle)],
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 77)
        self.assertIn("blocked_live_switch", result.stdout)

    def test_manual_or_live_enabled_run_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cycle = root / "cycle.sh"
            unit = root / "service.service"
            cycle.write_text("#!/bin/sh\n", encoding="ascii")
            cycle.chmod(0o700)
            unit.write_text("[Service]\n", encoding="ascii")
            proof = build_pilot_runtime_proof(
                cycle_path=cycle,
                service_unit_path=unit,
                environment={
                    "QOUNT_MINI_TREND_LIVE_ENABLE": "true",
                    "QOUNT_MINI_TREND_ARM_TOKEN": "secret",
                },
            )
        self.assertEqual(
            proof["diagnostics"]["verdict"], "blocked_independent_runtime"
        )
        self.assertFalse(validate_pilot_runtime_proof(proof))
        self.assertIn("systemd_invocation_present", proof["diagnostics"]["blockers"])
        self.assertIn("arm_token_absent", proof["diagnostics"]["blockers"])


if __name__ == "__main__":
    unittest.main()
