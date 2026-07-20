#!/usr/bin/env python3
"""Project the latest causal MiniTrend UM Base decision without placing orders."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.grid.data import load_funding, load_klines  # noqa: E402
from qount.mini_trend.forward import TOP3  # noqa: E402
from qount.mini_trend.futures_shadow_inputs import (  # noqa: E402
    load_funding_snapshots,
    merge_funding,
)
from qount.mini_trend.pilot_projection import (  # noqa: E402
    build_latest_pilot_projection,
    write_latest_pilot_projection_artifact,
)
from qount.mini_trend.pilot_paper import PilotPaperProtocol  # noqa: E402
from qount.settings import Settings  # noqa: E402


def _month(value: str) -> tuple[int, int]:
    year, month = value.split("-", 1)
    return int(year), int(month)


def _offline_only(url: str) -> bytes:
    raise RuntimeError(f"offline cache miss; network disabled for {url.rsplit('/', 1)[-1]}")


def _load_object(path: str | Path) -> dict:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object at {path}")
    return payload


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exchange-rules-path", required=True)
    parser.add_argument("--cache-dir", default="state/grid_b/klines")
    parser.add_argument("--funding-snapshot-root")
    parser.add_argument("--start-month", default="2025-12")
    parser.add_argument("--capital-usdt", type=float, required=True)
    parser.add_argument("--end-month", default=dt.datetime.now(dt.UTC).strftime("%Y-%m"))
    parser.add_argument("--output-path")
    return parser.parse_args(argv)


def _load_cached_inputs(args: argparse.Namespace) -> tuple[dict, dict]:
    bars = {
        symbol: load_klines(
            symbol,
            "1d",
            start=_month(args.start_month),
            end=_month(args.end_month),
            market="um",
            cache_dir=args.cache_dir,
            fetch=_offline_only,
            skip_missing=True,
        )
        for symbol in TOP3
    }
    archived_funding = {
        symbol: load_funding(
            symbol,
            start=_month(args.start_month),
            end=_month(args.end_month),
            cache_dir=args.cache_dir,
            fetch=_offline_only,
            skip_missing=True,
        )
        for symbol in TOP3
    }
    snapshots = (
        load_funding_snapshots(args.funding_snapshot_root)
        if args.funding_snapshot_root
        else {symbol: [] for symbol in TOP3}
    )
    return bars, merge_funding(archived_funding, snapshots)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    bars, funding = _load_cached_inputs(args)
    payload = build_latest_pilot_projection(
        bars,
        funding,
        _load_object(args.exchange_rules_path),
        protocol=PilotPaperProtocol(capital_usdt=args.capital_usdt),
    )
    artifact = write_latest_pilot_projection_artifact(
        Settings.from_env(), payload, explicit_path=args.output_path
    )
    print(f"artifact={artifact['artifact_path']}")
    print(f"verdict={artifact['diagnostics']['verdict']}")
    print(f"projection_ready={artifact['diagnostics']['projection_ready']}")
    print(f"live_orders_allowed={artifact['meta']['live_orders_allowed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
