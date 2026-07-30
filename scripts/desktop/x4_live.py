#!/usr/bin/env python3
"""Blocked compatibility entrypoint for the retired X4 live runner."""

from __future__ import annotations

import sys


def main() -> int:
    print("[BLOCKED] X4 live runner is retired and cannot be restarted.", file=sys.stderr)
    print(
        "Historical source: scripts/archive/desktop-legacy/x4_live.py",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
