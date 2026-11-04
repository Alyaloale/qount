#!/usr/bin/env python3
"""G20-LP v3 fill-time fix: accept raw Binance decimal-string timestamps.

Runs ON the VPS as root from the release directory.  Incident: the catch-up
live cycle (2026-11-04 03:59 UTC, signal day 2026-11-03) placed SOLUSDT and
then aborted with input_or_exchange_error:ExecutionContractError, blocking the
remaining 10 legs.  Root cause: fapiPrivateGetUserTrades returns every numeric
field as a decimal string; _time() only accepted int/float epoch millis and
ISO strings, so datetime.fromisoformat misread "1793764749308" as an ISO date
(fill_time_missing_or_invalid) while collecting fills for the SOLUSDT order.

Fix: _time() coerces all-digit strings to epoch milliseconds before the
existing int/float path.  Covered by
tests/test_binance_usdm_execution.py::test_raw_binance_usertrades_string_timestamps.

  publish.py            install files; timer stays armed
  publish.py --rollback restore previous files

The timer is never restarted by this script.  No credentials are read,
copied or written by this script.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

RELEASE = Path(__file__).resolve().parent
PAYLOAD = RELEASE / "payloads"
BEFORE = RELEASE / "before"
ROOT = Path("/root/qount")

NEW_FILES = {
    "binance_usdm.py": ROOT / "src/qount/execution/binance_usdm.py",
    "test_binance_usdm_execution.py": ROOT / "tests/test_binance_usdm_execution.py",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(*cmd: str) -> None:
    subprocess.run(cmd, check=True)


def publish() -> None:
    if not ROOT.is_dir():
        raise SystemExit("root_checkout_missing")
    BEFORE.mkdir(exist_ok=True)
    backup = {"files": {}}
    for name, target in NEW_FILES.items():
        if target.exists():
            shutil.copy2(target, BEFORE / name)
            backup["files"][str(target)] = sha(target)
    for name, target in NEW_FILES.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PAYLOAD / name, target)
    run("systemctl", "daemon-reload")
    release = dict(release="g20-v3-fill-time-fix-20261104", backup=backup,
                   installed={name: sha(target) for name, target in NEW_FILES.items()})
    (RELEASE / "release.json").write_text(json.dumps(release, indent=2) + "\n")
    print(json.dumps({"published": True,
                      "installed": release["installed"]}, indent=2))


def rollback() -> None:
    release = json.loads((RELEASE / "release.json").read_text())
    for name, target in NEW_FILES.items():
        saved = BEFORE / name
        if saved.exists():
            shutil.copy2(saved, target)
    run("systemctl", "daemon-reload")
    print(json.dumps({"rolled_back": True,
                      "restored": release["backup"]["files"]}, indent=2))


if __name__ == "__main__":
    if "--rollback" in sys.argv:
        rollback()
    else:
        publish()
