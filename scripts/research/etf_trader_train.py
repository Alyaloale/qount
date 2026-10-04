"""Train the ETF trader on generated worlds (design §3.3, §4; P2).

research_only=true / orders_authorized=false / trial=false. Synthetic worlds only: no market
data, credentials, accounts or paper state. Runs on the WSL GPU host (torch required).
Design: docs/etf-imitation-policy-design-2026-09.md
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from qount.research.etf_trader.policy import PolicyConfig
from qount.research.etf_trader.train import TrainConfig, train
from qount.research.etf_trader.training_runtime import COMPILE_MODES
from qount.research.etf_trader.worlds import require_external_dataset_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", choices=("us", "cn"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--episodes", type=int, default=TrainConfig.episodes)
    parser.add_argument("--batch-worlds", type=int, default=TrainConfig.batch_worlds)
    parser.add_argument("--years", type=float, default=TrainConfig.years)
    parser.add_argument("--warmup-years", type=float, default=TrainConfig.warmup_years)
    parser.add_argument("--plausibility-years", type=float, default=TrainConfig.plausibility_years)
    parser.add_argument("--d-phi", type=int, default=32)
    parser.add_argument("--hidden", type=int, default=64)
    parser.add_argument("--layers", type=int, default=1)
    parser.add_argument("--lr", type=float, default=TrainConfig.lr)
    parser.add_argument("--seed", type=int, default=TrainConfig.seed)
    parser.add_argument("--workers", type=int, default=TrainConfig.workers)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--max-minutes", type=float, default=None)
    parser.add_argument("--no-compile", action="store_true", help="Disable torch.compile")
    parser.add_argument("--compile-mode", choices=COMPILE_MODES, default=TrainConfig.compile_mode)
    parser.add_argument("--world-dataset", type=Path,
                        help="Verified, pre-generated dataset; training never generates worlds in this mode")
    parser.add_argument("--pipeline", action="store_true", help="Enable pipelined training (GPU+CPU overlap)")
    args = parser.parse_args(argv)

    cfg = replace(
        TrainConfig(),
        account=args.account, episodes=args.episodes, batch_worlds=args.batch_worlds, years=args.years,
        policy=PolicyConfig(d_phi=args.d_phi, hidden=args.hidden, layers=args.layers), lr=args.lr,
        seed=args.seed, workers=args.workers, device=args.device, warmup_years=args.warmup_years,
        plausibility_years=args.plausibility_years, compile_mode=args.compile_mode,
    )

    try:
        dataset = require_external_dataset_path(args.world_dataset) if args.world_dataset is not None else None
    except ValueError as exc:
        parser.error(str(exc))

    if args.pipeline:
        from qount.research.etf_trader.train_pipeline import train_pipelined
        res = train_pipelined(cfg, args.out, max_minutes=args.max_minutes, use_compile=not args.no_compile,
                              world_dataset=dataset)
    else:
        res = train(cfg, args.out, max_minutes=args.max_minutes, use_compile=not args.no_compile,
                    world_dataset=dataset)

    print(json.dumps({"lambda": res["lambda"], "episodes": len(res["history"]), "n_params": res["meta"]["n_params"],
                      "compiled": res["meta"].get("compiled", False), "pipelined": res.get("pipelined", False)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
