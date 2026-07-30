#!/usr/bin/env python3
"""Preregister or run the offline TOP3 capitulation-rebound price diagnostic."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.research_data.market_data import load_klines  # noqa: E402
from qount.mini_trend.capitulation_rebound import (  # noqa: E402
    CAPITULATION_REBOUND_PROTOCOL,
    build_capitulation_price_report,
    build_capitulation_preregistration,
    write_capitulation_preregistration_artifact,
    write_capitulation_report_artifact,
)
from qount.mini_trend.forward import TOP3  # noqa: E402
from qount.settings import Settings  # noqa: E402


def _offline_only(url: str) -> bytes:
    raise RuntimeError(f"offline cache miss; network disabled for {url.rsplit('/', 1)[-1]}")


def _month(value: str) -> tuple[int, int]:
    year, month = value[:7].split("-", 1)
    return int(year), int(month)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--preregistration-path")
    parser.add_argument("--cache-dir", default="state/grid_b/klines")
    parser.add_argument("--output-path")
    return parser.parse_args(argv)


def _load_object(path: str) -> dict:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object at {path}")
    return payload


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    settings = Settings.from_env()
    if not args.run:
        artifact = write_capitulation_preregistration_artifact(
            settings,
            build_capitulation_preregistration(),
            explicit_path=args.output_path,
        )
        print(f"artifact={artifact['artifact_path']}")
        print(f"contract_hash={artifact['decision_contract']['contract_hash']}")
        print(f"protocol_hash={artifact['protocol']['protocol_hash']}")
        print(f"strategy_results_evaluated={artifact['meta']['strategy_results_evaluated']}")
        return 0

    if not args.preregistration_path:
        raise ValueError("--run requires --preregistration-path")
    protocol = CAPITULATION_REBOUND_PROTOCOL
    bars = {
        symbol: load_klines(
            symbol,
            protocol.interval,
            start=_month(protocol.historical_start),
            end=_month(protocol.historical_end),
            market=protocol.market,
            cache_dir=args.cache_dir,
            fetch=_offline_only,
        )
        for symbol in TOP3
    }
    payload = build_capitulation_price_report(
        bars, _load_object(args.preregistration_path)
    )
    artifact = write_capitulation_report_artifact(
        settings, payload, explicit_path=args.output_path
    )
    print(f"artifact={artifact['artifact_path']}")
    print(f"verdict={artifact['diagnostics']['verdict']}")
    print(f"episodes={artifact['summary']['independent_episode_count']}")
    print(f"median_net_event_return={artifact['summary']['median_net_event_return']}")
    print(f"compound_price_cost_return={artifact['summary']['compound_price_cost_return']}")
    print(f"median_btc_beta_residual={artifact['summary']['median_btc_beta_residual']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
