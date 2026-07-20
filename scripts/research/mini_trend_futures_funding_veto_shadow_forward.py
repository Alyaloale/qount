#!/usr/bin/env python3
"""Preregister or run the future-only UM funding-veto shadow monitor."""

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
from qount.mini_trend.futures_funding_veto_shadow_forward import (  # noqa: E402
    build_funding_veto_shadow_forward_preregistration,
    build_funding_veto_shadow_forward_report,
    write_funding_veto_shadow_forward_preregistration_artifact,
    write_funding_veto_shadow_forward_report_artifact,
)
from qount.settings import Settings  # noqa: E402


def _load_object(path: str | Path) -> dict:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object at {path}")
    return payload


def _month(value: str) -> tuple[int, int]:
    year, month = value.split("-", 1)
    return int(year), int(month)


def _offline_only(url: str) -> bytes:
    raise RuntimeError(f"offline cache miss; network disabled for {url.rsplit('/', 1)[-1]}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--exchange-rules-path", required=True)
    parser.add_argument("--base-preregistration-path", required=True)
    parser.add_argument("--state-decay-historical-path", required=True)
    parser.add_argument("--preregistration-path")
    parser.add_argument("--cache-dir", default="state/grid_b/klines")
    parser.add_argument("--funding-snapshot-root")
    parser.add_argument("--start-month", default="2025-12")
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
    funding = archived_funding
    if args.funding_snapshot_root:
        funding = merge_funding(
            archived_funding,
            load_funding_snapshots(args.funding_snapshot_root),
        )
    return bars, funding


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    rules = _load_object(args.exchange_rules_path)
    evidence = {
        "base_preregistration_path": args.base_preregistration_path,
        "state_decay_historical_path": args.state_decay_historical_path,
    }
    if args.run:
        if not args.preregistration_path:
            raise ValueError("--run requires --preregistration-path")
        bars, funding = _load_cached_inputs(args)
        payload = build_funding_veto_shadow_forward_report(
            bars,
            funding,
            rules,
            _load_object(args.preregistration_path),
            **evidence,
        )
        artifact = write_funding_veto_shadow_forward_report_artifact(
            Settings.from_env(), payload, explicit_path=args.output_path
        )
    else:
        payload = build_funding_veto_shadow_forward_preregistration(rules, **evidence)
        artifact = write_funding_veto_shadow_forward_preregistration_artifact(
            Settings.from_env(), payload, explicit_path=args.output_path
        )
    print(f"artifact={artifact['artifact_path']}")
    if args.run:
        print(f"verdict={artifact['diagnostics']['verdict']}")
        print(f"last_common_date={artifact['data']['last_common_date']}")
        print(f"evaluation_bars={artifact['data']['evaluation_bar_count']}")
        print(f"strategy_results_evaluated={artifact['meta']['strategy_results_evaluated']}")
    else:
        print(f"contract_hash={artifact['decision_contract']['contract_hash']}")
        print(f"protocol_hash={artifact['protocol']['protocol_hash']}")
        print(f"strategy_results_evaluated={artifact['meta']['strategy_results_evaluated']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
