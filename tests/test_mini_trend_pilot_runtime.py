from __future__ import annotations

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
