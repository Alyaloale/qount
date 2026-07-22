from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from qount.halt import observe_halt_state
from qount.halt import archive_halt_observations
from qount.halt.contracts import HaltEvent


class ObserveHaltStateTest(unittest.TestCase):
    def test_no_halt_no_issues_returns_empty(self) -> None:
        events = observe_halt_state(
            halt_path=None,
            unknown_order_count=0,
            reconciliation_halt_required=False,
            reconciliation_passed=True,
            data_quality_blockers=0,
            observed_at="2026-07-23T00:00:00+00:00",
        )
        self.assertEqual(len(events), 0)

    def test_halt_file_classified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            halt_path = Path(tmp) / "HALT"
            halt_path.write_text("pilot_drawdown_halt\n", encoding="ascii")
            events = observe_halt_state(
                halt_path=str(halt_path),
                unknown_order_count=0,
                reconciliation_halt_required=False,
                reconciliation_passed=True,
                data_quality_blockers=0,
                observed_at="2026-07-23T00:00:00+00:00",
            )
            self.assertTrue(len(events) >= 1)
            drawdown_event = next(
                e for e in events if e.reason == "pilot_drawdown_halt"
            )
            self.assertEqual(drawdown_event.halt_type, "portfolio")
            self.assertEqual(drawdown_event.scope, "full_account")

    def test_unknown_orders_classified(self) -> None:
        events = observe_halt_state(
            halt_path=None,
            unknown_order_count=2,
            reconciliation_halt_required=False,
            reconciliation_passed=None,
            data_quality_blockers=0,
            observed_at="2026-07-23T00:00:00+00:00",
        )
        self.assertTrue(len(events) >= 1)
        unknown_events = [e for e in events if e.unknown_unresolved]
        self.assertTrue(len(unknown_events) >= 1)

    def test_reconciliation_halt_classified(self) -> None:
        events = observe_halt_state(
            halt_path=None,
            unknown_order_count=0,
            reconciliation_halt_required=True,
            reconciliation_passed=False,
            data_quality_blockers=0,
            observed_at="2026-07-23T00:00:00+00:00",
        )
        self.assertTrue(len(events) >= 1)

    def test_does_not_modify_halt_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            halt_path = Path(tmp) / "HALT"
            original_content = "pilot_risk_halt\n"
            halt_path.write_text(original_content, encoding="ascii")
            observe_halt_state(
                halt_path=str(halt_path),
                unknown_order_count=0,
                reconciliation_halt_required=False,
                reconciliation_passed=True,
                data_quality_blockers=0,
                observed_at="2026-07-23T00:00:00+00:00",
            )
            self.assertEqual(
                halt_path.read_text(encoding="ascii"),
                original_content,
            )

    def test_all_events_are_bypass_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            halt_path = Path(tmp) / "HALT"
            halt_path.write_text("pilot_drawdown_halt\n", encoding="ascii")
            events = observe_halt_state(
                halt_path=str(halt_path),
                unknown_order_count=1,
                reconciliation_halt_required=False,
                reconciliation_passed=None,
                data_quality_blockers=0,
                observed_at="2026-07-23T00:00:00+00:00",
            )
            for event in events:
                self.assertTrue(event.bypass_mode)
                self.assertTrue(event.risk_increase_frozen)
                self.assertTrue(event.recovery_requires_owner_auth)
                self.assertTrue(event.recovery_requires_dual_diff)


class ArchiveHaltObservationsTest(unittest.TestCase):
    def test_archive_creates_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive_dir = Path(tmp) / "halt_obs"
            events = observe_halt_state(
                halt_path=None,
                unknown_order_count=1,
                reconciliation_halt_required=False,
                reconciliation_passed=None,
                data_quality_blockers=0,
                observed_at="2026-07-23T00:00:00+00:00",
                archive_dir=str(archive_dir),
            )
            self.assertTrue(len(events) >= 1)
            files = list(archive_dir.glob("*.json"))
            self.assertEqual(len(files), 1)
            data = json.loads(files[0].read_text(encoding="ascii"))
            self.assertTrue(data["bypass_mode"])
            self.assertEqual(data["event_count"], len(events))
            self.assertEqual(len(data["events"]), len(events))

    def test_archive_no_events_no_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive_dir = Path(tmp) / "halt_obs"
            events = observe_halt_state(
                halt_path=None,
                unknown_order_count=0,
                reconciliation_halt_required=False,
                reconciliation_passed=True,
                data_quality_blockers=0,
                observed_at="2026-07-23T00:00:00+00:00",
                archive_dir=str(archive_dir),
            )
            self.assertEqual(len(events), 0)
            files = list(archive_dir.glob("*.json"))
            self.assertEqual(len(files), 0)


if __name__ == "__main__":
    unittest.main()
