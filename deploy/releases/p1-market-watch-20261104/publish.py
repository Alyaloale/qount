#!/usr/bin/env python3
"""P1 real-time market watch layer for the read-only dashboard frontend.

  publish.py            install static frontend files (no service restart)
  publish.py --rollback restore previous static files (no service restart)

Context: /account/history (1.81MB) and /account/performance (1.77MB) built
multi-MB JSON per 5-minute refresh and pushed qount-api.service past its
MemoryHigh=192M limit (2026-11-04 hang, see 96-memguard-20261104.conf).
This release downsamples chart output server-side (1h buckets <=90d, 6h
<=365d; wallet-scope and segment anchors always kept; raw observation counts
and every computed summary value unchanged) and adds client-side
stale-while-revalidate caching in app.js.

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
    "market.js": ROOT / "web/app/market.js",
    "app.js": ROOT / "web/app/app.js",
    "index.html": ROOT / "web/app/index.html",
    "market.test.cjs": ROOT / "tests/frontend/market.test.cjs",
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
    release = dict(release="p1-market-watch-20261104", backup=backup,
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
    print(json.dumps({"rolled_back": True,
                      "restored": release["backup"]["files"]}, indent=2))


if __name__ == "__main__":
    if "--rollback" in sys.argv:
        rollback()
    else:
        publish()
