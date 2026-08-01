#!/usr/bin/env python3
"""Preregister or run the UM lagged-funding cost-veto diagnostic."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.research_data.market_data import load_funding, load_klines  # noqa: E402
from qount.mini_trend.forward import TOP3  # noqa: E402
from qount.mini_trend.futures_funding_veto import (  # noqa: E402
    FUTURES_FUNDING_VETO_PROTOCOL,
    build_funding_veto_preregistration,
    write_funding_veto_preregistration_artifact,
)
from qount.mini_trend.futures_funding_veto_report import (  # noqa: E402
    build_funding_veto_historical_report,
    write_funding_veto_historical_artifact,
)
from qount.settings import Settings  # noqa: E402


def _load_object(path: str | Path) -> dict:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object at {path}")
    return payload


def _month(value: str) -> tuple[int, int]:
    year, month = value[:7].split("-", 1)
    return int(year), int(month)


def _offline_only(url: str) -> bytes:
    raise RuntimeError(f"offline cache miss; network disabled for {url.rsplit('/', 1)[-1]}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--exchange-rules-path", required=True)
    parser.add_argument("--live-lessons-path", required=True)
    parser.add_argument("--base-preregistration-path", required=True)
    parser.add_argument("--prior-stop-latch-path", required=True)
    parser.add_argument("--preregistration-path")
    parser.add_argument("--cache-dir", default="state/grid_b/klines")
    parser.add_argument("--kline-cache-dir")
    parser.add_argument("--funding-cache-dir")
    parser.add_argument("--output-path")
    return parser.parse_args(argv)


def _load_window(kline_cache_dir: str, funding_cache_dir: str, start: str, end: str) -> dict:
    start_month, end_month = _month(start), _month(end)
    return {
        "bars": {
            symbol: load_klines(
                symbol,
                "1d",
                start=start_month,
                end=end_month,
                market="um",
                cache_dir=kline_cache_dir,
                fetch=_offline_only,
            )
            for symbol in TOP3
        },
        "funding": {
            symbol: load_funding(
                symbol,
                start=start_month,
                end=end_month,
                cache_dir=funding_cache_dir,
                fetch=_offline_only,
            )
            for symbol in TOP3
        },
    }


def _historical_inputs(kline_cache_dir: str, funding_cache_dir: str) -> dict:
    protocol = FUTURES_FUNDING_VETO_PROTOCOL
    specs = list(protocol.historical_windows) + [protocol.full_window]
    return {
        spec["label"]: _load_window(
            kline_cache_dir, funding_cache_dir, spec["warmup_start"], spec["end"]
        )
        for spec in specs
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    rules = _load_object(args.exchange_rules_path)
    evidence = {
        "live_lessons_path": args.live_lessons_path,
        "base_preregistration_path": args.base_preregistration_path,
        "prior_stop_latch_path": args.prior_stop_latch_path,
    }
    if args.run:
        if not args.preregistration_path:
            raise ValueError("--run requires --preregistration-path")
        payload = build_funding_veto_historical_report(
            _historical_inputs(
                args.kline_cache_dir or args.cache_dir,
                args.funding_cache_dir or args.cache_dir,
            ),
            rules,
            _load_object(args.preregistration_path),
            **evidence,
        )
        artifact = write_funding_veto_historical_artifact(
            Settings.from_env(), payload, explicit_path=args.output_path
        )
    else:
        payload = build_funding_veto_preregistration(rules, **evidence)
        artifact = write_funding_veto_preregistration_artifact(
            Settings.from_env(), payload, explicit_path=args.output_path
        )
    print(f"artifact={artifact['artifact_path']}")
    if args.run:
        print(f"verdict={artifact['diagnostics']['verdict']}")
        full = artifact["full_window"]
        print(
            f"full_control={full['control']['return_pct']}% "
            f"full_candidate={full['candidate']['return_pct']}% "
            f"incremental={full['incremental_return_pct']}pp"
        )
        print(
            f"funding_vetoed_bars="
            f"{full['candidate']['funding_veto_activity']['vetoed_bar_count']}"
        )
        for row in artifact["segments"]:
            print(
                f"segment={row['label']} control={row['control']['return_pct']}% "
                f"candidate={row['candidate']['return_pct']}% "
                f"incremental={row['incremental_return_pct']}pp"
            )
    else:
        print(f"contract_hash={artifact['decision_contract']['contract_hash']}")
        print(f"protocol_hash={artifact['protocol']['protocol_hash']}")
        print(f"strategy_results_evaluated={artifact['meta']['strategy_results_evaluated']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
