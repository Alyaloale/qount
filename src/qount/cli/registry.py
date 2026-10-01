"""Parser registry for the stable qount-run command surface.

Keep argument definitions separate from command execution. The public entry
point remains qount.main:main; this module has no network, state, or
settings-loading side effects.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from .legacy_research import register_legacy_research_commands
from ..ai_hold_baseline import AI_HOLD_BASELINE_PROMPT_VARIANTS
from ..settings import Settings
from ..setup_model import SETUP_EDGE_MODEL_VARIANTS
from ..setup_model import TARGET_SLICE_SETS
from ..strategy_selection import DEFAULT_CARRY_BASIS_SOURCE
from ..strategy_selection import DEFAULT_CARRY_CAPITAL_MODEL
from ..strategy_selection import DEFAULT_CARRY_EXECUTION_COST_MODEL
from ..strategy_selection import DEFAULT_DIRECTIONAL_BARRIER_VOL_LOOKBACK_BARS
from ..strategy_selection import DEFAULT_DIRECTIONAL_EMBARGO_BARS
from ..strategy_selection import DEFAULT_DIRECTIONAL_EVALUATION_MODE
from ..strategy_selection import DEFAULT_DIRECTIONAL_EXIT_MODE
from ..strategy_selection import DEFAULT_DIRECTIONAL_OVERLAP_MODE
from ..strategy_selection import DEFAULT_DIRECTIONAL_PURGED_CV_FOLDS
from ..strategy_selection import DEFAULT_DISCOVERY_END_UTC
from ..strategy_selection import DEFAULT_STRATEGY_SCAN_FAMILIES
from ..strategy_selection import DEFAULT_STRATEGY_SCAN_FREQUENCIES
from ..strategy_selection import STRATEGY_SCAN_FAMILY_CHOICES


def _add_research_profile_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--research-profile",
        choices=["eth-only", "multi-symbol"],
        default=None,
        help="Apply a canonical research profile without editing .env. Currently supports eth-only and multi-symbol.",
    )


def symbols_filter_for_review(settings: Settings, research_profile: str | None, explicit_symbols: list[str] | None) -> list[str] | None:
    """Return the explicit review universe, or the active profile universe."""

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
    config_check = subparsers.add_parser(
        "config-check",
        help="Read-only configuration preflight; never loads network clients or creates runtime state.",
    )
    config_check.add_argument("--profile", choices=["mac", "wsl", "vps"], required=True)
    config_check.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Optional trusted dotenv file. Values are never printed.",
    )
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
    strategy_scan.add_argument("--families", nargs="+", choices=STRATEGY_SCAN_FAMILY_CHOICES, default=list(DEFAULT_STRATEGY_SCAN_FAMILIES), help="Strategy families to scan. xs_funding / xs_funding_rev test funding-as-feature.")
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
        "--directional-barrier-vol-lookback-bars",
        type=int,
        default=DEFAULT_DIRECTIONAL_BARRIER_VOL_LOOKBACK_BARS,
        help="Research-only lookback bars for volatility-scaled triple_barrier; 0 keeps fixed-pct barriers.",
    )
    strategy_scan.add_argument(
        "--directional-take-profit-sigma",
        type=float,
        default=0.0,
        help="Research-only take-profit barrier as a multiple of recent return sigma (needs vol lookback > 0).",
    )
    strategy_scan.add_argument(
        "--directional-stop-loss-sigma",
        type=float,
        default=0.0,
        help="Research-only stop-loss barrier as a multiple of recent return sigma (needs vol lookback > 0).",
    )
    strategy_scan.add_argument(
        "--directional-regime-min-dispersion-pct",
        type=float,
        default=0.0,
        help="Research-only cross-sectional regime gate; skip a bar when signal dispersion is below this. 0 disables.",
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
    strategy_scan.add_argument(
        "--carry-tilt-signal",
        choices=["funding_rate", "basis_pct"],
        default="funding_rate",
        help="Field ranked cross-sectionally by the xs_funding / xs_funding_rev families.",
    )
    strategy_scan.add_argument("--output-path", default=None, help="Optional output path for the scan JSON.")
    _add_research_profile_arg(strategy_scan)
    register_legacy_research_commands(subparsers)
    dashboard = subparsers.add_parser("dashboard-snapshot", help="Return a single aggregated monitoring snapshot.")
    dashboard.add_argument("--review-limit", type=int, default=10)
    dashboard.add_argument("--review-horizon-bars", type=int, default=1)
    dashboard.add_argument("--review-threshold-pct", type=float, default=0.003)
    dashboard.add_argument("--include-exchange", action="store_true", help="Include live exchange checks and account pulls.")
    dashboard.add_argument("--include-review", action="store_true", help="Include signal-review market backfill.")
    return parser
