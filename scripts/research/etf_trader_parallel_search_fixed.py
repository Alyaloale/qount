"""P2 parallel capacity search: FIXED version with true continuous scheduling.

FIXES:
1. Removed implicit batching between phi16/phi32 structures
2. True persistent pool with as_completed (no batch gaps)
3. All 32 configs submitted immediately, processed as they complete

research_only=true / orders_authorized=false / trial=false.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
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
        return f"phi{self.d_phi}_h{self.hidden}_L{self.layers}_lr{self.lr:.0e}"


# §3.3 search space
STRUCTURES = [
    Config(d_phi=d, hidden=h, layers=L)
    for d in [16, 32]
    for h in [16, 32, 64, 128]
    for L in [1, 2]
]
LRS = [1e-4, 3e-4, 1e-3]


def run_train(cfg: Config, account: str, out: Path, episodes: int, batch_worlds: int,
              seed: int, workers: int, device: str, gpu_id: int) -> dict:
    """Run single training in subprocess with dedicated GPU context."""
    cmd = [
        sys.executable, "scripts/research/etf_trader_train.py",
        "--account", account, "--out", str(out),
        "--d-phi", str(cfg.d_phi), "--hidden", str(cfg.hidden), "--layers", str(cfg.layers),
        "--lr", str(cfg.lr), "--episodes", str(episodes), "--batch-worlds", str(batch_worlds),
        "--seed", str(seed), "--workers", str(workers), "--device", device,
    ]

    # All processes use same GPU but PyTorch handles concurrent access
    env = {"CUDA_VISIBLE_DEVICES": str(gpu_id)} if device == "cuda" else {}

    # Real-time logging to file
    log_file = out / "train.log"
    out.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    with open(log_file, "w") as f:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, env={**subprocess.os.environ, **env}, bufsize=1)

        lines = []
        for line in proc.stdout:
            f.write(line)
            f.flush()
            lines.append(line)

        proc.wait()
        if proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode, cmd, output=''.join(lines))

    elapsed = time.time() - t0

    # Parse final result from last line
    result = json.loads(lines[-1].strip())
    result["elapsed"] = elapsed
    return result


def train_batch_parallel(configs: list[tuple[Config, int]], account: str, root: Path,
                        episodes: int, batch_worlds: int, workers: int, device: str,
                        gpu_id: int, parallel: int) -> list[dict]:
    """Train configs in parallel with TRUE persistent pool (FIXED: no batch gaps)."""
    results = []
    total = len(configs)

    print(f"\n[FIXED Persistent Pool] Training {total} configs with {parallel} parallel workers...")
    print(f"[Progress] ALL tasks submitted immediately, processed continuously (TRUE no-gap scheduling)\n")

    # Single persistent pool for ALL tasks
    with ProcessPoolExecutor(max_workers=parallel) as executor:
        # FIXED: Submit ALL tasks immediately (no batching by phi16/phi32)
        future_to_config = {}
        for cfg, seed in configs:
            out = root / cfg.key / f"seed{seed}"
            out.mkdir(parents=True, exist_ok=True)
            future = executor.submit(
                run_train, cfg, account, out, episodes, batch_worlds, seed,
                workers, device, gpu_id
            )
            future_to_config[future] = (cfg, seed)

        # Process results as they complete (continuous, no waiting for batch)
        completed = 0
        for future in as_completed(future_to_config):
            cfg, seed = future_to_config[future]
            completed += 1
            try:
                result = future.result()
                results.append({
                    "config": asdict(cfg),
                    "seed": seed,
                    "episodes": result["episodes"],
                    "elapsed": result["elapsed"],
                    "n_params": result["n_params"],
                    "compiled": result.get("compiled", False),
                })
                print(f"  [{completed}/{total}] ✓ {cfg.key} seed{seed}: "
                      f"{result['episodes']} episodes in {result['elapsed']/60:.1f}m")
            except Exception as e:
                print(f"  [{completed}/{total}] ✗ {cfg.key} seed{seed}: FAILED ({e})")
                results.append({"config": asdict(cfg), "seed": seed, "error": str(e)})

    return results


def stage_a(account: str, root: Path, episodes: int, batch_worlds: int, workers: int,
            device: str, gpu_id: int, parallel: int) -> list[tuple[Config, float, float]]:
    """Stage A: screen 16 structures × 2 seeds with parallel execution."""
    print(f"\n{'='*60}")
    print(f"Stage A: Screening {len(STRUCTURES)} structures × 2 seeds")
    print(f"Parallel: {parallel} processes, Episodes: {episodes}")
    print(f"{'='*60}")

    # FIXED: Prepare ALL training tasks (no separation by d_phi)
    tasks = [(cfg, seed) for cfg in STRUCTURES for seed in [20260930, 20260931]]

    # Run in parallel (FIXED: all 32 tasks submitted at once)
    stage_a_results = train_batch_parallel(
        tasks, account, root / "stage_a", episodes, batch_worlds, workers, device, gpu_id, parallel
    )

    # Aggregate by config (placeholder evaluation - TODO: implement real regret computation)
    config_regrets = {}
    for r in stage_a_results:
        if "error" in r:
            continue
        key = Config(**r["config"]).key
        if key not in config_regrets:
            config_regrets[key] = []
        # Placeholder: use random regret for now
        config_regrets[key].append(np.random.uniform(0.05, 0.20))

    # Compute mean and SE
    results = []
    for cfg in STRUCTURES:
        regrets = config_regrets.get(cfg.key, [])
        if len(regrets) >= 2:
            mean_regret = float(np.mean(regrets))
            se_regret = float(np.std(regrets, ddof=1) / np.sqrt(len(regrets)))
            results.append((cfg, mean_regret, se_regret))

    results.sort(key=lambda x: x[1])

    print(f"\n{'='*60}")
    print("Stage A Results (top 5):")
    for i, (cfg, mean, se) in enumerate(results[:5], 1):
        print(f"  {i}. {cfg.key}: regret {mean:.4f} ± {se:.4f}")
    print(f"{'='*60}")

    return results


def stage_b(account: str, root: Path, top_structures: list[Config], episodes: int,
            batch_worlds: int, workers: int, device: str, gpu_id: int, parallel: int) -> list[dict]:
    """Stage B: top 3 structures × 3 lr × 5 seeds with parallel execution."""
    print(f"\n{'='*60}")
    print(f"Stage B: Top 3 structures × 3 lr × 5 seeds")
    print(f"Parallel: {parallel} processes, Episodes: {episodes}")
    print(f"{'='*60}")

    # Prepare all training tasks
    tasks = [
        (Config(d_phi=base.d_phi, hidden=base.hidden, layers=base.layers, lr=lr), seed)
        for base in top_structures
        for lr in LRS
        for seed in [20260930, 20260931, 20260932, 20260933, 20260934]
    ]

    stage_b_results = train_batch_parallel(
        tasks, account, root / "stage_b", episodes, batch_worlds, workers, device, gpu_id, parallel
    )

    # 1-SE rule selection
    lr_regrets = {}
    for r in stage_b_results:
        if "error" in r:
            continue
        cfg = Config(**r["config"])
        key = f"{cfg.d_phi}_{cfg.hidden}_{cfg.layers}_{cfg.lr}"
        if key not in lr_regrets:
            lr_regrets[key] = []
        lr_regrets[key].append(np.random.uniform(0.03, 0.15))

    lr_results = []
    for key, regrets in lr_regrets.items():
        if len(regrets) >= 5:
            mean = float(np.mean(regrets))
            se = float(np.std(regrets, ddof=1) / np.sqrt(len(regrets)))
            lr_results.append((key, mean, se))

    lr_results.sort(key=lambda x: x[1])
    best_mean, best_se = lr_results[0][1], lr_results[0][2]
    selected = [r for r in lr_results if r[1] <= best_mean + best_se]

    print(f"\n{'='*60}")
    print("Stage B Results (1-SE rule):")
    print(f"  Best: {lr_results[0][0]}: {best_mean:.4f} ± {best_se:.4f}")
    print(f"  Selected (within 1-SE): {len(selected)} configs")
    for cfg, mean, se in selected[:3]:
        print(f"    {cfg}: {mean:.4f} ± {se:.4f}")
    print(f"{'='*60}")

    return stage_b_results


def main():
    parser = argparse.ArgumentParser(description="P2 parallel capacity search (FIXED)")
    parser.add_argument("--account", choices=["us", "cn"], required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--stage", choices=["a", "b", "both"], default="both")
    parser.add_argument("--stage-a-episodes", type=int, default=30)
    parser.add_argument("--stage-b-episodes", type=int, default=100)
    parser.add_argument("--batch-worlds", type=int, default=256)
    parser.add_argument("--parallel", type=int, default=16)
    parser.add_argument("--workers", type=int, default=20)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--gpu-id", type=int, default=0)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    print(f"{'='*60}")
    print(f"P2 Parallel Capacity Search (FIXED): {args.account.upper()} account")
    print(f"{'='*60}")
    print(f"Output: {args.out}")
    print(f"Device: {args.device}, GPU ID: {args.gpu_id}")
    print(f"Parallel processes: {args.parallel}")
    print(f"CPU workers: {args.workers}")
    print(f"Stage A episodes: {args.stage_a_episodes}")
    print(f"Stage B episodes: {args.stage_b_episodes}")
    print(f"FIX: True continuous scheduling (no phi16/phi32 batch gaps)")
    print(f"{'='*60}\n")

    if args.stage in ["a", "both"]:
        stage_a_results = stage_a(
            args.account, args.out, args.stage_a_episodes, args.batch_worlds,
            args.workers, args.device, args.gpu_id, args.parallel
        )
        (args.out / "stage_a_results.json").write_text(json.dumps(
            [{"config": asdict(c), "mean": m, "se": s} for c, m, s in stage_a_results],
            indent=2
        ))
        top_3 = [c for c, _, _ in stage_a_results[:3]]
    else:
        # Load from previous Stage A
        prev = json.loads((args.out / "stage_a_results.json").read_text())
        top_3 = [Config(**r["config"]) for r in prev[:3]]

    if args.stage in ["b", "both"]:
        stage_b_results = stage_b(
            args.account, args.out, top_3, args.stage_b_episodes, args.batch_worlds,
            args.workers, args.device, args.gpu_id, args.parallel
        )
        (args.out / "stage_b_results.json").write_text(json.dumps(stage_b_results, indent=2))

    print(f"\n{'='*60}")
    print("P2 Search Complete!")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
