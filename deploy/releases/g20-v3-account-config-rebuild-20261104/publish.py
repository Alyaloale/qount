#!/usr/bin/env python3
"""G20-LP v3 account-config hardening + owner-directed rebuild tooling.

Runs ON the VPS as root from the release directory.  Incident (2026-11-04):
the XRPUSDT leg was liquidated 11 minutes after entry on a leftover 100x
isolated account setting (0.08U margin behind a 7.9U leg); the owner then
flattened the wallet and directed a rebuild after the fixes.

Payloads:
* g20_v3_live.py: executed cycles normalize account config first (cross
  margin, EXECUTION_LEVERAGE=3 per-symbol margin setting, owner choice
  2026-11-04) and block when any isolated leg sits within 30% of its
  liquidation price.  -4046/-4048 margin-type answers are tolerated.
* rebuild_g20_v3_position.py: one-off owner-directed rebuild that reuses the
  idempotent execution stack with a distinct order identity ("...R") because
  the daily executor reconciles same-signal-date claims instead of ordering.
* test_g20_v3_live.py: five new tests for the config guard.

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
    "g20_v3_live.py": ROOT / "src/qount/execution/g20_v3_live.py",
    "rebuild_g20_v3_position.py": ROOT / "scripts/operations/rebuild_g20_v3_position.py",
    "test_g20_v3_live.py": ROOT / "tests/test_g20_v3_live.py",
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
    release = dict(release="g20-v3-account-config-rebuild-20261104", backup=backup,
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
