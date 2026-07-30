#!/usr/bin/env python3
"""R0 deep validation: chronological folds, cost sensitivity, beta residual stability, new-data review.

Four validations on the corrected R0 artifacts:

1. Chronological folds: split 2020-2026 into segments, compute trend
   standalone NAV for each to check temporal consistency.
2. Cost sensitivity: vary taker_fee, slippage, funding multiplier and
   measure NAV impact.
3. Beta residual fold stability: rolling 365-day window alpha consistency.
4. Untouched/new-data review: check if data beyond 2026-06 is available.

Usage:
    python3 scripts/research/governance/run_r0_validation.py --start 2020,1 --end 2026,6
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any

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
from qount.research_data.cost_model import default_cxd_trend_cost_model
from qount.research_data.nav import compute_max_drawdown
from qount.research_data.nav import compute_signal_nav
from qount.research_data.nav import compute_standalone_nav
from qount.legacy.x4.strategies import TrendFollow

from scripts.research.governance.run_r0_runtime import aggregate_funding_to_bars

DEFAULT_OUTPUT_DIR = ROOT / "state" / "research_governance" / "r0_validation"


# --- Write-once helpers -----------------------------------------------------


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
            raise RuntimeError(f"r0_validation_readback_mismatch:{path}")
        if stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise RuntimeError(f"r0_validation_mode_invalid:{path}")
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


def _nav_summary(result) -> dict[str, Any]:
    series = result.nav_series
    max_dd = compute_max_drawdown(series) if series else 0.0
    years = result.bars / 365.0 if result.bars > 0 else 1.0
    annual = (series[-1] ** (1.0 / years) - 1.0) if years > 0 and series and series[-1] > 0 else -1.0
    return {
        "final_nav": series[-1] if series else 0.0,
        "total_return": result.total_return,
        "total_cost": result.total_cost,
        "max_drawdown": max_dd,
        "annualized_return": annual,
        "bars": result.bars,
    }


def _daily_returns(nav_series: list[float]) -> list[float]:
    if len(nav_series) < 2:
        return []
    return [nav_series[i] / nav_series[i-1] - 1.0 for i in range(1, len(nav_series)) if nav_series[i-1] != 0]


def _regress(y: list[float], x: list[float]) -> tuple[float, float, float]:
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


# --- Validations ------------------------------------------------------------


def validate_chronological_folds(
    bars: list[Bar], funding: list, candidate_config: CandidateConfig, frozen_at: str,
) -> dict[str, Any]:
    """Split data into chronological segments and compute trend standalone NAV per segment."""
    print("\n--- Validation 1: Chronological Folds ---")
    # Split into ~2-year segments
    fold_boundaries = [
        ("2020-2021", "2020-01-01", "2021-12-31"),
        ("2022-2023", "2022-01-01", "2023-12-31"),
        ("2024-2026", "2024-01-01", "2026-12-31"),
    ]

    fold_results: list[dict[str, Any]] = []
    for label, start_date, end_date in fold_boundaries:
        segment_bars = [b for b in bars if start_date <= b.date <= end_date]
        if len(segment_bars) < 2:
            fold_results.append({"fold": label, "bars": len(segment_bars), "skipped": True})
            continue

        closes = bar_closes(segment_bars)
        strategy = TrendFollow(
            fast=candidate_config.fast, slow=candidate_config.slow,
            allow_short=candidate_config.allow_short, regime_sma=candidate_config.regime_sma,
        )
        positions = [strategy.on_bar(b) for b in segment_bars]
        cost_model = default_cxd_trend_cost_model(frozen_at=frozen_at)

        seg_funding = aggregate_funding_to_bars(segment_bars, funding) if funding else None
        seg_funding_rates = seg_funding.rates if seg_funding else None

        nav = compute_standalone_nav(closes, positions, cost_model, funding_rates=seg_funding_rates)
        summary = _nav_summary(nav)
        summary["fold"] = label
        summary["first_date"] = segment_bars[0].date
        summary["last_date"] = segment_bars[-1].date
        fold_results.append(summary)
        print(f"  {label}: NAV={summary['final_nav']:.4f} maxDD={summary['max_drawdown']:.2%} "
              f"annual={summary['annualized_return']:+.2%} ({len(segment_bars)} bars)")

    all_navs = [f["final_nav"] for f in fold_results if not f.get("skipped")]
    positive_folds = sum(1 for n in all_navs if n > 1.0)
    return {
        "folds": fold_results,
        "positive_folds": positive_folds,
        "total_folds": len(all_navs),
        "consistency": "pass" if positive_folds == len(all_navs) else "partial" if positive_folds > 0 else "fail",
    }


def validate_cost_sensitivity(
    bars: list[Bar], funding: list, candidate_config: CandidateConfig, frozen_at: str,
) -> dict[str, Any]:
    """Vary cost parameters and measure NAV impact."""
    print("\n--- Validation 2: Cost Sensitivity ---")
    closes = bar_closes(bars)
    strategy = TrendFollow(
        fast=candidate_config.fast, slow=candidate_config.slow,
        allow_short=candidate_config.allow_short, regime_sma=candidate_config.regime_sma,
    )
    positions = [strategy.on_bar(b) for b in bars]
    funding_aligned = aggregate_funding_to_bars(bars, funding) if funding else None
    funding_rates = funding_aligned.rates if funding_aligned else None

    scenarios: dict[str, dict[str, Any]] = {}

    # Baseline
    base_model = default_cxd_trend_cost_model(frozen_at=frozen_at)
    base_nav = compute_standalone_nav(closes, positions, base_model, funding_rates=funding_rates)
    base_final = base_nav.nav_series[-1]
    scenarios["baseline"] = {"final_nav": base_final, "taker_fee": 0.0004, "slippage_bps": 2.0, "funding_mult": 1.0}

    # Taker fee variations
    for mult, label in [(0.5, "taker_0.5x"), (2.0, "taker_2x"), (5.0, "taker_5x")]:
        model = default_cxd_trend_cost_model(taker_fee=0.0004 * mult, frozen_at=frozen_at)
        nav = compute_standalone_nav(closes, positions, model, funding_rates=funding_rates)
        scenarios[label] = {"final_nav": nav.nav_series[-1], "taker_fee": 0.0004 * mult, "slippage_bps": 2.0, "funding_mult": 1.0}

    # Slippage variations
    for mult, label in [(0.5, "slippage_0.5x"), (2.0, "slippage_2x"), (5.0, "slippage_5x")]:
        model = default_cxd_trend_cost_model(slippage_bps=2.0 * mult, frozen_at=frozen_at)
        nav = compute_standalone_nav(closes, positions, model, funding_rates=funding_rates)
        scenarios[label] = {"final_nav": nav.nav_series[-1], "taker_fee": 0.0004, "slippage_bps": 2.0 * mult, "funding_mult": 1.0}

    # Funding variations
    for mult, label in [(0.5, "funding_0.5x"), (2.0, "funding_2x")]:
        model = default_cxd_trend_cost_model(funding_multiplier=mult, frozen_at=frozen_at)
        nav = compute_standalone_nav(closes, positions, model, funding_rates=funding_rates)
        scenarios[label] = {"final_nav": nav.nav_series[-1], "taker_fee": 0.0004, "slippage_bps": 2.0, "funding_mult": mult}

    for label, s in sorted(scenarios.items()):
        delta = s["final_nav"] - base_final
        pct = delta / base_final * 100 if base_final != 0 else 0
        print(f"  {label:20s}: NAV={s['final_nav']:.4f} (delta={delta:+.4f}, {pct:+.1f}%)")

    all_positive = all(s["final_nav"] > 1.0 for s in scenarios.values())
    return {
        "scenarios": scenarios,
        "baseline_nav": base_final,
        "all_positive": all_positive,
        "min_nav": min(s["final_nav"] for s in scenarios.values()),
        "max_nav": max(s["final_nav"] for s in scenarios.values()),
    }


def validate_beta_residual_stability(
    bars: list[Bar], candidate_config: CandidateConfig,
) -> dict[str, Any]:
    """Rolling 365-day window alpha consistency."""
    print("\n--- Validation 3: Beta Residual Fold Stability ---")
    closes = bar_closes(bars)
    strategy = TrendFollow(
        fast=candidate_config.fast, slow=candidate_config.slow,
        allow_short=candidate_config.allow_short, regime_sma=candidate_config.regime_sma,
    )
    positions = [strategy.on_bar(b) for b in bars]
    trend_nav = compute_signal_nav(closes, positions)
    bh_nav = compute_signal_nav(closes, [1.0] * len(closes))

    trend_returns = _daily_returns(list(trend_nav.nav_series))
    bh_returns = _daily_returns(list(bh_nav.nav_series))
    dates = [b.date for b in bars]

    window = 365
    min_len = min(len(trend_returns), len(bh_returns), len(dates) - 1)

    rolling_alphas: list[dict[str, Any]] = []
    for start in range(0, min_len - window + 1, 90):  # 90-day step
        end = start + window
        if end > min_len:
            break
        tr_seg = trend_returns[start:end]
        bh_seg = bh_returns[start:end]
        alpha, beta, r_sq = _regress(tr_seg, bh_seg)
        rolling_alphas.append({
            "start_date": dates[start + 1] if start + 1 < len(dates) else "",
            "end_date": dates[end] if end < len(dates) else "",
            "alpha_daily": alpha,
            "alpha_annualized": alpha * 365,
            "beta": beta,
            "r_squared": r_sq,
            "window_bars": window,
        })

    for r in rolling_alphas:
        print(f"  {r['start_date']} to {r['end_date']}: alpha={r['alpha_annualized']:+.4%} "
              f"beta={r['beta']:.4f} R²={r['r_squared']:.4f}")

    if rolling_alphas:
        alphas = [r["alpha_annualized"] for r in rolling_alphas]
        positive_alphas = sum(1 for a in alphas if a > 0)
        return {
            "windows": rolling_alphas,
            "window_count": len(rolling_alphas),
            "positive_alpha_windows": positive_alphas,
            "alpha_min": min(alphas),
            "alpha_max": max(alphas),
            "alpha_mean": sum(alphas) / len(alphas),
            "consistency": "pass" if positive_alphas == len(alphas) else "partial" if positive_alphas > 0 else "fail",
        }
    return {"windows": [], "window_count": 0, "consistency": "no_data"}


def validate_new_data_review(start_parts: tuple[int, int], end_parts: tuple[int, int]) -> dict[str, Any]:
    """Check if data beyond the consumed window is available."""
    print("\n--- Validation 4: Untouched/New-Data Review ---")
    # Try loading one month beyond end_parts
    next_year = end_parts[0] + (1 if end_parts[1] == 12 else 0)
    next_month = 1 if end_parts[1] == 12 else end_parts[1] + 1
    try:
        next_bars = load_klines("BTCUSDT", "1d", start=(next_year, next_month), end=(next_year, next_month),
                                market="um", cache_dir=os.path.join("state", "r0_runtime", "klines"),
                                skip_missing=True)
        next_count = len(next_bars)
        print(f"  {next_year}-{next_month:02d}: {next_count} bars available")
    except Exception:
        next_count = 0
        print(f"  {next_year}-{next_month:02d}: no data available")

    return {
        "consumed_window": {"start": f"{start_parts[0]}-{start_parts[1]:02d}", "end": f"{end_parts[0]}-{end_parts[1]:02d}"},
        "next_month_available": next_count > 0,
        "next_month_bars": next_count,
        "next_month": f"{next_year}-{next_month:02d}",
    }


# --- Main -------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="R0 deep validation")
    parser.add_argument("--start", default="2020,1")
    parser.add_argument("--end", default=None)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    start_parts = tuple(int(x) for x in args.start.split(","))
    if args.end:
        end_parts = tuple(int(x) for x in args.end.split(","))
    else:
        now = _dt.datetime.now(_dt.UTC)
        end_parts = (now.year, now.month)

    frozen_at = utc_now().isoformat()
    candidate_config = CandidateConfig.default()

    print("=" * 60)
    print(f"R0 Deep Validation (config_hash={candidate_config.config_hash[:12]}...)")
    print("=" * 60)

    # Load data
    print(f"\nLoading BTCUSDT UM daily ({start_parts[0]}-{start_parts[1]:02d} to {end_parts[0]}-{end_parts[1]:02d})...")
    bars = load_klines("BTCUSDT", "1d", start=start_parts, end=end_parts, market="um",
                       cache_dir=os.path.join("state", "r0_runtime", "klines"), skip_missing=True)
    funding = load_funding("BTCUSDT", start=start_parts, end=end_parts,
                           cache_dir=os.path.join("state", "r0_runtime", "funding"), skip_missing=True)
    print(f"  {len(bars)} bars, {len(funding)} funding records ({bars[0].date} to {bars[-1].date})")

    # Run validations
    folds = validate_chronological_folds(bars, funding, candidate_config, frozen_at)
    sensitivity = validate_cost_sensitivity(bars, funding, candidate_config, frozen_at)
    beta_stability = validate_beta_residual_stability(bars, candidate_config)
    new_data = validate_new_data_review(start_parts, end_parts)

    # Summary
    print("\n" + "=" * 60)
    print("VALIDATION SUMMARY")
    print("=" * 60)
    print(f"  1. Chronological folds: {folds['consistency']} ({folds['positive_folds']}/{folds['total_folds']} positive)")
    print(f"  2. Cost sensitivity: all_positive={sensitivity['all_positive']} "
          f"range=[{sensitivity['min_nav']:.4f}, {sensitivity['max_nav']:.4f}]")
    print(f"  3. Beta residual stability: {beta_stability.get('consistency', 'N/A')} "
          f"({beta_stability.get('positive_alpha_windows', 0)}/{beta_stability.get('window_count', 0)} positive alpha)")
    print(f"  4. New data: {new_data['next_month_available']} ({new_data['next_month_bars']} bars in {new_data['next_month']})")

    if args.dry_run:
        print("\n[DRY RUN] no artifact written")
        return 0

    # Write artifact
    output_base = Path(args.output_dir)
    output_base.mkdir(parents=True, exist_ok=True)

    bundle_core: dict[str, Any] = {
        "schema_version": 1,
        "artifact_type": "r0_validation_artifact",
        "observed_at": frozen_at,
        "data_window": {"start": f"{start_parts[0]}-{start_parts[1]:02d}", "end": f"{end_parts[0]}-{end_parts[1]:02d}"},
        "candidate_config": candidate_config.to_dict(),
        "holdout_role": "discovery_pool",
        "validation_results": {
            "chronological_folds": folds,
            "cost_sensitivity": sensitivity,
            "beta_residual_stability": beta_stability,
            "new_data_review": new_data,
        },
        "orders_authorized": False,
    }

    bundle_id = hashlib.sha256(canonical_hash(bundle_core).encode("ascii")).hexdigest()
    bundle_dir = output_base / bundle_id

    if bundle_dir.exists():
        print(f"ERROR: bundle already exists: {bundle_dir}", file=sys.stderr)
        return 1

    bundle_dir.mkdir(mode=0o700)

    _write_once(bundle_dir / "validation_results.json", bundle_core["validation_results"])
    _write_once(bundle_dir / "candidate_config.json", candidate_config.to_dict())

    manifest = dict(bundle_core)
    manifest["bundle_id"] = bundle_id
    manifest["member_files"] = _member_refs(bundle_dir)
    manifest["manifest_hash"] = canonical_hash({k: v for k, v in manifest.items() if k != "manifest_hash"})
    _write_once(bundle_dir / "manifest.json", manifest)

    print(f"\nValidation artifact written: {bundle_dir}")
    print(f"  bundle_id: {bundle_id}")
    print(f"  members: {len(manifest['member_files'])}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
