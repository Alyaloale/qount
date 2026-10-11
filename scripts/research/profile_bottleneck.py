#!/usr/bin/env python3
"""Profile 训练瓶颈 - 找出每天 15ms 花在哪"""

import sys
import time
import torch
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from qount.research.etf_trader.train import train, TrainConfig
from qount.research.etf_trader.policy import Trader, TraderConfig
from qount.research.etf_trader.generator.world import WorldConfig
from qount.account import Account


def profile_detailed():
    """详细 profile 每个操作"""

    print("="*70)
    print("详细 Profile 训练瓶颈")
    print("="*70)

    # 小规模配置，快速测试
    cfg = TrainConfig(
        episodes=3,
        batch_worlds=64,
        workers=4,
        segment=252,
        compile_mode="reduce-overhead",
    )

    world_cfg = WorldConfig(years=2.0)

    model_cfg = TraderConfig(
        asset_dim=12,
        phi_hidden=16,
        phi_layers=1,
        h_dim=16,
    )

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device: {device}")
    print(f"Batch worlds: {cfg.batch_worlds}")
    print(f"Days per episode: {int(world_cfg.years * 252)}")
    print()

    # 手动实现训练循环
    from qount.research.etf_trader.train import to_tensors, run_segment
    from qount.research.etf_trader.torch_env import TorchEnv
    import concurrent.futures as cf

    acct = Account.US
    costs = acct.costs()

    # 生成世界
    print("生成第一个 episode 的世界...")
    t_gen_start = time.time()

    def gen_world(seed):
        from qount.research.etf_trader.generator.world import RandomWorld
        return RandomWorld.gen(acct, world_cfg, seed=seed)

    with cf.ProcessPoolExecutor(cfg.workers) as pool:
        worlds = list(pool.map(gen_world, range(cfg.batch_worlds)))

    t_gen = time.time() - t_gen_start
    print(f"✓ 世界生成: {t_gen:.2f}秒")

    # 转 tensor
    print("转 tensor...")
    t_tensor_start = time.time()
    et = to_tensors(worlds, device)
    t_tensor = time.time() - t_tensor_start
    print(f"✓ 转 tensor: {t_tensor:.2f}秒")

    # 创建模型
    print("创建模型...")
    model = Trader(model_cfg, acct).to(device)
    if cfg.compile_mode:
        print(f"Compiling with mode={cfg.compile_mode}...")
        model = torch.compile(model, mode=cfg.compile_mode)

    env = TorchEnv(et.batch, acct, costs, exact=False,
                   spread_mult=et.spread_mult, impact_mult=et.impact_mult)
    h = model.initial_state(env.B, device=device)

    print(f"✓ 模型创建完成")
    print()

    # 详细 profile 前 10 天
    print("="*70)
    print("详细 Profile（前 10 天）")
    print("="*70)

    from qount.research.etf_trader.train import policy_inputs, construct

    timings = {
        "observe": [],
        "policy_inputs": [],
        "model_forward": [],
        "construct": [],
        "env_step": [],
    }

    for day in range(min(10, env.T - 1)):
        t0 = time.time()
        obs = env.observe()
        t1 = time.time()

        asset, market, acc = policy_inputs(env, et, obs, acct)
        t2 = time.time()

        act, h = model(asset, market, acc, h)
        t3 = time.time()

        target = construct(et.static[:, obs.t, :, :4], et.sigma_c[:, obs.t],
                          et.eligible[:, obs.t], act, acct)
        t4 = time.time()

        env.step(target)
        t5 = time.time()

        timings["observe"].append(t1 - t0)
        timings["policy_inputs"].append(t2 - t1)
        timings["model_forward"].append(t3 - t2)
        timings["construct"].append(t4 - t3)
        timings["env_step"].append(t5 - t4)

        if day < 3:
            total = t5 - t0
            print(f"Day {day}: {total*1000:.2f}ms total")
            print(f"  observe:       {(t1-t0)*1000:.3f}ms")
            print(f"  policy_inputs: {(t2-t1)*1000:.3f}ms")
            print(f"  model_forward: {(t3-t2)*1000:.3f}ms")
            print(f"  construct:     {(t4-t3)*1000:.3f}ms")
            print(f"  env_step:      {(t5-t4)*1000:.3f}ms")

    # 统计（跳过前 2 天编译）
    print()
    print("="*70)
    print("平均时间（Days 2-9，跳过前 2 天编译）")
    print("="*70)

    for key in timings:
        times = timings[key][2:]
        if times:
            avg = sum(times) / len(times) * 1000
            print(f"{key:15s}: {avg:7.3f}ms")

    total_avg = sum(sum(timings[k][2:]) for k in timings) / len(timings["observe"][2:]) * 1000
    print(f"{'总计':15s}: {total_avg:7.3f}ms")

    # 找瓶颈
    print()
    print("="*70)
    print("瓶颈分析")
    print("="*70)

    for key in timings:
        times = timings[key][2:]
        if times:
            avg = sum(times) / len(times) * 1000
            pct = avg / total_avg * 100
            if pct > 25:
                print(f"⚠️  {key}: {avg:.2f}ms (占 {pct:.0f}%) ← 主要瓶颈")
            elif pct > 15:
                print(f"   {key}: {avg:.2f}ms (占 {pct:.0f}%) ← 次要瓶颈")

    print()
    print("结论：")
    print("- 如果 env_step 占主导 → 考虑批量化 env")
    print("- 如果 model_forward 占主导 → 检查编译是否生效")
    print("- 如果 construct 占主导 → 优化约束构建逻辑")
    print("- 如果都差不多 → 已经很平衡，用并行是正确选择")


if __name__ == "__main__":
    profile_detailed()
