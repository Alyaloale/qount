#!/usr/bin/env python3
"""Build checksum-verified historical Binance USD-M metrics research data."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.alpha_agents.historical_derivatives import HistoricalDerivativesConfig  # noqa: E402
from qount.alpha_agents.historical_derivatives import build_historical_derivatives_dataset  # noqa: E402
from qount.alpha_agents.historical_derivatives import write_historical_derivatives_artifact  # noqa: E402
from qount.settings import Settings  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT")
    parser.add_argument("--start-date", default="2024-01-01")
    parser.add_argument("--end-date", default="2024-01-31")
    parser.add_argument("--cache-dir", default="state/alpha_agents/binance_historical_metrics")
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--request-retries", type=int, default=3)
    parser.add_argument("--request-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--min-coverage-ratio", type=float, default=0.98)
    parser.add_argument("--output-path", default=None)
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    config = HistoricalDerivativesConfig(
        symbols=tuple(item.strip().upper() for item in args.symbols.split(",") if item.strip()),
        start_date=args.start_date,
        end_date=args.end_date,
        cache_dir=args.cache_dir,
        max_workers=args.max_workers,
        request_retries=args.request_retries,
        request_timeout_seconds=args.request_timeout_seconds,
        min_coverage_ratio=args.min_coverage_ratio,
    )
    payload = build_historical_derivatives_dataset(config)
    artifact = write_historical_derivatives_artifact(
        Settings.from_env(),
        payload,
        explicit_path=args.output_path,
    )
    diagnostics = artifact["diagnostics"]
    if args.print_json:
        print(json.dumps(artifact, ensure_ascii=False, indent=2))
    else:
        print(f"artifact={artifact['artifact_path']}")
        print(f"verdict={diagnostics['verdict']}")
        print(f"requested_archive_count={diagnostics['requested_archive_count']}")
        print(f"loaded_archive_count={diagnostics['loaded_archive_count']}")
        print(f"row_count={diagnostics['row_count']}")
        print(f"error_count={len(diagnostics['errors'])}")
        for symbol, summary in diagnostics["by_symbol"].items():
            print(f"{symbol}_coverage={summary['coverage_ratio']:.6f}")
    return 0 if diagnostics["verdict"] == "pass_data_smoke" else 1


if __name__ == "__main__":
    raise SystemExit(main())
