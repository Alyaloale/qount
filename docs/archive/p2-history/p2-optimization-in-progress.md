# P2 优化进行中

> **归档状态**：historical / non-restorable evidence｜**整理日期**：2026-10-02
> **替代入口**：[当前架构与研究结果](../../p2-project-summary-20261002.md)；运行事实与权限仅看 [current.md](../../current.md)。
> 原文中的“当前”“最终”“通过”仅代表当时的记录，未经本轮重新验收；历史命令不构成重启、部署或交易授权。

## 正在测试的优化

### 1. torch.compile 模式对比 ⏳

**测试中的配置**（7种，每种 5 episodes）：

1. **baseline** - 当前配置
   - compile_mode: reduce-overhead
   - batch_worlds: 256, workers: 8

2. **max-autotune** - 更激进的自动调优
   - compile_mode: max-autotune
   - 自动搜索最优 Triton kernel
   - 预期：可能 1.2-1.5x 加速

3. **default-compile** - 默认模式
   - compile_mode: default
   
4. **workers-12/16** - 测试更多 workers
   - 验证世界生成瓶颈

5. **batch-384/512** - 测试更大 batch
   - 验证 GPU 利用率

**预计完成时间**：40-60 分钟
**测试脚本**：`scripts/research/test_optimizations.py`

### 2. 代码优化（准备中）

**待优化点**：

#### A. 减少 list append + torch.stack

**当前代码** (`train.py:176-193`):
```python
rets, kls, used, eqs = [], [], [], []
for _ in range(days):
    # ... 计算 ...
    rets.append(out["ret"])
    eqs.append(out["equity"])
    kls.append(kl_to_prior(...))
    used.append(env.used_voluntary / env.U)

return {"ret": torch.stack(rets, 1), ...}
```

**优化方案**：
```python
# 预分配 tensor
rets = torch.zeros((batch, days), device=device)
for i in range(days):
    # ... 计算 ...
    rets[:, i] = out["ret"]
```

**预期加速**：5-10% （减少内存分配）

#### B. 批量化约束检查

**当前**：每步单独检查约束
**优化**：累积多步后批量检查

#### C. 减少 Python scalar 转换

检查代码中的 `.item()` 调用，尽量保持 tensor 操作

### 3. 世界生成优化（研究中）

**方案 A：多配置共享世界**
- 实现复杂度：高
- 需要重构训练流程
- 暂缓

**方案 B：增加并行数**
- 实现复杂度：低
- 立即可用
- 已验证有效（并行效率 70%）

## 优化测试结果（待更新）

测试完成后将更新以下数据：

| 配置 | 每次 update | vs baseline | 推荐 |
|------|------------|-------------|------|
| baseline | ?秒 | 1.0x | |
| max-autotune | ?秒 | ?x | |
| workers-12 | ?秒 | ?x | |
| batch-512 | ?秒 | ?x | |

## 下一步

等待测试完成后：
1. 分析最优配置
2. 如果 max-autotune 有效 → 更新训练脚本
3. 如果效果不明显 → 直接用 12-16 并行开始训练

## 实时监控

```bash
# 查看测试进度
ssh root@connect.nmb2.seetacloud.com "tail -f /root/autodl-tmp/experiments/opt_comparison.log"

# 查看 GPU 使用
ssh root@connect.nmb2.seetacloud.com "nvidia-smi"
```
