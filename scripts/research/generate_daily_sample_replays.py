#!/usr/bin/env python3
"""Generates the three offline replay sample categories for Phase S3-C (R14 Deterministic Daily Brief).

Sample Categories:
1. Normal Complete (正常完整): 513100.SH with fresh, complete bars -> QUALIFIED, actionable weight.
2. Missing Source & Benchmark Proxy (缺来源/代理): 000300.SH (proxy) & 510300.SH (missing) -> 0% target weight.
3. Stale Data & Incomplete Bar (陈旧/未收盘): STALE_DATA gate and INCOMPLETE_BAR gate -> 0% target weight.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from qount.research.personal_trading_assistant import (
    AssistantBar,
    CORE_ETF_UNIVERSE,
    DailyAssistantStatus,
    PersonalTradingAssistantKernel,
    format_daily_report_markdown,
    generate_deterministic_daily_report,
    load_dataset_from_clean_indices,
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def generate_samples(base_dir: Path | None = None) -> Path:
    target_dir = base_dir or (REPO_ROOT / "state" / "research_runs" / "assistant_daily_samples_20261012")

    # Immutable-run protection: these are evidence artifacts that later reports cite by hash, so a
    # re-run must never regenerate them in place. The previous mkdir(exist_ok=True) + open(..., "w")
    # silently rewrote every file, which invalidated any hash already published for this package.
    if target_dir.exists() and any(target_dir.iterdir()):
        raise FileExistsError(
            f"Sample replay package {target_dir} already exists and is non-empty; "
            f"immutable sample protection rejects overwriting. Pass a new base_dir for a new run."
        )
    target_dir.mkdir(parents=True, exist_ok=False)

    data_file = REPO_ROOT / "data" / "processed" / "clean_indices_daily_2013_2026.json"
    if not data_file.exists():
        raise FileNotFoundError(f"Missing base dataset: {data_file}")
    dataset = load_dataset_from_clean_indices(data_file)
    data_hash = sha256_file(data_file)

    kernel = PersonalTradingAssistantKernel(cash_apr=0.02, initial_capital=1_000_000.0)

    sample_dirs = {
        "sample1_normal_complete": target_dir / "sample1_normal_complete",
        "sample2_missing_source_and_proxy": target_dir / "sample2_missing_source_and_proxy",
        "sample3_stale_and_incomplete": target_dir / "sample3_stale_and_incomplete",
    }
    for p in sample_dirs.values():
        p.mkdir(parents=True, exist_ok=False)

    manifest_artifacts = {}

    # =========================================================================
    # Sample 1: 正常完整 (Normal Complete)
    # =========================================================================
    sym1 = "513100.SH"
    meta1 = CORE_ETF_UNIVERSE[sym1]
    bars1 = dataset[sym1]
    latest_date1 = bars1[-1].trade_date
    st1 = kernel.evaluate_daily_status(
        bars1,
        meta1,
        ma_period=120,
        band_pct=0.015,
        confirm_days=2,
        expected_as_of_date=latest_date1,
        require_completed_bar=True,
    )
    # Baseline for 513100
    _, m1 = kernel.simulate_trend_timing(bars1, meta1, ma_period=120, band_pct=0.015, confirm_days=2)

    rep1 = generate_deterministic_daily_report(
        daily_statuses=[st1],
        baseline_metrics={sym1: m1},
        expected_as_of_date=latest_date1,
        source_data_hash=data_hash,
        source_data_path="data/processed/clean_indices_daily_2013_2026.json",
        execution_run_id="sample1_normal_complete",
    )
    md1 = format_daily_report_markdown(rep1)

    s1_json = sample_dirs["sample1_normal_complete"] / "daily-report.json"
    s1_md = sample_dirs["sample1_normal_complete"] / "daily-report.md"
    s1_summary = sample_dirs["sample1_normal_complete"] / "summary.json"
    with open(s1_json, "x", encoding="utf-8") as f:
        json.dump(rep1, f, indent=2, ensure_ascii=False)
    with open(s1_md, "x", encoding="utf-8") as f:
        f.write(md1)
    with open(s1_summary, "x", encoding="utf-8") as f:
        json.dump({"sample": "sample1_normal_complete", "status": asdict(st1)}, f, indent=2, ensure_ascii=False)

    manifest_artifacts["sample1_normal_complete"] = {
        "daily_report_json": sha256_file(s1_json),
        "daily_report_md": sha256_file(s1_md),
        "summary_json": sha256_file(s1_summary),
    }

    # =========================================================================
    # Sample 2: 缺来源与基准代理 (Missing Source & Proxy)
    # =========================================================================
    meta_proxy = CORE_ETF_UNIVERSE["000300.SH"]
    bars_proxy = dataset["000300.SH"]
    meta_missing = CORE_ETF_UNIVERSE["510300.SH"]
    bars_missing = dataset["000300.SH"]  # Use index proxy bars for missing 510300

    st_proxy = kernel.evaluate_daily_status(
        bars_proxy,
        meta_proxy,
        ma_period=120,
        band_pct=0.015,
        confirm_days=2,
    )
    st_missing = kernel.evaluate_daily_status(
        bars_missing,
        meta_missing,
        ma_period=120,
        band_pct=0.015,
        confirm_days=2,
    )

    _, m_proxy = kernel.simulate_trend_timing(bars_proxy, meta_proxy, ma_period=120, band_pct=0.015, confirm_days=2)

    rep2 = generate_deterministic_daily_report(
        daily_statuses=[st_proxy, st_missing],
        baseline_metrics={"000300.SH": m_proxy},
        expected_as_of_date=bars_proxy[-1].trade_date,
        source_data_hash=data_hash,
        source_data_path="data/processed/clean_indices_daily_2013_2026.json",
        execution_run_id="sample2_missing_source_and_proxy",
    )
    md2 = format_daily_report_markdown(rep2)

    s2_json = sample_dirs["sample2_missing_source_and_proxy"] / "daily-report.json"
    s2_md = sample_dirs["sample2_missing_source_and_proxy"] / "daily-report.md"
    s2_summary = sample_dirs["sample2_missing_source_and_proxy"] / "summary.json"
    with open(s2_json, "x", encoding="utf-8") as f:
        json.dump(rep2, f, indent=2, ensure_ascii=False)
    with open(s2_md, "x", encoding="utf-8") as f:
        f.write(md2)
    with open(s2_summary, "x", encoding="utf-8") as f:
        json.dump({
            "sample": "sample2_missing_source_and_proxy",
            "proxy_status": asdict(st_proxy),
            "missing_status": asdict(st_missing),
        }, f, indent=2, ensure_ascii=False)

    manifest_artifacts["sample2_missing_source_and_proxy"] = {
        "daily_report_json": sha256_file(s2_json),
        "daily_report_md": sha256_file(s2_md),
        "summary_json": sha256_file(s2_summary),
    }

    # =========================================================================
    # Sample 3: 陈旧数据与未完整收盘K线拦截 (Stale Data & Incomplete Bar)
    # =========================================================================
    # 3a. Stale data: expected_as_of_date is future
    st_stale = kernel.evaluate_daily_status(
        bars1,
        meta1,
        ma_period=120,
        band_pct=0.015,
        confirm_days=2,
        expected_as_of_date="20261231",  # Much later than dataset end date
        require_completed_bar=True,
    )

    # 3b. Incomplete bar: last bar marked is_complete=False
    incomplete_bars = list(bars1[:-1]) + [
        AssistantBar(
            trade_date=bars1[-1].trade_date,
            open=bars1[-1].open,
            high=bars1[-1].high,
            low=bars1[-1].low,
            close=bars1[-1].close,
            vol=bars1[-1].vol,
            amount=bars1[-1].amount,
            is_complete=False,
        )
    ]
    st_incomplete = kernel.evaluate_daily_status(
        incomplete_bars,
        meta1,
        ma_period=120,
        band_pct=0.015,
        confirm_days=2,
        expected_as_of_date=bars1[-1].trade_date,
        require_completed_bar=True,
    )

    rep3 = generate_deterministic_daily_report(
        daily_statuses=[st_stale, st_incomplete],
        baseline_metrics={sym1: m1},
        expected_as_of_date="20261231",
        source_data_hash=data_hash,
        source_data_path="data/processed/clean_indices_daily_2013_2026.json",
        execution_run_id="sample3_stale_and_incomplete",
    )
    md3 = format_daily_report_markdown(rep3)

    s3_json = sample_dirs["sample3_stale_and_incomplete"] / "daily-report.json"
    s3_md = sample_dirs["sample3_stale_and_incomplete"] / "daily-report.md"
    s3_summary = sample_dirs["sample3_stale_and_incomplete"] / "summary.json"
    with open(s3_json, "x", encoding="utf-8") as f:
        json.dump(rep3, f, indent=2, ensure_ascii=False)
    with open(s3_md, "x", encoding="utf-8") as f:
        f.write(md3)
    with open(s3_summary, "x", encoding="utf-8") as f:
        json.dump({
            "sample": "sample3_stale_and_incomplete",
            "stale_status": asdict(st_stale),
            "incomplete_status": asdict(st_incomplete),
        }, f, indent=2, ensure_ascii=False)

    manifest_artifacts["sample3_stale_and_incomplete"] = {
        "daily_report_json": sha256_file(s3_json),
        "daily_report_md": sha256_file(s3_md),
        "summary_json": sha256_file(s3_summary),
    }

    # =========================================================================
    # Write top-level manifest & completion marker
    # =========================================================================
    manifest = {
        "schema_version": "1.0.0",
        "stage": "S3-C",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "safety_boundaries": {
            "research_only": True,
            "orders_authorized": False,
            "promotion_evidence": False,
        },
        "description": "Three offline replay sample sets for S3-C deterministic daily brief verification.",
        "samples": manifest_artifacts,
    }
    manifest_file = target_dir / "manifest.json"
    with open(manifest_file, "x", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    complete_marker = target_dir / "_COMPLETE"
    with open(complete_marker, "x", encoding="utf-8") as f:
        f.write(f"Completed S3-C sample generation at {datetime.now(timezone.utc).isoformat()}\n")

    print(f"Generated S3-C sample replays at {target_dir}")
    return target_dir


if __name__ == "__main__":
    generate_samples()
