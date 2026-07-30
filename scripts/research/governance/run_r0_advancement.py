#!/usr/bin/env python3
"""R0 advancement: trend beta-residual + multi-coin breadth + vol-target + CTA-R ETF.

Three research tracks in one script:

1. Trend beta-residual: regress C×D trend leg returns against BTC buy-hold
   and TOP3 equal-weight to decompose alpha vs beta.
2. Multi-coin breadth: run trend signal on BTC/ETH/BNB, combine into
   equal-weight and vol-targeted portfolios; measure maxDD improvement.
3. CTA-R selection-free: run trend on a cross-asset A-share ETF panel
   (equity / bonds / gold / overseas) with the same frozen cost model.

Usage:
    python3 scripts/research/governance/run_r0_advancement.py --start 2020,1 --end 2026,7
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import io
import json
import math
import os
import stat
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from typing import Sequence

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from qount.contracts import canonical_hash
from qount.research_data.market_data import Bar
from qount.research_data.market_data import closes as bar_closes
from qount.research_data.market_data import load_funding
from qount.research_data.market_data import load_klines
from qount.models import utc_now
from qount.research_data.candidate_config import CandidateConfig
from qount.research_data.cost_model import FrozenCostModel
from qount.research_data.cost_model import default_cxd_trend_cost_model
from qount.research_data.cost_model import default_cta_r_etf_cost_model
from qount.research_data.nav import compute_signal_nav
from qount.research_data.nav import compute_standalone_nav
from qount.legacy.x4.strategies import TrendFollow

ETF_ZIP = ROOT / "state" / "cta_r" / "etf_source" / "etf_data.zip"

# Cross-asset ETF panel for CTA-R (A-share market, all tradeable via brokerage)
CTA_R_ETF_PANEL = {
    "510300.SH": {"name": "沪深300ETF", "asset_class": "equity"},
    "510050.SH": {"name": "上证50ETF", "asset_class": "equity"},
    "159915.SZ": {"name": "创业板ETF", "asset_class": "equity"},
    "513100.SH": {"name": "纳指ETF", "asset_class": "overseas_equity"},
    "513500.SH": {"name": "标普500ETF", "asset_class": "overseas_equity"},
    "511010.SH": {"name": "国债ETF", "asset_class": "bonds"},
    "511260.SH": {"name": "国债5Y ETF", "asset_class": "bonds"},
    "518880.SH": {"name": "黄金ETF", "asset_class": "gold"},
    "159934.SZ": {"name": "黄金ETF_SZ", "asset_class": "gold"},
    "159980.SZ": {"name": "有色金属ETF", "asset_class": "commodity"},
}

# Crypto UM symbols for multi-coin breadth
CRYPTO_SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]


# --- Helpers ----------------------------------------------------------------

DEFAULT_OUTPUT_DIR = ROOT / "state" / "research_governance" / "r0_advancement"


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))
        .encode("ascii") + b"\n"
    )


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_once(path: Path, value: object) -> None:
    raw = _canonical_bytes(value)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as h:
            h.write(raw)
            h.flush()
            os.fsync(h.fileno())
        fd = -1
        os.link(tmp, path)
        _fsync_directory(path.parent)
        if path.read_bytes() != raw:
            raise RuntimeError(f"r0_advancement_readback_mismatch:{path}")
        if stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise RuntimeError(f"r0_advancement_mode_invalid:{path}")
    finally:
        if fd >= 0:
            os.close(fd)
        if tmp.exists():
            tmp.unlink()


def _member_refs(directory: Path) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for p in sorted(directory.iterdir()):
        if not p.is_file() or p.name == "manifest.json":
            continue
        raw = p.read_bytes()
        refs.append({"path": p.name, "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    return refs


def _load_um_data(symbol, start, end, cache_dir):
    bars = load_klines(symbol, "1d", start=start, end=end, market="um",
                       cache_dir=cache_dir, skip_missing=True)
    funding = load_funding(symbol, start=start, end=end,
                           cache_dir=os.path.join(cache_dir, "..", "funding"), skip_missing=True)
    return bars, funding


def _align_funding(bars, funding):
    if not funding:
        return None
    from scripts.research.governance.run_r0_runtime import aggregate_funding_to_bars
    return aggregate_funding_to_bars(bars, funding).rates


def _nav_summary(result):
    from qount.research_data.nav import compute_max_drawdown
    series = result.nav_series
    if not series:
        return {"final_nav": 0.0, "total_return": 0.0, "max_drawdown": 0.0}
    max_dd = compute_max_drawdown(series)
    years = result.bars / 365.0 if result.bars > 0 else 1.0
    annualized = (series[-1] ** (1.0 / years) - 1.0) if years > 0 and series[-1] > 0 else -1.0
    return {
        "final_nav": series[-1],
        "total_return": result.total_return,
        "total_cost": result.total_cost,
        "max_drawdown": max_dd,
        "annualized_return": annualized,
        "bars": result.bars,
        "turnover": result.turnover,
    }


def _daily_returns(nav_series):
    """Convert NAV series to daily returns."""
    if len(nav_series) < 2:
        return []
    return [nav_series[i] / nav_series[i-1] - 1.0 for i in range(1, len(nav_series)) if nav_series[i-1] != 0]


def _regress(y, x):
    """Simple OLS regression: y = alpha + beta * x. Returns (alpha, beta, r_squared)."""
    n = len(y)
    if n < 3:
        return 0.0, 0.0, 0.0
    mean_y = sum(y) / n
    mean_x = sum(x) / n
    cov = sum((y[i] - mean_y) * (x[i] - mean_x) for i in range(n)) / n
    var_x = sum((x[i] - mean_x) ** 2 for i in range(n)) / n
    var_y = sum((y[i] - mean_y) ** 2 for i in range(n)) / n
    if var_x == 0:
        return mean_y, 0.0, 0.0
    beta = cov / var_x
    alpha = mean_y - beta * mean_x
    r_sq = (cov ** 2 / (var_x * var_y)) if var_y > 0 else 0.0
    return alpha, beta, r_sq


# --- ETF data loading -------------------------------------------------------


def load_etf_closes(zip_path: Path, ts_code: str) -> tuple[list[str], list[float]]:
    """Load ETF daily close prices from the zip archive.

    Returns (dates, closes) in ascending date order.
    """

    daily_path = f"etf_data/daily/{ts_code}.csv"
    adj_path = f"etf_data/adj/{ts_code}.csv"
    with zipfile.ZipFile(zip_path) as zf:
        # Load daily closes
        if daily_path not in zf.namelist():
            return [], []
        with zf.open(daily_path) as f:
            lines = f.read().decode("utf-8").splitlines()
        # Load adj factors
        adj_map = {}
        if adj_path in zf.namelist():
            with zf.open(adj_path) as f:
                adj_lines = f.read().decode("utf-8").splitlines()
                for line in adj_lines[1:]:
                    parts = line.split(",")
                    if len(parts) >= 3:
                        adj_map[parts[1]] = float(parts[2])
        # Parse daily (dates are descending, reverse to ascending)
        records = []
        for line in reversed(lines[1:]):
            parts = line.split(",")
            if len(parts) >= 7:
                date = parts[1]
                close = float(parts[6])
                adj = adj_map.get(date, 1.0)
                records.append((date, close * adj))
        dates = [r[0] for r in records]
        closes = [r[1] for r in records]
    return dates, closes


def load_etf_panel(zip_path: Path, symbols: dict[str, dict]) -> dict[str, dict]:
    """Load multiple ETF close series, aligned by common dates."""

    all_data: dict[str, tuple[list[str], list[float]]] = {}
    for ts_code in symbols:
        dates, closes = load_etf_closes(zip_path, ts_code)
        if dates:
            all_data[ts_code] = (dates, closes)

    # Find common dates
    if not all_data:
        return {}
    first_key = list(all_data.keys())[0]
    common = set(all_data[first_key][0])
    for ts_code in all_data:
        common &= set(all_data[ts_code][0])
    common_dates = sorted(common)

    # Build aligned panel
    panel: dict[str, dict] = {}
    for ts_code, (dates, closes) in all_data.items():
        date_to_close = dict(zip(dates, closes))
        aligned = [date_to_close[d] for d in common_dates]
        panel[ts_code] = {
            "closes": aligned,
            "dates": common_dates,
            "name": symbols[ts_code]["name"],
            "asset_class": symbols[ts_code]["asset_class"],
        }
    return panel


# --- Vol targeting ----------------------------------------------------------


def vol_target_positions(closes, positions, target_vol=0.02, lookback=20):
    """Scale positions to target a fixed annualized volatility.

    Uses trailing realized volatility from ``lookback`` completed returns
    ending at bar ``i-1`` (causal: no future function) to scale exposure at
    bar ``i``.  ``lookback=20`` means 20 completed returns, so the loop starts
    at ``i = lookback + 1`` (bar 21) where 20 returns (bars 1..20) are
    available.  When vol is high, reduce position; when vol is low, increase
    (capped at 1.0).
    """

    scaled = list(positions)
    for i in range(lookback + 1, len(closes)):
        # Use returns [max(1, i-lookback), i) -- lookback completed returns, all known before bar i's close
        rets = [closes[j] / closes[j-1] - 1.0 for j in range(max(1, i - lookback), i) if closes[j-1] > 0]
        if not rets:
            continue
        realized_vol = math.sqrt(sum(r ** 2 for r in rets) / len(rets)) * math.sqrt(365)
        if realized_vol > 0:
            scale = min(1.0, target_vol / realized_vol)
            scaled[i] = positions[i] * scale
    return scaled


# --- Main -------------------------------------------------------------------


def main(argv=None):
    parser = argparse.ArgumentParser(description="R0 advancement: trend + CTA-R")
    parser.add_argument("--start", default="2020,1")
    parser.add_argument("--end", default=None)
    parser.add_argument("--fast", type=int, default=20)
    parser.add_argument("--slow", type=int, default=100)
    parser.add_argument("--regime-sma", type=int, default=0)
    parser.add_argument("--vol-target", type=float, default=0.02)
    parser.add_argument("--runtime-bundle", default=None,
                        help="Path to a verified R0-RUNTIME bundle to inherit candidate config from")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    candidate_config: CandidateConfig
    runtime_bundle_id: str | None = None
    if args.runtime_bundle:
        bundle_path = Path(args.runtime_bundle)
        if not bundle_path.is_dir():
            print(f"ERROR: runtime bundle not found: {bundle_path}", file=sys.stderr)
            return 1
        manifest_path = bundle_path / "manifest.json"
        if not manifest_path.exists():
            print(f"ERROR: manifest.json not found in runtime bundle", file=sys.stderr)
            return 1
        rt_manifest = json.loads(manifest_path.read_text(encoding="ascii"))
        runtime_bundle_id = rt_manifest.get("bundle_id")
        rt_cfg = rt_manifest.get("trend_config", {})
        candidate_config = CandidateConfig.from_dict(rt_cfg)
        print(f"Using candidate config from runtime bundle: {candidate_config.to_dict()}")
    else:
        candidate_config = CandidateConfig.create(
            fast=args.fast, slow=args.slow, regime_sma=args.regime_sma, allow_short=False,
        )
        print(f"Using candidate config from CLI args: {candidate_config.to_dict()}")

    start_parts = tuple(int(x) for x in args.start.split(","))
    if args.end:
        end_parts = tuple(int(x) for x in args.end.split(","))
    else:
        now = _dt.datetime.now(_dt.UTC)
        end_parts = (now.year, now.month)

    frozen_at = utc_now().isoformat()
    cache_dir = os.path.join("state", "r0_runtime", "klines")

    # ================================================================
    # Track 1+2: Crypto trend beta-residual + multi-coin breadth
    # ================================================================
    print("=" * 60)
    print("Track 1+2: Crypto Trend Beta-Residual + Multi-Coin Breadth")
    print("=" * 60)

    crypto_results: dict[str, dict] = {}
    all_crypto_navs: dict[str, list[float]] = {}
    all_crypto_dates: dict[str, list[str]] = {}
    crypto_source_hashes: dict[str, dict[str, str]] = {}

    for symbol in CRYPTO_SYMBOLS:
        print(f"\n--- {symbol} ---")
        bars, funding = _load_um_data(symbol, start_parts, end_parts, cache_dir)
        if len(bars) < 2:
            print(f"  Skipped (only {len(bars)} bars)")
            continue

        closes = bar_closes(bars)
        funding_aligned = _align_funding(bars, funding)

        # Trend signal
        strategy = TrendFollow(
            fast=candidate_config.fast, slow=candidate_config.slow,
            allow_short=candidate_config.allow_short, regime_sma=candidate_config.regime_sma,
        )
        positions = [strategy.on_bar(bar) for bar in bars]

        # Signal NAV
        signal_nav = compute_signal_nav(closes, positions)
        signal_summary = _nav_summary(signal_nav)

        # Standalone NAV
        cost_model = default_cxd_trend_cost_model(frozen_at=frozen_at)
        standalone_nav = compute_standalone_nav(closes, positions, cost_model, funding_rates=funding_aligned)
        standalone_summary = _nav_summary(standalone_nav)

        # Vol-targeted positions
        vt_positions = vol_target_positions(closes, positions, target_vol=args.vol_target)
        vt_signal_nav = compute_signal_nav(closes, vt_positions)
        vt_standalone_nav = compute_standalone_nav(closes, vt_positions, cost_model, funding_rates=funding_aligned)
        vt_signal_summary = _nav_summary(vt_signal_nav)
        vt_standalone_summary = _nav_summary(vt_standalone_nav)

        # Buy-hold benchmark
        bh_nav = compute_signal_nav(closes, [1.0] * len(closes))
        bh_summary = _nav_summary(bh_nav)

        print(f"  Signal:      NAV={signal_summary['final_nav']:.4f} maxDD={signal_summary['max_drawdown']:.2%}")
        print(f"  Standalone:  NAV={standalone_summary['final_nav']:.4f} maxDD={standalone_summary['max_drawdown']:.2%}")
        print(f"  Vol-target:  NAV={vt_standalone_summary['final_nav']:.4f} maxDD={vt_standalone_summary['max_drawdown']:.2%}")
        print(f"  Buy-hold:    NAV={bh_summary['final_nav']:.4f} maxDD={bh_summary['max_drawdown']:.2%}")

        crypto_results[symbol] = {
            "signal_nav": signal_summary,
            "standalone_nav": standalone_summary,
            "vt_signal_nav": vt_signal_summary,
            "vt_standalone_nav": vt_standalone_summary,
            "buy_hold_nav": bh_summary,
            "bars": len(bars),
            "first_date": bars[0].date if bars else None,
            "last_date": bars[-1].date if bars else None,
        }
        all_crypto_navs[symbol] = list(standalone_nav.nav_series)
        all_crypto_dates[symbol] = [b.date for b in bars]

        # Compute source hashes for provenance
        closes_hash = hashlib.sha256(
            json.dumps([round(c, 8) for c in closes]).encode()
        ).hexdigest()
        positions_hash = hashlib.sha256(
            json.dumps([round(p, 8) for p in positions]).encode()
        ).hexdigest()
        nav_hash = hashlib.sha256(
            json.dumps([round(n, 8) for n in standalone_nav.nav_series]).encode()
        ).hexdigest()
        funding_hash = ""
        if funding_aligned:
            funding_hash = hashlib.sha256(
                json.dumps([round(f, 8) for f in funding_aligned]).encode()
            ).hexdigest()
        crypto_source_hashes[symbol] = {
            "closes": closes_hash,
            "positions": positions_hash,
            "nav": nav_hash,
            "funding": funding_hash,
        }

    # Beta-residual: regress BTC trend returns vs BTC buy-hold
    print(f"\n--- Beta-Residual (BTC trend vs BTC buy-hold) ---")
    if "BTCUSDT" in all_crypto_navs and "BTCUSDT" in crypto_results:
        trend_returns = _daily_returns(all_crypto_navs["BTCUSDT"])
        bh_closes = bar_closes(_load_um_data("BTCUSDT", start_parts, end_parts, cache_dir)[0])
        bh_returns = _daily_returns(compute_signal_nav(bh_closes, [1.0] * len(bh_closes)).nav_series)
        min_len = min(len(trend_returns), len(bh_returns))
        if min_len >= 10:
            alpha, beta, r_sq = _regress(trend_returns[:min_len], bh_returns[:min_len])
            print(f"  alpha (daily)={alpha:.6f} beta={beta:.4f} R²={r_sq:.4f}")
            print(f"  annualized alpha={alpha * 365:.4%} beta={beta:.4f}")
            crypto_results["btc_beta_residual"] = {
                "alpha_daily": alpha, "beta": beta, "r_squared": r_sq,
                "alpha_annualized": alpha * 365,
            }

    # Multi-coin equal-weight portfolio (aligned by date intersection)
    print(f"\n--- Multi-Coin Equal-Weight Portfolio ---")
    if len(all_crypto_navs) >= 2:
        # Find date intersection across all symbols
        date_sets = [set(dates) for dates in all_crypto_dates.values()]
        common_dates = sorted(set.intersection(*date_sets)) if date_sets else []
        if len(common_dates) >= 2:
            # Build date-indexed NAV lookup per symbol
            nav_by_date: dict[str, dict[str, float]] = {}
            for sym in all_crypto_navs:
                nav_by_date[sym] = dict(zip(all_crypto_dates[sym], all_crypto_navs[sym]))

            # Equal-weight NAV on common dates only
            ew_nav = [1.0]
            for t in range(1, len(common_dates)):
                d_prev = common_dates[t - 1]
                d_curr = common_dates[t]
                avg_return = sum(
                    nav_by_date[s][d_curr] / nav_by_date[s][d_prev] - 1.0
                    for s in nav_by_date
                ) / len(nav_by_date)
                ew_nav.append(ew_nav[-1] * (1.0 + avg_return))
            from qount.research_data.nav import compute_max_drawdown
            ew_max_dd = compute_max_drawdown(ew_nav)
            years = len(common_dates) / 365.0
            ew_annual = (ew_nav[-1] ** (1.0 / years) - 1.0) if years > 0 and ew_nav[-1] > 0 else -1.0
            print(f"  Equal-weight NAV={ew_nav[-1]:.4f} maxDD={ew_max_dd:.2%} annual={ew_annual:+.2%}")
            print(f"  Common dates: {len(common_dates)} ({common_dates[0]} to {common_dates[-1]})")
            crypto_results["equal_weight_portfolio"] = {
                "final_nav": ew_nav[-1], "max_drawdown": ew_max_dd,
                "annualized_return": ew_annual, "coins": len(all_crypto_navs),
                "common_dates": len(common_dates),
                "first_date": common_dates[0],
                "last_date": common_dates[-1],
            }
        else:
            print(f"  Insufficient common dates: {len(common_dates)}")
    else:
        print(f"  Insufficient symbols: {len(all_crypto_navs)}")

    # ================================================================
    # Track 3: CTA-R cross-asset ETF selection-free trend
    # ================================================================
    print("\n" + "=" * 60)
    print("Track 3: CTA-R Cross-Asset ETF Selection-Free Trend")
    print("=" * 60)

    if not ETF_ZIP.exists():
        print(f"  ETF data not found: {ETF_ZIP}")
        etf_results = {}
        cta_r_portfolio = None
    else:
        print(f"\n  Loading ETF panel from {ETF_ZIP.name}...")
        panel = load_etf_panel(ETF_ZIP, CTA_R_ETF_PANEL)
        print(f"  Loaded {len(panel)} ETFs, {len(panel[list(panel.keys())[0]]['dates']) if panel else 0} common dates")

        etf_results: dict[str, dict] = {}
        cta_r_portfolio: dict[str, Any] | None = None

        if panel:
            etf_cost_model = default_cta_r_etf_cost_model(frozen_at=frozen_at)
            etf_results: dict[str, dict] = {}
            etf_navs: list[list[float]] = []

            for ts_code, data in panel.items():
                closes = data["closes"]
                if len(closes) < 2:
                    continue
                # Selection-free: same trend signal on all assets
                strategy = TrendFollow(
                    fast=candidate_config.fast, slow=candidate_config.slow,
                    allow_short=candidate_config.allow_short, regime_sma=candidate_config.regime_sma,
                )
                bars_fake = [Bar(ts_ms=i * 86400000, open=c, high=c, low=c, close=c, volume=0)
                             for i, c in enumerate(closes)]
                positions = [strategy.on_bar(b) for b in bars_fake]

                signal_nav = compute_signal_nav(closes, positions)
                standalone_nav = compute_standalone_nav(closes, positions, etf_cost_model)
                s = _nav_summary(signal_nav)
                sa = _nav_summary(standalone_nav)

                print(f"  {ts_code} ({data['name']}): signal={s['final_nav']:.4f} "
                      f"standalone={sa['final_nav']:.4f} maxDD={sa['max_drawdown']:.2%}")

                etf_results[ts_code] = {
                    "name": data["name"], "asset_class": data["asset_class"],
                    "signal_nav": s, "standalone_nav": sa,
                }
                etf_navs.append(list(standalone_nav.nav_series))

            # Equal-weight cross-asset portfolio
            if etf_navs:
                common_len = min(len(v) for v in etf_navs)
                ew_nav = [1.0]
                for t in range(1, common_len):
                    avg_return = sum(etf_navs[i][t] / etf_navs[i][t-1] - 1.0
                                    for i in range(len(etf_navs))) / len(etf_navs)
                    ew_nav.append(ew_nav[-1] * (1.0 + avg_return))
                from qount.research_data.nav import compute_max_drawdown as _cmd
                ew_max_dd = _cmd(ew_nav)
                years = common_len / 250.0  # ~250 trading days per year
                ew_annual = (ew_nav[-1] ** (1.0 / years) - 1.0) if years > 0 and ew_nav[-1] > 0 else -1.0
                print(f"\n  CTA-R Equal-Weight Portfolio:")
                print(f"    NAV={ew_nav[-1]:.4f} maxDD={ew_max_dd:.2%} annual={ew_annual:+.2%}")
                print(f"    Assets: {len(etf_navs)} ETFs across {len(set(d['asset_class'] for d in etf_results.values()))} asset classes")
                cta_r_portfolio = {
                    "final_nav": ew_nav[-1], "max_drawdown": ew_max_dd,
                    "annualized_return": ew_annual, "assets": len(etf_navs),
                    "asset_classes": len(set(d['asset_class'] for d in etf_results.values())),
                }

                # Asset class contribution
                by_class: dict[str, list[float]] = {}
                for ts_code, result in etf_results.items():
                    ac = result["asset_class"]
                    by_class.setdefault(ac, []).append(result["standalone_nav"]["final_nav"])
                print(f"\n  By Asset Class:")
                for ac, navs in sorted(by_class.items()):
                    print(f"    {ac}: avg NAV={sum(navs)/len(navs):.4f} ({len(navs)} ETFs)")

    # ================================================================
    # Summary
    # ================================================================
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    print("\n  Crypto Trend:")
    for sym in CRYPTO_SYMBOLS:
        if sym in crypto_results:
            r = crypto_results[sym]
            print(f"    {sym}: standalone={r['standalone_nav']['final_nav']:.4f} "
                  f"vt={r['vt_standalone_nav']['final_nav']:.4f} "
                  f"maxDD={r['standalone_nav']['max_drawdown']:.2%} -> "
                  f"vt_maxDD={r['vt_standalone_nav']['max_drawdown']:.2%}")

    if "btc_beta_residual" in crypto_results:
        br = crypto_results["btc_beta_residual"]
        print(f"\n  BTC Beta-Residual: alpha={br['alpha_annualized']:+.2%}/yr beta={br['beta']:.4f} R²={br['r_squared']:.4f}")

    if "equal_weight_portfolio" in crypto_results:
        ew = crypto_results["equal_weight_portfolio"]
        print(f"  3-coin equal-weight: NAV={ew['final_nav']:.4f} maxDD={ew['max_drawdown']:.2%}")

    # ================================================================
    # Write manifest-last artifact (immutable, provenance-bound)
    # ================================================================
    if args.dry_run:
        print(f"\n[DRY RUN] no artifact written")
        return 0

    output_base = Path(args.output_dir)
    output_base.mkdir(parents=True, exist_ok=True)

    # Compute source hashes for provenance
    etf_zip_hash = ""
    if ETF_ZIP.exists():
        etf_zip_hash = hashlib.sha256(ETF_ZIP.read_bytes()).hexdigest()

    bundle_core: dict[str, Any] = {
        "schema_version": 1,
        "artifact_type": "r0_advancement_artifact",
        "observed_at": frozen_at,
        "data_window": {"start": f"{start_parts[0]}-{start_parts[1]:02d}", "end": f"{end_parts[0]}-{end_parts[1]:02d}"},
        "candidate_config": candidate_config.to_dict(),
        "runtime_bundle_id": runtime_bundle_id,
        "config": {
            "fast": candidate_config.fast, "slow": candidate_config.slow,
            "regime_sma": candidate_config.regime_sma, "vol_target": args.vol_target,
        },
        "universe": {
            "crypto_symbols": CRYPTO_SYMBOLS,
            "cta_r_etf_panel": CTA_R_ETF_PANEL,
        },
        "holdout_role": "discovery_pool",
        "source_hashes": {
            "etf_zip": etf_zip_hash,
            "crypto": crypto_source_hashes,
        },
        "results": crypto_results,
        "etf_results": etf_results,
        "cta_r_portfolio": cta_r_portfolio,
        "orders_authorized": False,
    }

    bundle_id = hashlib.sha256(canonical_hash(bundle_core).encode("ascii")).hexdigest()
    bundle_dir = output_base / bundle_id

    if bundle_dir.exists():
        print(f"ERROR: bundle already exists: {bundle_dir}", file=sys.stderr)
        return 1

    bundle_dir.mkdir(mode=0o700)

    _write_once(bundle_dir / "results.json", crypto_results)
    _write_once(bundle_dir / "config.json", bundle_core["config"])
    _write_once(bundle_dir / "candidate_config.json", candidate_config.to_dict())
    if etf_results:
        _write_once(bundle_dir / "etf_results.json", etf_results)
    if cta_r_portfolio:
        _write_once(bundle_dir / "cta_r_portfolio.json", cta_r_portfolio)
    _write_once(bundle_dir / "provenance.json", {
        "source_hashes": bundle_core["source_hashes"],
        "universe": bundle_core["universe"],
        "holdout_role": bundle_core["holdout_role"],
        "data_window": bundle_core["data_window"],
    })

    manifest = dict(bundle_core)
    manifest["bundle_id"] = bundle_id
    manifest["member_files"] = _member_refs(bundle_dir)
    manifest["manifest_hash"] = canonical_hash({k: v for k, v in manifest.items() if k != "manifest_hash"})
    _write_once(bundle_dir / "manifest.json", manifest)

    print(f"\nAdvancement artifact written: {bundle_dir}")
    print(f"  bundle_id: {bundle_id}")
    print(f"  members: {len(manifest['member_files'])}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
