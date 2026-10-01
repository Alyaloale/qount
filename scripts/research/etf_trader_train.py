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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", choices=("us", "cn"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--episodes", type=int, default=TrainConfig.episodes)
    parser.add_argument("--batch-worlds", type=int, default=TrainConfig.batch_worlds)
    parser.add_argument("--years", type=float, default=TrainConfig.years)
    parser.add_argument("--d-phi", type=int, default=32)
    parser.add_argument("--hidden", type=int, default=64)
    parser.add_argument("--layers", type=int, default=1)
    parser.add_argument("--lr", type=float, default=TrainConfig.lr)
    parser.add_argument("--seed", type=int, default=TrainConfig.seed)
    parser.add_argument("--workers", type=int, default=TrainConfig.workers)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--max-minutes", type=float, default=None)
    args = parser.parse_args(argv)

    cfg = replace(
        TrainConfig(),
        account=args.account, episodes=args.episodes, batch_worlds=args.batch_worlds, years=args.years,
        policy=PolicyConfig(d_phi=args.d_phi, hidden=args.hidden, layers=args.layers), lr=args.lr,
        seed=args.seed, workers=args.workers, device=args.device,
    )
    res = train(cfg, args.out, max_minutes=args.max_minutes)
    print(json.dumps({"lambda": res["lambda"], "episodes": len(res["history"]), "n_params": res["meta"]["n_params"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
