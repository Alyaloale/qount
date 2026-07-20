#!/usr/bin/env python3
"""Print a read-only production publisher path audit as canonical JSON."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Sequence

from qount.operations import audit_publisher_paths


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify a VPS authority bundle and backup directory without writing "
            "files, installing units, or enabling timers."
        )
    )
    parser.add_argument("--authority-root", type=Path, required=True)
    parser.add_argument("--backup-root", type=Path, required=True)
    parser.add_argument(
        "--owner-authorized",
        action="store_true",
        help="Record explicit owner authorization without bypassing source gates.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = audit_publisher_paths(
        args.authority_root,
        args.backup_root,
        audited_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        owner_authorized=args.owner_authorized,
    )
    print(
        json.dumps(
            result.as_dict(),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0 if result.status == "ready_for_authorization" else 1


if __name__ == "__main__":
    raise SystemExit(main())
