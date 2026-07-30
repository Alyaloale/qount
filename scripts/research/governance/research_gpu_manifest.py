#!/usr/bin/env python3
"""Write a reproducibility manifest for the isolated GPU research node."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.artifacts import write_research_json_artifact  # noqa: E402
from qount.research_compute import build_research_compute_manifest  # noqa: E402
from qount.settings import Settings  # noqa: E402


DEFAULT_CODE_PATHS = (
    Path("src/qount/mini_trend/regime_ml.py"),
    Path("src/qount/mini_trend/regime_neural.py"),
    Path("scripts/research/mini_trend/mini_trend_regime_ml.py"),
    Path("scripts/research/mini_trend/mini_trend_regime_neural.py"),
)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-path", required=True)
    parser.add_argument(
        "--code-path",
        action="append",
        help="Repeat to bind an experiment-specific code file instead of the default ML set.",
    )
    parser.add_argument("--output-path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    settings = Settings.from_env()
    dataset_path = Path(args.dataset_path).expanduser()
    if not dataset_path.is_absolute():
        dataset_path = settings.project_root / dataset_path
    payload = build_research_compute_manifest(
        settings.project_root,
        dataset_path=dataset_path,
        code_paths=(
            tuple(Path(value) for value in args.code_path)
            if args.code_path
            else DEFAULT_CODE_PATHS
        ),
    )
    artifact = write_research_json_artifact(
        settings,
        payload,
        kind="research-gpu-environment",
        path_key="artifact_path",
        default_filename="research_gpu_environment.json",
        explicit_path=args.output_path,
    )
    print(f"artifact={artifact['artifact_path']}")
    print(f"manifest_hash={artifact['manifest_hash']}")
    print(f"dataset_data_hash={artifact['evidence']['dataset_data_hash']}")
    torch_environment = artifact["environment"]["torch"] or {}
    print(f"cuda_available={bool(torch_environment.get('cuda_available'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
