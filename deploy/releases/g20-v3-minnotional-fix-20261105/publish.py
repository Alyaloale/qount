#!/usr/bin/env python3
"""G20-LP v3 min-notional fix: never zero an executable target; heal missing legs.

Runs ON the VPS as root from the release directory.  Incident (2026-11-05
00:00:05 UTC cycle, signal day 2026-11-04): the XAUUSDT leg target 8.0444U
floored to step 0.001 = 4.07U (< 5U min notional) was zeroed, and a healthy
0.002 (8.14U) position was CLOSED instead of held.  Two defects:

1. plan_legs: a target AT OR ABOVE min notional was set to 0 when the step
   floor landed in the dust zone, conflating it with cash semantics (target
   below min notional).  Fixed: such targets round UP to the smallest
   executable quantity (_desired_quantity).
2. breaches(): only iterated held legs, so a missing pool leg (100% drift
   from its executable target) never triggered the off-schedule resize that
   restores it.  Fixed: iterate the pool against the executable desired
   notional; cash-semantics legs breach only while a tradeable position is
   left.  The old test asserting an empty book is not a breach codified the
   gap and was rewritten.

Covered by tests/test_g20_v3_live.py: test_xau_rounding_dust_rounds_up_not_closes,
test_target_above_minimum_never_rounds_to_unexecutable,
test_breach_covers_missing_and_held_legs, test_breach_cash_leg_only_when_
tradeable_position_left, test_missing_leg_triggers_off_schedule_resize,
test_cycle_keeps_granular_leg_near_target.

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

RELEASE = Path(__file__).resolve().parent
PAYLOAD = RELEASE / "payloads"
BEFORE = RELEASE / "before"
ROOT = Path("/root/qount")

NEW_FILES = {
    "g20_v3_live.py": ROOT / "src/qount/execution/g20_v3_live.py",
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
    release = dict(release="g20-v3-minnotional-fix-20261105", backup=backup,
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
    import sys
    if "--rollback" in sys.argv:
        rollback()
    else:
        publish()
