#!/usr/bin/env python3
"""Advance Dual-Engine paper state from one prepared canonical cycle input."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from qount.dual_engine import PaperCycleInput
from qount.dual_engine import run_paper_cycle


def _read_cycle(path: Path) -> PaperCycleInput:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate_key:{key}")
            result[key] = value
        return result

    raw = path.read_bytes()
    value = json.loads(raw, object_pairs_hook=reject_duplicates)
    if not isinstance(value, dict):
        raise ValueError("paper_cycle_must_be_object")
    canonical = (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        + b"\n"
    )
    if canonical != raw:
        raise ValueError("paper_cycle_not_canonical")
    return PaperCycleInput.from_dict(value)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycle", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    args = parser.parse_args(argv)
    snapshot = run_paper_cycle(args.state_root.resolve(), _read_cycle(args.cycle.resolve()))
    print(
        json.dumps(
            {
                "status": "paper_cycle_published",
                "snapshot_hash": snapshot.snapshot_hash,
                "orders_authorized": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
