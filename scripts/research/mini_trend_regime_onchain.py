#!/usr/bin/env python3
"""Build the Coin Metrics daily dataset or audit its fixed-polarity features."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.grid.data import load_funding, load_klines  # noqa: E402
from qount.mini_trend.forward import TOP3  # noqa: E402
from qount.mini_trend.regime_onchain import build_onchain_dataset  # noqa: E402
from qount.mini_trend.regime_onchain import write_onchain_dataset_artifact  # noqa: E402
from qount.mini_trend.regime_onchain_audit import build_onchain_feature_audit  # noqa: E402
from qount.mini_trend.regime_onchain_audit import (  # noqa: E402
    write_onchain_feature_audit_artifact,
)
from qount.settings import Settings  # noqa: E402


def _month(value: str) -> tuple[int, int]:
    year, month = value.split("-", 1)
    return int(year), int(month)


def _offline_only(url: str) -> bytes:
    raise RuntimeError(f"offline cache miss; network disabled for {url.rsplit('/', 1)[-1]}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("dataset", "audit"), required=True)
    parser.add_argument("--raw-cache-path")
    parser.add_argument("--onchain-path")
    parser.add_argument("--market-cache-dir")
    parser.add_argument("--start-month", default="2021-01")
    parser.add_argument("--end-month", default="2026-06")
    parser.add_argument("--output-path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.mode == "dataset":
        if not args.raw_cache_path:
            raise ValueError("dataset mode requires --raw-cache-path")
        payload = build_onchain_dataset(args.raw_cache_path)
        artifact = write_onchain_dataset_artifact(
            Settings.from_env(), payload, explicit_path=args.output_path
        )
        print(f"artifact={artifact['artifact_path']}")
        print(f"verdict={artifact['diagnostics']['verdict']}")
        print(f"rows={artifact['diagnostics']['actual_daily_rows']}")
        print(f"coverage={artifact['diagnostics']['coverage_ratio']:.8f}")
        print(f"data_hash={artifact['data_hash']}")
        return 0 if artifact["diagnostics"]["verdict"].startswith("pass_") else 1

    if not args.onchain_path or not args.market_cache_dir:
        raise ValueError("audit mode requires --onchain-path and --market-cache-dir")
    start, end = _month(args.start_month), _month(args.end_month)
    bars = {
        symbol: load_klines(
            symbol,
            "1d",
            start=start,
            end=end,
            market="um",
            cache_dir=args.market_cache_dir,
            fetch=_offline_only,
            skip_missing=True,
        )
        for symbol in TOP3
    }
    funding = {
        symbol: load_funding(
            symbol,
            start=start,
            end=end,
            cache_dir=args.market_cache_dir,
            fetch=_offline_only,
            skip_missing=True,
        )
        for symbol in TOP3
    }
    onchain = json.loads(Path(args.onchain_path).read_text(encoding="utf-8"))
    payload = build_onchain_feature_audit(bars, funding, onchain)
    artifact = write_onchain_feature_audit_artifact(
        Settings.from_env(), payload, explicit_path=args.output_path
    )
    print(f"artifact={artifact['artifact_path']}")
    print(f"verdict={artifact['diagnostics']['verdict']}")
    print(f"coverage={artifact['coverage']['ratio']:.8f}")
    for trial in artifact["trials"]:
        print(
            f"trial={trial['trial_id']} gates={trial['passed_gate_count']}/{trial['gate_count']} "
            f"rank_ic={trial['pooled_rank_ic']:.8f} "
            f"spread={trial['pooled_high_minus_low_actual']:.8f} "
            f"bootstrap={trial['bootstrap']['probability_spread_positive']:.6f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
