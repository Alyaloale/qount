from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from qount.shadow_accounting.progress import record_phase_b_cycle


def _results(
    state_dir: Path,
    *,
    valid: bool,
    cycle: str,
) -> dict:
    run_dir = state_dir / "shadow_accounting" / "runs" / cycle
    run_dir.mkdir(parents=True, exist_ok=True)
    shadow = {
        "run_id": cycle,
        "has_blocking_diff": not valid,
        "unknown_income_count": 0,
        "run_dir": str(run_dir),
        "watermark_hash": "a" * 64,
    }
    (run_dir / "shadow_run.json").write_text(
        json.dumps(shadow), encoding="ascii"
    )
    return {
        "mode": "all",
        "started_at": f"2026-07-{cycle}T00:00:00+00:00",
        "completed_at": f"2026-07-{cycle}T00:00:01+00:00",
        "symbols": ["BTCUSDT", "ETHUSDT", "BNBUSDT"],
        "shadow": shadow,
        "venue": {
            "compatibility": "pass" if valid else "blocked",
            "blockers": [] if valid else ["fixture_block"],
        },
        "halt": {"event_count": 0 if valid else 1, "halt_types": []},
    }


class PhaseBProgressTest(unittest.TestCase):
    def test_valid_streak_and_remaining_observations_do_not_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = record_phase_b_cycle(
                root,
                _results(root, valid=True, cycle="01"),
                observation_target=3,
            )
            self.assertEqual(first["valid_streak"], 1)
            self.assertEqual(first["remaining_observation_cycles"], 2)
            self.assertFalse(first["blocks_local_progress"])
            self.assertFalse(first["blocks_research"])
            self.assertFalse(first["blocks_allocator_development"])
            second = record_phase_b_cycle(
                root,
                _results(root, valid=False, cycle="02"),
                observation_target=3,
            )
            self.assertEqual(second["valid_streak"], 0)
            third = record_phase_b_cycle(
                root,
                _results(root, valid=True, cycle="03"),
                observation_target=3,
            )
            self.assertEqual(third["valid_streak"], 1)
            self.assertFalse(third["observation_target_reached"])
            self.assertEqual(third["invalid_cycle_count"], 1)

    def test_observation_milestone_is_created_without_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = record_phase_b_cycle(
                root,
                _results(root, valid=True, cycle="11"),
                observation_target=1,
            )
            self.assertTrue(first["observation_target_reached"])
            milestone_files = list((root / "milestones").glob("*.json"))
            self.assertEqual(len(milestone_files), 1)
            self.assertFalse((root / "exit").exists())
            self.assertNotIn("exit_gate_passed", first)
            self.assertFalse(first["orders_authorized"])
            self.assertFalse(first["automatic_authority_change"])
            self.assertEqual(first["authority_effect"], "none")

    def test_real_trade_coverage_is_reported_from_archive_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "shadow_accounting" / "runs" / "12"
            run_dir.mkdir(parents=True)
            shadow = {
                "run_id": "12",
                "has_blocking_diff": False,
                "unknown_income_count": 0,
                "run_dir": str(run_dir),
                "watermark_hash": "a" * 64,
            }
            (run_dir / "shadow_run.json").write_text(
                json.dumps(shadow), encoding="ascii"
            )
            (run_dir / "archive_manifest.json").write_text(
                json.dumps(
                    {"files": {"trades.jsonl": {"record_count": 2}}}
                ),
                encoding="ascii",
            )
            result = record_phase_b_cycle(
                root,
                {
                    "mode": "all",
                    "started_at": "2026-07-12T00:00:00+00:00",
                    "completed_at": "2026-07-12T00:00:01+00:00",
                    "symbols": ["BTCUSDT"],
                    "shadow": shadow,
                    "venue": {"compatibility": "pass", "blockers": []},
                    "halt": {"event_count": 0, "halt_types": []},
                },
                observation_target=1,
            )
            self.assertTrue(result["real_trade_coverage"]["available"])
            self.assertEqual(
                result["real_trade_coverage"]["trade_record_count"], 2
            )

    def test_real_trade_coverage_remains_true_after_later_empty_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = record_phase_b_cycle(
                root,
                _results(root, valid=True, cycle="21"),
                observation_target=3,
            )
            self.assertFalse(first["has_real_trade_coverage"])
            run_dir = root / "shadow_accounting" / "runs" / "22"
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "archive_manifest.json").write_text(
                json.dumps({"files": {"trades.jsonl": {"record_count": 1}}}),
                encoding="ascii",
            )
            traded = record_phase_b_cycle(
                root,
                {
                    **_results(root, valid=True, cycle="22"),
                    "shadow": {
                        **_results(root, valid=True, cycle="22")["shadow"],
                        "run_dir": str(run_dir),
                    },
                },
                observation_target=3,
            )
            self.assertTrue(traded["has_real_trade_coverage"])
            empty = record_phase_b_cycle(
                root,
                _results(root, valid=True, cycle="23"),
                observation_target=3,
            )
            self.assertTrue(empty["has_real_trade_coverage"])

    def test_tampered_cycle_is_rejected_before_exit_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record_phase_b_cycle(
                root,
                _results(root, valid=True, cycle="31"),
                observation_target=3,
            )
            cycle_path = next((root / "cycles").glob("*.json"))
            payload = json.loads(cycle_path.read_text(encoding="ascii"))
            payload["valid"] = False
            cycle_path.write_text(json.dumps(payload), encoding="ascii")
            with self.assertRaisesRegex(ValueError, "cycle_tampered"):
                record_phase_b_cycle(
                    root,
                    _results(root, valid=True, cycle="32"),
                    observation_target=3,
                )

    def test_schema_v1_keyword_is_only_an_observation_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = record_phase_b_cycle(
                root,
                _results(root, valid=True, cycle="41"),
                required_valid_streak=2,
            )
            self.assertEqual(result["observation_target"], 2)
            self.assertFalse(result["observation_target_reached"])
            self.assertFalse(result["blocks_local_progress"])


if __name__ == "__main__":
    unittest.main()
