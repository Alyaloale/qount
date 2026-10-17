"""测试不同优化配置的性能
快速对比 compile 模式、batch_worlds、workers 的影响
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")

from qount.research.etf_trader.train import train, TrainConfig


def test_config(name: str, cfg: TrainConfig, out_dir: Path) -> dict:
    """测试单个配置并返回性能指标"""
    print(f"\n{'='*60}")
    print(f"测试: {name}")
    print(f"{'='*60}")
    print(f"  batch_worlds: {cfg.batch_worlds}")
    print(f"  workers: {cfg.workers}")
    print(f"  compile_mode: {cfg.compile_mode}")

    t0 = time.time()
    result = train(cfg, out_dir, log_every=1, use_compile=True)
    elapsed = time.time() - t0

    hist = result["history"]

    # 跳过 episode 0（首次编译）
    if len(hist) > 1:
        avg_gen = sum(h["time_gen"] for h in hist[1:]) / len(hist[1:])
        avg_rollout = sum(h["time_rollout"] for h in hist[1:]) / len(hist[1:])
        avg_total = sum(h["seconds"] for h in hist[1:]) / len(hist[1:])
    else:
        avg_gen = hist[0]["time_gen"]
        avg_rollout = hist[0]["time_rollout"]
        avg_total = hist[0]["seconds"]

    seconds_per_update = avg_rollout / 8  # 每 episode 8 updates

    metrics = {
        "name": name,
        "total_time": elapsed,
        "avg_gen": avg_gen,
        "avg_rollout": avg_rollout,
        "avg_total": avg_total,
        "seconds_per_update": seconds_per_update,
        "compiled": result["meta"]["compiled"],
        "config": {
            "batch_worlds": cfg.batch_worlds,
            "workers": cfg.workers,
            "compile_mode": cfg.compile_mode,
        }
    }

    print(f"\n结果:")
    print(f"  总时间: {elapsed:.1f}秒")
    print(f"  平均 gen: {avg_gen:.1f}秒")
    print(f"  平均 rollout: {avg_rollout:.1f}秒")
    print(f"  每次 update: {seconds_per_update:.2f}秒")
    print(f"  编译状态: {metrics['compiled']}")

    return metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", default="us")
    parser.add_argument("--episodes", type=int, default=5, help="快速测试用少量 episodes")
    parser.add_argument("--out", type=Path, default=Path("experiments/optimization_tests"))
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    # 测试配置组合
    test_configs = [
        # 基准
        ("baseline", {"batch_worlds": 256, "workers": 8, "compile_mode": "reduce-overhead"}),

        # 不同 compile 模式
        ("max-autotune", {"batch_worlds": 256, "workers": 8, "compile_mode": "max-autotune"}),
        ("default-compile", {"batch_worlds": 256, "workers": 8, "compile_mode": "default"}),

        # 不同 workers（测试世界生成瓶颈）
        ("workers-12", {"batch_worlds": 256, "workers": 12, "compile_mode": "reduce-overhead"}),
        ("workers-16", {"batch_worlds": 256, "workers": 16, "compile_mode": "reduce-overhead"}),

        # 不同 batch_worlds
        ("batch-384", {"batch_worlds": 384, "workers": 12, "compile_mode": "reduce-overhead"}),
        ("batch-512", {"batch_worlds": 512, "workers": 16, "compile_mode": "reduce-overhead"}),
    ]

    results = []

    for name, config_overrides in test_configs:
        cfg = TrainConfig(
            account=args.account,
            episodes=args.episodes,
            **config_overrides
        )

        out_dir = args.out / name
        out_dir.mkdir(parents=True, exist_ok=True)

        try:
            metrics = test_config(name, cfg, out_dir)
            results.append(metrics)
        except Exception as e:
            print(f"✗ 配置 {name} 失败: {e}")
            results.append({
                "name": name,
                "error": str(e),
                "config": config_overrides,
            })

    # 保存结果
    results_file = args.out / "results.json"
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2)

    # 打印对比
    print(f"\n{'='*80}")
    print("性能对比总结")
    print(f"{'='*80}")
    print(f"{'配置':<20} {'总时间':<10} {'avg_gen':<10} {'avg_rollout':<12} {'秒/update':<10}")
    print("-" * 80)

    for r in results:
        if "error" in r:
            print(f"{r['name']:<20} ERROR: {r['error'][:40]}")
        else:
            print(f"{r['name']:<20} {r['total_time']:>8.1f}s  "
                  f"{r['avg_gen']:>8.1f}s  {r['avg_rollout']:>10.1f}s  "
                  f"{r['seconds_per_update']:>8.2f}s")

    # 找出最优配置
    valid_results = [r for r in results if "error" not in r]
    if valid_results:
        best = min(valid_results, key=lambda x: x["avg_total"])
        print(f"\n最优配置: {best['name']}")
        print(f"  平均每 episode: {best['avg_total']:.1f}秒")
        print(f"  vs baseline 加速: {results[0]['avg_total'] / best['avg_total']:.2f}x")

    print(f"\n详细结果保存至: {results_file}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
