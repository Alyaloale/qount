#!/usr/bin/env python3
"""Replay a verified legacy NotificationStore into the canonical store."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.notifications.migration import (  # noqa: E402
    replay_verified_notification_store,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--result-path", type=Path)
    args = parser.parse_args()
    result = replay_verified_notification_store(
        args.source.resolve(),
        args.target.resolve(),
        imported_at=dt.datetime.now(dt.timezone.utc).isoformat(),
    )
    raw = json.dumps(result, ensure_ascii=True, sort_keys=True) + "\n"
    if args.result_path is not None:
        args.result_path.parent.mkdir(parents=True, exist_ok=True)
        args.result_path.write_text(raw, encoding="ascii")
        args.result_path.chmod(0o600)
    print(raw, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
