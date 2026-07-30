#!/usr/bin/env python3
"""Build checksum-verified Binance USD-M premium/mark/index 5m features."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.alpha_agents.historical_premium import HistoricalPremiumConfig  # noqa: E402
from qount.alpha_agents.historical_premium import build_historical_premium_dataset  # noqa: E402
from qount.alpha_agents.historical_premium import write_historical_premium_artifact  # noqa: E402
from qount.settings import Settings  # noqa: E402


def _csv_tuple(raw: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT")
    parser.add_argument("--start-date", default="2024-01-01")
    parser.add_argument("--end-date", default="2024-03-31")
    parser.add_argument("--cache-dir", default="state/alpha_agents/binance_historical_premium")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--request-retries", type=int, default=3)
    parser.add_argument("--request-timeout-seconds", type=float, default=60.0)
    parser.add_argument("--min-coverage-ratio", type=float, default=0.98)
    parser.add_argument("--output-path")
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    payload = build_historical_premium_dataset(
        HistoricalPremiumConfig(
            symbols=tuple(item.upper() for item in _csv_tuple(args.symbols)),
            start_date=args.start_date,
            end_date=args.end_date,
            cache_dir=args.cache_dir,
            max_workers=args.max_workers,
            request_retries=args.request_retries,
            request_timeout_seconds=args.request_timeout_seconds,
            min_coverage_ratio=args.min_coverage_ratio,
        )
    )
    artifact = write_historical_premium_artifact(
        Settings.from_env(), payload, explicit_path=args.output_path
    )
    diagnostics = artifact["diagnostics"]
    if args.print_json:
        print(json.dumps(artifact, ensure_ascii=False, indent=2))
    else:
        print(f"artifact={artifact['artifact_path']}")
        print(f"verdict={diagnostics['verdict']}")
        print(f"loaded_archive_count={diagnostics['loaded_archive_count']}")
        print(f"archive_bytes={diagnostics['archive_bytes']}")
        print(f"complete_row_count={diagnostics['complete_row_count']}")
        for symbol, summary in diagnostics["by_symbol"].items():
            print(f"{symbol}_complete_coverage={summary['complete_coverage_ratio']:.6f}")
    return 0 if diagnostics["verdict"] == "pass_data_smoke" else 1


if __name__ == "__main__":
    raise SystemExit(main())
