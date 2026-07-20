#!/usr/bin/env python3
"""Build a content-addressed manifest for a qount data tree."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.storage_topology import build_tree_manifest, write_tree_manifest  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--source-node", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    payload = build_tree_manifest(Path(args.root), source_node=args.source_node)
    target = write_tree_manifest(payload, Path(args.output))
    print(f"manifest={target}")
    print(f"files={payload['file_count']}")
    print(f"bytes={payload['total_bytes']}")
    print(f"content_hash={payload['content_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
