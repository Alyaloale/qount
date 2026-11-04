#!/usr/bin/env python3
"""G20-LP v3 missed-cycle watchdog release: stale detection + hourly timer.

Runs ON the VPS as root from the release directory.  Owner request recorded in
docs/current.md (2026-11-03, next-goals item 2): alert when the v3 cycle
receipt goes stale (>30h) instead of a missed cycle only showing on the
frontend.

Payloads:
* v3_notifications.py      stale/waiting/missing state machine in the observer
* run_v3_notifications.py  docstring update (watchdog caller documented)
* qount-v3-watchdog.{service,timer}  hourly observe-only watchdog (no network)

  publish.py            install files, arm the watchdog timer
  publish.py --rollback restore previous files and disarm the watchdog timer

The v3 live timer is never restarted.  No credentials are read, copied or
written by this script.
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
UNITS = Path("/etc/systemd/system")

NEW_FILES = {
    "v3_notifications.py": ROOT / "src/qount/operations/v3_notifications.py",
    "run_v3_notifications.py": ROOT / "scripts/operations/run_v3_notifications.py",
    "qount-v3-watchdog.service": UNITS / "qount-v3-watchdog.service",
    "qount-v3-watchdog.timer": UNITS / "qount-v3-watchdog.timer",
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
    run("systemctl", "enable", "--now", "qount-v3-watchdog.timer")
    release = dict(release="qount-v3-watchdog-20261103", backup=backup,
                   installed={name: sha(target) for name, target in NEW_FILES.items()})
    (RELEASE / "release.json").write_text(json.dumps(release, indent=2) + "\n")
    print(json.dumps({"published": True, "watchdog_timer": "enabled"}, indent=2))


def rollback() -> None:
    release = json.loads((RELEASE / "release.json").read_text())
    run("systemctl", "disable", "--now", "qount-v3-watchdog.timer")
    for name, target in NEW_FILES.items():
        saved = BEFORE / name
        if saved.exists():
            shutil.copy2(saved, target)
        elif target.exists():
            target.unlink()
    run("systemctl", "daemon-reload")
    print(json.dumps({"rolled_back": True,
                      "restored": release["backup"]["files"]}, indent=2))


if __name__ == "__main__":
    if "--rollback" in sys.argv:
        rollback()
    else:
        publish()
