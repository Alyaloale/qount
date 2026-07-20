#!/usr/bin/env python3
"""Run the single frozen 1h low-turnover historical trade-flow kill-test."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.alpha_agents.tradeflow_experiment import TradeFlowExperimentConfig  # noqa: E402
from qount.alpha_agents.tradeflow_experiment import build_tradeflow_experiment  # noqa: E402
from qount.alpha_agents.tradeflow_experiment import write_tradeflow_experiment_artifact  # noqa: E402
from qount.settings import Settings  # noqa: E402


def _csv_tuple(raw: str) -> tuple[str, ...]:
    return tuple(item.strip().upper() for item in raw.split(",") if item.strip())


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tradeflow-path", required=True)
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT")
    parser.add_argument("--strategy-symbol", default="ETHUSDT")
    parser.add_argument("--start-month", default="2024-01")
    parser.add_argument("--end-month", default="2024-03")
    parser.add_argument("--evaluation-start-month", default=None)
    parser.add_argument("--evaluation-end-month", default=None)
    parser.add_argument("--holdout-role", choices=("discovery", "historical_oos"), default="discovery")
    parser.add_argument("--kline-cache-dir", default="state/alpha_agents/binance_klines")
    parser.add_argument("--funding-cache-dir", default="state/alpha_agents/binance_funding")
    parser.add_argument("--exchange-rules-path", required=True)
    parser.add_argument("--fee-pct", type=float, default=0.0005)
    parser.add_argument("--slippage-pct", type=float, default=0.0002)
    parser.add_argument("--account-equity-usdt", type=float, default=400.0)
    parser.add_argument("--target-notional-fraction", type=float, default=1.0)
    parser.add_argument("--leverage", type=float, default=1.0)
    parser.add_argument("--min-feature-coverage", type=float, default=0.98)
    parser.add_argument("--no-funding", action="store_true")
    parser.add_argument("--output-path", default=None)
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    config = TradeFlowExperimentConfig(
        tradeflow_path=args.tradeflow_path,
        symbols=_csv_tuple(args.symbols),
        strategy_symbol=args.strategy_symbol.upper(),
        start_month=args.start_month,
        end_month=args.end_month,
        evaluation_start_month=args.evaluation_start_month,
        evaluation_end_month=args.evaluation_end_month,
        holdout_role=args.holdout_role,
        kline_cache_dir=args.kline_cache_dir,
        funding_cache_dir=args.funding_cache_dir,
        exchange_rules_path=args.exchange_rules_path,
        include_funding=not args.no_funding,
        fee_pct=args.fee_pct,
        slippage_pct=args.slippage_pct,
        account_equity_usdt=args.account_equity_usdt,
        target_notional_fraction=args.target_notional_fraction,
        leverage=args.leverage,
        min_feature_coverage=args.min_feature_coverage,
    )
    payload = build_tradeflow_experiment(config)
    artifact = write_tradeflow_experiment_artifact(
        Settings.from_env(),
        payload,
        explicit_path=args.output_path,
    )
    diagnostics = artifact["diagnostics"]
    if args.print_json:
        print(json.dumps(artifact, ensure_ascii=False, indent=2))
    else:
        print(f"artifact={artifact['artifact_path']}")
        print(f"contract_hash={artifact['decision_contract']['contract_hash']}")
        print(f"verdict={diagnostics['verdict']}")
        print(f"rank_ic={diagnostics['ic']['rank_ic']:.6f}")
        print(f"net_residual_return_pct={diagnostics['score']['net_residual_return_pct']:.6f}")
        print(f"entry_count={diagnostics['execution']['entry_count']}")
        print(f"max_rolling_24h_turnover={diagnostics['execution']['max_rolling_24h_turnover']:.6f}")
        print(f"independent_oos_status={diagnostics['independent_oos_status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
