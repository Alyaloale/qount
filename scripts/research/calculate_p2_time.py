#!/usr/bin/env python3
"""重新计算 P2 容量搜索的实际时间估算"""

# 基于 WSL RTX 4060 实测数据
seconds_per_update = 3.6  # 256 世界 × 252 步 BPTT

# 训练参数（从 train.py TrainConfig）
years_per_episode = 8.0
segment_days = 252
updates_per_episode = int((years_per_episode * 252) / segment_days)  # 8 段

print("=== 基于实测的时间计算 ===\n")
print(f"每次更新：{seconds_per_update} 秒（256 世界 × 252 步）")
print(f"每个 episode：{years_per_episode} 年 = {updates_per_episode} 个段 = {updates_per_episode} 次更新")
print(f"每个 episode 耗时：{updates_per_episode * seconds_per_update / 60:.1f} 分钟\n")

# Stage A：150 episodes
stage_a_episodes = 150
stage_a_updates = stage_a_episodes * updates_per_episode
stage_a_seconds = stage_a_updates * seconds_per_update
stage_a_hours = stage_a_seconds / 3600

print("Stage A（150 episodes）:")
print(f"  单个配置：{stage_a_hours:.1f} 小时 = {stage_a_hours/24:.2f} 天")
print(f"  16 配置 × 2 种子 = 32 个训练")
print(f"  串行总时间：{stage_a_hours * 32 / 24:.1f} 天")
print(f"  **实际建议**：可以多个配置并行训练\n")

# Stage B：600 episodes
stage_b_episodes = 600
stage_b_updates = stage_b_episodes * updates_per_episode
stage_b_seconds = stage_b_updates * seconds_per_update
stage_b_hours = stage_b_seconds / 3600

print("Stage B（600 episodes，完整训练）:")
print(f"  单个配置：{stage_b_hours:.1f} 小时 = {stage_b_hours/24:.2f} 天")
print(f"  3 结构 × 3 学习率 × 5 种子 = 45 个训练")
print(f"  串行总时间：{stage_b_hours * 45 / 24:.1f} 天\n")

print("=== 优化方案 ===\n")
print("方案 1：减少 episodes")
print(f"  - Stage A 用 50 episodes：{50 * updates_per_episode * seconds_per_update / 3600:.1f} 小时/个")
print(f"  - Stage B 用 200 episodes：{200 * updates_per_episode * seconds_per_update / 3600:.1f} 小时/个")
print(f"  - 验证是否收敛，不收敛再延长\n")

print("方案 2：并行训练")
print(f"  - 如果有多个 GPU 或分时段")
print(f"  - Stage A 可以 2-4 个配置并行")
print(f"  - Stage B 可以 2-3 个配置并行\n")

print("方案 3：先快速验证")
print(f"  - 10 episodes 测试：{10 * updates_per_episode * seconds_per_update / 60:.1f} 分钟")
print(f"  - 验证训练流程正常")
print(f"  - 然后决定完整训练的 episodes 数")
