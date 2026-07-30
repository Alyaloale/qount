#!/usr/bin/env python3
"""Run direct return/drawdown ML discovery on the existing TOP3 daily history."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.research_data.market_data import load_funding, load_klines  # noqa: E402
from qount.mini_trend.forward import TOP3  # noqa: E402
from qount.mini_trend.regime_economic_ml import EconomicMLConfig  # noqa: E402
from qount.mini_trend.regime_economic_ml import build_economic_ml_matrix  # noqa: E402
from qount.mini_trend.regime_economic_ml import write_economic_ml_matrix_artifact  # noqa: E402
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
    parser.add_argument("--start-month", default="2021-01")
    parser.add_argument("--end-month", default="2026-06")
    parser.add_argument("--start-date", default="2021-07-20")
    parser.add_argument("--end-date", default="2026-05-31")
    parser.add_argument("--horizons", default="10,20,30,60")
    parser.add_argument("--targets", default="return,drawdown")
    parser.add_argument(
        "--models", default="ridge,hist_gb,random_forest,lightgbm,xgboost"
    )
    parser.add_argument("--bootstrap-samples", type=int, default=1000)
    parser.add_argument("--use-gpu", action="store_true")
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
    payload = build_economic_ml_matrix(
        bars,
        funding,
        EconomicMLConfig(
            start_date=args.start_date,
            end_date=args.end_date,
            horizons=_csv_ints(args.horizons),
            targets=_csv_strings(args.targets),
            models=_csv_strings(args.models),
            bootstrap_samples=args.bootstrap_samples,
        ),
        use_gpu=args.use_gpu,
    )
    artifact = write_economic_ml_matrix_artifact(
        Settings.from_env(), payload, explicit_path=args.output_path
    )
    print(f"artifact={artifact['artifact_path']}")
    print(f"verdict={artifact['diagnostics']['verdict']}")
    print(f"trials={artifact['diagnostics']['trial_count']}")
    print(f"cumulative_trials={artifact['diagnostics']['cumulative_trial_count']}")
    print(f"retained={artifact['diagnostics']['retained_trial_count']}")
    for target, best in artifact["best_by_target"].items():
        if best:
            print(
                f"best_{target}={best['trial_id']} gates={best['passed_gate_count']}/"
                f"{best['gate_count']} rank_ic={best['pooled_rank_ic']:.8f} "
                f"spread={best['pooled_high_minus_low_actual']:.8f} "
                f"bootstrap={best['bootstrap']['probability_spread_positive']:.6f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
