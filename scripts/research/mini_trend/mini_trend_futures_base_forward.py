#!/usr/bin/env python3
"""Preregister or run the future-only, no-carry UM base trend control."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.mini_trend.futures_base_forward import build_futures_base_forward_preregistration  # noqa: E402
from qount.mini_trend.futures_base_forward import write_futures_base_forward_preregistration_artifact  # noqa: E402
from qount.mini_trend.futures_base_forward_report import build_base_forward_report  # noqa: E402
from qount.mini_trend.futures_base_forward_report import write_base_forward_report_artifact  # noqa: E402
from qount.research_data.market_data import load_funding, load_klines  # noqa: E402
from qount.settings import Settings  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--exchange-rules-path", required=True)
    parser.add_argument("--live-lessons-path", required=True)
    parser.add_argument("--preregistration-path")
    parser.add_argument("--cache-dir", default="state/grid_b/klines")
    parser.add_argument("--kline-cache-dir")
    parser.add_argument("--funding-cache-dir")
    parser.add_argument("--start-month", default="2025-01")
    parser.add_argument("--end-month", default="2026-07")
    parser.add_argument("--output-path")
    return parser.parse_args(argv)


def _month(value: str) -> tuple[int, int]:
    year, month = value.split("-", 1)
    return int(year), int(month)


def _offline_only(url: str) -> bytes:
    raise RuntimeError(f"offline cache miss; network disabled for {url.rsplit('/', 1)[-1]}")


def _load_cached_inputs(args: argparse.Namespace) -> tuple[dict, dict]:
    kline_cache_dir = args.kline_cache_dir or args.cache_dir
    funding_cache_dir = args.funding_cache_dir or args.cache_dir
    bars = {
        symbol: load_klines(
            symbol,
            "1d",
            start=_month(args.start_month),
            end=_month(args.end_month),
            market="um",
            cache_dir=kline_cache_dir,
            fetch=_offline_only,
            skip_missing=True,
        )
        for symbol in ("BTCUSDT", "ETHUSDT", "BNBUSDT")
    }
    funding = {
        symbol: load_funding(
            symbol,
            start=_month(args.start_month),
            end=_month(args.end_month),
            cache_dir=funding_cache_dir,
            fetch=_offline_only,
            skip_missing=True,
        )
        for symbol in ("BTCUSDT", "ETHUSDT", "BNBUSDT")
    }
    return bars, funding


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    rules = json.loads(Path(args.exchange_rules_path).read_text(encoding="utf-8"))
    if args.run:
        if not args.preregistration_path:
            raise ValueError("--run requires --preregistration-path")
        bars, funding = _load_cached_inputs(args)
        payload = build_base_forward_report(
            bars,
            funding,
            rules,
            json.loads(Path(args.preregistration_path).read_text(encoding="utf-8")),
            args.live_lessons_path,
        )
        artifact = write_base_forward_report_artifact(
            Settings.from_env(), payload, explicit_path=args.output_path
        )
    else:
        payload = build_futures_base_forward_preregistration(rules, args.live_lessons_path)
        artifact = write_futures_base_forward_preregistration_artifact(
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
