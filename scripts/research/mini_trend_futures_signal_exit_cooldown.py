#!/usr/bin/env python3
"""Preregister or run the fixed three-bar signal-exit cooldown ablation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.grid.data import load_funding, load_klines  # noqa: E402
from qount.mini_trend.forward import TOP3  # noqa: E402
from qount.mini_trend.futures_signal_exit_cooldown import (  # noqa: E402
    build_signal_exit_cooldown_preregistration,
)
from qount.mini_trend.futures_signal_exit_cooldown import (  # noqa: E402
    build_signal_exit_cooldown_report,
)
from qount.mini_trend.futures_signal_exit_cooldown import (  # noqa: E402
    write_signal_exit_cooldown_artifact,
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
    parser.add_argument("--episode-artifact-path", required=True)
    parser.add_argument("--exchange-rules-path", required=True)
    parser.add_argument("--preregistration-path")
    parser.add_argument("--market-cache-dir")
    parser.add_argument("--start-month", default="2021-01")
    parser.add_argument("--end-month", default="2026-05")
    parser.add_argument("--output-path", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    episode_artifact = _load(args.episode_artifact_path)
    rules = _load(args.exchange_rules_path)
    if args.mode == "preregister":
        payload = build_signal_exit_cooldown_preregistration(episode_artifact, rules)
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
        payload = build_signal_exit_cooldown_report(
            bars,
            funding,
            rules,
            episode_artifact,
            _load(args.preregistration_path),
        )
    artifact = write_signal_exit_cooldown_artifact(
        Settings.from_env(), payload, explicit_path=args.output_path
    )
    print(f"artifact={artifact['artifact_path']}")
    if args.mode == "preregister":
        print(f"contract_hash={artifact['contract']['contract_hash']}")
        print(f"trial_count={artifact['contract']['trial_count']}")
        print(f"cumulative_trial_count={artifact['contract']['cumulative_trial_count']}")
        audit = artifact["source"]["rapid_reentry_audit"]
        print(
            f"rapid_reentries={audit['rapid_reentry_count']} "
            f"rapid_reentry_net_pnl={audit['rapid_reentry_net_pnl_usdt']:.8f}"
        )
        return 0
    diagnostics = artifact["diagnostics"]
    reference = artifact["reference"]
    candidate = artifact["candidate"]
    comparison = artifact["comparison"]
    activity = artifact["candidate_activity"]
    probabilities = artifact["paired_block_bootstrap"]["win_probabilities"]
    print(f"verdict={diagnostics['verdict']}")
    print(f"cumulative_trial_count={diagnostics['cumulative_trial_count']}")
    print(
        f"reference={reference['return_pct']:.8f}/{reference['sharpe']:.8f}/"
        f"{reference['max_drawdown_pct']:.8f} "
        f"candidate={candidate['return_pct']:.8f}/{candidate['sharpe']:.8f}/"
        f"{candidate['max_drawdown_pct']:.8f}"
    )
    print(
        f"return_delta={comparison['return_delta_percentage_points']:.8f} "
        f"dd_improvement={comparison['drawdown_improvement_percentage_points']:.8f} "
        f"triggers={activity['signal_exit_trigger_count']} "
        f"blocked={activity['blocked_entry_symbol_bar_count']} "
        f"orders={reference['order_count']}->{candidate['order_count']}"
    )
    print(
        f"bootstrap_return={probabilities['candidate_terminal_return_above_reference']:.6f} "
        f"bootstrap_sharpe={probabilities['candidate_sharpe_above_reference']:.6f} "
        f"bootstrap_dd={probabilities['candidate_max_drawdown_below_reference']:.6f} "
        f"gates={artifact['passed_gate_count']}/{artifact['gate_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
