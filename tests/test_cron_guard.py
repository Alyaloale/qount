from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
GUARD = REPO / "scripts" / "desktop" / "cron_guard.sh"
PRODUCTION_CRONTAB = REPO / "deploy" / "cron" / "qount-production.crontab"


class CronGuardTests(unittest.TestCase):
    def test_production_crontab_is_inert_until_explicit_authorization(self) -> None:
        text = PRODUCTION_CRONTAB.read_text()
        active = [
            line
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertEqual(active, [])
        self.assertEqual(text.count("/usr/bin/flock -n"), 2)
        self.assertEqual(text.count("/usr/bin/timeout"), 2)
        self.assertNotIn("/run/lock/qount/", text)
        self.assertIn("DISABLED: */5 * * * * QOUNT_CXD_CAPITAL=auto", text)
        self.assertNotIn("cxd_publish_cron.sh", text)
        self.assertNotIn("*/2 * * * *", text)

    def _fixture(self, root: Path) -> tuple[Path, dict[str, str], Path, Path]:
        log = root / "job.log"
        body = root / "body.log"
        script = root / "job.sh"
        script.write_text(
            "#!/bin/bash\n"
            "set -u\n"
            f"source {str(GUARD)!r}\n"
            "qount_cron_guard \"$0\" test-job 5 \"$LOG\" \"$@\"\n"
            "printf 'ran\\n' >> \"$BODY\"\n"
        )

        timeout_bin = root / "timeout"
        timeout_bin.write_text(
            "#!/bin/bash\n"
            "if [ \"${FAKE_TIMEOUT_RESULT:-0}\" != 0 ]; then exit \"$FAKE_TIMEOUT_RESULT\"; fi\n"
            "while [ \"$#\" -gt 0 ]; do\n"
            "  case \"$1\" in --signal=*|--kill-after=*) shift ;; *s) shift; break ;; *) exit 64 ;; esac\n"
            "done\n"
            "exec \"$@\"\n"
        )
        flock_bin = root / "flock"
        flock_bin.write_text("#!/bin/bash\nexit \"${FAKE_FLOCK_RESULT:-0}\"\n")
        timeout_bin.chmod(0o755)
        flock_bin.chmod(0o755)

        env = os.environ.copy()
        env.update(
            {
                "LOG": str(log),
                "BODY": str(body),
                "QOUNT_TIMEOUT_BIN": str(timeout_bin),
                "QOUNT_FLOCK_BIN": str(flock_bin),
                "QOUNT_CRON_LOCK_DIR": str(root / "locks"),
            }
        )
        return script, env, log, body

    def test_outer_timeout_wrapper_reexecutes_and_runs_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script, env, _log, body = self._fixture(Path(tmp))
            result = subprocess.run(["/bin/bash", str(script)], env=env, check=False)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(body.read_text(), "ran\n")

    def test_busy_lock_skips_without_running_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script, env, log, body = self._fixture(Path(tmp))
            env["QOUNT_CRON_GUARDED_JOB"] = "test-job"
            env["FAKE_FLOCK_RESULT"] = "1"
            result = subprocess.run(["/bin/bash", str(script)], env=env, check=False)
            self.assertEqual(result.returncode, 0)
            self.assertFalse(body.exists())
            self.assertIn("previous run still active", log.read_text())

    def test_timeout_is_logged_and_propagated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script, env, log, body = self._fixture(Path(tmp))
            env["FAKE_TIMEOUT_RESULT"] = "124"
            result = subprocess.run(["/bin/bash", str(script)], env=env, check=False)
            self.assertEqual(result.returncode, 124)
            self.assertFalse(body.exists())
            self.assertIn("exceeded 5s runtime limit", log.read_text())


if __name__ == "__main__":
    unittest.main()
