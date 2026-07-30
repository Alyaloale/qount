#!/usr/bin/env python3
"""Run the public-only liquidation-cascade forward collector.

This collector is intentionally data-only.  It records public Binance USD-M
liquidation flow and contemporaneous context for the frozen 180-day window;
it cannot read private account data, calculate PnL, create a signal, or place
an order.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.mini_trend.liquidation_cascade_collection import (  # noqa: E402
    CONFIGURATION_EXIT_STATUS,
    DISK_GUARD_EXIT_STATUS,
    CollectorConfigurationError,
    DiskSpaceExhausted,
    LiquidationCascadeCollectorConfig,
    read_collection_status,
    run_liquidation_cascade_collector,
)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT,BNBUSDT")
    parser.add_argument("--snapshot-interval-seconds", type=int, default=300)
    parser.add_argument("--event-snapshot-min-interval-seconds", type=int, default=15)
    parser.add_argument("--depth-limit", type=int, default=20)
    parser.add_argument("--min-free-disk-gb", type=float, default=8.0)
    parser.add_argument("--disk-check-interval-seconds", type=float, default=60.0)
    parser.add_argument("--run-seconds", type=float, default=0.0)
    parser.add_argument("--ws-base-url", default="wss://fstream.binance.com")
    parser.add_argument("--rest-base-url", default="https://fapi.binance.com")
    parser.add_argument("--no-proxy-env", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    state_root = Path(args.state_root).expanduser()
    if args.status:
        try:
            status = read_collection_status(state_root)
        except (CollectorConfigurationError, FileNotFoundError) as exc:
            print(f"status_error={exc}", file=sys.stderr)
            return CONFIGURATION_EXIT_STATUS
        print(json.dumps(status, ensure_ascii=True, sort_keys=True, indent=2))
        return 0
    if args.min_free_disk_gb < 0:
        raise CollectorConfigurationError("collection_min_free_disk_gb_invalid")
    config = LiquidationCascadeCollectorConfig(
        state_root=state_root,
        symbols=tuple(item.strip().upper() for item in args.symbols.split(",") if item.strip()),
        snapshot_interval_seconds=args.snapshot_interval_seconds,
        event_snapshot_min_interval_seconds=args.event_snapshot_min_interval_seconds,
        depth_limit=args.depth_limit,
        min_free_disk_bytes=int(args.min_free_disk_gb * 1024**3),
        disk_check_interval_seconds=args.disk_check_interval_seconds,
        ws_base_url=args.ws_base_url,
        rest_base_url=args.rest_base_url,
        use_proxy_env=not args.no_proxy_env,
    )
    try:
        result = asyncio.run(run_liquidation_cascade_collector(config, run_seconds=args.run_seconds))
    except CollectorConfigurationError as exc:
        print(f"configuration_error={exc}", file=sys.stderr)
        return CONFIGURATION_EXIT_STATUS
    except DiskSpaceExhausted as exc:
        print(f"disk_guard_error={exc}", file=sys.stderr)
        return DISK_GUARD_EXIT_STATUS
    if args.print_json:
        print(json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2))
    else:
        counters = result["counters"]
        print(f"status={result['status']}")
        print(f"state_root={state_root}")
        print(f"connections={counters['connection_opens']}")
        print(f"liquidation_events={counters['liquidation_events']}")
        print(f"periodic_snapshots={counters['periodic_snapshots']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
