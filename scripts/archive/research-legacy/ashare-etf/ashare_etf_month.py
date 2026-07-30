#!/usr/bin/env python3
"""Build the research-only one-month A-share ETF regime report."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.ashare_etf_month import DEFAULT_COST_PER_SIDE_BPS  # noqa: E402
from qount.ashare_etf_month import DEFAULT_HORIZON_DAYS  # noqa: E402
from qount.ashare_etf_month import build_month_report  # noqa: E402
from qount.ashare_etf_month import load_universe_bars  # noqa: E402
from qount.ashare_etf_month import write_month_report_artifact  # noqa: E402
from qount.settings import Settings  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", choices=("tushare", "eastmoney", "tencent"), default="tushare"
    )
    parser.add_argument("--start-date", default="2018-01-01")
    parser.add_argument("--end-date", default=dt.date.today().isoformat())
    parser.add_argument("--cache-dir", default="state/research_cache/ashare_etf_month")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--token-env", default="TUSHARE_TOKEN")
    parser.add_argument("--horizon-days", type=int, default=DEFAULT_HORIZON_DAYS)
    parser.add_argument("--cost-per-side-bps", type=float, default=DEFAULT_COST_PER_SIDE_BPS)
    parser.add_argument("--output-path", default=None)
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    token = os.environ.get(args.token_env) if args.source == "tushare" else None
    if args.source == "tushare" and not token:
        raise SystemExit(
            f"missing {args.token_env}; export it in the shell (do not write it to the repo)"
        )
    bars = load_universe_bars(
        source=args.source,
        start_date=args.start_date,
        end_date=args.end_date,
        cache_dir=args.cache_dir,
        refresh=args.refresh,
        tushare_token=token,
    )
    report = build_month_report(
        bars,
        data_source=args.source,
        horizon_days=args.horizon_days,
        cost_per_side_bps=args.cost_per_side_bps,
    )
    artifact = write_month_report_artifact(
        Settings.from_env(), report, explicit_path=args.output_path
    )
    if args.print_json:
        print(json.dumps(artifact, ensure_ascii=False, indent=2))
    else:
        recommendation = artifact["recommendation"]
        stats = recommendation["matching_regime_stats"]
        print(f"artifact={artifact['artifact_path']}")
        print(f"as_of={artifact['as_of']}")
        print(f"source={artifact['data']['source']}")
        print(f"ai_regime={artifact['ai_regime']['label']}")
        print(f"portfolio={recommendation['portfolio']}")
        print(f"evidence_gate={recommendation['evidence_gate']['verdict']}")
        print(f"matching_samples={stats['sample_count']}")
        print(f"matching_median_return={stats['median_return']}")
        print(f"initial_exposure_cap={recommendation['initial_exposure_cap']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
