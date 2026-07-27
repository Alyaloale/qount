from __future__ import annotations

import json
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

    def test_forward_cycle_preserves_observation_when_free_balance_is_low(self) -> None:
        cycle = (
            ROOT / "scripts" / "desktop" / "mini_trend_um_forward_cycle.sh"
        ).read_text(encoding="ascii")

        self.assertIn('CAPITAL_USDT="100.00000000"', cycle)
        self.assertNotIn("assert v >= 100", cycle)
        self.assertIn('--preflight-path "$PREFLIGHT_PATH"', cycle)
        self.assertIn('write_authority_bundle.py', cycle)

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
        self.assertIn("current_decision_status", cycle)
        self.assertIn("executed|missing)", cycle)
        self.assertIn("new) ;;", cycle)
        self.assertIn("duplicate_decision_noop", cycle)
        self.assertIn("--standard-production-root", cycle)
        self.assertIn("QOUNT_BASE_STANDARD_PRODUCTION_ROOT", service)
        self.assertIn("Base standard-production", service)
        self.assertIn("await_latest_completed_pilot_bar", cycle)
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
        self.assertIn("natural-fill observer", timer)

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

    def test_live_cycle_treats_missing_latest_bar_as_order_free_wait(self) -> None:
        cycle = ROOT / "scripts" / "desktop" / "mini_trend_um_live_cycle.sh"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            state = root / "state"
            run = state / "forward" / "runs" / "20260722T120000Z"
            arm = state / "arm" / "manual-final-arm.json"
            live_env = root / "config" / "mini-trend-live.env"
            fake_bin = root / "bin"
            fake_repo = root / "repo"
            fake_scripts = fake_repo / "scripts" / "desktop"
            fake_scripts.mkdir(parents=True)
            (fake_repo / "src").symlink_to(ROOT / "src", target_is_directory=True)
            arm.parent.mkdir(parents=True)
            live_env.parent.mkdir(parents=True)
            fake_bin.mkdir()
            fake_stat = fake_bin / "stat"
            fake_stat.write_text(
                "#!/bin/sh\n"
                "if [ \"$2\" = '%a:%u' ]; then\n"
                "  printf '600:%s\\n' \"$(id -u)\"\n"
                "else\n"
                "  printf '700\\n'\n"
                "fi\n",
                encoding="ascii",
            )
            fake_stat.chmod(0o700)
            fake_flock = fake_bin / "flock"
            fake_flock.write_text("#!/bin/sh\nexit 0\n", encoding="ascii")
            fake_flock.chmod(0o700)
            fake_forward = fake_scripts / "mini_trend_um_forward_cycle.sh"
            fake_forward.write_text(
                "#!/bin/bash\n"
                "set -euo pipefail\n"
                f"mkdir -p '{run}'\n"
                f"printf '%s\\n' '"
                + json.dumps(
                    {
                        "diagnostics": {
                            "verdict": "await_latest_completed_pilot_bar"
                        },
                        "decision": None,
                    },
                    separators=(",", ":"),
                )
                + f"' >'{run / 'latest_projection.json'}'\n"
                f"ln -sfn 'runs/{run.name}' '{state / 'forward' / 'latest'}'\n",
                encoding="ascii",
            )
            fake_forward.chmod(0o700)
            arm.write_text('{"arm_id":"test-arm"}\n', encoding="ascii")
            arm.chmod(0o600)
            live_env.write_text("# test-only\n", encoding="ascii")
            live_env.chmod(0o600)
            env = os.environ.copy()
            env.update(
                {
                    "QOUNT_PROJECT_ROOT": str(fake_repo),
                    "QOUNT_PYTHON_BIN": str(ROOT / ".venv" / "bin" / "python"),
                    "QOUNT_MINI_TREND_STATE_ROOT": str(state),
                    "QOUNT_MINI_TREND_ARM_PATH": str(arm),
                    "QOUNT_MINI_TREND_LIVE_ENV_PATH": str(live_env),
                    "QOUNT_MINI_TREND_LIVE_ENABLE": "true",
                    "QOUNT_MINI_TREND_LIVE_CONFIRMATION": "test-arm",
                    "QOUNT_MINI_TREND_ARM_TOKEN": "test-token",
                    "PATH": f"{fake_bin}:{env['PATH']}",
                }
            )
            result = subprocess.run(
                ["/bin/bash", str(cycle)],
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("await_latest_completed_pilot_bar", result.stdout)
        self.assertNotIn("blocked_missing_decision", result.stdout)

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
