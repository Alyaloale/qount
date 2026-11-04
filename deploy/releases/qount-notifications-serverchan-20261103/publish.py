#!/usr/bin/env python3
"""ServerChan notification channel release: provider, v3 producer, retry units.

Runs ON the VPS as root from the release directory.  Owner decision recorded in
docs/current.md (2026-11-03): replace the personal-bot WeChat channel with
ServerChan service-account pushes; exception alerts immediate, one daily
receipt summary per signal date.

Payloads:
* serverchan.py          new provider (SendKey API, no conversation window)
* v3_notifications.py    v3 receipt/HALT observer -> AlertEvent enqueue
* run_v3_notifications.py  ExecStopPost entry (enqueue + optional --deliver)
* run_notification_retry.py  extended with --channel serverchan
* notifications/__init__.py  exports
* qount-serverchan-retry.{service,timer}  5-minute delivery retry backstop
* qount-g20-v3-live.service  ExecStopPost notify hook + store write access

  publish.py            install files, arm the retry timer; v3 timer untouched
  publish.py --rollback restore previous files and disarm the new timer

The v3 timer is never restarted.  The SendKey credential is NOT part of this
release: the owner installs it separately at
/etc/qount/notifications/serverchan-sendkey (0600 root, parent 0700 root).
No credentials are read, copied or written by this script.
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
CRED_DIR = Path("/etc/qount/notifications")

NEW_FILES = {
    "serverchan.py": ROOT / "src/qount/notifications/serverchan.py",
    "v3_notifications.py": ROOT / "src/qount/operations/v3_notifications.py",
    "run_v3_notifications.py": ROOT / "scripts/operations/run_v3_notifications.py",
    "run_notification_retry.py": ROOT / "scripts/operations/run_notification_retry.py",
    "notifications_init.py": ROOT / "src/qount/notifications/__init__.py",
    "qount-serverchan-retry.service": UNITS / "qount-serverchan-retry.service",
    "qount-serverchan-retry.timer": UNITS / "qount-serverchan-retry.timer",
    "qount-g20-v3-live.service": UNITS / "qount-g20-v3-live.service",
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
    CRED_DIR.mkdir(parents=True, exist_ok=True)
    CRED_DIR.chmod(0o700)
    run("systemctl", "daemon-reload")
    run("systemctl", "enable", "--now", "qount-serverchan-retry.timer")
    release = dict(release="qount-notifications-serverchan-20261103", backup=backup,
                   installed={name: sha(target) for name, target in NEW_FILES.items()})
    (RELEASE / "release.json").write_text(json.dumps(release, indent=2) + "\n")
    print(json.dumps({"published": True, "serverchan_timer": "enabled",
                      "credential_dir": str(CRED_DIR)}, indent=2))


def rollback() -> None:
    release = json.loads((RELEASE / "release.json").read_text())
    run("systemctl", "disable", "--now", "qount-serverchan-retry.timer")
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
