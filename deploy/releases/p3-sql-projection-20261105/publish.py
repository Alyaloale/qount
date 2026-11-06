#!/usr/bin/env python3
"""P3 SQL-side projection for the read-only dashboard API (memory-hang cure).

  publish.py            install files and restart the read-only API
  publish.py --rollback restore previous files and restart the read-only API

Context: P2 (2026-11-04) downsamples chart OUTPUT, but read_asset_history and
read_account_performance still fetchall() every raw snapshot payload and
json.loads() it in Python before downsampling.  One 5-minute frontend refresh
cycle (history 30/90/365 + performance) allocated ~66MB per cycle; Python
arenas are never returned to the OS, so RSS ratcheted 221MB -> 353MB in one
day, crossed MemoryHigh (2026-11-05 06:xx UTC hang; same failure as 2026-11-04)
and the memcg throttle stalled the event loop: every endpoint, including the
static frontend files, stopped responding.

This release pushes field extraction into SQLite (JSON1 json_type/json_extract)
and streams the cursor, so full snapshot payloads never accumulate in Python.
Measured peak Python allocation per call (6000-observation DB): history
16.3MB -> 3.9MB, performance load 43.1MB -> 4.3MB.  Output JSON, downsampling
semantics, summary values and raw observation counts are unchanged (locked by
the existing test suites plus two new projection-semantics regression tests).
Requires SQLite >= 3.38 with JSON1 (verified: Mac 3.50.4, VPS 3.40.1).

Incident-day stopgap already applied (kept by this release): MemoryHigh/MemoryMax
raised 288M/448M -> 512M/768M in 96-memguard-20261104.conf and via
`systemctl set-property` (revert by editing back / removing the drop-in).

Only the read-only API service is restarted.  Timers, trading services,
Caddy, credentials and databases are untouched.
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
    "account_assets.py": ROOT / "src/qount/operations/account_assets.py",
    "account_performance.py": ROOT / "src/qount/operations/account_performance.py",
    "test_account_assets.py": ROOT / "tests/test_account_assets.py",
    "test_account_performance.py": ROOT / "tests/test_account_performance.py",
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
    run("systemctl", "restart", "qount-api.service")
    release = dict(release="p3-sql-projection-20261105", backup=backup,
                   installed={name: sha(target) for name, target in NEW_FILES.items()},
                   payload={name: sha(PAYLOAD / name) for name in NEW_FILES})
    (RELEASE / "release.json").write_text(json.dumps(release, indent=2) + "\n")
    print(json.dumps({"published": True, "installed": release["installed"]}, indent=2))


def rollback() -> None:
    release = json.loads((RELEASE / "release.json").read_text())
    for name, target in NEW_FILES.items():
        saved = BEFORE / name
        if saved.exists():
            shutil.copy2(saved, target)
    run("systemctl", "restart", "qount-api.service")
    print(json.dumps({"rolled_back": True,
                      "restored": release["backup"]["files"]}, indent=2))


if __name__ == "__main__":
    if "--rollback" in sys.argv:
        rollback()
    else:
        publish()
