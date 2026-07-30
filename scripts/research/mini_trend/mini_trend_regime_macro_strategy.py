#!/usr/bin/env python3
"""Run the three frozen risk rules on the retained H.4.1 ranker."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.research_data.market_data import load_funding, load_klines  # noqa: E402
from qount.mini_trend.forward import TOP3  # noqa: E402
from qount.mini_trend.regime_macro_strategy import build_macro_strategy_ablation  # noqa: E402
from qount.mini_trend.regime_macro_strategy import (  # noqa: E402
    write_macro_strategy_ablation_artifact,
)
from qount.settings import Settings  # noqa: E402


def _month(value: str) -> tuple[int, int]:
    year, month = value.split("-", 1)
    return int(year), int(month)


def _offline_only(url: str) -> bytes:
    raise RuntimeError(f"offline cache miss; network disabled for {url.rsplit('/', 1)[-1]}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market-cache-dir", required=True)
    parser.add_argument("--exchange-rules-path", required=True)
    parser.add_argument("--macro-audit-path", required=True)
    parser.add_argument("--start-month", default="2021-01")
    parser.add_argument("--end-month", default="2026-06")
    parser.add_argument("--output-path", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    start, end = _month(args.start_month), _month(args.end_month)
    bars = {
        symbol: load_klines(
            symbol,
            "1d",
            start=start,
            end=end,
            market="um",
            cache_dir=args.market_cache_dir,
            fetch=_offline_only,
            skip_missing=True,
        )
        for symbol in TOP3
    }
    funding = {
        symbol: load_funding(
            symbol,
            start=start,
            end=end,
            cache_dir=args.market_cache_dir,
            fetch=_offline_only,
            skip_missing=True,
        )
        for symbol in TOP3
    }
    rules = json.loads(Path(args.exchange_rules_path).read_text(encoding="utf-8"))
    audit = json.loads(Path(args.macro_audit_path).read_text(encoding="utf-8"))
    payload = build_macro_strategy_ablation(bars, funding, rules, audit)
    artifact = write_macro_strategy_ablation_artifact(
        Settings.from_env(), payload, explicit_path=args.output_path
    )
    diagnostics = artifact["diagnostics"]
    control = artifact["control"]
    print(f"artifact={artifact['artifact_path']}")
    print(f"verdict={diagnostics['verdict']}")
    print(f"cumulative_trial_count={diagnostics['cumulative_trial_count']}")
    print(
        f"control_return={control['return_pct']:.8f} "
        f"control_sharpe={control['sharpe']:.8f} "
        f"control_max_dd={control['max_drawdown_pct']:.8f}"
    )
    for trial in artifact["trials"]:
        candidate = trial["candidate"]
        comparison = trial["comparison"]
        print(
            f"trial={trial['trial_id']} gates={trial['passed_gate_count']}/{trial['gate_count']} "
            f"return={candidate['return_pct']:.8f} "
            f"sharpe={candidate['sharpe']:.8f} "
            f"max_dd={candidate['max_drawdown_pct']:.8f} "
            f"return_delta={comparison['return_delta_percentage_points']:.8f} "
            f"dd_improvement={comparison['drawdown_improvement_percentage_points']:.8f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
