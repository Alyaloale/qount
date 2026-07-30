#!/usr/bin/env python3
"""R0-DECISION: apply kill tests and produce retain/revise/reject decisions.

Reads the R0-RUNTIME bundle, runs tail stress tests (cost doubling, 1-bar
delay, random missed fills), evaluates each candidate's kill tests, and
writes a decision artifact with documented reasoning.

Stress tests (per roadmap §5.1):
  - cost_doubling: 2x taker_fee + slippage
  - delay_1_bar: positions shifted forward by 1 bar
  - missed_fills: 10% of position changes randomly set to 0
  - worse_execution: 5x slippage

Kill tests (per CandidateRevalidationRecord):
  - standalone_nav_non_positive_after_tail
  - independent_nav_reconciliation_failure
  - point_in_time_data_gap

Usage:
    python3 scripts/research/governance/run_r0_decision.py \
        --runtime-bundle state/research_governance/r0_runtime/<bundle_id> \
        --symbol BTCUSDT --start 2020,1 --end 2026,7
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import random
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
from qount.research_data.cost_model import default_cxd_carry_cost_model
from qount.research_data.cost_model import default_cxd_trend_cost_model
from qount.research_data.nav import compute_carry_signal_nav
from qount.research_data.nav import compute_carry_standalone_nav
from qount.research_data.nav import compute_signal_nav
from qount.research_data.nav import compute_standalone_nav
from qount.legacy.x4.strategies import TrendFollow
from scripts.research.governance.run_r0_runtime import aggregate_funding_to_bars

DEFAULT_OUTPUT_DIR = ROOT / "state" / "research_governance" / "r0_decision"


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
            raise RuntimeError(f"r0_decision_readback_mismatch:{path}")
        if stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise RuntimeError(f"r0_decision_mode_invalid:{path}")
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


# --- Stress tests -----------------------------------------------------------


def stress_cost_doubling(closes, positions, funding, frozen_at):
    """Re-run with 2x taker_fee + 2x slippage."""
    model = default_cxd_trend_cost_model(
        taker_fee=0.0004 * 2, slippage_bps=2.0 * 2, frozen_at=frozen_at,
    )
    return compute_standalone_nav(closes, positions, model, funding_rates=funding)


def stress_delay_1_bar(closes, positions, funding, frozen_at):
    """Shift positions forward by 1 bar (execute on next bar's close)."""
    delayed = [0.0] + list(positions[:-1])
    model = default_cxd_trend_cost_model(frozen_at=frozen_at)
    return compute_standalone_nav(closes, delayed, model, funding_rates=funding)


def stress_missed_fills(closes, positions, funding, frozen_at, miss_rate=0.1, seed=42):
    """Randomly skip 10% of position changes (simulate missed fills)."""
    rng = random.Random(seed)
    missed = list(positions)
    for i in range(1, len(missed)):
        if missed[i] != missed[i - 1] and rng.random() < miss_rate:
            missed[i] = missed[i - 1]  # keep previous position
    model = default_cxd_trend_cost_model(frozen_at=frozen_at)
    return compute_standalone_nav(closes, missed, model, funding_rates=funding)


def stress_worse_execution(closes, positions, funding, frozen_at):
    """5x slippage to simulate adverse market conditions."""
    model = default_cxd_trend_cost_model(
        slippage_bps=2.0 * 5, frozen_at=frozen_at,
    )
    return compute_standalone_nav(closes, positions, model, funding_rates=funding)


def stress_worse_execution_carry(spot_closes, perp_closes, funding, frozen_at):
    """5x slippage for carry leg."""
    model = default_cxd_carry_cost_model(
        slippage_bps=1.0 * 5, frozen_at=frozen_at,
    )
    return compute_carry_standalone_nav(spot_closes, perp_closes, model, funding_rates=funding)


# --- Nav summary ------------------------------------------------------------


def _nav_summary(result) -> dict[str, Any]:
    from qount.research_data.nav import compute_max_drawdown
    series = result.nav_series
    max_dd = compute_max_drawdown(series)
    years = result.bars / 365.0 if result.bars > 0 else 1.0
    annualized = (series[-1] ** (1.0 / years) - 1.0) if series and years > 0 and series[-1] > 0 else -1.0
    return {
        "final_nav": series[-1] if series else 0.0,
        "total_return": result.total_return,
        "total_cost": result.total_cost,
        "max_drawdown": max_dd,
        "annualized_return": annualized,
        "cost_incomplete": result.cost_incomplete,
    }


# --- Independent NAV reconciliation ------------------------------------------


def _independent_trend_nav(
    closes: list[float],
    positions: list[float],
    cost_model: Any,
    funding_rates: list[float] | None,
) -> float:
    """Independent trend NAV: simple loop, does NOT use compute_standalone_nav.

    Extracts rates directly from cost model components and computes NAV
    step by step.  Used by kill test 2 to reconcile against the runtime
    bundle's NAV.
    """

    rates: dict[str, float] = {}
    for comp in cost_model.components:
        rates[comp.name] = float(comp.rate)
    taker = rates.get("taker_fee", 0.0)
    slippage = rates.get("slippage", 0.0)
    funding_mult = rates.get("funding", 0.0)
    turnover_rate = taker + slippage

    nav = 1.0
    for t in range(1, len(closes)):
        prev_c = float(closes[t - 1])
        curr_c = float(closes[t])
        if prev_c <= 0:
            continue
        ret = curr_c / prev_c - 1.0
        pos = float(positions[t - 1])
        turnover = abs(float(positions[t]) - float(positions[t - 1]))
        cost = turnover * turnover_rate
        fund = 0.0
        if funding_rates and t - 1 < len(funding_rates):
            fund = pos * float(funding_rates[t - 1]) * funding_mult
        nav = nav * (1.0 + pos * ret - cost - fund)
    return nav


def _independent_carry_nav(
    spot_closes: list[float],
    perp_closes: list[float],
    cost_model: Any,
    funding_rates: list[float] | None,
    weight: float = 0.5,
) -> float:
    """Independent carry NAV: simple loop, does NOT use compute_carry_standalone_nav.

    Uses additive NAV (matching the new carry model) with gross = 2*weight.
    """

    rates: dict[str, float] = {}
    for comp in cost_model.components:
        rates[comp.name] = float(comp.rate)
    taker = rates.get("taker_fee", 0.0)
    maker = rates.get("maker_fee", 0.0)
    spread = rates.get("spread", 0.0)
    slippage = rates.get("slippage", 0.0)
    legging = rates.get("legging_cost", 0.0)
    funding_mult = rates.get("funding", 0.0)

    turnover_rate = taker + maker + spread + slippage + legging
    turnover_per_entry = 2.0 * weight

    nav = 1.0 - turnover_per_entry * turnover_rate   # entry cost

    for t in range(1, len(spot_closes)):
        prev_s = float(spot_closes[t - 1])
        curr_s = float(spot_closes[t])
        prev_p = float(perp_closes[t - 1])
        curr_p = float(perp_closes[t])
        if prev_s <= 0 or prev_p <= 0:
            continue
        spot_ret = curr_s / prev_s - 1.0
        perp_ret = curr_p / prev_p - 1.0
        market_pnl = weight * (spot_ret - perp_ret)
        fund = 0.0
        if funding_rates and t - 1 < len(funding_rates):
            fund = -weight * float(funding_rates[t - 1]) * funding_mult
        nav = nav + market_pnl - fund

    nav -= turnover_per_entry * turnover_rate  # exit cost
    return nav


# --- Kill test evaluation ---------------------------------------------------


def evaluate_kill_tests(
    baseline_nav: float,
    stress_results: dict[str, dict[str, Any]],
    *,
    candidate_name: str,
    independent_nav: float | None = None,
    runtime_nav: float | None = None,
    funding_missing_count: int = 0,
    funding_incomplete: bool = False,
    r0_data_available: bool = False,
) -> dict[str, Any]:
    """Evaluate the three kill tests and return pass/fail + reasoning."""

    results: dict[str, Any] = {}

    # Kill test 1: standalone_nav_non_positive_after_tail
    all_navs = [baseline_nav] + [s["final_nav"] for s in stress_results.values()]
    nav_positive = all(n > 1.0 for n in all_navs)
    results["standalone_nav_non_positive_after_tail"] = {
        "pass": nav_positive,
        "baseline_nav": baseline_nav,
        "stress_navs": {k: v["final_nav"] for k, v in stress_results.items()},
        "reasoning": (
            "All NAVs positive after tail stress" if nav_positive else
            f"At least one NAV <= 1.0: {[round(n, 4) for n in all_navs]}"
        ),
    }

    # Kill test 2: independent_nav_reconciliation_failure
    if independent_nav is not None and runtime_nav is not None:
        reconciled = abs(independent_nav - runtime_nav) < 1e-6
        results["independent_nav_reconciliation_failure"] = {
            "pass": reconciled,
            "independent_nav": round(independent_nav, 10),
            "runtime_nav": round(runtime_nav, 10),
            "delta": abs(independent_nav - runtime_nav),
            "reasoning": (
                f"Independent NAV {independent_nav:.10f} matches runtime {runtime_nav:.10f}"
                if reconciled else
                f"Independent NAV {independent_nav:.10f} != runtime {runtime_nav:.10f}"
            ),
        }
    else:
        results["independent_nav_reconciliation_failure"] = {
            "pass": False,
            "reasoning": "No reconciliation data provided (independent_nav or runtime_nav is None)",
        }

    # Kill test 3: point_in_time_data_gap
    if not r0_data_available:
        results["point_in_time_data_gap"] = {
            "pass": False,
            "r0_data_available": False,
            "reasoning": "R0-DATA bundle not available locally; PIT membership cannot be verified",
        }
    elif funding_missing_count > 0 or funding_incomplete:
        results["point_in_time_data_gap"] = {
            "pass": False,
            "r0_data_available": True,
            "funding_missing_count": funding_missing_count,
            "funding_incomplete": funding_incomplete,
            "reasoning": f"Funding gaps detected: missing_count={funding_missing_count}, incomplete={funding_incomplete}",
        }
    else:
        results["point_in_time_data_gap"] = {
            "pass": True,
            "r0_data_available": True,
            "funding_missing_count": funding_missing_count,
            "funding_incomplete": funding_incomplete,
            "reasoning": "R0-DATA available; no funding gaps detected",
        }

    all_pass = all(r["pass"] for r in results.values())
    return {
        "candidate": candidate_name,
        "all_kill_tests_pass": all_pass,
        "kill_tests": results,
        "decision": "retain" if all_pass else ("revise" if baseline_nav > 1.0 else "reject"),
        "decision_reasoning": _decision_reasoning(candidate_name, all_pass, baseline_nav, stress_results),
    }


def _decision_reasoning(candidate: str, all_pass: bool, baseline_nav: float, stress: dict) -> str:
    if all_pass:
        return f"{candidate}: all kill tests pass, Standalone NAV {baseline_nav:.4f} > 1.0 under all stress; retain for shadow/beta-residual audit"
    if baseline_nav <= 1.0:
        return f"{candidate}: Standalone NAV {baseline_nav:.4f} <= 1.0 at baseline; reject this version, allow revised mechanism"
    # Some stress test failed but baseline is positive
    failed = [k for k, v in stress.items() if v["final_nav"] <= 1.0]
    return f"{candidate}: baseline NAV {baseline_nav:.4f} positive but stress {failed} failed; revise with tail audit"


# --- Main -------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="R0-DECISION kill tests + retain/revise/reject")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--start", default="2020,1")
    parser.add_argument("--end", default=None)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--runtime-bundle", required=True,
                        help="Path to a verified R0-RUNTIME bundle directory (required)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    start_parts = tuple(int(x) for x in args.start.split(","))
    if args.end:
        end_parts = tuple(int(x) for x in args.end.split(","))
    else:
        now = _dt.datetime.now(_dt.UTC)
        end_parts = (now.year, now.month)

    symbol = args.symbol
    frozen_at = utc_now().isoformat()

    # --- Load data ---
    print(f"Loading data for {symbol}...")
    um_bars = load_klines(symbol, "1d", start=start_parts, end=end_parts, market="um",
                          cache_dir=os.path.join("state", "r0_runtime", "klines"), skip_missing=True)
    spot_bars = load_klines(symbol, "1d", start=start_parts, end=end_parts, market="spot",
                            cache_dir=os.path.join("state", "r0_runtime", "klines"), skip_missing=True)
    funding = load_funding(symbol, start=start_parts, end=end_parts,
                           cache_dir=os.path.join("state", "r0_runtime", "funding"), skip_missing=True)

    print(f"  UM: {len(um_bars)} bars, Spot: {len(spot_bars)} bars, Funding: {len(funding)} records")

    # --- Read trend config from runtime bundle (required) ---
    runtime_bundle_id = None
    runtime_bundle_verified = False
    input_verification: dict[str, Any] = {
        "closes_hash_match": False,
        "funding_hash_match": False,
        "baseline_nav_match": False,
        "carry_nav_match": False,
        "config_hash_match": False,
    }
    rt_manifest: dict[str, Any] | None = None
    candidate_config: CandidateConfig | None = None

    bundle_path = Path(args.runtime_bundle)
    print(f"\n--- Reading Runtime Bundle Config ---")
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
    input_verification["config_hash_match"] = candidate_config.config_hash == rt_cfg.get("config_hash", "")
    print(f"  Using config from bundle: {candidate_config.to_dict()}")
    if not input_verification["config_hash_match"]:
        print(f"ERROR: config_hash mismatch in runtime bundle", file=sys.stderr)
        return 1

    # --- Generate trend positions ---
    um_closes = bar_closes(um_bars)
    strategy = TrendFollow(
        fast=candidate_config.fast, slow=candidate_config.slow,
        allow_short=candidate_config.allow_short, regime_sma=candidate_config.regime_sma,
    )
    positions = [strategy.on_bar(bar) for bar in um_bars]

    # Aggregate funding (sum all settlements per holding interval)
    funding_aligned = aggregate_funding_to_bars(um_bars, funding) if funding else None
    funding_rates_list = funding_aligned.rates if funding_aligned else None
    funding_incomplete = funding_aligned.incomplete if funding_aligned else False

    # --- Baseline NAVs ---
    trend_cost = default_cxd_trend_cost_model(frozen_at=frozen_at)
    trend_baseline = compute_standalone_nav(
        um_closes, positions, trend_cost,
        funding_rates=funding_rates_list,
        funding_incomplete=funding_incomplete,
    )
    trend_baseline_summary = _nav_summary(trend_baseline)

    # Compute carry baseline (needed for verification)
    spot_by_date = {b.date: b for b in spot_bars}
    um_by_date = {b.date: b for b in um_bars}
    common_dates = sorted(set(spot_by_date) & set(um_by_date))
    carry_baseline_summary: dict[str, Any] | None = None
    spot_closes: list[float] = []
    um_closes_aligned: list[float] = []
    funding_rates_carry: list[float] | None = None
    funding_incomplete_carry = False
    carry_cost_model = None
    if len(common_dates) >= 2:
        aligned_spot = [spot_by_date[d] for d in common_dates]
        aligned_um = [um_by_date[d] for d in common_dates]
        spot_closes = bar_closes(aligned_spot)
        um_closes_aligned = bar_closes(aligned_um)
        funding_aligned_carry = aggregate_funding_to_bars(aligned_um, funding) if funding else None
        funding_rates_carry = funding_aligned_carry.rates if funding_aligned_carry else None
        funding_incomplete_carry = funding_aligned_carry.incomplete if funding_aligned_carry else False
        carry_cost_model = default_cxd_carry_cost_model(frozen_at=frozen_at)
        carry_baseline = compute_carry_standalone_nav(
            spot_closes, um_closes_aligned, carry_cost_model,
            funding_rates=funding_rates_carry,
            funding_incomplete=funding_incomplete_carry,
        )
        carry_baseline_summary = _nav_summary(carry_baseline)

    # --- Runtime bundle hash verification (provenance) ---
    if rt_manifest is not None:
        print(f"\n--- Runtime Bundle Verification ---")

        # Verify manifest hash
        rt_core = {k: v for k, v in rt_manifest.items() if k != "manifest_hash"}
        if rt_manifest.get("manifest_hash") != canonical_hash(rt_core):
            print(f"ERROR: runtime bundle manifest hash invalid", file=sys.stderr)
            return 1

        # Verify closes hash
        local_closes_hash = hashlib.sha256(
            json.dumps([round(c, 8) for c in um_closes]).encode()
        ).hexdigest()
        input_verification["closes_hash_match"] = (
            local_closes_hash == rt_manifest.get("um_closes_hash")
        )
        print(f"  closes_hash_match: {input_verification['closes_hash_match']}")

        # Verify funding raw hash
        if funding:
            funding_raw_bytes = json.dumps(
                [[f.ts_ms, f.rate] for f in sorted(funding, key=lambda f: f.ts_ms)],
                ensure_ascii=True, separators=(",", ":"),
            ).encode("ascii")
            local_funding_hash = hashlib.sha256(funding_raw_bytes).hexdigest()
            input_verification["funding_hash_match"] = (
                local_funding_hash == rt_manifest.get("funding_raw_hash")
            )
            print(f"  funding_hash_match: {input_verification['funding_hash_match']}")

        # Verify baseline NAV matches
        rt_trend_nav = rt_manifest.get("trend_standalone_nav", {})
        input_verification["baseline_nav_match"] = (
            abs(trend_baseline_summary["final_nav"] - rt_trend_nav.get("final_nav", 0.0)) < 1e-10
        )
        print(f"  baseline_nav_match: {input_verification['baseline_nav_match']}")

        # Verify carry baseline NAV matches
        rt_carry_nav = rt_manifest.get("carry_standalone_nav", {})
        if rt_carry_nav and carry_baseline_summary:
            input_verification["carry_nav_match"] = (
                abs(carry_baseline_summary["final_nav"] - rt_carry_nav.get("final_nav", 0.0)) < 1e-10
            )
            print(f"  carry_nav_match: {input_verification['carry_nav_match']}")

        runtime_bundle_verified = all(input_verification.values())
        if not runtime_bundle_verified:
            print(f"ERROR: runtime bundle verification failed", file=sys.stderr)
            return 1
        print(f"  runtime_bundle_verified: {runtime_bundle_verified}")

        # Extract funding gap info for kill test 3
        rt_funding_agg = rt_manifest.get("funding_aggregation", {})
        funding_missing_count = rt_funding_agg.get("missing_count", 0)
        funding_incomplete_flag = rt_funding_agg.get("incomplete", False)
    else:
        funding_missing_count = 0
        funding_incomplete_flag = False

    # Check R0-DATA bundle availability for kill test 3
    r0_data_dir = ROOT / "state" / "research_governance" / "r0_data"
    r0_data_available = r0_data_dir.is_dir() and any(r0_data_dir.iterdir())

    print(f"\n=== Trend Leg Baseline ===")
    print(f"  Standalone NAV: {trend_baseline_summary['final_nav']:.4f} "
          f"(return={trend_baseline_summary['total_return']:+.2%}, "
          f"maxDD={trend_baseline_summary['max_drawdown']:.2%}, "
          f"annual={trend_baseline_summary['annualized_return']:+.2%})")

    # --- Stress tests ---
    print(f"\n=== Trend Leg Stress Tests ===")
    trend_stress: dict[str, dict[str, Any]] = {}

    s = stress_cost_doubling(um_closes, positions, funding_rates_list, frozen_at)
    trend_stress["cost_doubling"] = _nav_summary(s)
    print(f"  cost_doubling:     NAV={trend_stress['cost_doubling']['final_nav']:.4f} "
          f"(maxDD={trend_stress['cost_doubling']['max_drawdown']:.2%})")

    s = stress_delay_1_bar(um_closes, positions, funding_rates_list, frozen_at)
    trend_stress["delay_1_bar"] = _nav_summary(s)
    print(f"  delay_1_bar:       NAV={trend_stress['delay_1_bar']['final_nav']:.4f} "
          f"(maxDD={trend_stress['delay_1_bar']['max_drawdown']:.2%})")

    s = stress_missed_fills(um_closes, positions, funding_rates_list, frozen_at)
    trend_stress["missed_fills_10pct"] = _nav_summary(s)
    print(f"  missed_fills_10%:  NAV={trend_stress['missed_fills_10pct']['final_nav']:.4f} "
          f"(maxDD={trend_stress['missed_fills_10pct']['max_drawdown']:.2%})")

    s = stress_worse_execution(um_closes, positions, funding_rates_list, frozen_at)
    trend_stress["worse_execution_5x"] = _nav_summary(s)
    print(f"  worse_execution:   NAV={trend_stress['worse_execution_5x']['final_nav']:.4f} "
          f"(maxDD={trend_stress['worse_execution_5x']['max_drawdown']:.2%})")

    # --- Carry leg stress + kill tests ---
    print(f"\n=== Carry Leg Baseline + Stress ===")
    carry_decision = None
    carry_stress: dict[str, dict[str, Any]] | None = None
    if carry_baseline_summary is not None:
        print(f"  Baseline:   NAV={carry_baseline_summary['final_nav']:.4f} "
              f"(return={carry_baseline_summary['total_return']:+.2%})")
        carry_stress = {}
        s = stress_worse_execution_carry(spot_closes, um_closes_aligned, funding_rates_carry, frozen_at)
        carry_stress["worse_execution_5x"] = _nav_summary(s)
        print(f"  Stress 5x:  NAV={carry_stress['worse_execution_5x']['final_nav']:.4f}")

        # Independent carry NAV reconciliation
        indep_carry_nav: float | None = None
        rt_carry_nav_val: float | None = None
        if carry_cost_model:
            indep_carry_nav = _independent_carry_nav(
                spot_closes, um_closes_aligned, carry_cost_model, funding_rates_carry,
            )
        if rt_manifest:
            rt_carry = rt_manifest.get("carry_standalone_nav", {})
            rt_carry_nav_val = rt_carry.get("final_nav") if rt_carry else None

        carry_decision = evaluate_kill_tests(
            carry_baseline_summary["final_nav"], carry_stress,
            candidate_name="cxd_carry_leg",
            independent_nav=indep_carry_nav,
            runtime_nav=rt_carry_nav_val,
            funding_missing_count=funding_missing_count,
            funding_incomplete=funding_incomplete_flag,
            r0_data_available=r0_data_available,
        )
    else:
        carry_decision = {
            "candidate": "cxd_carry_leg",
            "all_kill_tests_pass": False,
            "kill_tests": {},
            "decision": "blocked",
            "decision_reasoning": "Insufficient common bars for carry computation",
        }

    # --- Evaluate trend kill tests ---
    indep_trend_nav = _independent_trend_nav(um_closes, positions, trend_cost, funding_rates_list)
    rt_trend_nav_val: float | None = None
    if rt_manifest:
        rt_trend = rt_manifest.get("trend_standalone_nav", {})
        rt_trend_nav_val = rt_trend.get("final_nav") if rt_trend else None

    trend_decision = evaluate_kill_tests(
        trend_baseline_summary["final_nav"], trend_stress,
        candidate_name="cxd_trend_leg",
        independent_nav=indep_trend_nav,
        runtime_nav=rt_trend_nav_val,
        funding_missing_count=funding_missing_count,
        funding_incomplete=funding_incomplete_flag,
        r0_data_available=r0_data_available,
    )

    cta_r_decision = {
        "candidate": "cta_r_cross_asset",
        "all_kill_tests_pass": False,
        "kill_tests": {},
        "decision": "blocked",
        "decision_reasoning": "CTA-R has no runtime NAV; evidence is partial (no cross-asset data collected)",
    }

    print(f"\n=== Decisions ===")
    for d in [trend_decision, carry_decision, cta_r_decision]:
        print(f"  {d['candidate']}: {d['decision'].upper()} ({d['decision_reasoning'][:80]}...)")

    # --- Build artifact ---
    bundle_core: dict[str, Any] = {
        "schema_version": 1,
        "artifact_type": "r0_decision_artifact",
        "observed_at": frozen_at,
        "symbol": symbol,
        "data_window": {"start": f"{start_parts[0]}-{start_parts[1]:02d}", "end": f"{end_parts[0]}-{end_parts[1]:02d}"},
        "runtime_bundle_id": runtime_bundle_id,
        "runtime_bundle_verified": runtime_bundle_verified,
        "candidate_config": candidate_config.to_dict() if candidate_config else None,
        "input_verification": input_verification,
        "trend_baseline": trend_baseline_summary,
        "trend_stress": trend_stress,
        "trend_decision": trend_decision,
        "carry_baseline": carry_baseline_summary if carry_decision and carry_decision["decision"] != "blocked" else None,
        "carry_stress": carry_stress if carry_decision and carry_decision["decision"] != "blocked" else None,
        "carry_decision": carry_decision,
        "cta_r_decision": cta_r_decision,
        "orders_authorized": False,
    }

    if args.dry_run:
        print(f"\n[DRY RUN]")
        return 0

    # Write bundle
    output_base = Path(args.output_dir)
    output_base.mkdir(parents=True, exist_ok=True)
    bundle_id = hashlib.sha256(canonical_hash(bundle_core).encode("ascii")).hexdigest()
    bundle_dir = output_base / bundle_id

    if bundle_dir.exists():
        print(f"ERROR: bundle already exists", file=sys.stderr)
        return 1

    bundle_dir.mkdir(mode=0o700)

    _write_once(bundle_dir / "trend_decision.json", trend_decision)
    _write_once(bundle_dir / "carry_decision.json", carry_decision)
    _write_once(bundle_dir / "cta_r_decision.json", cta_r_decision)
    if candidate_config:
        _write_once(bundle_dir / "candidate_config.json", candidate_config.to_dict())
    _write_once(bundle_dir / "stress_results.json", {
        "trend_baseline": trend_baseline_summary,
        "trend_stress": trend_stress,
        "carry_baseline": carry_baseline_summary if carry_decision and carry_decision["decision"] != "blocked" else None,
        "carry_stress": carry_stress if carry_decision and carry_decision["decision"] != "blocked" else None,
    })

    manifest = dict(bundle_core)
    manifest["bundle_id"] = bundle_id
    manifest["member_files"] = _member_refs(bundle_dir)
    manifest["manifest_hash"] = canonical_hash({k: v for k, v in manifest.items() if k != "manifest_hash"})
    _write_once(bundle_dir / "manifest.json", manifest)

    print(f"\nDecision bundle written: {bundle_dir}")
    print(f"  bundle_id: {bundle_id}")
    print(f"  members: {len(manifest['member_files'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
