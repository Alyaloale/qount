#!/usr/bin/env python3
"""Run the fixed small-GRU discovery model on a MiniTrend regime dataset artifact."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.mini_trend.regime_neural import RegimeGRUConfig  # noqa: E402
from qount.mini_trend.regime_neural import run_regime_gru_walk_forward  # noqa: E402
from qount.mini_trend.regime_neural import write_regime_neural_artifact  # noqa: E402
from qount.settings import Settings  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-path", required=True)
    parser.add_argument("--device", default="auto", choices=("auto", "cpu", "cuda"))
    parser.add_argument("--output-path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    source = json.loads(Path(args.dataset_path).expanduser().read_text(encoding="utf-8"))
    dataset = source.get("dataset", source)
    result = run_regime_gru_walk_forward(
        dataset,
        RegimeGRUConfig(),
        requested_device=args.device,
    )
    artifact = write_regime_neural_artifact(
        Settings.from_env(), result, explicit_path=args.output_path
    )
    print(f"artifact={artifact['artifact_path']}")
    print(f"verdict={artifact['diagnostics']['verdict']}")
    aggregate = artifact["aggregate"]
    print(f"folds={aggregate['fold_count']}")
    print(f"balanced_accuracy={aggregate['mean_balanced_accuracy']:.6f}")
    print(f"macro_f1={aggregate['mean_macro_f1']:.6f}")
    print(f"brier_uplift={aggregate['mean_brier_improvement_vs_constant']:.6f}")
    print(f"elapsed_seconds={aggregate['total_elapsed_seconds']:.3f}")
    print(f"peak_gpu_memory_bytes={aggregate['maximum_peak_gpu_memory_bytes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
