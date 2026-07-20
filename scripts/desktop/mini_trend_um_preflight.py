#!/usr/bin/env python3
"""Run the read-only MiniTrend UM account preflight; never mutate the account."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.mini_trend.pilot_preflight import build_pilot_account_preflight  # noqa: E402
from qount.mini_trend.pilot_preflight import (  # noqa: E402
    write_pilot_account_preflight_artifact,
)
from qount.settings import Settings  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    settings = Settings.from_env()
    payload = build_pilot_account_preflight(settings)
    artifact = write_pilot_account_preflight_artifact(
        settings,
        payload,
        explicit_path=args.output_path,
    )
    print(f"artifact={artifact['artifact_path']}")
    print(f"verdict={artifact['diagnostics']['verdict']}")
    print(f"blockers={len(artifact['diagnostics']['blockers'])}")
    print(f"private_api_order_attempted={artifact['meta']['private_api_order_attempted']}")
    print(f"live_orders_allowed={artifact['meta']['live_orders_allowed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
