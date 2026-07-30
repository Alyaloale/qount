#!/usr/bin/env python3
"""Audit public Equity Mapping source adapters without creating a market event."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.mini_trend.equity_mapping_sources import (  # noqa: E402
    build_equity_mapping_source_capacity,
)
from qount.mini_trend.equity_mapping_sources import (  # noqa: E402
    write_equity_mapping_source_capacity_artifact,
)
from qount.settings import Settings  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cash-date", required=True)
    parser.add_argument("--mapped-symbol", default="NVDAUSDT")
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    report, raw_bodies = build_equity_mapping_source_capacity(
        cash_trading_date=args.cash_date,
        mapped_symbol=args.mapped_symbol,
        timeout_seconds=args.timeout_seconds,
    )
    artifact = write_equity_mapping_source_capacity_artifact(
        Settings.from_env(), report, raw_bodies
    )
    print(f"artifact={artifact['artifact_path']}")
    print(f"verdict={artifact['verdict']}")
    print(f"blockers={','.join(artifact['blockers'])}")
    print(f"raw_files={artifact['raw_manifest']['file_count']}")
    print("trial_count=0")
    print("market_event_created=False")
    print("orders_allowed=False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
