#!/usr/bin/env python3
"""G20-LP v3 live authorization-gate fix: unit env override for the live gates.

Runs ON the VPS as root from the release directory.  Incident: the first live
cycle (2026-11-04 00:00:05 UTC) failed 3x with OrdersNotAuthorized and opened no
positions.  Root cause: systemd applies EnvironmentFile= after Environment=, and
the shared /root/qount/.env (2026-07-19) ships QOUNT_LIVE_ENABLE=false, silently
defeating the unit's Environment=QOUNT_LIVE_ENABLE=true dual-authorization gate.

Fix (no change to /root/qount/.env — shared by 7 services and holding keys):
* /etc/qount/g20-v3-live.env is loaded AFTER .env and re-asserts the two gates;
  among EnvironmentFile= files the later one wins.
* qount-g20-v3-live.service gains that EnvironmentFile= line after the .env one.

  publish.py            install files, daemon-reload; timer stays armed
  publish.py --rollback restore previous files and daemon-reload

The timer is never restarted by this script (a restart with Persistent=true
could fire a catch-up cycle at an arbitrary hour).  No credentials are read,
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
UNITS = Path("/etc/systemd/system")
ETC = Path("/etc/qount")

NEW_FILES = {
    "qount-g20-v3-live.service": UNITS / "qount-g20-v3-live.service",
    "g20-v3-live.env": ETC / "g20-v3-live.env",
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
        if name == "g20-v3-live.env":
            target.chmod(0o600)
    run("systemctl", "daemon-reload")
    release = dict(release="g20-v3-auth-gate-fix-20261104", backup=backup,
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
        elif name == "g20-v3-live.env" and target.exists():
            target.unlink()
    run("systemctl", "daemon-reload")
    print(json.dumps({"rolled_back": True,
                      "restored": release["backup"]["files"]}, indent=2))


if __name__ == "__main__":
    if "--rollback" in sys.argv:
        rollback()
    else:
        publish()
