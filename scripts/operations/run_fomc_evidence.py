#!/usr/bin/env python3
"""Freeze FOMC replay evidence and create a credential-free local backup."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Sequence

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.small_account.fomc_evidence import create_fomc_evidence_backup  # noqa: E402
from qount.small_account.fomc_evidence import finalize_fomc_event_bundle  # noqa: E402
from qount.small_account.fomc_live import FomcLiveStore  # noqa: E402
from qount.small_account.fomc_watcher import FomcStateStore  # noqa: E402
from qount.small_account.fomc_watcher import load_fomc_event_definition  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-config", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--backup-root", type=Path, required=True)
    parser.add_argument("--release-provenance-path", type=Path)
    parser.add_argument("--observed-at", help="UTC override for deterministic verification.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    event = load_fomc_event_definition(args.event_config)
    observed_at = args.observed_at or dt.datetime.now(dt.timezone.utc)
    state_store = FomcStateStore(args.state_root, event.event_id)
    live_store = FomcLiveStore(args.state_root, event.event_id)
    with live_store.cycle_lock():
        bundle = finalize_fomc_event_bundle(
            event,
            state_store,
            live_store,
            event_config_path=args.event_config,
            release_provenance_path=args.release_provenance_path,
            finalized_at=observed_at,
        )
    backup = create_fomc_evidence_backup(
        event,
        state_root=args.state_root,
        backup_root=args.backup_root,
        completed_at=observed_at,
    )
    print(
        json.dumps(
            {
                "event_id": event.event_id,
                "final_bundle_id": bundle.get("bundle_id") if bundle else None,
                "backup_id": backup["backup_id"],
                "backup_file_count": backup["file_count"],
                "sensitive_paths_excluded": backup["sensitive_paths_excluded"],
            },
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
