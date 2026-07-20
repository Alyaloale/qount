#!/usr/bin/env python3
"""Write a credential-free environment manifest for a qount compute node."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.research_compute import build_research_compute_manifest  # noqa: E402


DEFAULT_CODE_PATHS = (
    Path("pyproject.toml"),
    Path("deploy/wsl/qount-compute.env"),
    Path("src/qount/settings.py"),
    Path("src/qount/storage_topology.py"),
    Path("src/qount/mini_trend/regime_ml.py"),
    Path("src/qount/mini_trend/regime_neural.py"),
    Path("src/qount/mini_trend/regime_economic_ml.py"),
    Path("src/qount/mini_trend/regime_adaptation_matrix.py"),
    Path("src/qount/mini_trend/regime_adaptation_confirm.py"),
    Path("src/qount/mini_trend/regime_adaptation_ablation.py"),
    Path("src/qount/mini_trend/regime_onchain.py"),
    Path("src/qount/mini_trend/regime_onchain_audit.py"),
    Path("src/qount/mini_trend/regime_onchain_model.py"),
    Path("src/qount/mini_trend/regime_onchain_strategy.py"),
    Path("src/qount/mini_trend/onchain_vintage.py"),
    Path("src/qount/mini_trend/macro_h41.py"),
    Path("src/qount/mini_trend/macro_h41_model.py"),
    Path("src/qount/mini_trend/regime_macro_onchain_fusion.py"),
    Path("src/qount/mini_trend/regime_macro_strategy.py"),
    Path("src/qount/mini_trend/regime_macro_event.py"),
    Path("src/qount/mini_trend/regime_macro_boost_veto.py"),
    Path("src/qount/mini_trend/futures_base_episode_attribution.py"),
    Path("src/qount/mini_trend/futures_signal_exit_cooldown.py"),
)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=str(REPO))
    parser.add_argument("--dataset-path")
    parser.add_argument("--output", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    project_root = Path(args.project_root).expanduser().resolve()
    dataset_path = Path(args.dataset_path) if args.dataset_path else None
    if dataset_path is not None and not dataset_path.is_absolute():
        dataset_path = project_root / dataset_path
    payload = build_research_compute_manifest(
        project_root,
        dataset_path=dataset_path,
        code_paths=DEFAULT_CODE_PATHS,
    )
    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output)
    print(f"manifest={output.resolve()}")
    print(f"manifest_hash={payload['manifest_hash']}")
    print(f"code_bundle_hash={payload['evidence']['code_bundle_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
