"""Argument registration for frozen L1/L3/L4/L6 research commands.

These commands remain visible for reproducibility, but their implementations
belong to frozen research lines.  Keeping their argument definitions together
makes that boundary explicit without changing the public ``qount-run`` CLI.
"""

from __future__ import annotations

from typing import Any

from ..l1_cross_asset import DEFAULT_TIINGO_START_DATE
from ..l3_information_edge import DEFILLAMA_STABLECOIN_CHARTS_URL


def register_legacy_research_commands(subparsers: Any) -> None:
    """Add compatibility parsers for frozen research command families."""

    l3_stablecoin = subparsers.add_parser(
        "l3-stablecoin-fetch",
        help="Research-only L3 S0.1 data layer: fetch/cache/normalize DefiLlama stablecoin supply.",
    )
    l3_stablecoin.add_argument("--start", default=None, help="Optional weekly anchor window start (ISO); defaults to first observation.")
    l3_stablecoin.add_argument("--end", default=None, help="Optional weekly anchor window end (ISO); defaults to last observation.")
    l3_stablecoin.add_argument("--url", default=DEFILLAMA_STABLECOIN_CHARTS_URL, help="DefiLlama stablecoin charts URL.")
    l3_stablecoin.add_argument("--cache-path", default=None, help="Optional state cache path; reused on later runs unless --force-refresh.")
    l3_stablecoin.add_argument("--force-refresh", action="store_true", help="Ignore any cached payload and re-fetch from the network.")
    l3_stablecoin.add_argument("--output-path", default=None, help="Optional output path for the diagnostic JSON.")

    l3_timing = subparsers.add_parser(
        "l3-stablecoin-timing-scan",
        help="Research-only L3 S1 kill-test: stablecoin supply growth vs BTC weekly forward-return IC + DSR/PBO.",
    )
    l3_timing.add_argument("--start", required=True, help="Weekly anchor window start (ISO).")
    l3_timing.add_argument("--end", required=True, help="Weekly anchor window end (ISO).")
    l3_timing.add_argument("--symbol", default="BTC/USDT", help="Single liquid timing target; default BTC/USDT.")
    l3_timing.add_argument("--signal-lookback-weeks-grid", nargs="+", type=int, default=None, help="Supply log-growth lookbacks in weeks; default 4 8 13.")
    l3_timing.add_argument("--horizon-weeks-grid", nargs="+", type=int, default=None, help="Forward prediction horizons in weeks; default 1 2 3 4.")
    l3_timing.add_argument("--cost-per-side-pct", type=float, default=None, help="Per-side cost; default settings fee+slippage.")
    l3_timing.add_argument("--supply-cache-path", default=None, help="Optional DefiLlama supply cache path.")
    l3_timing.add_argument("--price-cache-path", default=None, help="Optional BTC daily-close cache path.")
    l3_timing.add_argument("--url", default=DEFILLAMA_STABLECOIN_CHARTS_URL, help="DefiLlama stablecoin charts URL.")
    l3_timing.add_argument("--force-refresh", action="store_true", help="Ignore caches and re-fetch supply and price.")
    l3_timing.add_argument("--holdout-role", choices=["discovery", "validation_v1", "unknown"], default="discovery")
    l3_timing.add_argument("--output-path", default=None, help="Optional output path for the kill-test JSON.")

    l3_xs = subparsers.add_parser(
        "l3-chain-tvl-scan",
        help="Research-only L3b S1 kill-test: chain TVL growth vs token weekly cross-sectional forward-return IC + effective-breadth + DSR/PBO.",
    )
    l3_xs.add_argument("--start", required=True, help="Weekly anchor window start (ISO).")
    l3_xs.add_argument("--end", required=True, help="Weekly anchor window end (ISO).")
    l3_xs.add_argument("--tokens", nargs="+", default=None, help="Optional subset of chain tokens (e.g. ETH/USDT SOL/USDT); default uses the built-in chain-token map.")
    l3_xs.add_argument("--signal-lookback-weeks-grid", nargs="+", type=int, default=None, help="TVL log-growth lookbacks in weeks; default 4 8 13.")
    l3_xs.add_argument("--horizon-weeks-grid", nargs="+", type=int, default=None, help="Forward prediction horizons in weeks; default 1 2 4.")
    l3_xs.add_argument("--cost-per-side-pct", type=float, default=None, help="Per-side cost; default settings fee+slippage.")
    l3_xs.add_argument("--top-fraction", type=float, default=0.25, help="Long/short fraction for the diagnostic LS series.")
    l3_xs.add_argument("--min-cross-section-tokens", type=int, default=4, help="Minimum tokens per cross-section to score an anchor.")
    l3_xs.add_argument("--cache-dir", default=None, help="Optional directory for per-chain TVL and per-token price caches.")
    l3_xs.add_argument("--force-refresh", action="store_true", help="Ignore caches and re-fetch TVL and price.")
    l3_xs.add_argument("--holdout-role", choices=["discovery", "validation_v1", "unknown"], default="discovery")
    l3_xs.add_argument("--output-path", default=None, help="Optional output path for the kill-test JSON.")

    l1_breadth = subparsers.add_parser(
        "l1-cross-asset-breadth-scan",
        help="Research-only L1 first kill-test: effective breadth of a free cross-asset EOD panel (Tiingo). Needs QOUNT_TIINGO_API_KEY.",
    )
    l1_breadth.add_argument("--start", required=True, help="Weekly anchor window start (ISO).")
    l1_breadth.add_argument("--end", required=True, help="Weekly anchor window end (ISO).")
    l1_breadth.add_argument("--tickers", nargs="+", default=None, help="Optional cross-asset ticker panel; default uses the built-in panel.")
    l1_breadth.add_argument("--start-date", default=DEFAULT_TIINGO_START_DATE, help="Tiingo EOD history start date (YYYY-MM-DD).")
    l1_breadth.add_argument("--cache-dir", default=None, help="Optional directory for per-ticker EOD caches.")
    l1_breadth.add_argument("--force-refresh", action="store_true", help="Ignore caches and re-fetch EOD data.")
    l1_breadth.add_argument("--holdout-role", choices=["discovery", "validation_v1", "unknown"], default="discovery")
    l1_breadth.add_argument("--output-path", default=None, help="Optional output path for the breadth-scan JSON.")

    l1_tsmom = subparsers.add_parser(
        "l1-cross-asset-tsmom-scan",
        help="Research-only L1 S2 kill-test: cross-asset time-series-momentum (trend) annualized IR + DSR/PBO. Needs QOUNT_TIINGO_API_KEY.",
    )
    l1_tsmom.add_argument("--start", required=True, help="Weekly anchor window start (ISO).")
    l1_tsmom.add_argument("--end", required=True, help="Weekly anchor window end (ISO).")
    l1_tsmom.add_argument("--tickers", nargs="+", default=None, help="Optional cross-asset ticker panel; default uses the built-in panel.")
    l1_tsmom.add_argument("--lookback-weeks-grid", nargs="+", type=int, default=None, help="Trend lookbacks in weeks; default 13 26 52.")
    l1_tsmom.add_argument("--vol-lookback-weeks", type=int, default=26, help="Trailing weeks for the inverse-vol position scaling.")
    l1_tsmom.add_argument("--ensemble", action="store_true", help="Blend the lookback grid into one parameter-free multi-horizon trend (purged folds instead of DSR/PBO).")
    l1_tsmom.add_argument("--n-folds", type=int, default=5, help="Contiguous time folds for ensemble robustness.")
    l1_tsmom.add_argument("--cost-per-side-pct", type=float, default=None, help="Per-side cost; default settings fee+slippage.")
    l1_tsmom.add_argument("--start-date", default=DEFAULT_TIINGO_START_DATE, help="Tiingo EOD history start date (YYYY-MM-DD).")
    l1_tsmom.add_argument("--cache-dir", default=None, help="Optional directory for per-ticker EOD caches.")
    l1_tsmom.add_argument("--force-refresh", action="store_true", help="Ignore caches and re-fetch EOD data.")
    l1_tsmom.add_argument("--holdout-role", choices=["discovery", "validation_v1", "unknown"], default="discovery")
    l1_tsmom.add_argument("--output-path", default=None, help="Optional output path for the tsmom-scan JSON.")

    l4_funding = subparsers.add_parser(
        "l4-cross-exchange-funding-scan",
        help="Research-only L4 S1 kill-test: cross-exchange perp funding-spread capture vs two-venue round-trip cost (market-neutral, no direction).",
    )
    l4_funding.add_argument("--start", required=True, help="Bucket window start (ISO).")
    l4_funding.add_argument("--end", required=True, help="Bucket window end (ISO).")
    l4_funding.add_argument("--venues", nargs="+", default=None, help="ccxt venue ids; default binance bybit okx hyperliquid.")
    l4_funding.add_argument("--symbols", nargs="+", default=None, help="Unified linear-perp symbols; default BTC/ETH/SOL/XRP/DOGE/BNB USDT.")
    l4_funding.add_argument("--cost-per-side-pct", type=float, default=None, help="Per-leg execution cost; default settings fee+slippage.")
    l4_funding.add_argument("--taker-cost-per-side-pct", type=float, default=None, help="Optional taker per-leg cost for the required-maker-fill feasibility read.")
    l4_funding.add_argument("--cache-dir", default=None, help="Optional directory for per-venue per-symbol funding caches.")
    l4_funding.add_argument("--force-refresh", action="store_true", help="Ignore caches and re-fetch funding history.")
    l4_funding.add_argument("--holdout-role", choices=["discovery", "validation_v1", "unknown"], default="discovery")
    l4_funding.add_argument("--output-path", default=None, help="Optional output path for the kill-test JSON.")

    l6_ic = subparsers.add_parser(
        "l6-microstructure-ic-scan",
        help="Research-only L6 Phase 1 kill-test: A-share Level-2 order-flow IC-vs-horizon decay across T+0 ETFs + DSR/PBO + break-even.",
    )
    l6_ic.add_argument("--data-dir", required=True, help="Directory of per-instrument Wind tick folders (e.g. state/l6_l2_raw/20260407).")
    l6_ic.add_argument("--symbols", nargs="+", required=True, help="Instrument folder names (e.g. 159919.SZ 159915.SZ).")
    l6_ic.add_argument("--horizons-ms", nargs="+", type=int, default=None, help="Forward-return horizons in ms; default 3s..30min grid.")
    l6_ic.add_argument("--cost-per-side-pct", type=float, default=0.0005, help="T+0 ETF per-side round-trip cost; default 5bps.")
    l6_ic.add_argument("--ic-gate", type=float, default=0.05, help="Breadth-adjusted required rank-IC; default 0.05 (daily ceiling).")
    l6_ic.add_argument("--holdout-role", choices=["discovery", "validation_v1", "unknown"], default="discovery")
    l6_ic.add_argument("--output-path", default=None, help="Optional output path for the kill-test JSON.")

    l6_daily = subparsers.add_parser(
        "l6-daily-features",
        help="Research-only L6-daily ETL: per-(stock) L2-derived daily informed-flow features for one trading day.",
    )
    l6_daily.add_argument("--day-dir", required=True, help="Directory of per-instrument Wind tick folders for one day.")
    l6_daily.add_argument("--symbols", nargs="+", default=None, help="Instrument folder names; omit with --all-symbols.")
    l6_daily.add_argument("--all-symbols", action="store_true", help="Enumerate every <code>.SZ/.SH folder in --day-dir.")
    l6_daily.add_argument("--output-path", default=None, help="Optional output path for the daily feature panel JSON.")

    l6_d1 = subparsers.add_parser(
        "l6-daily-d1-scan",
        help="Research-only L6-daily D1: cross-day cross-section rank-IC of daily informed-flow features.",
    )
    l6_d1.add_argument("--panel-dir", required=True, help="Dir holding D0 panels (l6_daily_<date>/l6_daily_<date>.json).")
    l6_d1.add_argument("--universe", choices=["etf", "all"], default="etf", help="Cross-section universe; default etf.")
    l6_d1.add_argument("--active-top-n", type=int, default=None, help="Keep only top-N by turnover proxy per day.")
    l6_d1.add_argument("--holding", type=int, default=1, help="Forward horizon in trading days; default 1.")
    l6_d1.add_argument("--top-fraction", type=float, default=0.2, help="Long-short decile fraction; default 0.2.")
    l6_d1.add_argument("--output-path", default=None, help="Optional output path for the D1 scan JSON.")

    l6_d2 = subparsers.add_parser(
        "l6-daily-d2-scan",
        help="Research-only L6-daily D2: incremental rank-IC of a feature vs the price/volume baseline.",
    )
    l6_d2.add_argument("--panel-dir", required=True, help="Dir holding D0 panels (l6_daily_<date>/...json).")
    l6_d2.add_argument("--target-feature", default="close_auction_imbalance", help="Feature to test for increment.")
    l6_d2.add_argument("--baseline-lookback", type=int, default=1, help="Trailing-return lookback (price/volume baseline).")
    l6_d2.add_argument("--universe", choices=["etf", "all"], default="etf")
    l6_d2.add_argument("--active-top-n", type=int, default=None)
    l6_d2.add_argument("--holding", type=int, default=1)
    l6_d2.add_argument("--output-path", default=None, help="Optional output path for the D2 scan JSON.")

    l6_d4 = subparsers.add_parser(
        "l6-daily-d4-scan",
        help="Research-only L6-daily D4: linear multi-feature composite cross-section IC vs breadth requirement.",
    )
    l6_d4.add_argument("--panel-dir", required=True, help="Dir holding D0 panels (l6_daily_<date>/...json).")
    l6_d4.add_argument("--universe", choices=["etf", "all"], default="etf")
    l6_d4.add_argument("--active-top-n", type=int, default=None)
    l6_d4.add_argument("--holding", type=int, default=1)
    l6_d4.add_argument("--weight-mode", choices=["sign_equal", "ic_weighted"], default="sign_equal")
    l6_d4.add_argument("--purged-cv", action="store_true", help="Also report leave-one-section-out OOS composite IC.")
    l6_d4.add_argument("--embargo", type=int, default=1, help="Sections to embargo around the held-out one (purged-cv).")
    l6_d4.add_argument("--output-path", default=None, help="Optional output path for the D4 scan JSON.")

    l6_t0 = subparsers.add_parser(
        "l6-t0-exec-scan",
        help="Research-only L6 line B: overnight-vs-intraday split of the close_auction reversal, net of ETF T+0 cost.",
    )
    l6_t0.add_argument("--panel-dir", required=True, help="Dir holding panels WITH day_open (l6_daily_<date>/...json).")
    l6_t0.add_argument("--feature", default="close_auction_imbalance", help="Signal feature; default close_auction_imbalance.")
    l6_t0.add_argument("--universe", choices=["etf", "all"], default="etf")
    l6_t0.add_argument("--active-top-n", type=int, default=None, help="Keep only top-N by turnover proxy per day.")
    l6_t0.add_argument("--top-fraction", type=float, default=0.2, help="Long-short tail fraction; default 0.2.")
    l6_t0.add_argument("--round-trip-cost-bps", type=float, default=6.0, help="Flat-cost fallback (bps) when panels lack quoted spreads; default 6.")
    l6_t0.add_argument("--commission-roundtrip-bps", type=float, default=2.5, help="Per-ETF round-trip commission (bps) for empirical taker/auction nets; default 2.5.")
    l6_t0.add_argument("--output-path", default=None, help="Optional output path for the T0 exec scan JSON.")

    # ``cta-paper-sim`` delegates to qount.cta_sim, which owns its full parser.
    # This stub keeps the compatibility command visible in qount-run --help.
    subparsers.add_parser(
        "cta-paper-sim",
        add_help=False,
        help="Offline CTA-R sim/gate/walk-forward (delegates to `python -m qount.cta_sim`; run that for full --help).",
    )
