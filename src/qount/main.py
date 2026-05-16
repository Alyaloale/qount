from __future__ import annotations

import argparse
import json

from .backtest import BacktestService
from .backtest import parse_backtest_datetime
from .orchestrator import Orchestrator
from .settings import Settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="qount")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("run-once", help="Run one end-to-end trading cycle.")
    subparsers.add_parser("healthcheck", help="Verify relay and Binance public connectivity.")
    preflight = subparsers.add_parser("preflight-live", help="Run live safety checks for the configured exchange.")
    preflight.add_argument("--arm", action="store_true", help="Deprecated compatibility flag. Live guard is now persistent and this flag is ignored.")
    subparsers.add_parser("live-guard-status", help="Show whether the current live config is persistently allowing real trading.")
    subparsers.add_parser("runtime-status", help="Show halt state, AI failure streak, and the active day-start equity key.")
    subparsers.add_parser("clear-halt", help="Clear the runtime halt flag and reset the AI failure streak.")
    subparsers.add_parser("paper-status", help="Show paper portfolio plus recent runs and orders.")
    signal_review = subparsers.add_parser("signal-review", help="Batch review recorded AI decisions against realized future movement.")
    signal_review.add_argument("--limit", type=int, default=20)
    signal_review.add_argument("--horizon-bars", type=int, default=3)
    signal_review.add_argument("--threshold-pct", type=float, default=0.003)
    paper_replay = subparsers.add_parser("paper-replay", help="Replay recorded paper orders into an equity timeline.")
    paper_replay.add_argument("--include-noop", action="store_true")
    backtest = subparsers.add_parser("backtest", help="Run an isolated historical paper backtest with the current candidate/AI/risk pipeline.")
    backtest.add_argument("--start", required=True, help="Inclusive start time in ISO 8601. Include an explicit timezone offset when possible.")
    backtest.add_argument("--end", required=True, help="Inclusive end time in ISO 8601. Include an explicit timezone offset when possible.")
    backtest.add_argument("--starting-quote", type=float, default=None, help="Optional paper starting equity override.")
    backtest.add_argument("--max-bars", type=int, default=None, help="Optional cap on processed bars for quicker iteration.")
    backtest.add_argument("--review-horizon-bars", type=int, default=3)
    backtest.add_argument("--review-threshold-pct", type=float, default=0.003)
    backtest.add_argument("--artifact-dir", default=None, help="Optional output directory for the isolated backtest database and reports.")
    dashboard = subparsers.add_parser("dashboard-snapshot", help="Return a single aggregated monitoring snapshot.")
    dashboard.add_argument("--review-limit", type=int, default=10)
    dashboard.add_argument("--review-horizon-bars", type=int, default=1)
    dashboard.add_argument("--review-threshold-pct", type=float, default=0.003)
    dashboard.add_argument("--include-exchange", action="store_true", help="Include live exchange checks and account pulls.")
    dashboard.add_argument("--include-review", action="store_true", help="Include signal-review market backfill.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    settings = Settings.from_env()
    orchestrator = Orchestrator(settings)

    if args.command == "run-once":
        result = orchestrator.run_once()
    elif args.command == "healthcheck":
        result = orchestrator.healthcheck()
    elif args.command == "preflight-live":
        result = orchestrator.preflight_live(arm=args.arm)
    elif args.command == "live-guard-status":
        result = orchestrator.live_guard_status()
    elif args.command == "runtime-status":
        result = orchestrator.runtime_status()
    elif args.command == "clear-halt":
        result = orchestrator.clear_halt()
    elif args.command == "paper-status":
        result = orchestrator.paper_status()
    elif args.command == "signal-review":
        result = orchestrator.signal_review(limit=args.limit, horizon_bars=args.horizon_bars, threshold_pct=args.threshold_pct)
    elif args.command == "paper-replay":
        result = orchestrator.paper_replay(include_noop=args.include_noop)
    elif args.command == "backtest":
        result = BacktestService(settings).run(
            start=parse_backtest_datetime(args.start),
            end=parse_backtest_datetime(args.end),
            review_horizon_bars=args.review_horizon_bars,
            review_threshold_pct=args.review_threshold_pct,
            starting_quote=args.starting_quote,
            max_bars=args.max_bars,
            artifact_dir=args.artifact_dir,
        )
    elif args.command == "dashboard-snapshot":
        result = orchestrator.dashboard_snapshot(
            review_limit=args.review_limit,
            review_horizon_bars=args.review_horizon_bars,
            review_threshold_pct=args.review_threshold_pct,
            include_exchange=args.include_exchange,
            include_review=args.include_review,
        )
    else:
        parser.error(f"unknown command: {args.command}")
        return

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
