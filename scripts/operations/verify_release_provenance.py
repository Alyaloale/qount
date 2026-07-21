#!/usr/bin/env python3
"""Verify that a deployed VPS source tree matches its release manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.operations.release_provenance import (  # noqa: E402
    build_release_provenance_verification,
)
from qount.operations.release_provenance import write_release_provenance  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(REPO))
    parser.add_argument("--provenance-path", required=True)
    parser.add_argument("--output-path", required=True)
    args = parser.parse_args()
    payload = json.loads(Path(args.provenance_path).read_text(encoding="ascii"))
    if not isinstance(payload, dict):
        raise ValueError("release provenance must be a JSON object")
    result = build_release_provenance_verification(args.repo_root, payload)
    target = write_release_provenance(args.output_path, result)
    print(f"path={target}")
    print(f"git_commit={result['provenance']['git_commit']}")
    print(f"version={result['provenance']['version']}")
    print(f"verification_hash={result['verification_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
