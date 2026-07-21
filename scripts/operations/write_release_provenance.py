#!/usr/bin/env python3
"""Write the immutable source manifest used to verify a VPS release."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.operations.release_provenance import build_release_provenance  # noqa: E402
from qount.operations.release_provenance import write_release_provenance  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(REPO))
    parser.add_argument("--output-path", required=True)
    args = parser.parse_args()
    root = Path(args.repo_root).expanduser().resolve()
    commit = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    payload = build_release_provenance(root, git_commit=commit)
    target = write_release_provenance(args.output_path, payload)
    print(f"path={target}")
    print(f"git_commit={payload['git_commit']}")
    print(f"version={payload['version']}")
    print(f"source_tree_hash={payload['source_tree_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
