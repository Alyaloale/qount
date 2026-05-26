from __future__ import annotations

import argparse
import json
from pathlib import Path

from .backtest import BacktestService
from .backtest import parse_backtest_datetime
from .hourly_model import HourlySignalModelService
from .orchestrator import Orchestrator
from .research_profile import apply_research_profile
from .research_profile import normalize_research_profile
from .research_profile import setup_model_horizon_bars_for_profile
from .research_profile import setup_model_split_higher_phase_for_profile
from .setup_model import SetupEdgeModelService
from .settings import Settings
from .walk_forward import parse_walk_forward_window
from .walk_forward import WalkForwardService


def _add_research_profile_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--research-profile",
        choices=["eth-only"],
        default=None,
        help="Apply a canonical research profile without editing .env. Currently supports eth-only.",
    )


def _symbols_filter_for_review(settings: Settings, research_profile: str | None, explicit_symbols: list[str] | None) -> list[str] | None:
    if explicit_symbols is not None:
        return explicit_symbols
    if research_profile is not None:
        return list(settings.symbols)
    return None


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
    signal_review.add_argument("--replay-current-risk", action="store_true", help="Re-evaluate recorded snapshots and validated decisions with the current risk engine before scoring.")
    signal_review.add_argument("--symbols", nargs="+", default=None, help="Optional symbol filter, for example BTC/USDT:USDT ETH/USDT:USDT.")
    _add_research_profile_arg(signal_review)
    signal_review_study = subparsers.add_parser("signal-review-study", help="Compare the same recorded signal window across multiple review horizons and edge buckets.")
    signal_review_study.add_argument("--limit", type=int, default=160)
    signal_review_study.add_argument("--horizons", nargs="+", type=int, default=[3, 6, 12, 24])
    signal_review_study.add_argument("--threshold-pct", type=float, default=0.003)
    signal_review_study.add_argument("--replay-current-risk", action="store_true", help="Re-evaluate recorded snapshots and validated decisions with the current risk engine before scoring.")
    signal_review_study.add_argument("--symbols", nargs="+", default=None, help="Optional symbol filter, for example BTC/USDT:USDT ETH/USDT:USDT.")
    _add_research_profile_arg(signal_review_study)
    execution_cost_audit = subparsers.add_parser("execution-cost-audit", help="Audit live execution fee/slippage samples plus current exposure geometry.")
    execution_cost_audit.add_argument("--limit", type=int, default=100)
    execution_cost_audit.add_argument("--mode", default=None, help="Optional order mode filter, for example live or paper.")
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
    _add_research_profile_arg(backtest)
    walk_forward = subparsers.add_parser("walk-forward", help="Train setup models before each validation window, then run isolated historical backtests.")
    walk_forward.add_argument("--window", action="append", default=[], help="Validation window as label=START,END. May be repeated.")
    walk_forward.add_argument("--symbols", nargs="+", default=None, help="Optional symbol filter, for example ETH/USDT.")
    walk_forward.add_argument("--setup-phases", nargs="+", default=None, help="Optional setup-phase filter.")
    walk_forward.add_argument("--train-lookback-days", type=int, default=90)
    walk_forward.add_argument("--horizon-bars", type=int, default=None)
    walk_forward.add_argument("--gap-bars", type=int, default=1, help="Completed 5m bars between the training label cutoff and validation start.")
    walk_forward.add_argument("--min-samples", type=int, default=60)
    walk_forward.add_argument("--ridge-alpha", type=float, default=0.0005)
    walk_forward.add_argument("--split-higher-phase", action="store_true", default=None)
    walk_forward.add_argument("--review-horizon-bars", type=int, default=3)
    walk_forward.add_argument("--review-threshold-pct", type=float, default=0.003)
    walk_forward.add_argument("--starting-quote", type=float, default=None)
    walk_forward.add_argument("--max-bars-per-window", type=int, default=None, help="Optional cap on processed bars for each validation window.")
    walk_forward.add_argument("--artifact-dir", default=None, help="Optional output directory for the walk-forward run.")
    _add_research_profile_arg(walk_forward)
    hourly_model = subparsers.add_parser("train-hourly-model", help="Train a lightweight 1h ridge model per symbol and save it to a JSON artifact.")
    hourly_model.add_argument("--symbols", nargs="+", default=None, help="Optional symbol filter, for example SOL/USDT:USDT XRP/USDT:USDT.")
    hourly_model.add_argument("--lookback-days", type=int, default=90)
    hourly_model.add_argument("--horizon-bars", type=int, default=3, help="Prediction horizon in completed 1h bars.")
    hourly_model.add_argument("--ridge-alpha", type=float, default=0.0005)
    hourly_model.add_argument("--artifact-path", default=None, help="Optional output path for the trained model JSON.")
    _add_research_profile_arg(hourly_model)
    setup_model = subparsers.add_parser("train-setup-model", help="Train symbol+setup 5m edge models for narrow setup phases and save them to a JSON artifact.")
    setup_model.add_argument("--symbols", nargs="+", default=None, help="Optional symbol filter, for example SOL/USDT:USDT XRP/USDT:USDT.")
    setup_model.add_argument("--setup-phases", nargs="+", default=None, help="Optional setup-phase filter.")
    setup_model.add_argument("--lookback-days", type=int, default=90)
    setup_model.add_argument("--horizon-bars", type=int, default=None, help="Prediction horizon in completed 5m bars.")
    setup_model.add_argument("--min-samples", type=int, default=60)
    setup_model.add_argument("--ridge-alpha", type=float, default=0.0005)
    setup_model.add_argument("--split-higher-phase", action="store_true", default=None, help="Train nested models per higher_timeframe phase when enough samples exist.")
    setup_model.add_argument("--artifact-path", default=None, help="Optional output path for the trained setup-model JSON.")
    _add_research_profile_arg(setup_model)
    setup_study = subparsers.add_parser("setup-edge-study", help="Study historical post-cost edge by symbol, setup phase, and traditional pattern.")
    setup_study.add_argument("--symbols", nargs="+", default=None, help="Optional symbol filter.")
    setup_study.add_argument("--setup-phases", nargs="+", default=None, help="Optional setup-phase filter.")
    setup_study.add_argument("--lookback-days", type=int, default=120)
    setup_study.add_argument("--horizon-bars", type=int, default=3)
    setup_study.add_argument("--min-samples", type=int, default=20)
    setup_study.add_argument("--top-k", type=int, default=12)
    _add_research_profile_arg(setup_study)
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
    research_profile = normalize_research_profile(getattr(args, "research_profile", None))
    if research_profile is not None:
        if getattr(args, "symbols", None):
            parser.error("--research-profile cannot be combined with --symbols; the profile owns the symbol universe.")
        settings = apply_research_profile(settings, research_profile)
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
        result = orchestrator.signal_review(
            limit=args.limit,
            horizon_bars=args.horizon_bars,
            threshold_pct=args.threshold_pct,
            replay_current_risk=args.replay_current_risk,
            symbols_filter=_symbols_filter_for_review(settings, research_profile, args.symbols),
        )
    elif args.command == "signal-review-study":
        result = orchestrator.signal_review_study(
            limit=args.limit,
            horizons=args.horizons,
            threshold_pct=args.threshold_pct,
            replay_current_risk=args.replay_current_risk,
            symbols_filter=_symbols_filter_for_review(settings, research_profile, args.symbols),
        )
    elif args.command == "execution-cost-audit":
        result = orchestrator.execution_cost_audit(limit=args.limit, mode=args.mode)
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
            research_profile=research_profile,
        )
    elif args.command == "walk-forward":
        horizon_bars = setup_model_horizon_bars_for_profile(research_profile, args.horizon_bars)
        split_higher_phase = setup_model_split_higher_phase_for_profile(research_profile, args.split_higher_phase)
        result = WalkForwardService(settings).run(
            windows=[parse_walk_forward_window(raw) for raw in args.window],
            symbols_filter=args.symbols,
            setup_phases=args.setup_phases,
            train_lookback_days=args.train_lookback_days,
            horizon_bars=horizon_bars,
            gap_bars=args.gap_bars,
            min_samples=args.min_samples,
            ridge_alpha=args.ridge_alpha,
            split_higher_phase=split_higher_phase,
            review_horizon_bars=args.review_horizon_bars,
            review_threshold_pct=args.review_threshold_pct,
            starting_quote=args.starting_quote,
            max_bars_per_window=args.max_bars_per_window,
            artifact_dir=args.artifact_dir,
            research_profile=research_profile,
        )
    elif args.command == "train-hourly-model":
        artifact_path = None if args.artifact_path is None else Path(args.artifact_path).expanduser()
        if artifact_path is not None and not artifact_path.is_absolute():
            artifact_path = settings.project_root / artifact_path
        result = HourlySignalModelService(settings).train(
            symbols_filter=args.symbols,
            lookback_days=args.lookback_days,
            horizon_bars=args.horizon_bars,
            ridge_alpha=args.ridge_alpha,
            artifact_path=artifact_path,
        )
    elif args.command == "train-setup-model":
        artifact_path = None if args.artifact_path is None else Path(args.artifact_path).expanduser()
        if artifact_path is not None and not artifact_path.is_absolute():
            artifact_path = settings.project_root / artifact_path
        horizon_bars = setup_model_horizon_bars_for_profile(research_profile, args.horizon_bars)
        split_higher_phase = setup_model_split_higher_phase_for_profile(research_profile, args.split_higher_phase)
        result = SetupEdgeModelService(settings).train(
            symbols_filter=args.symbols,
            setup_phases=args.setup_phases,
            lookback_days=args.lookback_days,
            horizon_bars=horizon_bars,
            min_samples=args.min_samples,
            ridge_alpha=args.ridge_alpha,
            artifact_path=artifact_path,
            split_higher_phase=split_higher_phase,
        )
    elif args.command == "setup-edge-study":
        result = SetupEdgeModelService(settings).study(
            symbols_filter=args.symbols,
            setup_phases=args.setup_phases,
            lookback_days=args.lookback_days,
            horizon_bars=args.horizon_bars,
            min_samples=args.min_samples,
            top_k=args.top_k,
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
