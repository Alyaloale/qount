#!/usr/bin/env python3
"""Preregister or run the fixed H.4.1 marginal-risk boost veto."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.research_data.market_data import load_funding, load_klines  # noqa: E402
from qount.mini_trend.forward import TOP3  # noqa: E402
from qount.mini_trend.regime_macro_boost_veto import (  # noqa: E402
    build_macro_boost_veto_preregistration,
)
from qount.mini_trend.regime_macro_boost_veto import (  # noqa: E402
    build_macro_boost_veto_report,
)
from qount.mini_trend.regime_macro_boost_veto import (  # noqa: E402
    write_macro_boost_veto_artifact,
)
from qount.settings import Settings  # noqa: E402


def _month(value: str) -> tuple[int, int]:
    year, month = value.split("-", 1)
    return int(year), int(month)


def _offline_only(url: str) -> bytes:
    raise RuntimeError(f"offline cache miss; network disabled for {url.rsplit('/', 1)[-1]}")


def _load(path: str) -> dict:
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("preregister", "report"), required=True)
    parser.add_argument("--macro-audit-path", required=True)
    parser.add_argument("--exchange-rules-path", required=True)
    parser.add_argument("--preregistration-path")
    parser.add_argument("--market-cache-dir")
    parser.add_argument("--start-month", default="2021-01")
    parser.add_argument("--end-month", default="2026-05")
    parser.add_argument("--output-path", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    macro_audit = _load(args.macro_audit_path)
    rules = _load(args.exchange_rules_path)
    if args.mode == "preregister":
        payload = build_macro_boost_veto_preregistration(macro_audit, rules)
    else:
        if not args.preregistration_path or not args.market_cache_dir:
            raise ValueError("report mode requires preregistration and market cache paths")
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
        payload = build_macro_boost_veto_report(
            bars,
            funding,
            rules,
            macro_audit,
            _load(args.preregistration_path),
        )
    artifact = write_macro_boost_veto_artifact(
        Settings.from_env(), payload, explicit_path=args.output_path
    )
    print(f"artifact={artifact['artifact_path']}")
    if args.mode == "preregister":
        print(f"contract_hash={artifact['contract']['contract_hash']}")
        print(f"trial_count={artifact['contract']['trial_count']}")
        print(f"cumulative_trial_count={artifact['contract']['cumulative_trial_count']}")
        return 0
    diagnostics = artifact["diagnostics"]
    candidate = artifact["candidate"]
    reference = artifact["reference_funding_veto"]
    comparison = artifact["comparison_vs_funding_veto"]
    probabilities = artifact["paired_block_bootstrap"]["win_probabilities"]
    activity = artifact["candidate_activity"]
    print(f"verdict={diagnostics['verdict']}")
    print(f"cumulative_trial_count={diagnostics['cumulative_trial_count']}")
    print(
        f"reference_return={reference['return_pct']:.8f} "
        f"reference_sharpe={reference['sharpe']:.8f} "
        f"reference_max_dd={reference['max_drawdown_pct']:.8f}"
    )
    print(
        f"candidate_return={candidate['return_pct']:.8f} "
        f"candidate_sharpe={candidate['sharpe']:.8f} "
        f"candidate_max_dd={candidate['max_drawdown_pct']:.8f} "
        f"return_delta={comparison['return_delta_percentage_points']:.8f} "
        f"dd_improvement={comparison['drawdown_improvement_percentage_points']:.8f}"
    )
    print(
        f"macro_eligible={activity['macro_boost_eligible_bar_count']} "
        f"macro_vetoed={activity['macro_vetoed_bar_count']} "
        f"bootstrap_sharpe={probabilities['candidate_sharpe_above_reference']:.6f} "
        f"bootstrap_dd={probabilities['candidate_max_drawdown_below_reference']:.6f} "
        f"gates={artifact['passed_gate_count']}/{artifact['gate_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
