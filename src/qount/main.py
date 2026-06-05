from __future__ import annotations

import argparse
from typing import Any
from dataclasses import replace
import json
from pathlib import Path

from .ai_hold_baseline import AI_HOLD_BASELINE_PROMPT_VARIANTS
from .ai_hold_baseline import AIHoldBaselineService
from .artifacts import write_research_json_artifact
from .backtest import BacktestService
from .backtest import parse_backtest_datetime
from .hourly_model import HourlySignalModelService
from .idle_window_diagnostic import IdleWindowDiagnosticService
from .orchestrator import Orchestrator
from .research_profile import apply_research_profile
from .research_profile import normalize_research_profile
from .research_profile import setup_model_horizon_bars_for_profile
from .research_profile import setup_model_split_higher_phase_for_profile
from .research_slice_scan import research_slice_scan
from .setup_model import SetupEdgeModelService
from .setup_model import SETUP_EDGE_MODEL_VARIANTS
from .setup_model import TARGET_SLICE_SETS
from .settings import Settings
from .strategy_selection import DEFAULT_DISCOVERY_END_UTC
from .strategy_selection import DEFAULT_CARRY_BASIS_SOURCE
from .strategy_selection import DEFAULT_CARRY_CAPITAL_MODEL
from .strategy_selection import DEFAULT_CARRY_EXECUTION_COST_MODEL
from .strategy_selection import DEFAULT_STRATEGY_SCAN_FAMILIES
from .strategy_selection import DEFAULT_STRATEGY_SCAN_FREQUENCIES
from .strategy_selection import DEFAULT_DIRECTIONAL_EVALUATION_MODE
from .strategy_selection import DEFAULT_DIRECTIONAL_EXIT_MODE
from .strategy_selection import DEFAULT_DIRECTIONAL_EMBARGO_BARS
from .strategy_selection import DEFAULT_DIRECTIONAL_OVERLAP_MODE
from .strategy_selection import DEFAULT_DIRECTIONAL_PURGED_CV_FOLDS
from .strategy_selection import StrategySelectionScanService
from .walk_forward import parse_walk_forward_window
from .walk_forward import WalkForwardService


def _add_research_profile_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--research-profile",
        choices=["eth-only", "multi-symbol"],
        default=None,
        help="Apply a canonical research profile without editing .env. Currently supports eth-only and multi-symbol.",
    )


def _symbols_filter_for_review(settings: Settings, research_profile: str | None, explicit_symbols: list[str] | None) -> list[str] | None:
    if explicit_symbols is not None:
        return explicit_symbols
    if research_profile is not None:
        return list(settings.symbols)
    return None


def _add_research_exit_override_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--trailing-arm-pct",
        type=float,
        default=None,
        help="Optional research-only trailing profit arm override, as a fraction such as 0.003.",
    )
    parser.add_argument(
        "--trailing-retrace-pct",
        type=float,
        default=None,
        help="Optional research-only trailing retrace override, as a fraction such as 0.005.",
    )


def _add_research_shadow_candidate_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--research-shadow-candidate-tags",
        nargs="+",
        default=None,
        help=(
            "Research-only isolated candidate exposure: only fresh-entry snapshots "
            "matching one of these research_slice_tags are sent through AI/risk."
        ),
    )


def _add_research_run_metadata_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--holdout-role",
        choices=["discovery", "validation_v1", "unknown"],
        default="unknown",
        help="Machine-readable anti-overfit role for this research artifact.",
    )
    parser.add_argument(
        "--ai-decision-cache",
        action="store_true",
        help="Enable research-only AI decision cache for historical backtest/walk-forward runs.",
    )


def apply_command_settings_overrides(settings: Settings, args: argparse.Namespace) -> Settings:
    updates: dict[str, Any] = {}
    trailing_arm_pct = getattr(args, "trailing_arm_pct", None)
    trailing_retrace_pct = getattr(args, "trailing_retrace_pct", None)
    shadow_candidate_tags = getattr(args, "research_shadow_candidate_tags", None)
    if trailing_arm_pct is not None:
        updates["trailing_profit_arm_pct"] = trailing_arm_pct
    if trailing_retrace_pct is not None:
        updates["trailing_profit_retrace_pct"] = trailing_retrace_pct
    if shadow_candidate_tags is not None:
        updates["research_shadow_candidate_tags"] = tuple(
            tag.strip()
            for tag in shadow_candidate_tags
            if str(tag).strip()
        )
    if not updates:
        return settings
    return replace(settings, **updates)


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
    _add_research_exit_override_args(backtest)
    _add_research_shadow_candidate_args(backtest)
    _add_research_run_metadata_args(backtest)
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
    walk_forward.add_argument("--setup-model-version", choices=SETUP_EDGE_MODEL_VARIANTS, default="v1")
    walk_forward.add_argument("--review-horizon-bars", type=int, default=3)
    walk_forward.add_argument("--review-threshold-pct", type=float, default=0.003)
    walk_forward.add_argument("--starting-quote", type=float, default=None)
    walk_forward.add_argument("--max-bars-per-window", type=int, default=None, help="Optional cap on processed bars for each validation window.")
    walk_forward.add_argument("--artifact-dir", default=None, help="Optional output directory for the walk-forward run.")
    _add_research_exit_override_args(walk_forward)
    _add_research_shadow_candidate_args(walk_forward)
    _add_research_run_metadata_args(walk_forward)
    _add_research_profile_arg(walk_forward)
    setup_edge_wf = subparsers.add_parser("setup-edge-walk-forward", help="Train per-window setup models only; do not run AI, risk, or paper execution.")
    setup_edge_wf.add_argument("--window", action="append", default=[], help="Validation window as label=START,END. May be repeated.")
    setup_edge_wf.add_argument("--symbols", nargs="+", default=None, help="Optional symbol filter, for example ETH/USDT.")
    setup_edge_wf.add_argument("--setup-phases", nargs="+", default=None, help="Optional setup-phase filter.")
    setup_edge_wf.add_argument("--train-lookback-days", type=int, default=90)
    setup_edge_wf.add_argument("--horizon-bars", type=int, default=None)
    setup_edge_wf.add_argument("--gap-bars", type=int, default=1, help="Completed 5m bars between the training label cutoff and validation start.")
    setup_edge_wf.add_argument("--min-samples", type=int, default=60)
    setup_edge_wf.add_argument("--ridge-alpha", type=float, default=0.0005)
    setup_edge_wf.add_argument("--split-higher-phase", action="store_true", default=None)
    setup_edge_wf.add_argument("--setup-model-version", choices=SETUP_EDGE_MODEL_VARIANTS, default="v1")
    setup_edge_wf.add_argument("--artifact-dir", default=None, help="Optional output directory for the setup-edge walk-forward run.")
    setup_edge_wf.add_argument("--holdout-role", choices=["discovery", "validation_v1", "unknown"], default="unknown")
    _add_research_profile_arg(setup_edge_wf)
    candidate_wf = subparsers.add_parser("candidate-walk-forward", help="Train per-window setup models and run candidate filter statistics only; do not call AI or execute.")
    candidate_wf.add_argument("--window", action="append", default=[], help="Validation window as label=START,END. May be repeated.")
    candidate_wf.add_argument("--symbols", nargs="+", default=None, help="Optional symbol filter, for example ETH/USDT.")
    candidate_wf.add_argument("--setup-phases", nargs="+", default=None, help="Optional setup-phase filter.")
    candidate_wf.add_argument("--train-lookback-days", type=int, default=90)
    candidate_wf.add_argument("--horizon-bars", type=int, default=None)
    candidate_wf.add_argument("--gap-bars", type=int, default=1, help="Completed 5m bars between the training label cutoff and validation start.")
    candidate_wf.add_argument("--min-samples", type=int, default=60)
    candidate_wf.add_argument("--ridge-alpha", type=float, default=0.0005)
    candidate_wf.add_argument("--split-higher-phase", action="store_true", default=None)
    candidate_wf.add_argument("--setup-model-version", choices=SETUP_EDGE_MODEL_VARIANTS, default="v1")
    candidate_wf.add_argument("--max-bars-per-window", type=int, default=None, help="Optional cap on processed bars for each validation window.")
    candidate_wf.add_argument("--artifact-dir", default=None, help="Optional output directory for the candidate walk-forward run.")
    candidate_wf.add_argument("--holdout-role", choices=["discovery", "validation_v1", "unknown"], default="unknown")
    _add_research_profile_arg(candidate_wf)
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
    setup_model.add_argument("--setup-model-version", choices=SETUP_EDGE_MODEL_VARIANTS, default="v1")
    setup_model.add_argument("--artifact-path", default=None, help="Optional output path for the trained setup-model JSON.")
    _add_research_profile_arg(setup_model)
    setup_compare = subparsers.add_parser("setup-model-compare", help="Compare setup-model v1 vs v2 interaction features on a chronological offline split.")
    setup_compare.add_argument("--symbols", nargs="+", default=None, help="Optional symbol filter.")
    setup_compare.add_argument("--setup-phases", nargs="+", default=None, help="Optional setup-phase filter.")
    setup_compare.add_argument("--lookback-days", type=int, default=120)
    setup_compare.add_argument("--horizon-bars", type=int, default=None)
    setup_compare.add_argument("--min-samples", type=int, default=20)
    setup_compare.add_argument("--ridge-alpha", type=float, default=0.0005)
    setup_compare.add_argument("--split-higher-phase", action="store_true", default=None)
    setup_compare.add_argument("--eval-fraction", type=float, default=0.30, help="Chronological tail fraction reserved for evaluation.")
    setup_compare.add_argument("--output-path", default=None, help="Optional output path for the comparison JSON.")
    _add_research_profile_arg(setup_compare)
    setup_study = subparsers.add_parser("setup-edge-study", help="Study historical post-cost edge by symbol, setup phase, and traditional pattern.")
    setup_study.add_argument("--symbols", nargs="+", default=None, help="Optional symbol filter.")
    setup_study.add_argument("--setup-phases", nargs="+", default=None, help="Optional setup-phase filter.")
    setup_study.add_argument("--lookback-days", type=int, default=120)
    setup_study.add_argument("--horizon-bars", type=int, default=None)
    setup_study.add_argument("--min-samples", type=int, default=20)
    setup_study.add_argument("--top-k", type=int, default=12)
    setup_study.add_argument("--discover-slices", action="store_true", help="Add offline multi-feature edge slice discovery to the study output.")
    setup_study.add_argument("--stability-splits", type=int, default=4, help="Chronological folds used to summarize discovered slice stability.")
    setup_study.add_argument("--target-slice-set", choices=TARGET_SLICE_SETS, default=None, help="Add a named offline target-slice summary to the study output.")
    setup_study.add_argument("--artifact-path", default=None, help="Optional output path for the setup edge study JSON.")
    _add_research_profile_arg(setup_study)
    slice_scan = subparsers.add_parser("research-slice-scan", help="Scan existing backtest or walk-forward artifacts for offline research-slice tag coverage.")
    slice_scan.add_argument("--artifact-dir", required=True, help="Existing backtest or walk-forward artifact directory to scan.")
    slice_scan.add_argument("--symbols", nargs="+", default=None, help="Optional symbol filter, for example ETH/USDT.")
    slice_scan.add_argument("--target-tags", nargs="+", default=None, help="Optional research slice tags to highlight.")
    slice_scan.add_argument("--horizon-bars", nargs="+", type=int, default=None, help="Future snapshot horizons used for offline tag edge summaries.")
    slice_scan.add_argument("--output-path", default=None, help="Optional output path for the scan JSON.")
    _add_research_profile_arg(slice_scan)
    ai_hold = subparsers.add_parser("ai-hold-baseline", help="Replay historical fresh-entry AI prompts to quantify hold bias.")
    ai_hold.add_argument("--artifact-dir", required=True, help="Existing backtest or walk-forward artifact directory to sample.")
    ai_hold.add_argument("--prompt-variant", choices=AI_HOLD_BASELINE_PROMPT_VARIANTS, default="v1")
    ai_hold.add_argument("--repeat", type=int, default=1, help="Number of fresh AI calls per selected sample.")
    ai_hold.add_argument("--limit", type=int, default=20, help="Maximum prompt samples to replay.")
    ai_hold.add_argument("--run-ids", nargs="+", type=int, default=None, help="Optional run_id filter inside each backtest database.")
    ai_hold.add_argument("--symbols", nargs="+", default=None, help="Optional symbol filter, for example ETH/USDT.")
    ai_hold.add_argument("--target-tags", nargs="+", default=None, help="Optional research_slice_tags that selected samples must contain.")
    ai_hold.add_argument("--dry-run", action="store_true", help="Only enumerate samples and stored actions; do not call AI.")
    ai_hold.add_argument("--output-path", default=None, help="Optional output path for the diagnostic JSON.")
    _add_research_profile_arg(ai_hold)
    idle_diag = subparsers.add_parser("idle-window-diagnostic", help="Summarize 0-trade windows without calling AI or changing strategy behavior.")
    idle_diag.add_argument("--artifact-dir", required=True, help="Existing backtest or walk-forward artifact directory to inspect.")
    idle_diag.add_argument("--symbols", nargs="+", default=None, help="Optional symbol filter, for example ETH/USDT.")
    idle_diag.add_argument("--horizon-bars", type=int, default=6, help="Future bars used for top candidate edge diagnostics.")
    idle_diag.add_argument("--top-candidates", type=int, default=5, help="Top scored candidates per idle window to include.")
    idle_diag.add_argument("--reason-limit", type=int, default=10, help="Maximum reasons/patterns to include in histograms.")
    idle_diag.add_argument("--include-traded-windows", action="store_true", help="Also include windows with paper fills/closes.")
    idle_diag.add_argument("--output-path", default=None, help="Optional output path for the diagnostic JSON.")
    _add_research_profile_arg(idle_diag)
    strategy_scan = subparsers.add_parser("strategy-selection-scan", help="Research-only S1' frequency x strategy-family scan over discovery data.")
    strategy_scan.add_argument("--symbols", nargs="+", default=None, help="Optional symbol filter, for example SOL/USDT XRP/USDT BTC/USDT ETH/USDT.")
    strategy_scan.add_argument("--frequencies", nargs="+", default=list(DEFAULT_STRATEGY_SCAN_FREQUENCIES), help="Timeframes to scan, default: 5m 1h 4h 1d.")
    strategy_scan.add_argument("--families", nargs="+", choices=DEFAULT_STRATEGY_SCAN_FAMILIES, default=list(DEFAULT_STRATEGY_SCAN_FAMILIES), help="Strategy families to scan.")
    strategy_scan.add_argument("--start", default=None, help="Optional discovery scan start time. Defaults to end minus --lookback-days.")
    strategy_scan.add_argument("--end", default=DEFAULT_DISCOVERY_END_UTC.isoformat(), help="Discovery scan end time; default freezes at validation_v1 boundary.")
    strategy_scan.add_argument("--holdout-role", choices=["discovery", "validation_v1", "unknown"], default="discovery")
    strategy_scan.add_argument("--lookback-days", type=int, default=120)
    strategy_scan.add_argument("--signal-lookback-bars", type=int, default=12)
    strategy_scan.add_argument("--holding-bars", type=int, default=1)
    strategy_scan.add_argument(
        "--signal-lookback-grid-bars",
        nargs="+",
        type=int,
        default=None,
        help="Research-only directional family grid over signal lookback bars; default uses --signal-lookback-bars.",
    )
    strategy_scan.add_argument(
        "--holding-grid-bars",
        nargs="+",
        type=int,
        default=None,
        help="Research-only directional family grid over holding bars; default uses --holding-bars.",
    )
    strategy_scan.add_argument(
        "--directional-overlap-mode",
        choices=["all", "stride"],
        default=DEFAULT_DIRECTIONAL_OVERLAP_MODE,
        help="Research-only overlap control for directional families; stride keeps one cross-section per holding window.",
    )
    strategy_scan.add_argument(
        "--directional-evaluation-mode",
        choices=["cross_section", "portfolio_replay"],
        default=DEFAULT_DIRECTIONAL_EVALUATION_MODE,
        help="Research-only directional evaluation mode; portfolio_replay simulates overlapping held signals.",
    )
    strategy_scan.add_argument(
        "--directional-max-open-positions",
        type=int,
        default=0,
        help="Research-only cap for portfolio_replay open positions; 0 means unlimited diagnostic capacity.",
    )
    strategy_scan.add_argument(
        "--directional-exit-mode",
        choices=["close", "triple_barrier"],
        default=DEFAULT_DIRECTIONAL_EXIT_MODE,
        help="Research-only directional exit model; triple_barrier uses OHLC highs/lows during the holding window.",
    )
    strategy_scan.add_argument(
        "--directional-take-profit-pct",
        type=float,
        default=0.0,
        help="Research-only take-profit barrier for --directional-exit-mode triple_barrier.",
    )
    strategy_scan.add_argument(
        "--directional-stop-loss-pct",
        type=float,
        default=0.0,
        help="Research-only stop-loss barrier for --directional-exit-mode triple_barrier.",
    )
    strategy_scan.add_argument(
        "--directional-purged-cv-folds",
        type=int,
        default=DEFAULT_DIRECTIONAL_PURGED_CV_FOLDS,
        help="Research-only chronological fold diagnostics for directional families; 0 disables.",
    )
    strategy_scan.add_argument(
        "--directional-embargo-bars",
        type=int,
        default=DEFAULT_DIRECTIONAL_EMBARGO_BARS,
        help="Research-only embargo bars reported around each directional purged-CV fold.",
    )
    strategy_scan.add_argument("--min-cross-section-symbols", type=int, default=3)
    strategy_scan.add_argument("--top-fraction", type=float, default=0.25)
    strategy_scan.add_argument("--carry-model", choices=["naive", "threshold_dual_leg"], default="naive")
    strategy_scan.add_argument("--carry-entry-threshold-pct", type=float, default=0.0)
    strategy_scan.add_argument("--carry-exit-threshold-pct", type=float, default=None)
    strategy_scan.add_argument("--carry-min-hold-periods", type=int, default=1)
    strategy_scan.add_argument("--carry-entry-threshold-grid-pct", nargs="+", type=float, default=None)
    strategy_scan.add_argument("--carry-exit-threshold-grid-pct", nargs="+", type=float, default=None)
    strategy_scan.add_argument("--carry-min-hold-grid", nargs="+", type=int, default=None)
    strategy_scan.add_argument("--carry-basis-source", choices=["funding_history", "premium_index"], default=DEFAULT_CARRY_BASIS_SOURCE)
    strategy_scan.add_argument(
        "--carry-execution-cost-model",
        choices=["directional_round_trip", "per_order"],
        default=DEFAULT_CARRY_EXECUTION_COST_MODEL,
        help="Research-only CARRY execution cost interpretation; default preserves prior artifact semantics.",
    )
    strategy_scan.add_argument(
        "--carry-capital-model",
        choices=["perp_notional", "spot_perp_gross"],
        default=DEFAULT_CARRY_CAPITAL_MODEL,
        help="Research-only CARRY return denominator; spot_perp_gross divides by spot notional plus perp margin.",
    )
    strategy_scan.add_argument(
        "--carry-perp-margin-fraction",
        type=float,
        default=1.0,
        help="Perp margin capital per 1.0 perp notional when --carry-capital-model spot_perp_gross is used.",
    )
    strategy_scan.add_argument(
        "--carry-basis-tail-stop-pct",
        type=float,
        default=None,
        help="Research-only CARRY basis stop; closes a dual-leg carry position when abs(basis_pct) reaches this threshold.",
    )
    strategy_scan.add_argument(
        "--carry-basis-entry-max-abs-pct",
        type=float,
        default=None,
        help="Research-only CARRY basis regime filter; blocks new entries when abs(basis_pct) is above this threshold.",
    )
    strategy_scan.add_argument(
        "--carry-maker-order-cost-pct",
        type=float,
        default=None,
        help="Research-only post-only diagnostic maker order cost; used only to compute required maker fill rate.",
    )
    strategy_scan.add_argument(
        "--carry-taker-order-cost-pct",
        type=float,
        default=None,
        help="Research-only post-only diagnostic taker order cost; used only to compute required maker fill rate.",
    )
    strategy_scan.add_argument("--output-path", default=None, help="Optional output path for the scan JSON.")
    _add_research_profile_arg(strategy_scan)
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
    settings = apply_command_settings_overrides(settings, args)
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
            holdout_role=args.holdout_role,
            ai_decision_cache_enable=args.ai_decision_cache,
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
            setup_model_version=args.setup_model_version,
            review_horizon_bars=args.review_horizon_bars,
            review_threshold_pct=args.review_threshold_pct,
            starting_quote=args.starting_quote,
            max_bars_per_window=args.max_bars_per_window,
            artifact_dir=args.artifact_dir,
            research_profile=research_profile,
            holdout_role=args.holdout_role,
            ai_decision_cache_enable=args.ai_decision_cache,
        )
    elif args.command == "setup-edge-walk-forward":
        horizon_bars = setup_model_horizon_bars_for_profile(research_profile, args.horizon_bars)
        split_higher_phase = setup_model_split_higher_phase_for_profile(research_profile, args.split_higher_phase)
        result = WalkForwardService(settings).run_setup_edge(
            windows=[parse_walk_forward_window(raw) for raw in args.window],
            symbols_filter=args.symbols,
            setup_phases=args.setup_phases,
            train_lookback_days=args.train_lookback_days,
            horizon_bars=horizon_bars,
            gap_bars=args.gap_bars,
            min_samples=args.min_samples,
            ridge_alpha=args.ridge_alpha,
            split_higher_phase=split_higher_phase,
            setup_model_version=args.setup_model_version,
            artifact_dir=args.artifact_dir,
            research_profile=research_profile,
            holdout_role=args.holdout_role,
        )
    elif args.command == "candidate-walk-forward":
        horizon_bars = setup_model_horizon_bars_for_profile(research_profile, args.horizon_bars)
        split_higher_phase = setup_model_split_higher_phase_for_profile(research_profile, args.split_higher_phase)
        result = WalkForwardService(settings).run_candidate(
            windows=[parse_walk_forward_window(raw) for raw in args.window],
            symbols_filter=args.symbols,
            setup_phases=args.setup_phases,
            train_lookback_days=args.train_lookback_days,
            horizon_bars=horizon_bars,
            gap_bars=args.gap_bars,
            min_samples=args.min_samples,
            ridge_alpha=args.ridge_alpha,
            split_higher_phase=split_higher_phase,
            setup_model_version=args.setup_model_version,
            max_bars_per_window=args.max_bars_per_window,
            artifact_dir=args.artifact_dir,
            research_profile=research_profile,
            holdout_role=args.holdout_role,
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
            model_version=args.setup_model_version,
        )
    elif args.command == "setup-model-compare":
        horizon_bars = setup_model_horizon_bars_for_profile(research_profile, args.horizon_bars)
        split_higher_phase = setup_model_split_higher_phase_for_profile(research_profile, args.split_higher_phase)
        result = SetupEdgeModelService(settings).compare_versions(
            symbols_filter=args.symbols,
            setup_phases=args.setup_phases,
            lookback_days=args.lookback_days,
            horizon_bars=horizon_bars,
            min_samples=args.min_samples,
            ridge_alpha=args.ridge_alpha,
            split_higher_phase=split_higher_phase,
            eval_fraction=args.eval_fraction,
        )
        result = write_research_json_artifact(
            settings,
            result,
            kind="setup-model-compare",
            path_key="output_path",
            default_filename="setup_model_compare.json",
            explicit_path=args.output_path,
        )
    elif args.command == "setup-edge-study":
        horizon_bars = setup_model_horizon_bars_for_profile(research_profile, args.horizon_bars)
        result = SetupEdgeModelService(settings).study(
            symbols_filter=args.symbols,
            setup_phases=args.setup_phases,
            lookback_days=args.lookback_days,
            horizon_bars=horizon_bars,
            min_samples=args.min_samples,
            top_k=args.top_k,
            discover_slices=args.discover_slices,
            stability_splits=args.stability_splits,
            target_slice_set=args.target_slice_set,
        )
        result = write_research_json_artifact(
            settings,
            result,
            kind="setup-edge-study",
            path_key="artifact_path",
            default_filename="setup_edge_study.json",
            explicit_path=args.artifact_path,
        )
    elif args.command == "research-slice-scan":
        result = research_slice_scan(
            Path(args.artifact_dir),
            symbols_filter=_symbols_filter_for_review(settings, research_profile, args.symbols),
            target_tags=args.target_tags,
            horizon_bars=args.horizon_bars,
            contract_market=settings.contract_market,
            fee_pct=settings.estimated_fee_pct,
            slippage_pct=settings.estimated_slippage_pct,
        )
        result = write_research_json_artifact(
            settings,
            result,
            kind="research-slice-scan",
            path_key="output_path",
            default_filename="research_slice_scan.json",
            explicit_path=args.output_path,
        )
    elif args.command == "ai-hold-baseline":
        result = AIHoldBaselineService(settings).run(
            artifact_dir=Path(args.artifact_dir),
            prompt_variant=args.prompt_variant,
            repeat=args.repeat,
            limit=args.limit,
            run_ids=args.run_ids,
            target_tags=args.target_tags,
            symbols_filter=_symbols_filter_for_review(settings, research_profile, args.symbols),
            dry_run=args.dry_run,
        )
        result = write_research_json_artifact(
            settings,
            result,
            kind="ai-hold-baseline",
            path_key="output_path",
            default_filename="ai_hold_baseline.json",
            explicit_path=args.output_path,
        )
    elif args.command == "idle-window-diagnostic":
        result = IdleWindowDiagnosticService(settings).run(
            artifact_dir=Path(args.artifact_dir),
            symbols_filter=_symbols_filter_for_review(settings, research_profile, args.symbols),
            horizon_bars=args.horizon_bars,
            top_candidates=args.top_candidates,
            reason_limit=args.reason_limit,
            include_traded_windows=args.include_traded_windows,
        )
        result = write_research_json_artifact(
            settings,
            result,
            kind="idle-window-diagnostic",
            path_key="output_path",
            default_filename="idle_window_diagnostic.json",
            explicit_path=args.output_path,
        )
    elif args.command == "strategy-selection-scan":
        result = StrategySelectionScanService(settings).run(
            symbols_filter=args.symbols,
            frequencies=args.frequencies,
            families=args.families,
            start=None if args.start is None else parse_backtest_datetime(args.start),
            end=None if args.end is None else parse_backtest_datetime(args.end),
            lookback_days=args.lookback_days,
            signal_lookback_bars=args.signal_lookback_bars,
            holding_bars=args.holding_bars,
            signal_lookback_grid_bars=args.signal_lookback_grid_bars,
            holding_grid_bars=args.holding_grid_bars,
            directional_overlap_mode=args.directional_overlap_mode,
            directional_evaluation_mode=args.directional_evaluation_mode,
            directional_max_open_positions=args.directional_max_open_positions,
            directional_exit_mode=args.directional_exit_mode,
            directional_take_profit_pct=args.directional_take_profit_pct,
            directional_stop_loss_pct=args.directional_stop_loss_pct,
            directional_purged_cv_folds=args.directional_purged_cv_folds,
            directional_embargo_bars=args.directional_embargo_bars,
            min_cross_section_symbols=args.min_cross_section_symbols,
            top_fraction=args.top_fraction,
            carry_model=args.carry_model,
            carry_entry_threshold_pct=args.carry_entry_threshold_pct,
            carry_exit_threshold_pct=args.carry_exit_threshold_pct,
            carry_min_hold_periods=args.carry_min_hold_periods,
            carry_entry_threshold_grid_pct=args.carry_entry_threshold_grid_pct,
            carry_exit_threshold_grid_pct=args.carry_exit_threshold_grid_pct,
            carry_min_hold_grid=args.carry_min_hold_grid,
            carry_basis_source=args.carry_basis_source,
            carry_execution_cost_model=args.carry_execution_cost_model,
            carry_capital_model=args.carry_capital_model,
            carry_perp_margin_fraction=args.carry_perp_margin_fraction,
            carry_basis_tail_stop_pct=args.carry_basis_tail_stop_pct,
            carry_basis_entry_max_abs_pct=args.carry_basis_entry_max_abs_pct,
            carry_maker_order_cost_pct=args.carry_maker_order_cost_pct,
            carry_taker_order_cost_pct=args.carry_taker_order_cost_pct,
            holdout_role=args.holdout_role,
        )
        result = write_research_json_artifact(
            settings,
            result,
            kind="strategy-selection-scan",
            path_key="output_path",
            default_filename="strategy_selection_scan.json",
            explicit_path=args.output_path,
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
