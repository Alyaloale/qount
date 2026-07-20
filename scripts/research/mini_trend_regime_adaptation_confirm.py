#!/usr/bin/env python3
"""Confirm the fixed retained rolling-return ranker with larger block bootstraps."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.grid.data import load_funding, load_klines  # noqa: E402
from qount.mini_trend.forward import TOP3  # noqa: E402
from qount.mini_trend.regime_adaptation_confirm import AdaptationConfirmConfig  # noqa: E402
from qount.mini_trend.regime_adaptation_confirm import (  # noqa: E402
    build_adaptation_confirmation,
)
from qount.mini_trend.regime_adaptation_confirm import (  # noqa: E402
    write_adaptation_confirmation_artifact,
)
from qount.settings import Settings  # noqa: E402


def _month(value: str) -> tuple[int, int]:
    year, month = value.split("-", 1)
    return int(year), int(month)


def _offline_only(url: str) -> bytes:
    raise RuntimeError(f"offline cache miss; network disabled for {url.rsplit('/', 1)[-1]}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--source-matrix-path", required=True)
    parser.add_argument("--start-month", default="2021-01")
    parser.add_argument("--end-month", default="2026-06")
    parser.add_argument("--bootstrap-samples", type=int, default=10000)
    parser.add_argument("--output-path")
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
            cache_dir=args.cache_dir,
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
            cache_dir=args.cache_dir,
            fetch=_offline_only,
            skip_missing=True,
        )
        for symbol in TOP3
    }
    source = json.loads(Path(args.source_matrix_path).read_text(encoding="utf-8"))
    payload = build_adaptation_confirmation(
        bars,
        funding,
        source,
        AdaptationConfirmConfig(bootstrap_samples=args.bootstrap_samples),
    )
    artifact = write_adaptation_confirmation_artifact(
        Settings.from_env(), payload, explicit_path=args.output_path
    )
    result = artifact["confirmation_result"]
    print(f"artifact={artifact['artifact_path']}")
    print(f"verdict={artifact['diagnostics']['verdict']}")
    print(f"gates={artifact['diagnostics']['passed_gate_count']}/{artifact['diagnostics']['gate_count']}")
    print(f"rank_ic={result['pooled_rank_ic']:.8f}")
    print(f"spread={result['pooled_high_minus_low_actual']:.8f}")
    for block, row in artifact["bootstrap_sensitivity"].items():
        print(
            f"block_{block}_probability={row['probability_spread_positive']:.6f} "
            f"median={row['median_spread']:.8f} p05={row['p05_spread']:.8f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
