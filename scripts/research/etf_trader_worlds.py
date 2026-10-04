"""Generate and save CPU-only synthetic ETF worlds; run training as a separate command."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from qount.research.etf_trader.worlds import (
    WorldDataset, WorldDatasetConfig, estimated_bytes, generate_dataset, require_external_dataset_path,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--account", choices=("us", "cn"), default="us")
    parser.add_argument("--worlds", type=int, default=256, help="Total worlds (episodes × batch-worlds for training)")
    parser.add_argument("--split", choices=("train", "val", "test"), default="train")
    parser.add_argument("--seed", type=int, default=WorldDatasetConfig.seed)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--years", type=float, default=WorldDatasetConfig.years)
    parser.add_argument("--warmup-years", type=float, default=WorldDatasetConfig.warmup_years)
    parser.add_argument("--plausibility-years", type=float, default=WorldDatasetConfig.plausibility_years)
    parser.add_argument("--max-draws", type=int, default=WorldDatasetConfig.max_draws)
    parser.add_argument("--shard-worlds", type=int, default=WorldDatasetConfig.shard_worlds)
    parser.add_argument("--dtype", choices=("float32", "float64"), default="float32")
    parser.add_argument("--backend", choices=("native", "numpy", "auto"), default="native")
    parser.add_argument("--workers", type=int, default=0, help="0 uses available CPU cores")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--resume", action="store_true")
    mode.add_argument("--verify", action="store_true", help="Read and verify a completed dataset without generating")
    mode.add_argument("--estimate-only", action="store_true", help="Estimate array bytes; no writes or build")
    args = parser.parse_args(argv)
    cfg = WorldDatasetConfig(account=args.account, seed=args.seed, split=args.split, worlds=args.worlds,
                             start_index=args.start_index, years=args.years, warmup_years=args.warmup_years,
                             plausibility_years=args.plausibility_years, max_draws=args.max_draws,
                             shard_worlds=args.shard_worlds, dtype=args.dtype, backend=args.backend)
    try:
        if args.estimate_only:
            result = {"worlds": cfg.worlds, "array_bytes": estimated_bytes(cfg), "rows_per_world": cfg.rows}
        else:
            out = require_external_dataset_path(args.out)
            manifest = WorldDataset(out).manifest if args.verify else generate_dataset(
                cfg, out, workers=args.workers, resume=args.resume
            )
            result = {"status": manifest["status"], "shards": len(manifest["shards"]),
                      "array_bytes": manifest["estimated_array_bytes"],
                      "contract_sha256": manifest["contract_sha256"]}
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(2, f"{exc}\n")
    print(json.dumps({**result, "research_only": True, "orders_authorized": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
