#!/usr/bin/env python3
"""Build the historical MiniTrend regime dataset and run tabular discovery models."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.grid.data import load_funding, load_klines  # noqa: E402
from qount.mini_trend.forward import TOP3  # noqa: E402
from qount.mini_trend.regime_ml import RegimeMLConfig  # noqa: E402
from qount.mini_trend.regime_ml import build_regime_ml_dataset  # noqa: E402
from qount.mini_trend.regime_ml import run_regime_ml_walk_forward  # noqa: E402
from qount.mini_trend.regime_ml import write_regime_ml_artifact  # noqa: E402
from qount.settings import Settings  # noqa: E402


def _month(value: str) -> tuple[int, int]:
    year, month = value.split("-", 1)
    return int(year), int(month)


def _offline_only(url: str) -> bytes:
    raise RuntimeError(f"offline cache miss; network disabled for {url.rsplit('/', 1)[-1]}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", default="state/grid_b/klines")
    parser.add_argument("--start-month", default="2021-01")
    parser.add_argument("--end-month", default="2026-06")
    parser.add_argument("--start-date", default="2021-07-20")
    parser.add_argument("--end-date", default="2026-05-31")
    parser.add_argument("--horizon-days", type=int, default=30)
    parser.add_argument("--barrier-sigma", type=float, default=1.0)
    parser.add_argument(
        "--models", default="logistic,hist_gb,lightgbm,xgboost,hmm"
    )
    parser.add_argument("--use-gpu", action="store_true")
    parser.add_argument("--model-trial-count", type=int, default=1)
    parser.add_argument("--dataset-only", action="store_true")
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
    config = RegimeMLConfig(
        start_date=args.start_date,
        end_date=args.end_date,
        horizon_days=args.horizon_days,
        barrier_sigma=args.barrier_sigma,
    )
    dataset = build_regime_ml_dataset(bars, funding, config)
    payload = dataset
    if not args.dataset_only:
        result = run_regime_ml_walk_forward(
            dataset,
            model_names=tuple(name.strip() for name in args.models.split(",") if name.strip()),
            use_gpu=args.use_gpu,
            model_trial_count=args.model_trial_count,
        )
        payload = {
            "schema_version": result["schema_version"],
            "artifact_type": "mini_trend_regime_ml_discovery",
            "created_at": result["created_at"],
            "meta": result["meta"],
            "dataset": dataset,
            "walk_forward": result,
            "diagnostics": result["diagnostics"],
        }
    artifact = write_regime_ml_artifact(
        Settings.from_env(), payload, explicit_path=args.output_path
    )
    print(f"artifact={artifact['artifact_path']}")
    print(f"dataset_rows={dataset['summary']['row_count']}")
    print(f"label_counts={dataset['summary']['label_counts']}")
    if not args.dataset_only:
        print(f"verdict={artifact['diagnostics']['verdict']}")
        for name, metrics in artifact["walk_forward"]["aggregate"].items():
            print(
                f"model={name} folds={metrics['fold_count']} "
                f"balanced_accuracy={metrics['mean_balanced_accuracy']:.6f} "
                f"macro_f1={metrics['mean_macro_f1']:.6f} "
                f"brier_uplift={metrics['mean_brier_improvement_vs_constant']:.6f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
