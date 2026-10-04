> **状态**：historical snapshot / superseded｜**更新时间**：2026-10-02

> **归档状态**：historical / non-restorable evidence｜**归档日期**：2026-10-02
> **替代入口**：[当前架构与研究结果](../../../p2-project-summary-20261002.md)；运行事实及权限仅看 [current.md](../../../current.md)。
> 保留现存正文用于追溯，旧时点状态、预计完成时间和历史命令不是当前结论或重启授权。
> 下文仅保留 14:12 当时记录，checkpoint 缺失、速度、预计完成时间和状态不得当作现状。
> 最新证据见 [研究主文档](../../../p2-project-summary-20261002.md)，当前事实见 [current.md](../../../current.md)。
> `research_only=true / orders_authorized=false`。

# P2 训练进度更新 - 2026-10-02 14:12

## 云端3090进度

**时间**: 14:12:25 CST  
**运行时长**: ~10分钟（14:02启动）  
**配置**: Stage B - phi32_h16_L2_lr1e-04

### 5个Seeds状态 (Episode 1/100)

所有seeds完成Episode 0-1，性能一致：

| Seed | Episode | 用时(秒) | ann_log_return | p95_max_dd | lambda_dd | KL |
|------|---------|----------|----------------|------------|-----------|-----|
| 20260930 | 1 | 58.0 | 0.05745 | 0.1816 | 0.1229 | 5.18e-06 |
| 20260931 | 1 | 70.8 | 0.06061 | 0.1719 | 0.0561 | 5.72e-06 |
| 20260932 | 1 | 59.2 | 0.05718 | 0.1950 | 0.1427 | 2.33e-06 |
| 20260933 | 1 | 64.2 | 0.05802 | 0.1730 | 0.0632 | 4.30e-06 |
| 20260934 | 1 | 67.9 | 0.05872 | 0.1810 | 0.1624 | 8.74e-06 |

### Episode 0特征

- **首次编译**: 163-167秒世界生成 + 300-330秒rollout
- **总时长**: 466-496秒（~8分钟）
- **初始性能**: ann_log_return 0.057-0.060, max_dd 0.163-0.190

### Episode 1特征 (编译后)

- **世界生成**: 0.01-0.05秒 (缓存命中)
- **Rollout**: 56-68秒
- **总时长**: 58-71秒 (**加速7-8倍**)
- **GPU显存**: 7.9 GB (稳定)
- **GPU利用率**: 0% (当前间隙期)

### 预计完成时间

- **每episode**: ~60秒（编译后）
- **剩余**: 99 episodes × 60秒 = 99分钟
- **预计完成**: ~15:50 (Stage B单个配置)

---

## WSL 4060进度

**时间**: 14:12:18 CST  
**配置**: Stage A - 多配置并行

### phi32_h32_L2 (seed 20260931) - Episode 13/30

```json
{"episode": 13, "updates": 112, "seconds": 181.13,
 "time_gen": 0.01, "time_rollout": 180.55,
 "ann_log_return": 0.06429, "p95_max_dd": 0.1611,
 "lambda_dd": 0.2211, "kl": 0.1203, "grad_norm": 0.01635}
```

**性能趋势**:
- Episode 11: return 0.06197
- Episode 12: return 0.06586 (**峰值**)
- Episode 13: return 0.06429 (回调)
- Max drawdown稳定: 0.161-0.189
- KL散度增长: 0.100 → 0.120 (学习进行中)

### phi32_h64_L1 (seed 20260930) - Episode 13/30

```json
{"episode": 13, "updates": 112, "seconds": 205.46,
 "time_gen": 0.02, "time_rollout": 204.16,
 "ann_log_return": 0.06134, "p95_max_dd": 0.1674,
 "lambda_dd": 0.2520, "kl": 0.08143, "grad_norm": 0.01458}
```

**性能趋势**:
- Episode 11: return 0.06284
- Episode 12: return 0.06345
- Episode 13: return 0.06134 (下降)
- Lambda_dd增长显著: 0.192 → 0.252 (风险惩罚增强)

### 预计完成时间

- **平均episode**: ~200秒
- **剩余**: 17 episodes × 200秒 = 57分钟
- **预计完成**: ~15:10

---

## 性能对比

### 编译加速效果 (3090)

| 阶段 | 世界生成 | Rollout | 总时长 |
|------|----------|---------|--------|
| Episode 0 | 163-167s | 300-330s | 466-496s |
| Episode 1+ | 0.01-0.05s | 56-68s | 58-71s |
| **加速比** | **3300x** | **5x** | **7-8x** |

### WSL vs 3090速度

| 指标 | WSL 4060 (eager) | 3090 (compiled) | 比率 |
|------|------------------|-----------------|------|
| Episode时长 | 180-230s | 56-68s | **3-4x慢** |
| 世界生成 | 0.01-0.02s | 0.01-0.05s | 相近 |
| Rollout | 180-210s | 56-68s | **3x慢** |

**原因**: WSL的torch.compile失败，回退到eager模式，rollout性能显著下降。

---

## 关键问题

### 1. Checkpoint未生成

两端都没有找到checkpoint文件，可能原因：
- Episode数太少（等待10或更多episode）
- 配置未启用checkpoint保存
- 路径问题

### 2. WSL torch.compile失败

```
Warning: torch.compile failed (cannot import name 'SubgraphCPUBenchmarkRequest' 
from 'torch._inductor.autotune_process')
```

导致性能下降3-4倍，需要修复。

### 3. 训练目标不清晰

- CLAUDE.md提到"批次间隙bug修复"和对比训练
- 实际运行的是不同阶段的配置测试
- 需要明确训练目标和实验设计

---

## 下一步监控点

1. **3090 Episode 10** (~16分钟后): 检查是否生成checkpoint
2. **WSL Episode 20** (~30分钟后): 检查收敛趋势
3. **3090完成Stage B** (~100分钟后): 分析5个seeds的结果
4. **WSL完成Stage A** (~60分钟后): 对比4个配置的性能

---

## 资源利用

### 3090
- GPU显存: 7.9 GB / 24 GB (33%, 5并行)
- GPU利用率: 波动 0-60% (间隙期明显)
- Episode间隙: ~10-20秒 (可优化)

### WSL 4060
- CPU: 多个90%+ 进程
- 每episode稳定: 180-230秒
- torch.compile失败影响性能
