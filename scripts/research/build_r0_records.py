#!/usr/bin/env python3
"""Build the local R0 research-governance contract artifacts.

The command creates only preregistration/lineage records.  It does not fetch
market data, run PnL, promote a candidate, or modify any production authority.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
import sys

sys.path.insert(0, str(ROOT / "src"))

from qount.governance import build_r0_candidate_records


def _write_once(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode("ascii")
    if path.is_file():
        if path.read_bytes() == raw:
            return
        raise FileExistsError(f"r0_record_conflict:{path}")
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
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
        os.link(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
        if path.read_bytes() != raw:
            raise RuntimeError(f"r0_record_readback_mismatch:{path}")
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "state" / "research_governance" / "r0"),
    )
    args = parser.parse_args()
    output = Path(args.output_dir)
    for record in build_r0_candidate_records():
        _write_once(
            output / f"candidate-{record.candidate_id}.json",
            asdict(record),
        )
    print(f"R0 candidate contracts written: {output}")
    print("  cxd: blocked_pending_owner_authorization / virtual-only")
    print("  cta-r: planned / research-only")
    print("  orders_authorized: false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
