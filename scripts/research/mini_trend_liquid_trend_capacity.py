#!/usr/bin/env python3
"""Audit LiquidTrend10 daily data, funding, liquidity, filters, and breadth."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.grid.data import load_funding, load_klines  # noqa: E402
from qount.mini_trend.liquid_trend import LIQUID_TREND_UNIVERSE  # noqa: E402
from qount.mini_trend.liquid_trend import LiquidTrendCapacityConfig  # noqa: E402
from qount.mini_trend.liquid_trend import build_liquid_trend_capacity_report  # noqa: E402
from qount.mini_trend.liquid_trend import write_liquid_trend_capacity_artifact  # noqa: E402
from qount.settings import Settings  # noqa: E402


def _offline_only(url: str) -> bytes:
    raise RuntimeError(f"offline cache miss; network disabled for {url.rsplit('/', 1)[-1]}")


def _month(value: str) -> tuple[int, int]:
    year, month = value[:7].split("-", 1)
    return int(year), int(month)


def _load_object(path: str | Path) -> dict:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object at {path}")
    return payload


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--exchange-rules-path", required=True)
    parser.add_argument("--start-month", default="2021-01")
    parser.add_argument("--end-month", default="2026-05")
    parser.add_argument("--start-date", default="2021-07-20")
    parser.add_argument("--end-date", default="2026-05-31")
    parser.add_argument("--output-path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    start, end = _month(args.start_month), _month(args.end_month)
    bars = {
        symbol: load_klines(
            symbol,
            "1d",
            start=start,
            end=end,
            market="um",
            cache_dir=args.cache_dir,
            fetch=_offline_only,
        )
        for symbol in LIQUID_TREND_UNIVERSE
    }
    funding = {
        symbol: load_funding(
            symbol,
            start=start,
            end=end,
            cache_dir=args.cache_dir,
            fetch=_offline_only,
        )
        for symbol in LIQUID_TREND_UNIVERSE
    }
    payload = build_liquid_trend_capacity_report(
        bars,
        funding,
        _load_object(args.exchange_rules_path),
        LiquidTrendCapacityConfig(
            start_date=args.start_date,
            end_date=args.end_date,
        ),
    )
    artifact = write_liquid_trend_capacity_artifact(
        Settings.from_env(), payload, explicit_path=args.output_path
    )
    breadth = artifact["breadth"]
    diagnostics = artifact["diagnostics"]
    print(f"artifact={artifact['artifact_path']}")
    print(f"verdict={diagnostics['verdict']}")
    print(f"gates={diagnostics['passed_gate_count']}/{diagnostics['gate_count']}")
    print(f"common_bar_coverage={artifact['coverage']['common_bar_coverage']:.8f}")
    print(f"mean_abs_pairwise_correlation={breadth['mean_abs_pairwise_correlation']:.8f}")
    print(f"effective_breadth={breadth['effective_breadth']:.8f}")
    print(f"effective_breadth_eigen={breadth['effective_breadth_eigen']:.8f}")
    print(f"first_principal_component_share={breadth['first_principal_component_share']:.8f}")
    downside = breadth.get("downside_btc_negative") or {}
    print(
        "downside_mean_abs_pairwise_correlation="
        f"{float(downside.get('mean_abs_pairwise_correlation', 0.0)):.8f}"
    )
    print(f"cluster_count={breadth['cluster_count']}")
    print(f"blockers={','.join(diagnostics['blockers']) or 'none'}")
    print("strategy_results_evaluated=False")
    print("paper_or_live_allowed=False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
