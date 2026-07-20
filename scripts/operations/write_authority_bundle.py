#!/usr/bin/env python3
"""Translate one order-free MiniTrend run into standard authority artifacts."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Sequence

from qount.operations.authority_writer import AuthorityWriterConfig
from qount.operations.authority_writer import AuthorityWriterError
from qount.operations.authority_writer import write_order_free_authority_bundle


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Write a complete order-free Dashboard authority bundle."
    )
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--authority-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--backup-root", type=Path, required=True)
    parser.add_argument("--dashboard-root", type=Path, required=True)
    parser.add_argument("--lock-path", type=Path, required=True)
    parser.add_argument("--target-stress-loss-fraction", type=float, default=0.01)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = AuthorityWriterConfig(
        repo_root=args.repo_root,
        source_root=args.source_root,
        authority_root=args.authority_root,
        runtime_root=args.runtime_root,
        backup_root=args.backup_root,
        dashboard_root=args.dashboard_root,
        lock_path=args.lock_path,
        target_stress_loss_fraction=args.target_stress_loss_fraction,
    )
    try:
        result = write_order_free_authority_bundle(
            config,
            captured_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        )
    except (OSError, TypeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                ensure_ascii=True,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result.as_dict(), ensure_ascii=True, sort_keys=True))
    return 0 if result.status == "written" else 75


if __name__ == "__main__":
    raise SystemExit(main())
