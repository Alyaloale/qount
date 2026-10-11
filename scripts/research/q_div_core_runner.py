#!/usr/bin/env python3
"""CLI runner for formal Q-DIV-Core 4-curve backtest.

Usage:
    PYTHONPATH=src python3 scripts/research/q_div_core_runner.py
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sys

from qount.research.q_div_core import QDivCoreConfig, run_q_div_core_backtest
from qount.research.q_div_sources import PublicHistorySources

DEFAULT_ROOT = "/mnt/e/qount_data/qount/datasets/equity_selection/q_div_full_v3_20261011T084100Z"
DEFAULT_REPAIR = "/mnt/e/qount_data/qount/datasets/equity_selection/q_div_transport_repair_20261011T093600Z"
DEFAULT_ARTIFACTS = "/mnt/e/qount_data/qount/artifacts/equity_selection"


def main():
    parser = argparse.ArgumentParser(description="Run formal Q-DIV-Core 4-curve backtest on WSL/E")
    parser.add_argument("--root", default=DEFAULT_ROOT, help="P1 dataset root on E:")
    parser.add_argument("--repair", default=DEFAULT_REPAIR, help="Transport repair dataset root on E:")
    parser.add_argument("--output-dir", default=None, help="Output artifact directory on E:")
    args = parser.parse_args()

    root = Path(args.root)
    repair = Path(args.repair)
    if not root.exists():
        raise SystemExit(f"Error: root dataset path {root} does not exist.")

    repairs = [repair] if repair.exists() else []

    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        ts = dt.datetime.now().strftime("%Y%m%dT%H%M%SZ")
        output_dir = Path(DEFAULT_ARTIFACTS) / f"ashare_q_div_core_{ts}"

    print(f"=== Q-DIV-Core 4-Curve Formal Backtest ===", flush=True)
    print(f"Dataset root:   {root}", flush=True)
    print(f"Repair roots:   {[str(r) for r in repairs]}", flush=True)
    print(f"Output artifact: {output_dir}", flush=True)
    print(f"Research only:  orders_authorized=false, promotion_evidence=false", flush=True)

    sources = PublicHistorySources(root, repair_roots=repairs)
    config = QDivCoreConfig()

    result = run_q_div_core_backtest(sources, config=config, output_dir=output_dir, log_fn=lambda msg: print(msg, flush=True))

    print("\n=== BACKTEST SUMMARY ===", flush=True)
    print(json.dumps({
        "study_id": result["study_id"],
        "status": result["status"],
        "curves": {k: {"cagr": v["cagr"], "mdd": v["max_drawdown"], "sharpe": v["sharpe_ratio"], "turnover": v["one_way_annual_turnover"]} for k, v in result["curves"].items()},
        "primary_benchmark": {"name": result["primary_benchmark"]["name"], "cagr": result["primary_benchmark"]["metrics"]["cagr"], "mdd": result["primary_benchmark"]["metrics"]["max_drawdown"]},
        "all_frozen_gates_passed": result["all_frozen_gates_passed"],
        "gates_evaluation": result["gates_evaluation"],
    }, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
