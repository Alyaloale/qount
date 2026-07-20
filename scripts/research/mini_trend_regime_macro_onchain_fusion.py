#!/usr/bin/env python3
"""Run the one fixed H.4.1 plus hash-rate fusion trial."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.grid.data import load_funding, load_klines  # noqa: E402
from qount.mini_trend.forward import TOP3  # noqa: E402
from qount.mini_trend.regime_macro_onchain_fusion import (  # noqa: E402
    build_macro_onchain_fusion,
)
from qount.mini_trend.regime_macro_onchain_fusion import (  # noqa: E402
    write_macro_onchain_fusion_artifact,
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
    parser.add_argument("--h41-dataset", required=True)
    parser.add_argument("--h41-audit", required=True)
    parser.add_argument("--onchain-dataset", required=True)
    parser.add_argument("--onchain-model", required=True)
    parser.add_argument("--start-month", default="2021-01")
    parser.add_argument("--end-month", default="2026-06")
    parser.add_argument("--bootstrap-samples", type=int, default=10_000)
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
    load = lambda path: json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    payload = build_macro_onchain_fusion(
        bars,
        funding,
        load(args.h41_dataset),
        load(args.h41_audit),
        load(args.onchain_dataset),
        load(args.onchain_model),
    )
    artifact = write_macro_onchain_fusion_artifact(
        Settings.from_env(), payload, explicit_path=args.output_path
    )
    result = artifact["candidate"]
    diagnostics = artifact["diagnostics"]
    print(f"artifact={artifact['artifact_path']}")
    print(f"verdict={diagnostics['verdict']}")
    print(f"gates={diagnostics['passed_gate_count']}/{diagnostics['gate_count']}")
    print(f"cumulative_trial_count={diagnostics['cumulative_trial_count']}")
    print(f"rank_ic={result['pooled_rank_ic']:.8f}")
    print(f"spread={result['pooled_high_minus_low_actual']:.8f}")
    print(f"bootstrap={result['bootstrap']['probability_spread_positive']:.6f}")
    for parent, comparison in artifact["comparison"].items():
        print(
            f"{parent}_rank_ic_delta={comparison['pooled_rank_ic_delta']:.8f} "
            f"spread_delta={comparison['pooled_spread_delta']:.8f} "
            f"bootstrap_delta={comparison['bootstrap_probability_delta']:.6f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
