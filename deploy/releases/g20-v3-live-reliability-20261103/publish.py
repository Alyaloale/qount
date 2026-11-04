#!/usr/bin/env python3
"""G20-LP v3 live reliability release: executor bug fix + unit retry hardening.

Runs ON the VPS as root from the release directory.  Owner authorization:
"先修复并发布" (2026-11-03, docs/current.md 运行核对记录本轮).

Payloads:
* g20_v3_live.py: positions outside the pool block the cycle explicitly
  (positions_outside_pool) instead of crashing on a KeyError in the drift
  check; breaches() only evaluates pool legs.
* qount-g20-v3-live.service: Restart=on-failure / RestartSec=15min with
  StartLimitIntervalSec=2h / StartLimitBurst=3 (aligned with the 2026-10-30
  paper-line reliability hardening).
* qount-g20-v3-live.timer: Persistent=true so a midnight outage catches the
  cycle up at boot instead of silently skipping it.

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

NEW_FILES = {
    "g20_v3_live.py": ROOT / "src/qount/execution/g20_v3_live.py",
    "qount-g20-v3-live.service": UNITS / "qount-g20-v3-live.service",
    "qount-g20-v3-live.timer": UNITS / "qount-g20-v3-live.timer",
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
    release = dict(release="g20-v3-live-reliability-20261103", backup=backup,
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
