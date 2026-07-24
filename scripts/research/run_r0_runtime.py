#!/usr/bin/env python3
"""R0-RUNTIME: compute Signal NAV and Standalone Executable NAV for C×D and CTA-R.

Loads real Binance klines/funding from data.binance.vision, generates trend
and carry signal positions, and computes the three NAV levels using frozen
cost models from R0-COST/NAV.

Outputs are write-once artifacts (0700/0600) with source hashes, cost model
hashes, and contamination-role watermarks.  These artifacts feed R0-RECORD.

Usage (Mac with network):
    python3 scripts/research/run_r0_runtime.py --symbol BTCUSDT \
        --start 2020,1 --end 2026,7

This script does NOT route orders, modify production, or authorize live trading.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import math
import os
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Callable
from typing import Sequence

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from qount.contracts import canonical_hash
from qount.grid.data import Bar
from qount.grid.data import closes as bar_closes
from qount.grid.data import load_funding
from qount.grid.data import load_klines
from qount.models import utc_now
from qount.research_data.candidate_config import CandidateConfig
from qount.research_data.cost_model import FrozenCostModel
from qount.research_data.cost_model import default_cxd_carry_cost_model
from qount.research_data.cost_model import default_cxd_trend_cost_model
from qount.research_data.nav import NavResult
from qount.research_data.nav import compute_carry_signal_nav
from qount.research_data.nav import compute_carry_standalone_nav
from qount.research_data.nav import compute_signal_nav
from qount.research_data.nav import compute_standalone_nav
from qount.x4.strategies import TrendFollow

R0_RUNTIME_SCHEMA_VERSION = 1
DEFAULT_OUTPUT_DIR = ROOT / "state" / "research_governance" / "r0_runtime"


# --- Write-once helpers (mirrors build_r0_data.py pattern) ------------------


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))
        .encode("ascii")
        + b"\n"
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
            raise RuntimeError(f"r0_runtime_readback_mismatch:{path}")
        if stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise RuntimeError(f"r0_runtime_mode_invalid:{path}")
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


def _verify_bundle(directory: Path) -> dict[str, Any]:
    if directory.is_symlink() or not directory.is_dir():
        raise RuntimeError("r0_runtime_dir_invalid")
    if stat.S_IMODE(directory.stat().st_mode) != 0o700:
        raise RuntimeError("r0_runtime_dir_mode_invalid")
    manifest = json.loads((directory / "manifest.json").read_text(encoding="ascii"))
    core = {k: v for k, v in manifest.items() if k != "manifest_hash"}
    if manifest.get("manifest_hash") != canonical_hash(core):
        raise RuntimeError("r0_runtime_manifest_hash_invalid")
    if manifest.get("bundle_id") != directory.name:
        raise RuntimeError("r0_runtime_identity_invalid")
    if manifest.get("member_files") != _member_refs(directory):
        raise RuntimeError("r0_runtime_member_mismatch")
    return manifest


# --- Signal generation ------------------------------------------------------


def generate_trend_positions(
    bars: Sequence[Bar],
    *,
    fast: int = 20,
    slow: int = 100,
    allow_short: bool = False,
    regime_sma: int = 0,
) -> list[float]:
    """Generate equity-normalized position weights from TrendFollow strategy.

    Returns a list aligned with *bars*: ``positions[t]`` is the target weight
    held from bar ``t`` to ``t+1``.  Warmup bars return 0.0.
    """

    strategy = TrendFollow(fast=fast, slow=slow, allow_short=allow_short, regime_sma=regime_sma)
    return [strategy.on_bar(bar) for bar in bars]


@dataclass(frozen=True)
class FundingAlignment:
    """Result of aggregating funding settlements into per-bar holding intervals.

    ``rates[i]`` is the **sum** of all funding settlement rates whose timestamp
    falls in ``[bar_i.ts_ms, bar_{i+1}.ts_ms)`` -- not a single "most recent"
    rate.  ``settlement_counts[i]`` is the number of settlements in that
    interval.  ``incomplete`` is True when any interval that *should* have
    settlements has zero (a data gap), not merely when the asset has no funding
    history at all.
    """

    rates: list[float]
    settlement_counts: list[int]
    incomplete: bool
    missing_intervals: list[dict[str, Any]]


def aggregate_funding_to_bars(
    bars: Sequence[Bar],
    funding_rates: Sequence,
) -> FundingAlignment:
    """Aggregate all funding settlements within each bar's holding interval.

    For each bar ``i``, the holding interval is ``[bar_i.ts_ms, bar_{i+1}.ts_ms)``.
    All funding settlements whose ``ts_ms`` falls in this interval are **summed**
    (Binance UM settles every 8h, so a full day typically has 3 settlements).

    Completeness: if any interval has 0 settlements *after* at least one
    prior interval had settlements, ``incomplete`` is set to True and the gap
    is recorded in ``missing_intervals``.  Intervals before the first settlement
    are not flagged (the asset simply had no funding history yet).
    """

    n = len(bars)
    rates = [0.0] * n
    counts = [0] * n
    missing_intervals: list[dict[str, Any]] = []

    if not funding_rates:
        return FundingAlignment(
            rates=rates, settlement_counts=counts,
            incomplete=False, missing_intervals=missing_intervals,
        )

    fund_sorted = sorted(funding_rates, key=lambda f: f.ts_ms)
    fi = 0
    seen_any_settlement = False

    for i in range(n):
        bar_ts = bars[i].ts_ms
        next_ts = bars[i + 1].ts_ms if i + 1 < n else bar_ts + 86_400_000

        while fi < len(fund_sorted) and fund_sorted[fi].ts_ms < next_ts:
            if fund_sorted[fi].ts_ms >= bar_ts:
                rates[i] += fund_sorted[fi].rate
                counts[i] += 1
            fi += 1

        if counts[i] == 0 and seen_any_settlement:
            missing_intervals.append({
                "bar_index": i,
                "bar_date": bars[i].date,
                "interval_start_ms": bar_ts,
                "interval_end_ms": next_ts,
                "expected_settlements": 3,
                "actual_settlements": 0,
            })
        if counts[i] > 0:
            seen_any_settlement = True

    incomplete = len(missing_intervals) > 0
    return FundingAlignment(
        rates=rates, settlement_counts=counts,
        incomplete=incomplete, missing_intervals=missing_intervals,
    )


def align_funding_to_bars(
    bars: Sequence[Bar],
    funding_rates: Sequence,
) -> list[float]:
    """Deprecated: returns only the rates list from aggregate_funding_to_bars.

    Use ``aggregate_funding_to_bars`` instead to also get settlement counts and
    completeness information.
    """

    return aggregate_funding_to_bars(bars, funding_rates).rates


# --- Summary stats ----------------------------------------------------------


def nav_summary(result: NavResult) -> dict[str, Any]:
    """Build a summary dict from a NavResult."""

    from qount.research_data.nav import compute_max_drawdown
    series = result.nav_series
    max_dd = compute_max_drawdown(series)
    years = result.bars / 365.0 if result.bars > 0 else 1.0
    annualized = (series[-1] ** (1.0 / years) - 1.0) if series and years > 0 and series[-1] > 0 else 0.0
    return {
        "final_nav": series[-1] if series else 0.0,
        "total_return": result.total_return,
        "total_cost": result.total_cost,
        "cost_breakdown": result.cost_breakdown,
        "cost_incomplete": result.cost_incomplete,
        "cost_model_hash": result.cost_model_hash,
        "bars": result.bars,
        "turnover": result.turnover,
        "max_drawdown": max_dd,
        "annualized_return": annualized,
    }


# --- Main -------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="R0-RUNTIME NAV computation")
    parser.add_argument("--symbol", default="BTCUSDT", help="Trading symbol")
    parser.add_argument("--start", default="2020,1", help="Start year,month (e.g. 2020,1)")
    parser.add_argument("--end", default=None, help="End year,month (default: current)")
    parser.add_argument("--fast", type=int, default=20, help="Fast SMA period")
    parser.add_argument("--slow", type=int, default=100, help="Slow SMA period")
    parser.add_argument("--regime-sma", type=int, default=0, help="Regime SMA gate (0=off)")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    candidate_config = CandidateConfig.create(
        fast=args.fast, slow=args.slow, regime_sma=args.regime_sma, allow_short=False,
    )

    start_parts = tuple(int(x) for x in args.start.split(","))
    if len(start_parts) != 2:
        print("ERROR: --start must be year,month", file=sys.stderr)
        return 1

    if args.end:
        end_parts = tuple(int(x) for x in args.end.split(","))
    else:
        now = _dt.datetime.now(_dt.UTC)
        end_parts = (now.year, now.month)

    symbol = args.symbol
    frozen_at = utc_now().isoformat()

    # --- Load data ---
    print(f"Loading UM daily klines for {symbol} ({start_parts[0]}-{start_parts[1]:02d} to {end_parts[0]}-{end_parts[1]:02d})...")
    um_bars = load_klines(symbol, "1d", start=start_parts, end=end_parts, market="um",
                          cache_dir=os.path.join("state", "r0_runtime", "klines"), skip_missing=True)
    print(f"  Loaded {len(um_bars)} UM bars ({um_bars[0].date} to {um_bars[-1].date})" if um_bars else "  No bars!")

    if len(um_bars) < 2:
        print("ERROR: insufficient UM bars", file=sys.stderr)
        return 1

    print(f"Loading spot daily klines for {symbol}...")
    spot_bars = load_klines(symbol, "1d", start=start_parts, end=end_parts, market="spot",
                            cache_dir=os.path.join("state", "r0_runtime", "klines"), skip_missing=True)
    print(f"  Loaded {len(spot_bars)} spot bars" if spot_bars else "  No spot bars!")

    print(f"Loading UM funding rates for {symbol}...")
    try:
        funding = load_funding(symbol, start=start_parts, end=end_parts,
                               cache_dir=os.path.join("state", "r0_runtime", "funding"), skip_missing=True)
        print(f"  Loaded {len(funding)} funding records")
    except Exception as exc:
        print(f"  Funding load failed: {exc}")
        funding = []

    # --- Trend leg ---
    print(f"\n--- Trend Leg (fast={args.fast}, slow={args.slow}, regime={args.regime_sma}, config_hash={candidate_config.config_hash[:12]}) ---")
    trend_positions = generate_trend_positions(
        um_bars, fast=args.fast, slow=args.slow, regime_sma=args.regime_sma,
    )
    um_closes = bar_closes(um_bars)

    trend_cost_model = default_cxd_trend_cost_model(frozen_at=frozen_at)
    trend_signal = compute_signal_nav(um_closes, trend_positions)

    funding_aligned = aggregate_funding_to_bars(um_bars, funding) if funding else None
    trend_standalone = compute_standalone_nav(
        um_closes, trend_positions, trend_cost_model,
        funding_rates=funding_aligned.rates if funding_aligned else None,
        funding_incomplete=funding_aligned.incomplete if funding_aligned else False,
    )

    trend_signal_summary = nav_summary(trend_signal)
    trend_standalone_summary = nav_summary(trend_standalone)
    print(f"  Signal NAV:      final={trend_signal_summary['final_nav']:.4f} "
          f"return={trend_signal_summary['total_return']:+.2%} "
          f"maxDD={trend_signal_summary['max_drawdown']:.2%}")
    print(f"  Standalone NAV:  final={trend_standalone_summary['final_nav']:.4f} "
          f"return={trend_standalone_summary['total_return']:+.2%} "
          f"cost={trend_standalone_summary['total_cost']:.4f} "
          f"incomplete={trend_standalone_summary['cost_incomplete']}")

    # --- Carry leg ---
    print(f"\n--- Carry Leg (spot + UM perp, delta-neutral) ---")
    carry_signal = None
    carry_standalone = None
    # Align spot and UM bars by date (they may differ by 1-2 days)
    spot_by_date = {b.date: b for b in spot_bars}
    um_by_date = {b.date: b for b in um_bars}
    common_dates = sorted(set(spot_by_date) & set(um_by_date))
    if len(common_dates) >= 2:
        aligned_spot = [spot_by_date[d] for d in common_dates]
        aligned_um = [um_by_date[d] for d in common_dates]
        spot_closes = bar_closes(aligned_spot)
        um_closes_aligned = bar_closes(aligned_um)
        carry_cost_model = default_cxd_carry_cost_model(frozen_at=frozen_at)
        carry_signal = compute_carry_signal_nav(spot_closes, um_closes_aligned)
        # Re-align funding to the common dates
        funding_aligned_carry = aggregate_funding_to_bars(aligned_um, funding) if funding else None
        carry_standalone = compute_carry_standalone_nav(
            spot_closes, um_closes_aligned, carry_cost_model,
            funding_rates=funding_aligned_carry.rates if funding_aligned_carry else None,
            funding_incomplete=funding_aligned_carry.incomplete if funding_aligned_carry else False,
        )
        cs = nav_summary(carry_signal)
        csa = nav_summary(carry_standalone)
        print(f"  Aligned {len(common_dates)} common bars ({common_dates[0]} to {common_dates[-1]})")
        print(f"  Signal NAV:      final={cs['final_nav']:.4f} return={cs['total_return']:+.2%}")
        print(f"  Standalone NAV:  final={csa['final_nav']:.4f} return={csa['total_return']:+.2%} "
              f"cost={csa['total_cost']:.4f} incomplete={csa['cost_incomplete']}")
    else:
        print(f"  Skipped (insufficient common bars: {len(common_dates)})")

    # --- Data hash ---
    um_closes_hash = hashlib.sha256(json.dumps([round(c, 8) for c in um_closes]).encode()).hexdigest()
    spot_closes_hash = hashlib.sha256(json.dumps([round(c, 8) for c in bar_closes(spot_bars)]).encode()).hexdigest() if spot_bars else ""
    funding_raw_hash = ""
    if funding:
        funding_raw_bytes = json.dumps(
            [[f.ts_ms, f.rate] for f in sorted(funding, key=lambda f: f.ts_ms)],
            ensure_ascii=True, separators=(",", ":"),
        ).encode("ascii")
        funding_raw_hash = hashlib.sha256(funding_raw_bytes).hexdigest()

    # --- Funding aggregation diagnostics ---
    funding_agg_info: dict[str, Any] = {
        "method": "interval_sum",
        "expected_per_day": 3,
        "total_settlements": len(funding),
        "missing_count": 0,
        "incomplete": False,
        "settlement_counts": [],
        "missing_intervals": [],
    }
    if funding_aligned:
        funding_agg_info["missing_count"] = len(funding_aligned.missing_intervals)
        funding_agg_info["incomplete"] = funding_aligned.incomplete
        funding_agg_info["settlement_counts"] = funding_aligned.settlement_counts
        funding_agg_info["missing_intervals"] = funding_aligned.missing_intervals

    # --- Build bundle ---
    bundle_core: dict[str, Any] = {
        "schema_version": R0_RUNTIME_SCHEMA_VERSION,
        "artifact_type": "r0_runtime_nav_artifact",
        "observed_at": frozen_at,
        "symbol": symbol,
        "data_window": {"start": f"{start_parts[0]}-{start_parts[1]:02d}", "end": f"{end_parts[0]}-{end_parts[1]:02d}"},
        "um_bars": len(um_bars),
        "spot_bars": len(spot_bars),
        "funding_records": len(funding),
        "um_closes_hash": um_closes_hash,
        "spot_closes_hash": spot_closes_hash,
        "funding_raw_hash": funding_raw_hash,
        "funding_aggregation": funding_agg_info,
        "trend_config": candidate_config.to_dict(),
        "trend_cost_model": trend_cost_model.to_dict(),
        "trend_signal_nav": trend_signal_summary,
        "trend_standalone_nav": trend_standalone_summary,
        "carry_cost_model": carry_cost_model.to_dict() if carry_standalone else None,
        "carry_signal_nav": nav_summary(carry_signal) if carry_signal else None,
        "carry_standalone_nav": nav_summary(carry_standalone) if carry_standalone else None,
        "orders_authorized": False,
        "candidate_pnl_ready": not (trend_standalone.cost_incomplete or (carry_standalone and carry_standalone.cost_incomplete)),
    }

    if args.dry_run:
        print(f"\n[DRY RUN] {json.dumps({k: v for k, v in bundle_core.items() if k not in ('trend_cost_model', 'carry_cost_model')}, indent=2, default=str)}")
        return 0

    # Write bundle
    output_base = Path(args.output_dir)
    output_base.mkdir(parents=True, exist_ok=True)
    bundle_id = hashlib.sha256(canonical_hash(bundle_core).encode("ascii")).hexdigest()
    bundle_dir = output_base / bundle_id

    if bundle_dir.exists():
        print(f"ERROR: bundle already exists: {bundle_dir}", file=sys.stderr)
        return 1

    bundle_dir.mkdir(mode=0o700)

    _write_once(bundle_dir / "trend_signal_nav.json", trend_signal.to_dict())
    _write_once(bundle_dir / "trend_standalone_nav.json", trend_standalone.to_dict())
    _write_once(bundle_dir / "trend_config.json", {
        **candidate_config.to_dict(), "cost_model": trend_cost_model.to_dict(),
    })
    if carry_signal and carry_standalone:
        _write_once(bundle_dir / "carry_signal_nav.json", carry_signal.to_dict())
        _write_once(bundle_dir / "carry_standalone_nav.json", carry_standalone.to_dict())
        _write_once(bundle_dir / "carry_config.json", {
            "cost_model": carry_cost_model.to_dict(),
        })
    _write_once(bundle_dir / "data_hashes.json", {
        "um_closes_hash": um_closes_hash,
        "spot_closes_hash": spot_closes_hash,
        "funding_raw_hash": funding_raw_hash,
        "um_bar_count": len(um_bars),
        "spot_bar_count": len(spot_bars),
        "funding_record_count": len(funding),
        "funding_aggregation": funding_agg_info,
        "um_first_date": um_bars[0].date if um_bars else None,
        "um_last_date": um_bars[-1].date if um_bars else None,
    })

    manifest = dict(bundle_core)
    manifest["bundle_id"] = bundle_id
    manifest["member_files"] = _member_refs(bundle_dir)
    manifest["manifest_hash"] = canonical_hash({k: v for k, v in manifest.items() if k != "manifest_hash"})
    _write_once(bundle_dir / "manifest.json", manifest)

    verified = _verify_bundle(bundle_dir)
    print(f"\nBundle written and verified: {bundle_dir}")
    print(f"  bundle_id: {bundle_id}")
    print(f"  members: {len(verified['member_files'])}")
    print(f"  trend_signal_final: {trend_signal_summary['final_nav']:.4f}")
    print(f"  trend_standalone_final: {trend_standalone_summary['final_nav']:.4f}")
    if carry_signal:
        print(f"  carry_signal_final: {nav_summary(carry_signal)['final_nav']:.4f}")
        print(f"  carry_standalone_final: {nav_summary(carry_standalone)['final_nav']:.4f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
