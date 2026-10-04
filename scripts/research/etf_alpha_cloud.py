#!/usr/bin/env python3
"""Prepare, verify, package and run the isolated RTX3080Ti P3 research delivery."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("pack", "export-inputs", "inspect", "prepare", "benchmark", "run", "collect", "verify", "benchmark-candidate"):
        command = commands.add_parser(name)
        if name in {"inspect", "prepare", "benchmark", "run", "collect", "benchmark-candidate"}:
            command.add_argument("--contract", type=Path, required=True)
        if name in {"pack", "export-inputs", "prepare", "benchmark", "collect", "benchmark-candidate"}:
            command.add_argument("--out", type=Path, required=True)
        if name == "export-inputs":
            command.add_argument("--data-root", type=Path, required=True)
            command.add_argument("--fold-contract", type=Path, required=True)
        if name == "inspect":
            command.add_argument("--cpu-only", action="store_true")
        if name == "run":
            command.add_argument("--calibration", type=Path, required=True)
            command.add_argument("--bootstrap-root", type=Path)
        if name == "collect":
            command.add_argument("--run-root", type=Path, required=True)
        if name == "verify":
            command.add_argument("--archive", type=Path, required=True)
        if name == "benchmark-candidate":
            command.add_argument("--compiled", action="store_true")
            command.add_argument("--bootstrap", action="store_true")
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[2]
    from qount.research.etf_alpha.artifacts import read_json, write_json
    from qount.research.etf_alpha import cloud, cloud_bundle
    config = read_json(args.contract) if hasattr(args, "contract") else None
    if args.command == "pack":
        result = cloud_bundle.pack(repository, args.out)
    elif args.command == "export-inputs":
        result = cloud_bundle.export_inputs(args.data_root, args.fold_contract, args.out)
    elif args.command == "inspect":
        result = cloud.inspect(config, check_gpu=not args.cpu_only)
    elif args.command == "prepare":
        result = cloud.prepare(config, args.out)
    elif args.command == "benchmark":
        result = cloud.calibrate(config, args.out, repository)
    elif args.command == "benchmark-candidate":
        cloud.require_compute_authorization(config)
        from qount.research.etf_alpha.cloud_benchmark import candidate
        result = candidate(compiled=args.compiled, bootstrap=args.bootstrap)
        write_json(args.out, result)
    elif args.command == "run":
        result = cloud.execute(args.contract, repository=repository, calibration=args.calibration,
                               bootstrap_root=args.bootstrap_root)
    elif args.command == "collect":
        result = cloud_bundle.collect_results(config, args.run_root, args.out)
    else:
        result = cloud_bundle.verify_archive(args.archive)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False), flush=True)
    return 1 if result.get("status") == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
