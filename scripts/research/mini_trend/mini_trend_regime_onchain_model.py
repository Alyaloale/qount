#!/usr/bin/env python3
"""Run the single fixed rolling-RF ablation with the retained hash-rate feature."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.research_data.market_data import load_funding, load_klines  # noqa: E402
from qount.mini_trend.forward import TOP3  # noqa: E402
from qount.mini_trend.regime_onchain_model import build_onchain_model_ablation  # noqa: E402
from qount.mini_trend.regime_onchain_model import (  # noqa: E402
    write_onchain_model_ablation_artifact,
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
    parser.add_argument("--onchain-path", required=True)
    parser.add_argument("--onchain-audit-path", required=True)
    parser.add_argument("--source-matrix-path", required=True)
    parser.add_argument("--start-month", default="2021-01")
    parser.add_argument("--end-month", default="2026-06")
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
    load = lambda path: json.loads(Path(path).read_text(encoding="utf-8"))
    payload = build_onchain_model_ablation(
        bars,
        funding,
        load(args.onchain_path),
        load(args.onchain_audit_path),
        load(args.source_matrix_path),
    )
    artifact = write_onchain_model_ablation_artifact(
        Settings.from_env(), payload, explicit_path=args.output_path
    )
    candidate = artifact["candidate"]
    comparison = artifact["comparison"]
    print(f"artifact={artifact['artifact_path']}")
    print(f"verdict={artifact['diagnostics']['verdict']}")
    print(
        f"gates={artifact['diagnostics']['passed_gate_count']}/"
        f"{artifact['diagnostics']['gate_count']}"
    )
    print(f"rank_ic={candidate['pooled_rank_ic']:.8f}")
    print(f"spread={candidate['pooled_high_minus_low_actual']:.8f}")
    print(f"bootstrap={candidate['bootstrap']['probability_spread_positive']:.6f}")
    print(f"rank_ic_delta={comparison['pooled_rank_ic_delta']:.8f}")
    print(f"spread_delta={comparison['pooled_spread_delta']:.8f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
