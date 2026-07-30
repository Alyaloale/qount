#!/usr/bin/env python3
"""Preregister, run, and summarize the frozen flow-price absorption kill-test."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.alpha_agents.flow_absorption import build_flow_absorption_discovery_report  # noqa: E402
from qount.alpha_agents.flow_absorption import build_flow_absorption_experiment  # noqa: E402
from qount.alpha_agents.flow_absorption import build_flow_absorption_preregistration  # noqa: E402
from qount.alpha_agents.flow_absorption import write_flow_absorption_artifact  # noqa: E402
from qount.alpha_agents.tradeflow_experiment import TradeFlowExperimentConfig  # noqa: E402
from qount.settings import Settings  # noqa: E402


def _csv_tuple(raw: str) -> tuple[str, ...]:
    return tuple(item.strip().upper() for item in raw.split(",") if item.strip())


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("preregister", "experiment", "report"), required=True)
    parser.add_argument("--tradeflow-path")
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
        payload = build_flow_absorption_preregistration()
    elif args.mode == "experiment":
        payload = build_flow_absorption_experiment(
            TradeFlowExperimentConfig(
                tradeflow_path=_require(args.tradeflow_path, "--tradeflow-path"),
                symbols=_csv_tuple(args.symbols),
                strategy_symbol=args.strategy_symbol.upper(),
                start_month=args.start_month,
                end_month=args.end_month,
                holdout_role="discovery",
                kline_cache_dir=args.kline_cache_dir,
                funding_cache_dir=args.funding_cache_dir,
                exchange_rules_path=_require(args.exchange_rules_path, "--exchange-rules-path"),
            )
        )
    else:
        payload = build_flow_absorption_discovery_report(
            preregistration_path=_require(args.preregistration_path, "--preregistration-path"),
            experiment_paths=args.experiment_path,
        )
    artifact = write_flow_absorption_artifact(
        Settings.from_env(),
        payload,
        explicit_path=args.output_path,
    )
    if args.print_json:
        print(json.dumps(artifact, ensure_ascii=False, indent=2))
    else:
        diagnostics = artifact["diagnostics"]
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
