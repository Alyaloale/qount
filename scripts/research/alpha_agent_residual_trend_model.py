#!/usr/bin/env python3
"""Preregister, fit, and report the fixed residual-trend logistic baseline."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.alpha_agents.residual_trend_model import ResidualTrendModelConfig  # noqa: E402
from qount.alpha_agents.residual_trend_model import build_residual_trend_model_experiment  # noqa: E402
from qount.alpha_agents.residual_trend_model import build_residual_trend_model_preregistration  # noqa: E402
from qount.alpha_agents.residual_trend_model import build_residual_trend_model_report  # noqa: E402
from qount.alpha_agents.residual_trend_model import write_residual_trend_model_artifact  # noqa: E402
from qount.settings import Settings  # noqa: E402


def _csv_tuple(raw: str) -> tuple[str, ...]:
    return tuple(item.strip().upper() for item in raw.split(",") if item.strip())


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("preregister", "experiment", "report"), required=True)
    parser.add_argument("--depth-path")
    parser.add_argument("--premium-path")
    parser.add_argument("--preregistration-path")
    parser.add_argument("--experiment-path", action="append", default=[])
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT")
    parser.add_argument("--strategy-symbol", default="ETHUSDT")
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
        payload = build_residual_trend_model_preregistration()
    elif args.mode == "experiment":
        payload = build_residual_trend_model_experiment(
            ResidualTrendModelConfig(
                depth_path=_require(args.depth_path, "--depth-path"),
                premium_path=_require(args.premium_path, "--premium-path"),
                symbols=_csv_tuple(args.symbols),
                strategy_symbol=args.strategy_symbol.upper(),
                exchange_rules_path=_require(args.exchange_rules_path, "--exchange-rules-path"),
                kline_cache_dir=args.kline_cache_dir,
                funding_cache_dir=args.funding_cache_dir,
            )
        )
    else:
        payload = build_residual_trend_model_report(
            preregistration_path=_require(args.preregistration_path, "--preregistration-path"),
            experiment_paths=args.experiment_path,
        )
    artifact = write_residual_trend_model_artifact(
        Settings.from_env(), payload, explicit_path=args.output_path
    )
    diagnostics = artifact["diagnostics"]
    if args.print_json:
        print(json.dumps(artifact, ensure_ascii=False, indent=2))
    else:
        print(f"artifact={artifact['artifact_path']}")
        print(f"verdict={diagnostics['verdict']}")
        if args.mode == "experiment":
            print(f"auc={diagnostics['prediction']['auc']:.6f}")
            print(f"rank_ic={diagnostics['prediction']['rank_ic']:.6f}")
            print(f"net_residual_return_pct={diagnostics['score']['net_residual_return_pct']:.6f}")
            print(f"entry_count={diagnostics['execution']['entry_count']}")
        elif args.mode == "report":
            print(f"passing_symbol_count={diagnostics['passing_symbol_count']}")
            print(f"mean_net_residual_return_pct={diagnostics['mean_net_residual_return_pct']:.6f}")
            print(f"a10_sequence_enabled={diagnostics['a10_sequence_enabled']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
