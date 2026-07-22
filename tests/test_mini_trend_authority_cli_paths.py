from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    path = ROOT / "scripts" / "desktop" / name
    spec = importlib.util.spec_from_file_location(f"test_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load script: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _authority_paths(root: Path) -> dict[str, str]:
    return {
        "authority_root": str(root / "authority"),
        "runtime_root": str(root / "runtime"),
        "backup_root": str(root / "backups"),
        "dashboard_root": str(root / "dashboard"),
        "authority_lock_path": str(root / "locks" / "publisher.lock"),
        "notification_store": str(root / "notifications" / "store.sqlite3"),
    }


class MiniTrendAuthorityCliPathsTest(unittest.TestCase):
    def _selector(self, root: Path) -> Path:
        run_dir = root / "forward" / "runs" / "20260722T052621Z"
        run_dir.mkdir(parents=True)
        run_dir.chmod(0o700)
        selector = root / "forward" / "latest"
        selector.symlink_to(run_dir, target_is_directory=True)
        return selector

    def test_arm_preserves_authority_source_selector_symlink(self) -> None:
        module = _load_script("mini_trend_um_arm.py")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selector = self._selector(root)
            readiness = root / "readiness.json"
            readiness.write_text("{}\n", encoding="ascii")
            output = root / "arm" / "manual-final-arm.json"
            payload = {
                "arm_id": "arm-test",
                "readiness_hash": "a" * 64,
            }
            promotion = types.SimpleNamespace(authority_hash="b" * 64)
            paths = _authority_paths(root)
            argv = [
                "--readiness-path",
                str(readiness),
                "--confirm-readiness-hash",
                "a" * 64,
                "--output-path",
                str(output),
                "--authority-root",
                paths["authority_root"],
                "--authority-source-root",
                str(selector),
                "--runtime-root",
                paths["runtime_root"],
                "--backup-root",
                paths["backup_root"],
                "--dashboard-root",
                paths["dashboard_root"],
                "--authority-lock-path",
                paths["authority_lock_path"],
                "--notification-store",
                paths["notification_store"],
            ]
            with (
                mock.patch.dict(os.environ, {"QOUNT_MINI_TREND_ARM_TOKEN": "secret"}),
                mock.patch.object(module, "build_manual_arm", return_value=payload),
                mock.patch.object(
                    module,
                    "authorize_minimal_live_authority_bundle",
                    return_value=promotion,
                ) as authorize,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(module.main(argv), 0)
            config = authorize.call_args.args[0]
            self.assertEqual(config.source_root, selector.absolute())
            self.assertTrue(config.source_root.is_symlink())

    def test_live_dispatch_preserves_selector_and_fails_on_refresh_error(self) -> None:
        module = _load_script("mini_trend_um_dispatch.py")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selector = self._selector(root)
            inputs = {}
            for name in ("preflight", "projection", "readiness", "rules"):
                path = root / f"{name}.json"
                path.write_text("{}\n", encoding="ascii")
                inputs[name] = str(path)
            paths = _authority_paths(root)
            output = root / "dispatch.json"
            argv = [
                "--mode",
                "live",
                "--preflight-path",
                inputs["preflight"],
                "--projection-path",
                inputs["projection"],
                "--readiness-path",
                inputs["readiness"],
                "--exchange-rules-path",
                inputs["rules"],
                "--journal-path",
                str(root / "journal.jsonl"),
                "--authority-root",
                paths["authority_root"],
                "--authority-source-root",
                str(selector),
                "--runtime-root",
                paths["runtime_root"],
                "--backup-root",
                paths["backup_root"],
                "--dashboard-root",
                paths["dashboard_root"],
                "--authority-lock-path",
                paths["authority_lock_path"],
                "--notification-store",
                paths["notification_store"],
                "--output-path",
                str(output),
            ]
            bundle = types.SimpleNamespace(batch={}, ledger_snapshot={}, registry={})
            dispatch = {"status": "completed", "exchange_mutation_attempted": False}
            artifact = {
                "artifact_path": str(output),
                "diagnostics": {"verdict": "live_dispatch_ready"},
                "dispatch_result": dispatch,
                "market_orders": [],
                "stop_orders": [],
                "meta": {"live_orders_allowed": True},
            }
            with (
                mock.patch.object(module.Settings, "from_env", return_value=object()),
                mock.patch.object(module, "read_vps_authority_bundle", return_value=bundle),
                mock.patch.object(module, "RuntimeLedger"),
                mock.patch.object(module, "fetch_pilot_dispatch_snapshot", return_value={}),
                mock.patch.object(module, "verify_dispatch_journal", return_value={}),
                mock.patch.object(module, "build_pilot_dispatch_plan", return_value={}),
                mock.patch.object(module, "run_pilot_dispatch", return_value=dispatch),
                mock.patch.object(
                    module,
                    "refresh_authority_bundle_from_runtime",
                    side_effect=ValueError("refresh failed"),
                ) as refresh,
                mock.patch.object(
                    module, "write_pilot_dispatch_artifact", return_value=artifact
                ),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(module.main(argv), 2)
            config = refresh.call_args.args[0]
            self.assertEqual(config.source_root, selector.absolute())
            self.assertTrue(config.source_root.is_symlink())
            self.assertIn("authority_refresh_error", dispatch)


if __name__ == "__main__":
    unittest.main()
