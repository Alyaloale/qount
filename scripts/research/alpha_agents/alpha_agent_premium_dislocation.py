#!/usr/bin/env python3
"""Preregister, run, and summarize the frozen premium-dislocation kill-test."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.alpha_agents.premium_dislocation import PremiumDislocationConfig  # noqa: E402
from qount.alpha_agents.premium_dislocation import build_premium_dislocation_discovery_report  # noqa: E402
from qount.alpha_agents.premium_dislocation import build_premium_dislocation_experiment  # noqa: E402
from qount.alpha_agents.premium_dislocation import build_premium_dislocation_preregistration  # noqa: E402
from qount.alpha_agents.premium_dislocation import write_premium_dislocation_artifact  # noqa: E402
from qount.settings import Settings  # noqa: E402


def _csv_tuple(raw: str) -> tuple[str, ...]:
    return tuple(item.strip().upper() for item in raw.split(",") if item.strip())


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("preregister", "experiment", "report"), required=True)
    parser.add_argument("--premium-path")
    parser.add_argument("--preregistration-path")
    parser.add_argument("--experiment-path", action="append", default=[])
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT")
    parser.add_argument("--strategy-symbol", default="ETHUSDT")
    parser.add_argument("--start-month", default="2024-01")
    parser.add_argument("--end-month", default="2024-03")
    parser.add_argument("--exchange-rules-path")
    parser.add_argument("--kline-cache-dir", default="state/alpha_agents/binance_klines")
    parser.add_argument("--funding-cache-dir", default="state/alpha_agents/binance_funding")
    parser.add_argument("--output-path")
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def _require(value: str | None, flag: str) -> str:
    if not value:
        raise ValueError(f"{flag} is required for this mode")
    return value


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.mode == "preregister":
        payload = build_premium_dislocation_preregistration()
    elif args.mode == "experiment":
        payload = build_premium_dislocation_experiment(
            PremiumDislocationConfig(
                premium_path=_require(args.premium_path, "--premium-path"),
                symbols=_csv_tuple(args.symbols),
                strategy_symbol=args.strategy_symbol.upper(),
                start_month=args.start_month,
                end_month=args.end_month,
                exchange_rules_path=_require(args.exchange_rules_path, "--exchange-rules-path"),
                kline_cache_dir=args.kline_cache_dir,
                funding_cache_dir=args.funding_cache_dir,
            )
        )
    else:
        payload = build_premium_dislocation_discovery_report(
            preregistration_path=_require(args.preregistration_path, "--preregistration-path"),
            experiment_paths=args.experiment_path,
        )
    artifact = write_premium_dislocation_artifact(
        Settings.from_env(), payload, explicit_path=args.output_path
    )
    diagnostics = artifact["diagnostics"]
    if args.print_json:
        print(json.dumps(artifact, ensure_ascii=False, indent=2))
    else:
        print(f"artifact={artifact['artifact_path']}")
        print(f"verdict={diagnostics['verdict']}")
        if args.mode == "experiment":
            print(f"rank_ic={diagnostics['ic']['rank_ic']:.6f}")
            print(f"net_residual_return_pct={diagnostics['score']['net_residual_return_pct']:.6f}")
            print(f"entry_count={diagnostics['execution']['entry_count']}")
        elif args.mode == "report":
            print(f"passing_symbol_count={diagnostics['passing_symbol_count']}")
            print(f"median_rank_ic={diagnostics['median_rank_ic']:.6f}")
            print(f"mean_net_residual_return_pct={diagnostics['mean_net_residual_return_pct']:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
