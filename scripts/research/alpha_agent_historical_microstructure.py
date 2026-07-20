#!/usr/bin/env python3
"""Audit Binance USD-M historical microstructure archive coverage.

This research-only command fetches public CHECKSUM sidecars, writes a coverage
artifact, and never downloads account data, reads private keys, or places orders.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.alpha_agents.historical_microstructure import HistoricalMicrostructureConfig  # noqa: E402
from qount.alpha_agents.historical_microstructure import build_historical_microstructure_coverage  # noqa: E402
from qount.alpha_agents.historical_microstructure import write_historical_microstructure_artifact  # noqa: E402
from qount.settings import Settings  # noqa: E402


def _csv_tuple(raw: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT")
    parser.add_argument("--daily-dates", default="2024-01-01,2026-07-10")
    parser.add_argument("--monthly-months", default="2024-01")
    parser.add_argument("--datasets", default="aggTrades,bookTicker,bookDepth,metrics,forceOrder")
    parser.add_argument("--request-retries", type=int, default=3)
    parser.add_argument("--request-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--output-path", default=None)
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    config = HistoricalMicrostructureConfig(
        symbols=tuple(symbol.upper() for symbol in _csv_tuple(args.symbols)),
        daily_dates=_csv_tuple(args.daily_dates),
        monthly_months=_csv_tuple(args.monthly_months),
        datasets=_csv_tuple(args.datasets),
        request_retries=args.request_retries,
        request_timeout_seconds=args.request_timeout_seconds,
    )
    payload = build_historical_microstructure_coverage(config)
    artifact = write_historical_microstructure_artifact(
        Settings.from_env(),
        payload,
        explicit_path=args.output_path,
    )
    if args.print_json:
        print(json.dumps(artifact, ensure_ascii=False, indent=2))
    else:
        diagnostics = artifact["diagnostics"]
        print(f"artifact={artifact['artifact_path']}")
        print(f"verdict={diagnostics['verdict']}")
        print(f"probe_count={diagnostics['probe_count']}")
        print(f"status_counts={json.dumps(diagnostics['status_counts'], sort_keys=True)}")
        print(
            "historical_first_eligible="
            + ",".join(diagnostics["historical_first_eligible"])
        )
    return 0 if artifact["diagnostics"]["verdict"] == "coverage_mapped" else 1


if __name__ == "__main__":
    raise SystemExit(main())
