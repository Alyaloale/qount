from __future__ import annotations

import json
from pathlib import Path

from .ai_hold_baseline import AI_HOLD_BASELINE_PROMPT_VARIANTS
from .ai_hold_baseline import AIHoldBaselineService
from .artifacts import write_research_json_artifact
from .backtest import BacktestService
from .backtest import parse_backtest_datetime
from .cli.registry import apply_command_settings_overrides
from .cli.registry import build_parser
from .cli.registry import symbols_filter_for_review
from .config_contract import check_environment
from .hourly_model import HourlySignalModelService
from .idle_window_diagnostic import IdleWindowDiagnosticService
from .l1_cross_asset import L1CrossAssetBreadthService
from .l1_cross_asset import L1TimeSeriesMomentumService
from .l4_cross_exchange import L4CrossExchangeFundingService
from .l3_information_edge import L3ChainTvlCrossSectionService
from .l3_information_edge import L3StablecoinSupplyService
from .l3_information_edge import L3StablecoinTimingService
from .orchestrator import Orchestrator
from .research_profile import apply_research_profile
from .research_profile import normalize_research_profile
from .research_profile import setup_model_horizon_bars_for_profile
from .research_profile import setup_model_split_higher_phase_for_profile
from .research_slice_scan import research_slice_scan
from .setup_model import SetupEdgeModelService
from .settings import Settings
from .strategy_selection import StrategySelectionScanService
from .walk_forward import parse_walk_forward_window
from .walk_forward import WalkForwardService


def main() -> None:
    # The CTA-R sim is self-contained and settings-free; delegate to its full CLI (single
    # source of truth) before building the heavy parser / loading Settings.
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "cta-paper-sim":
        from .cta_sim import main as cta_sim_main

        raise SystemExit(cta_sim_main(sys.argv[2:]))

    parser = build_parser()
    args = parser.parse_args()
    if args.command == "config-check":
        result = check_environment(profile=args.profile, env_file=args.env_file)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result["ok"]:
            raise SystemExit(2)
        return
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
            symbols_filter=symbols_filter_for_review(settings, research_profile, args.symbols),
        )
    elif args.command == "signal-review-study":
        result = orchestrator.signal_review_study(
            limit=args.limit,
            horizons=args.horizons,
            threshold_pct=args.threshold_pct,
            replay_current_risk=args.replay_current_risk,
            symbols_filter=symbols_filter_for_review(settings, research_profile, args.symbols),
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
            symbols_filter=symbols_filter_for_review(settings, research_profile, args.symbols),
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
            symbols_filter=symbols_filter_for_review(settings, research_profile, args.symbols),
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
            symbols_filter=symbols_filter_for_review(settings, research_profile, args.symbols),
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
            directional_barrier_vol_lookback_bars=args.directional_barrier_vol_lookback_bars,
            directional_take_profit_sigma=args.directional_take_profit_sigma,
            directional_stop_loss_sigma=args.directional_stop_loss_sigma,
            directional_regime_min_dispersion_pct=args.directional_regime_min_dispersion_pct,
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
            carry_tilt_signal_field=args.carry_tilt_signal,
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
    elif args.command == "l3-stablecoin-fetch":
        result = L3StablecoinSupplyService(settings).run(
            start_ms=None if args.start is None else int(parse_backtest_datetime(args.start).timestamp() * 1000),
            end_ms=None if args.end is None else int(parse_backtest_datetime(args.end).timestamp() * 1000),
            cache_path=args.cache_path,
            url=args.url,
            force_refresh=args.force_refresh,
        )
        result = write_research_json_artifact(
            settings,
            result,
            kind="l3-stablecoin-fetch",
            path_key="output_path",
            default_filename="l3_stablecoin_fetch.json",
            explicit_path=args.output_path,
        )
    elif args.command == "l3-stablecoin-timing-scan":
        result = L3StablecoinTimingService(settings).run(
            start_ms=int(parse_backtest_datetime(args.start).timestamp() * 1000),
            end_ms=int(parse_backtest_datetime(args.end).timestamp() * 1000),
            symbol=args.symbol,
            signal_lookback_weeks_grid=args.signal_lookback_weeks_grid,
            horizon_weeks_grid=args.horizon_weeks_grid,
            cost_per_side_pct=args.cost_per_side_pct,
            supply_cache_path=args.supply_cache_path,
            price_cache_path=args.price_cache_path,
            url=args.url,
            force_refresh=args.force_refresh,
            holdout_role=args.holdout_role,
        )
        result = write_research_json_artifact(
            settings,
            result,
            kind="l3-stablecoin-timing-scan",
            path_key="output_path",
            default_filename="l3_stablecoin_timing_scan.json",
            explicit_path=args.output_path,
        )
    elif args.command == "l3-chain-tvl-scan":
        chain_token_map = None
        if args.tokens:
            from .l3_information_edge import L3B_DEFAULT_CHAIN_TOKEN_MAP

            missing = [token for token in args.tokens if token not in L3B_DEFAULT_CHAIN_TOKEN_MAP]
            if missing:
                parser.error(f"unknown chain tokens (no TVL mapping): {missing}")
            chain_token_map = {token: L3B_DEFAULT_CHAIN_TOKEN_MAP[token] for token in args.tokens}
        result = L3ChainTvlCrossSectionService(settings).run(
            start_ms=int(parse_backtest_datetime(args.start).timestamp() * 1000),
            end_ms=int(parse_backtest_datetime(args.end).timestamp() * 1000),
            chain_token_map=chain_token_map,
            signal_lookback_weeks_grid=args.signal_lookback_weeks_grid,
            horizon_weeks_grid=args.horizon_weeks_grid,
            cost_per_side_pct=args.cost_per_side_pct,
            top_fraction=args.top_fraction,
            min_cross_section_tokens=args.min_cross_section_tokens,
            cache_dir=args.cache_dir,
            force_refresh=args.force_refresh,
            holdout_role=args.holdout_role,
        )
        result = write_research_json_artifact(
            settings,
            result,
            kind="l3-chain-tvl-scan",
            path_key="output_path",
            default_filename="l3_chain_tvl_scan.json",
            explicit_path=args.output_path,
        )
    elif args.command == "l1-cross-asset-breadth-scan":
        result = L1CrossAssetBreadthService(settings).run(
            start_ms=int(parse_backtest_datetime(args.start).timestamp() * 1000),
            end_ms=int(parse_backtest_datetime(args.end).timestamp() * 1000),
            tickers=args.tickers,
            start_date=args.start_date,
            cache_dir=args.cache_dir,
            force_refresh=args.force_refresh,
            holdout_role=args.holdout_role,
        )
        result = write_research_json_artifact(
            settings,
            result,
            kind="l1-cross-asset-breadth-scan",
            path_key="output_path",
            default_filename="l1_cross_asset_breadth_scan.json",
            explicit_path=args.output_path,
        )
    elif args.command == "l1-cross-asset-tsmom-scan":
        result = L1TimeSeriesMomentumService(settings).run(
            start_ms=int(parse_backtest_datetime(args.start).timestamp() * 1000),
            end_ms=int(parse_backtest_datetime(args.end).timestamp() * 1000),
            tickers=args.tickers,
            lookback_weeks_grid=args.lookback_weeks_grid,
            vol_lookback_weeks=args.vol_lookback_weeks,
            cost_per_side_pct=args.cost_per_side_pct,
            ensemble=args.ensemble,
            n_folds=args.n_folds,
            start_date=args.start_date,
            cache_dir=args.cache_dir,
            force_refresh=args.force_refresh,
            holdout_role=args.holdout_role,
        )
        result = write_research_json_artifact(
            settings,
            result,
            kind="l1-cross-asset-tsmom-scan",
            path_key="output_path",
            default_filename="l1_cross_asset_tsmom_scan.json",
            explicit_path=args.output_path,
        )
    elif args.command == "l4-cross-exchange-funding-scan":
        result = L4CrossExchangeFundingService(settings).run(
            start_ms=int(parse_backtest_datetime(args.start).timestamp() * 1000),
            end_ms=int(parse_backtest_datetime(args.end).timestamp() * 1000),
            venues=args.venues,
            symbols=args.symbols,
            cost_per_side_pct=args.cost_per_side_pct,
            taker_cost_per_side_pct=args.taker_cost_per_side_pct,
            cache_dir=args.cache_dir,
            force_refresh=args.force_refresh,
            holdout_role=args.holdout_role,
        )
        result = write_research_json_artifact(
            settings,
            result,
            kind="l4-cross-exchange-funding-scan",
            path_key="output_path",
            default_filename="l4_cross_exchange_funding_scan.json",
            explicit_path=args.output_path,
        )
    elif args.command == "l6-microstructure-ic-scan":
        from .l6_microstructure import HORIZONS_MS
        from .l6_microstructure import run_l6_microstructure_ic_scan

        result = run_l6_microstructure_ic_scan(
            args.data_dir,
            args.symbols,
            horizons_ms=tuple(args.horizons_ms) if args.horizons_ms else HORIZONS_MS,
            cost_per_side_pct=args.cost_per_side_pct,
            ic_gate=args.ic_gate,
            holdout_role=args.holdout_role,
        )
        result = write_research_json_artifact(
            settings,
            result,
            kind="l6-microstructure-ic-scan",
            path_key="output_path",
            default_filename="l6_microstructure_ic_scan.json",
            explicit_path=args.output_path,
        )
    elif args.command == "l6-daily-features":
        import re as _re

        from .l6_microstructure import DAILY_FEATURES
        from .l6_microstructure import L6_MICROSTRUCTURE_VERSION
        from .l6_microstructure import compute_daily_feature_panel

        day_dir = Path(args.day_dir)
        if args.all_symbols:
            symbols = sorted(p.name for p in day_dir.iterdir()
                             if p.is_dir() and _re.fullmatch(r"\d+\.(SZ|SH)", p.name))
        elif args.symbols:
            symbols = args.symbols
        else:
            parser.error("l6-daily-features needs --symbols or --all-symbols")
        panel = compute_daily_feature_panel(day_dir, symbols)
        result = {
            "version": L6_MICROSTRUCTURE_VERSION,
            "day_dir": str(day_dir),
            "feature_names": list(DAILY_FEATURES),
            "n_symbols_requested": len(symbols),
            "n_symbols_scored": len(panel),
            "features": panel,
        }
        result = write_research_json_artifact(
            settings,
            result,
            kind="l6-daily-features",
            path_key="output_path",
            default_filename="l6_daily_features.json",
            explicit_path=args.output_path,
        )
    elif args.command == "l6-daily-d1-scan":
        import glob

        from .l6_microstructure import evaluate_l6_daily_d1
        from .l6_microstructure import load_daily_panels

        paths = sorted(glob.glob(str(Path(args.panel_dir) / "**" / "l6_daily_*.json"), recursive=True))
        if not paths:
            parser.error(f"no l6_daily_*.json panels under {args.panel_dir}")
        panels = load_daily_panels(paths)
        result = evaluate_l6_daily_d1(
            panels,
            universe=args.universe,
            active_top_n=args.active_top_n,
            holding=args.holding,
            top_fraction=args.top_fraction,
        )
        result = write_research_json_artifact(
            settings,
            result,
            kind="l6-daily-d1-scan",
            path_key="output_path",
            default_filename="l6_daily_d1_scan.json",
            explicit_path=args.output_path,
        )
    elif args.command == "l6-daily-d2-scan":
        import glob

        from .l6_microstructure import evaluate_l6_daily_d2
        from .l6_microstructure import load_daily_panels

        paths = sorted(glob.glob(str(Path(args.panel_dir) / "**" / "l6_daily_*.json"), recursive=True))
        if not paths:
            parser.error(f"no l6_daily_*.json panels under {args.panel_dir}")
        panels = load_daily_panels(paths)
        result = evaluate_l6_daily_d2(
            panels,
            target_feature=args.target_feature,
            baseline_lookback=args.baseline_lookback,
            universe=args.universe,
            active_top_n=args.active_top_n,
            holding=args.holding,
        )
        result = write_research_json_artifact(
            settings,
            result,
            kind="l6-daily-d2-scan",
            path_key="output_path",
            default_filename="l6_daily_d2_scan.json",
            explicit_path=args.output_path,
        )
    elif args.command == "l6-daily-d4-scan":
        import glob

        from .l6_microstructure import evaluate_l6_daily_d4
        from .l6_microstructure import load_daily_panels

        paths = sorted(glob.glob(str(Path(args.panel_dir) / "**" / "l6_daily_*.json"), recursive=True))
        if not paths:
            parser.error(f"no l6_daily_*.json panels under {args.panel_dir}")
        panels = load_daily_panels(paths)
        result = evaluate_l6_daily_d4(
            panels,
            universe=args.universe,
            active_top_n=args.active_top_n,
            holding=args.holding,
            weight_mode=args.weight_mode,
            purged_cv=args.purged_cv,
            embargo=args.embargo,
        )
        result = write_research_json_artifact(
            settings,
            result,
            kind="l6-daily-d4-scan",
            path_key="output_path",
            default_filename="l6_daily_d4_scan.json",
            explicit_path=args.output_path,
        )
    elif args.command == "l6-t0-exec-scan":
        import glob

        from .l6_microstructure import evaluate_l6_t0_execution
        from .l6_microstructure import load_daily_panels

        paths = sorted(glob.glob(str(Path(args.panel_dir) / "**" / "l6_daily_*.json"), recursive=True))
        if not paths:
            parser.error(f"no l6_daily_*.json panels under {args.panel_dir}")
        panels = load_daily_panels(paths)
        result = evaluate_l6_t0_execution(
            panels,
            feature=args.feature,
            universe=args.universe,
            active_top_n=args.active_top_n,
            top_fraction=args.top_fraction,
            round_trip_cost_bps=args.round_trip_cost_bps,
            commission_roundtrip_bps=args.commission_roundtrip_bps,
        )
        result = write_research_json_artifact(
            settings,
            result,
            kind="l6-t0-exec-scan",
            path_key="output_path",
            default_filename="l6_t0_exec_scan.json",
            explicit_path=args.output_path,
        )
    # "cta-paper-sim" is handled by the early delegation at the top of main().
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
