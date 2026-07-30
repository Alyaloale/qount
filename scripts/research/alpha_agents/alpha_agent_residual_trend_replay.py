#!/usr/bin/env python3
"""Preregister and run byte-bound 2025Q1 frozen residual-trend model replay."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.alpha_agents.residual_trend_replay import ResidualTrendReplayConfig  # noqa: E402
from qount.alpha_agents.residual_trend_replay import build_residual_trend_replay  # noqa: E402
from qount.alpha_agents.residual_trend_replay import build_residual_trend_replay_preregistration  # noqa: E402
from qount.alpha_agents.residual_trend_replay import build_residual_trend_replay_report  # noqa: E402
from qount.alpha_agents.residual_trend_replay import write_residual_trend_replay_artifact  # noqa: E402
from qount.settings import Settings  # noqa: E402


def _csv_tuple(raw: str) -> tuple[str, ...]:
    return tuple(item.strip().upper() for item in raw.split(",") if item.strip())


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("preregister", "replay", "report"), required=True)
    parser.add_argument("--depth-path")
    parser.add_argument("--premium-path")
    parser.add_argument("--model-path")
    parser.add_argument("--preregistration-path")
    parser.add_argument("--replay-path", action="append", default=[])
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT")
    parser.add_argument("--strategy-symbol", default="ETHUSDT")
    parser.add_argument("--exchange-rules-path")
    parser.add_argument("--kline-cache-dir", default="state/alpha_agents/binance_klines")
    parser.add_argument("--funding-cache-dir", default="state/alpha_agents/binance_funding")
    parser.add_argument("--request-retries", type=int, default=5)
    parser.add_argument("--request-timeout-seconds", type=float, default=60.0)
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
        payload = build_residual_trend_replay_preregistration()
    elif args.mode == "replay":
        payload = build_residual_trend_replay(
            ResidualTrendReplayConfig(
                depth_path=_require(args.depth_path, "--depth-path"),
                premium_path=_require(args.premium_path, "--premium-path"),
                model_path=_require(args.model_path, "--model-path"),
                symbols=_csv_tuple(args.symbols),
                strategy_symbol=args.strategy_symbol.upper(),
                exchange_rules_path=_require(args.exchange_rules_path, "--exchange-rules-path"),
                kline_cache_dir=args.kline_cache_dir,
                funding_cache_dir=args.funding_cache_dir,
                request_retries=args.request_retries,
                request_timeout_seconds=args.request_timeout_seconds,
            )
        )
    else:
        payload = build_residual_trend_replay_report(
            preregistration_path=_require(
                args.preregistration_path, "--preregistration-path"
            ),
            replay_paths=args.replay_path,
        )
    artifact = write_residual_trend_replay_artifact(
        Settings.from_env(), payload, explicit_path=args.output_path
    )
    diagnostics = artifact["diagnostics"]
    if args.print_json:
        print(json.dumps(artifact, ensure_ascii=False, indent=2))
    else:
        print(f"artifact={artifact['artifact_path']}")
        print(f"verdict={diagnostics['verdict']}")
        if args.mode == "replay":
            print(f"auc={diagnostics['prediction']['auc']:.6f}")
            print(f"rank_ic={diagnostics['prediction']['rank_ic']:.6f}")
            print(
                "net_residual_return_pct="
                f"{diagnostics['score']['net_residual_return_pct']:.6f}"
            )
            print(f"entry_count={diagnostics['execution']['entry_count']}")
        elif args.mode == "report":
            print(f"supportive_symbol_count={diagnostics['supportive_symbol_count']}")
            print(
                "mean_net_residual_return_pct="
                f"{diagnostics['mean_net_residual_return_pct']:.6f}"
            )
            print(f"a10_sequence_enabled={diagnostics['a10_sequence_enabled']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
