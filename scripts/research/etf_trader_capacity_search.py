"""P2 capacity search: two-stage hyperparameter selection (design §3.3).

Stage A: 16 structure configs × 2 seeds, 1/4 budget (150 episodes), lr=3e-4 → top 3
Stage B: top 3 structures × 3 lr × 5 seeds, full budget (600 episodes) → 1-SE rule

Selection criterion: val-world mean regret to oracle; 1-SE rule favors smaller models.
research_only=true / orders_authorized=false / trial=false. Synthetic worlds only.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np


@dataclass
class Config:
    d_phi: int
    hidden: int
    layers: int
    lr: float = 3e-4

    @property
    def key(self) -> str:
        return f"phi{self.d_phi}_h{self.hidden}_L{self.layers}"


# §3.3 search space
STRUCTURES = [
    Config(d_phi=d, hidden=h, layers=L)
    for d in [16, 32]
    for h in [16, 32, 64, 128]
    for L in [1, 2]
]
LRS = [1e-4, 3e-4, 1e-3]
STAGE_A_SEEDS = [20260930, 20260931]
STAGE_B_SEEDS = [20260930, 20260931, 20260932, 20260933, 20260934]


def run_train(cfg: Config, account: str, out: Path, episodes: int, batch_worlds: int,
              seed: int, workers: int, device: str, max_minutes: float | None) -> dict:
    """Call etf_trader_train.py; return parsed result."""
    cmd = [
        sys.executable, "scripts/research/etf_trader_train.py",
        "--account", account, "--out", str(out),
        "--d-phi", str(cfg.d_phi), "--hidden", str(cfg.hidden), "--layers", str(cfg.layers),
        "--lr", str(cfg.lr), "--episodes", str(episodes), "--batch-worlds", str(batch_worlds),
        "--seed", str(seed), "--workers", str(workers), "--device", device,
    ]
    if max_minutes is not None:
        cmd += ["--max-minutes", str(max_minutes)]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(res.stdout.strip().splitlines()[-1])


def evaluate_on_val(checkpoint: Path, account: str, n_val: int, workers: int, device: str) -> float:
    """Load checkpoint and compute mean regret on independent val worlds (§8.1).

    Returns mean regret (lower is better). Placeholder: returns random for now.
    TODO: implement evaluate.py with oracle baseline and regret computation.
    """
    # Placeholder implementation until evaluate.py is ready
    rng = np.random.default_rng(int(checkpoint.stem.split("_")[-1]))
    return float(rng.uniform(0.05, 0.20))  # simulated regret in [5%, 20%]


def stage_a(account: str, root: Path, batch_worlds: int, workers: int, device: str,
            max_minutes: float | None, n_val: int) -> list[tuple[Config, float, float]]:
    """Stage A: screen 16 structures × 2 seeds with 1/4 budget.

    Returns list of (config, mean_regret, se_regret) sorted by mean_regret.
    """
    episodes_a = 150  # 1/4 of 600
    results = []

    for i, cfg in enumerate(STRUCTURES, 1):
        print(f"\n[Stage A {i}/{len(STRUCTURES)}] {cfg.key}, lr={cfg.lr:.0e}")
        regrets = []

        for seed_idx, seed in enumerate(STAGE_A_SEEDS, 1):
            out = root / "stage_a" / cfg.key / f"seed{seed}"
            out.mkdir(parents=True, exist_ok=True)

            print(f"  Training seed {seed_idx}/{len(STAGE_A_SEEDS)} (seed={seed})...")
            t0 = time.time()
            train_res = run_train(cfg, account, out, episodes_a, batch_worlds, seed, workers, device, max_minutes)
            elapsed = time.time() - t0
            print(f"    Done in {elapsed/60:.1f}m, {train_res['episodes']} episodes, {train_res['n_params']} params")

            # Evaluate on val worlds
            ckpt = out / "model.pt"
            regret = evaluate_on_val(ckpt, account, n_val, workers, device)
            regrets.append(regret)
            print(f"    Val regret: {regret:.4f}")

        mean_regret = float(np.mean(regrets))
        se_regret = float(np.std(regrets, ddof=1) / np.sqrt(len(regrets)))
        results.append((cfg, mean_regret, se_regret))
        print(f"  {cfg.key}: mean regret {mean_regret:.4f} ± {se_regret:.4f}")

    results.sort(key=lambda x: x[1])
    return results


def stage_b(account: str, root: Path, top_structures: list[Config], batch_worlds: int,
            workers: int, device: str, max_minutes: float | None, n_val: int) -> list[dict]:
    """Stage B: top 3 structures × 3 lr × 5 seeds, full budget.

    Returns list of result dicts with config, mean_regret, se_regret.
    """
    episodes_b = 600
    results = []
    total = len(top_structures) * len(LRS)

    for i, base_cfg in enumerate(top_structures, 1):
        for j, lr in enumerate(LRS, 1):
            cfg = Config(d_phi=base_cfg.d_phi, hidden=base_cfg.hidden, layers=base_cfg.layers, lr=lr)
            idx = (i - 1) * len(LRS) + j
            print(f"\n[Stage B {idx}/{total}] {cfg.key}, lr={cfg.lr:.0e}")

            regrets = []
            for seed_idx, seed in enumerate(STAGE_B_SEEDS, 1):
                out = root / "stage_b" / f"{cfg.key}_lr{lr:.0e}" / f"seed{seed}"
                out.mkdir(parents=True, exist_ok=True)

                print(f"  Training seed {seed_idx}/{len(STAGE_B_SEEDS)} (seed={seed})...")
                t0 = time.time()
                train_res = run_train(cfg, account, out, episodes_b, batch_worlds, seed, workers, device, max_minutes)
                elapsed = time.time() - t0
                print(f"    Done in {elapsed/60:.1f}m, {train_res['episodes']} episodes")

                ckpt = out / "model.pt"
                regret = evaluate_on_val(ckpt, account, n_val, workers, device)
                regrets.append(regret)
                print(f"    Val regret: {regret:.4f}")

            mean_regret = float(np.mean(regrets))
            se_regret = float(np.std(regrets, ddof=1) / np.sqrt(len(regrets)))
            results.append({
                "config": asdict(cfg),
                "mean_regret": mean_regret,
                "se_regret": se_regret,
                "regrets": regrets,
            })
            print(f"  {cfg.key} lr={lr:.0e}: mean regret {mean_regret:.4f} ± {se_regret:.4f}")

    return results


def select_1se(results: list[dict]) -> dict:
    """Apply 1-SE rule: smallest model within 1 SE of the best (§3.3)."""
    results = sorted(results, key=lambda x: x["mean_regret"])
    best = results[0]
    threshold = best["mean_regret"] + best["se_regret"]

    # Among configs within threshold, pick smallest (fewest params)
    def param_count(cfg):
        d, h, L = cfg["d_phi"], cfg["hidden"], cfg["layers"]
        enc = 12 * d + d * d
        gru_in = 2 * d + 12
        gru = gru_in * 4 * h + h * 4 * h + 4 * h if L == 1 else gru_in * 4 * h + h * 4 * h + 4 * h + h * 4 * h + h * 4 * h + 4 * h
        head = h * 8 + 8
        return enc + gru + head

    candidates = [r for r in results if r["mean_regret"] <= threshold]
    selected = min(candidates, key=lambda r: param_count(r["config"]))
    return selected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", choices=("us", "cn"), required=True)
    parser.add_argument("--out", type=Path, required=True, help="Root directory for all search outputs")
    parser.add_argument("--batch-worlds", type=int, default=256)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--max-minutes", type=float, default=None, help="Per-training time limit")
    parser.add_argument("--n-val", type=int, default=1000, help="Number of validation worlds for regret eval")
    parser.add_argument("--stage", choices=("a", "b", "both"), default="both")
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)

    print(f"=== P2 Capacity Search: {args.account.upper()} account ===")
    print(f"Output root: {args.out}")
    print(f"Device: {args.device}, Workers: {args.workers}, Batch: {args.batch_worlds} worlds\n")

    # Stage A
    if args.stage in ("a", "both"):
        print("=== Stage A: Screen 16 structures × 2 seeds ===")
        stage_a_results = stage_a(args.account, args.out, args.batch_worlds, args.workers,
                                   args.device, args.max_minutes, args.n_val)

        print("\n=== Stage A Summary ===")
        for i, (cfg, mean, se) in enumerate(stage_a_results[:5], 1):
            print(f"{i}. {cfg.key}: {mean:.4f} ± {se:.4f}")

        with open(args.out / "stage_a_results.json", "w") as f:
            json.dump([{"config": asdict(c), "mean_regret": m, "se_regret": s}
                       for c, m, s in stage_a_results], f, indent=2)

        top3 = [cfg for cfg, _, _ in stage_a_results[:3]]
        print(f"\nTop 3 for Stage B: {[c.key for c in top3]}")
    else:
        # Load from previous Stage A
        with open(args.out / "stage_a_results.json") as f:
            stage_a_data = json.load(f)
        top3 = [Config(**r["config"]["d_phi"], **r["config"]["hidden"], **r["config"]["layers"])
                for r in stage_a_data[:3]]

    # Stage B
    if args.stage in ("b", "both"):
        print("\n=== Stage B: Top 3 × 3 lr × 5 seeds ===")
        stage_b_results = stage_b(args.account, args.out, top3, args.batch_worlds, args.workers,
                                   args.device, args.max_minutes, args.n_val)

        with open(args.out / "stage_b_results.json", "w") as f:
            json.dump(stage_b_results, f, indent=2)

        # Select final config by 1-SE rule
        selected = select_1se(stage_b_results)

        print("\n=== Stage B Summary (sorted by regret) ===")
        for i, r in enumerate(sorted(stage_b_results, key=lambda x: x["mean_regret"])[:5], 1):
            c = r["config"]
            print(f"{i}. phi{c['d_phi']}_h{c['hidden']}_L{c['layers']} lr={c['lr']:.0e}: "
                  f"{r['mean_regret']:.4f} ± {r['se_regret']:.4f}")

        print(f"\n=== Selected by 1-SE rule ===")
        c = selected["config"]
        print(f"Config: d_phi={c['d_phi']}, hidden={c['hidden']}, layers={c['layers']}, lr={c['lr']:.0e}")
        print(f"Val regret: {selected['mean_regret']:.4f} ± {selected['se_regret']:.4f}")

        with open(args.out / "selected_config.json", "w") as f:
            json.dump(selected, f, indent=2)

    print(f"\n=== Search complete. Results saved to {args.out} ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
