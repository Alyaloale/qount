#!/usr/bin/env python3
"""Run a deterministic Alpha Agents feature-grid experiment.

This is research-only. It loads public Binance klines/funding, selects a simple
feature candidate on the train split, emits OOS returns, and never reads private
Binance keys or places orders.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.alpha_agents.exchange_rules import fetch_exchange_info  # noqa: E402
from qount.alpha_agents.exchange_rules import load_symbol_rules  # noqa: E402
from qount.alpha_agents.feature_experiment import FeatureExperimentConfig  # noqa: E402
from qount.alpha_agents.feature_experiment import build_feature_experiment_dataset  # noqa: E402
from qount.alpha_agents.feature_experiment import write_feature_experiment_artifact  # noqa: E402
from qount.settings import Settings  # noqa: E402


def _csv_tuple(raw: str, *, cast=str) -> tuple:
    return tuple(cast(item.strip()) for item in raw.split(",") if item.strip())


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT")
    parser.add_argument("--strategy-symbol", default="ETHUSDT")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--start-month", required=True)
    parser.add_argument("--end-month", required=True)
    parser.add_argument("--market", default="um", choices=("spot", "um"))
    parser.add_argument("--kline-source", default="public_dump", choices=("public_dump", "rest"))
    parser.add_argument("--horizon-bars", type=int, default=6)
    parser.add_argument("--train-fraction", type=float, default=0.60)
    parser.add_argument("--lookbacks", default="6,12,24,48")
    parser.add_argument(
        "--feature-families",
        default="momentum,reversal,relative_momentum,vol_adjusted_momentum",
    )
    parser.add_argument("--thresholds", default="0,0.0025,0.005")
    parser.add_argument("--modes", default="long_short,long_cash,short_cash")
    parser.add_argument("--polarities", default="1")
    parser.add_argument(
        "--selection-metric",
        default="net_residual_return",
        choices=("net_residual_return", "rank_ic"),
    )
    parser.add_argument("--beta-lookback-bars", type=int, default=24)
    parser.add_argument("--fee-pct", type=float, default=0.0005)
    parser.add_argument("--slippage-pct", type=float, default=0.0002)
    parser.add_argument("--account-equity-usdt", type=float, default=400.0)
    parser.add_argument("--target-notional-fraction", type=float, default=1.0)
    parser.add_argument("--leverage", type=float, default=1.0)
    parser.add_argument("--include-funding", action="store_true", default=False)
    parser.add_argument("--output-granularity", default="month", choices=("bar", "month"))
    parser.add_argument("--cache-dir", default="state/alpha_agents/binance_klines")
    parser.add_argument("--funding-cache-dir", default="state/alpha_agents/binance_funding")
    parser.add_argument("--derivatives-state-path", default=None)
    parser.add_argument("--min-feature-coverage", type=float, default=0.05)
    parser.add_argument("--exchange-rules-path", default=None)
    parser.add_argument("--fetch-exchange-info", action="store_true")
    parser.add_argument("--output-path", default=None)
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    config = FeatureExperimentConfig(
        symbols=_csv_tuple(args.symbols, cast=str),
        strategy_symbol=args.strategy_symbol,
        interval=args.interval,
        start_month=args.start_month,
        end_month=args.end_month,
        market=args.market,
        kline_source=args.kline_source,
        horizon_bars=args.horizon_bars,
        train_fraction=args.train_fraction,
        lookbacks=_csv_tuple(args.lookbacks, cast=int),
        feature_families=_csv_tuple(args.feature_families, cast=str),
        thresholds=_csv_tuple(args.thresholds, cast=float),
        modes=_csv_tuple(args.modes, cast=str),
        polarities=_csv_tuple(args.polarities, cast=int),
        selection_metric=args.selection_metric,
        beta_lookback_bars=args.beta_lookback_bars,
        fee_pct=args.fee_pct,
        slippage_pct=args.slippage_pct,
        account_equity_usdt=args.account_equity_usdt,
        target_notional_fraction=args.target_notional_fraction,
        leverage=args.leverage,
        include_funding=args.include_funding,
        output_granularity=args.output_granularity,
        cache_dir=args.cache_dir,
        funding_cache_dir=args.funding_cache_dir,
        derivatives_state_path=args.derivatives_state_path,
        min_feature_coverage=args.min_feature_coverage,
    )
    symbol_rules = None
    exchange_info = None
    if args.exchange_rules_path:
        symbol_rules = load_symbol_rules(args.exchange_rules_path, market=args.market)
    elif args.fetch_exchange_info:
        exchange_info = fetch_exchange_info(market=args.market)
    payload = build_feature_experiment_dataset(config, exchange_info=exchange_info, symbol_rules=symbol_rules)
    artifact = write_feature_experiment_artifact(Settings.from_env(), payload, explicit_path=args.output_path)
    if args.print_json:
        print(json.dumps(artifact, ensure_ascii=False, indent=2))
    else:
        score = artifact["diagnostics"]["selected_oos_score"]
        print(f"artifact={artifact['artifact_path']}")
        print(f"selected_candidate={artifact['selected_candidate']['candidate_id']}")
        print(f"oos_period_count={artifact['diagnostics']['output_period_count']}")
        print(f"oos_net_residual_return_pct={score['net_residual_return_pct']:.6f}")
        print(f"oos_beta_to_btc={score['beta_to_btc']:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
