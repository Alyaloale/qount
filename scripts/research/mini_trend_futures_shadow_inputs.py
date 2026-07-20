#!/usr/bin/env python3
"""Refresh public UM shadow inputs directly on WSL/external storage."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.mini_trend.futures_shadow_inputs import (  # noqa: E402
    ShadowInputRefreshConfig,
    proxy_fetch,
    refresh_shadow_inputs,
    write_shadow_input_refresh_artifact,
)
from qount.settings import Settings  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--funding-snapshot-root", required=True)
    parser.add_argument("--seed-cache-dir")
    parser.add_argument("--start-month", default="2025-12")
    parser.add_argument("--end-date")
    parser.add_argument("--request-timeout-seconds", type=float, default=30.0)
    parser.add_argument(
        "--transport-label",
        default="direct_wsl",
        choices=("direct_wsl", "direct_vps"),
        help="Audit label for the direct public-data route.",
    )
    parser.add_argument(
        "--proxy-url-env",
        help="Optional environment variable containing an owner-configured HTTP(S) proxy URL.",
    )
    parser.add_argument("--output-path", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    now = dt.datetime.now(dt.UTC)
    end_date = args.end_date or (now.date() - dt.timedelta(days=1)).isoformat()
    config = ShadowInputRefreshConfig(
        request_timeout_seconds=args.request_timeout_seconds
    )
    funding_fetch = None
    transport = args.transport_label
    if args.proxy_url_env:
        proxy_url = os.environ.get(args.proxy_url_env)
        if not proxy_url:
            raise ValueError(f"proxy environment variable is not set: {args.proxy_url_env}")
        funding_fetch = proxy_fetch(
            proxy_url,
            timeout_seconds=config.request_timeout_seconds,
        )
        transport = "owner_configured_proxy"
    payload = refresh_shadow_inputs(
        cache_dir=args.cache_dir,
        funding_snapshot_root=args.funding_snapshot_root,
        start_month=args.start_month,
        end_date=end_date,
        retrieved_at=now,
        seed_cache_dir=args.seed_cache_dir,
        config=config,
        funding_fetch=funding_fetch,
        funding_transport=transport,
    )
    artifact = write_shadow_input_refresh_artifact(
        Settings.from_env(), payload, explicit_path=args.output_path
    )
    print(f"artifact={artifact['artifact_path']}")
    print(f"verdict={artifact['diagnostics']['verdict']}")
    print(f"files={len(artifact['files'])}")
    print(f"unavailable={artifact['diagnostics']['unavailable_count']}")
    print(
        "funding_complete_symbols="
        f"{len(artifact['funding_api']['complete_symbols'])}/{len(config.symbols)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
