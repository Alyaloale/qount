#!/usr/bin/env python3
"""Collect one immutable Coin Metrics daily snapshot into the external evidence store."""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.mini_trend.onchain_vintage import collect_onchain_vintage  # noqa: E402
from qount.mini_trend.onchain_vintage import write_onchain_vintage_artifact  # noqa: E402
from qount.settings import Settings  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", required=True)
    parser.add_argument("--source-date")
    parser.add_argument("--retrieved-at")
    parser.add_argument("--output-path", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    retrieved_at = (
        dt.datetime.fromisoformat(args.retrieved_at)
        if args.retrieved_at
        else dt.datetime.now(dt.UTC)
    )
    source_date = args.source_date or (
        retrieved_at.astimezone(dt.UTC).date() - dt.timedelta(days=1)
    ).isoformat()
    payload, raw_path = collect_onchain_vintage(
        raw_root=args.raw_root,
        source_date=source_date,
        retrieved_at=retrieved_at,
    )
    artifact = write_onchain_vintage_artifact(
        Settings.from_env(), payload, explicit_path=args.output_path
    )
    print(f"artifact={artifact['artifact_path']}")
    print(f"raw_path={raw_path}")
    print(f"source_date={artifact['snapshot']['source_date']}")
    print(f"retrieved_at={artifact['snapshot']['retrieved_at']}")
    print(f"snapshot_hash={artifact['snapshot_hash']}")
    print(f"verdict={artifact['diagnostics']['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
