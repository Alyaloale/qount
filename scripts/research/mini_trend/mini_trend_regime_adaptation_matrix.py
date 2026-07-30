#!/usr/bin/env python3
"""Run fixed rolling-window adaptation trials for return ranking."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.research_data.market_data import load_funding, load_klines  # noqa: E402
from qount.mini_trend.forward import TOP3  # noqa: E402
from qount.mini_trend.regime_adaptation_matrix import AdaptationMatrixConfig  # noqa: E402
from qount.mini_trend.regime_adaptation_matrix import build_adaptation_matrix  # noqa: E402
from qount.mini_trend.regime_adaptation_matrix import (  # noqa: E402
    write_adaptation_matrix_artifact,
)
from qount.settings import Settings  # noqa: E402


def _csv_ints(value: str) -> tuple[int, ...]:
    return tuple(int(item) for item in value.split(",") if item.strip())


def _csv_strings(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _month(value: str) -> tuple[int, int]:
    year, month = value.split("-", 1)
    return int(year), int(month)


def _offline_only(url: str) -> bytes:
    raise RuntimeError(f"offline cache miss; network disabled for {url.rsplit('/', 1)[-1]}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--dvol-path", required=True)
    parser.add_argument("--start-month", default="2021-01")
    parser.add_argument("--end-month", default="2026-06")
    parser.add_argument("--start-date", default="2021-07-20")
    parser.add_argument("--end-date", default="2026-05-31")
    parser.add_argument("--horizons", default="10,20,30,60")
    parser.add_argument("--training-windows", default="365,730,1095")
    parser.add_argument("--feature-sets", default="base,dvol")
    parser.add_argument("--bootstrap-samples", type=int, default=1000)
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
    dvol = json.loads(Path(args.dvol_path).read_text(encoding="utf-8"))
    payload = build_adaptation_matrix(
        bars,
        funding,
        dvol,
        AdaptationMatrixConfig(
            start_date=args.start_date,
            end_date=args.end_date,
            horizons=_csv_ints(args.horizons),
            training_windows_days=_csv_ints(args.training_windows),
            feature_sets=_csv_strings(args.feature_sets),
            bootstrap_samples=args.bootstrap_samples,
        ),
    )
    artifact = write_adaptation_matrix_artifact(
        Settings.from_env(), payload, explicit_path=args.output_path
    )
    best = artifact["best_trial"]
    print(f"artifact={artifact['artifact_path']}")
    print(f"verdict={artifact['diagnostics']['verdict']}")
    print(f"trials={artifact['diagnostics']['trial_count']}")
    print(f"cumulative_trials={artifact['diagnostics']['cumulative_trial_count']}")
    print(f"retained={artifact['diagnostics']['retained_trial_count']}")
    if best:
        print(f"best_trial={best['trial_id']}")
        print(f"best_gates={best['passed_gate_count']}/{best['gate_count']}")
        print(f"best_rank_ic={best['pooled_rank_ic']:.8f}")
        print(f"best_spread={best['pooled_high_minus_low_actual']:.8f}")
        print(f"best_bootstrap={best['bootstrap']['probability_spread_positive']:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
