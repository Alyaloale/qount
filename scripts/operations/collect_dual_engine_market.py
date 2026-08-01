#!/usr/bin/env python3
"""Collect one scheduled public-data event and advance Dual-Engine paper state."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence

from qount.dual_engine import DualEngineMarketConfig
from qount.dual_engine import NoScheduledPaperEvent
from qount.dual_engine import collect_market_cycle
from qount.dual_engine import run_paper_cycle


def _read_object(path: Path) -> Mapping[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate_key:{key}")
            result[key] = value
        return result

    value = json.loads(path.read_bytes(), object_pairs_hook=reject_duplicates)
    if not isinstance(value, Mapping):
        raise ValueError("config_must_be_object")
    return value


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        + b"\n"
    )


def _archive_cycle(root: Path, cycle: Mapping[str, Any]) -> Path:
    directory = root / "inputs"
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    path = directory / f"{cycle['cycle_hash']}.json"
    raw = _canonical_bytes(cycle)
    if path.exists():
        if path.is_symlink() or path.read_bytes() != raw:
            raise ValueError("paper_cycle_archive_collision")
        return path
    descriptor, temporary_name = tempfile.mkstemp(
        dir=directory,
        prefix=".cycle.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        descriptor = -1
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()
    return path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--event", choices=("daily-close", "g20-open"), required=True)
    parser.add_argument("--observed-at")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    observed_at = args.observed_at or dt.datetime.now(dt.timezone.utc).isoformat()
    config = DualEngineMarketConfig.from_dict(_read_object(args.config.resolve()))
    try:
        cycle = collect_market_cycle(
            config,
            observed_at=observed_at,
            event=args.event,
        )
    except NoScheduledPaperEvent as exc:
        print(json.dumps({"status": "skipped", "reason": str(exc)}, sort_keys=True))
        return 0
    state_root = args.state_root.resolve()
    input_path = _archive_cycle(state_root, cycle.as_dict())
    snapshot = run_paper_cycle(state_root, cycle)
    print(
        json.dumps(
            {
                "status": "paper_cycle_published",
                "event": args.event,
                "cycle_hash": cycle.cycle_hash,
                "snapshot_hash": snapshot.snapshot_hash,
                "input_path": str(input_path),
                "orders_authorized": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
