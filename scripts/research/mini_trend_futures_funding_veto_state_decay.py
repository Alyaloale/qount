#!/usr/bin/env python3
"""Preregister or run the UM funding-veto execution-state decay audit."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.grid.data import load_funding, load_klines  # noqa: E402
from qount.mini_trend.forward import TOP3  # noqa: E402
from qount.mini_trend.futures_funding_veto_state_decay import (  # noqa: E402
    FUNDING_VETO_STATE_DECAY_PROTOCOL,
    build_funding_veto_state_decay_preregistration,
    build_funding_veto_state_decay_report,
    write_funding_veto_state_decay_preregistration_artifact,
    write_funding_veto_state_decay_report_artifact,
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
    parser.add_argument("--funding-veto-historical-path", required=True)
    parser.add_argument("--attribution-historical-path", required=True)
    parser.add_argument("--preregistration-path")
    parser.add_argument("--cache-dir", default="state/grid_b/klines")
    parser.add_argument("--output-path")
    return parser.parse_args(argv)


def _historical_input(cache_dir: str) -> dict:
    spec = FUNDING_VETO_STATE_DECAY_PROTOCOL.full_window
    start_month, end_month = _month(spec["warmup_start"]), _month(spec["end"])
    return {
        "bars": {
            symbol: load_klines(
                symbol,
                "1d",
                start=start_month,
                end=end_month,
                market="um",
                cache_dir=cache_dir,
                fetch=_offline_only,
            )
            for symbol in TOP3
        },
        "funding": {
            symbol: load_funding(
                symbol,
                start=start_month,
                end=end_month,
                cache_dir=cache_dir,
                fetch=_offline_only,
            )
            for symbol in TOP3
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    rules = _load_object(args.exchange_rules_path)
    evidence = {
        "funding_veto_historical_path": args.funding_veto_historical_path,
        "attribution_historical_path": args.attribution_historical_path,
    }
    if args.run:
        if not args.preregistration_path:
            raise ValueError("--run requires --preregistration-path")
        payload = build_funding_veto_state_decay_report(
            _historical_input(args.cache_dir),
            rules,
            _load_object(args.preregistration_path),
            **evidence,
        )
        artifact = write_funding_veto_state_decay_report_artifact(
            Settings.from_env(), payload, explicit_path=args.output_path
        )
    else:
        payload = build_funding_veto_state_decay_preregistration(rules, **evidence)
        artifact = write_funding_veto_state_decay_preregistration_artifact(
            Settings.from_env(), payload, explicit_path=args.output_path
        )
    print(f"artifact={artifact['artifact_path']}")
    if args.run:
        print(f"verdict={artifact['diagnostics']['verdict']}")
        decay = artifact["state_decay"]
        print(
            "divergent_bars="
            f"state:{decay['state_divergent_bar_count']},"
            f"return:{decay['return_divergent_bar_count']},"
            f"downstream_return:{decay['downstream_return_divergent_bar_count']}"
        )
        print(
            "spells="
            f"state:{decay['state_spell_count']},return:{decay['return_spell_count']} "
            f"first_sync_median:{decay['first_sync_duration_summary']['median']}"
        )
    else:
        print(f"contract_hash={artifact['decision_contract']['contract_hash']}")
        print(f"protocol_hash={artifact['protocol']['protocol_hash']}")
        print(
            "state_decay_results_evaluated="
            f"{artifact['meta']['state_decay_results_evaluated']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
