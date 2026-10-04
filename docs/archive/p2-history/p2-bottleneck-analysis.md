# P2 性能瓶颈深度分析

> **归档状态**：historical / non-restorable evidence｜**整理日期**：2026-10-02
> **替代入口**：[当前架构与研究结果](../../p2-project-summary-20261002.md)；运行事实与权限仅看 [current.md](../../current.md)。
> 原文中的“当前”“最终”“通过”仅代表当时的记录，未经本轮重新验收；历史命令不构成重启、部署或交易授权。

## 🎯 核心发现

**文档的"5小时完成搜索"需要三个条件同时满足：**

1. ✅ **并行训练**：4-5 个进程
2. ❌ **torch.compile 3x 加速**：实际只有 1.1x
3. ❌ **世界生成完全隐藏**：实际生成(40s) > 训练(32s)

## 1. torch.compile 加速不足

### 文档预期
- 单次 update：3.6秒（无 compile）
- compile 后：**1.2秒**（3x 加速）

### 我们实测
- Episode 0 rollout：153秒（152 updates = 19.1秒/update）❌ 首次编译慢
- Episode 2+ rollout：32秒（8 updates = **4秒/update**）
- **实际加速：3.6秒 → 4秒 = 0.9x**（反而慢了！）

### 问题原因

**我们的 compile 配置**：
```python
model = torch.compile(model, mode='reduce-overhead', fullgraph=False)
```

**文档建议的优化**：
- CUDA Graphs
- torch.func.vmap 打包多个种子
- 合并小 kernel

**我们缺少的**：
- ❌ 没有 CUDA Graphs
- ❌ 没有 vmap 打包
- ❌ 真实 env "每步有约一百多个小 kernel"（文档原话）

## 2. 世界生成未能完全隐藏

### 理想状态
- 世界生成时间 ≤ GPU 训练时间
- prefetch 完全重叠

### 实际状态
- 世界生成：40秒（256 worlds，8 workers）
- GPU 训练：32秒（8 updates × 4秒）
- **瓶颈：生成比训练慢 8秒**

### 问题原因
- 单世界生成：2.3秒（C++ 已加速）
- 这是固有成本（18年数据 + 复杂生成器）
- workers 增加也无法突破物理极限

## 3. episodes 配置差异

### 文档建议（并行脚本默认）
- Stage A: **30 episodes**
- Stage B: **100 episodes**

### 我们使用
- Stage A: **150 episodes**（5倍）
- Stage B: **600 episodes**（6倍）

### 影响
- 单个配置时间：5-6倍
- 但训练质量更好

## 完整对比表

| 项目 | 文档目标 | 我们实际 | 差距 |
|------|----------|----------|------|
| **Stage A episodes** | 30 | 150 | 5x |
| **Stage B episodes** | 100 | 600 | 6x |
| **单次 update时间** | 1.2s（compile后） | 4s | 3.3x |
| **世界生成** | <训练时间 | >训练时间 | +25% |
| **并行进程** | 4-5 | 2-12可选 | ✓ |

## 时间估算（最终版）

### 使用文档配置（30/100 episodes）+ 8 并行

**Stage A**（32 configs）：
- 单配置：30 ep × (8 updates × 4s + 40s gen) / 3600 = 0.6h
- 总时间：32 × 0.6h ÷ 8 = **2.4h**

**Stage B**（45 configs）：
- 单配置：100 ep × (8 updates × 4s + 40s gen) / 3600 = 1.9h
- 总时间：45 × 1.9h ÷ 8 = **10.7h**

**总计：13.1小时**（vs 文档的 5小时）

### 使用我们的配置（150/600 episodes）+ 8 并行

**Stage A**（32 configs）：
- 单配置：3h
- 总时间：32 × 3h ÷ 8 = **12h**

**Stage B**（45 configs）：
- 单配置：12h
- 总时间：45 × 12h ÷ 8 = **67.5h**

**总计：79.5小时 ≈ 3.3天**

## 🚀 优化建议

### 立即可行
1. **减少 episodes**：
   - Stage A: 150 → 50（仍是文档的 1.7倍）
   - Stage B: 600 → 200（仍是文档的 2倍）
   - **节省时间：70%**

2. **增加并行数**：
   - 从 8 → 12 进程
   - **节省时间：33%**

### 中期优化
3. **实现 CUDA Graphs**：
   - 目标：3x 加速
   - 需要代码改动

4. **优化世界生成**：
   - 多配置共享世界
   - 减少重复生成

## 推荐方案

**方案 A：快速验证（使用文档配置）**
```bash
python scripts/research/etf_trader_parallel_search.py \
  --account us \
  --out experiments/p2_quick \
  --stage-a-episodes 30 \
  --stage-b-episodes 100 \
  --parallel 12 \
  --workers 20

# 预计：8-10 小时完成
```

**方案 B：高质量训练（减少但不极端）**
```bash
# Stage A
python scripts/research/etf_trader_parallel_search.py \
  --account us \
  --out experiments/p2_balanced \
  --stage-a-episodes 50 \
  --parallel 12 \
  --workers 20 \
  --stage a

# Stage B（使用 Stage A 选出的 top-3）
python scripts/research/etf_trader_parallel_search.py \
  --account us \
  --out experiments/p2_balanced \
  --stage-b-episodes 200 \
  --parallel 12 \
  --workers 20 \
  --stage b

# 预计：4h + 17h = 21 小时完成
```

**方案 C：原计划（高质量但慢）**
- 150/600 episodes
- 12 并行
- **预计：53 小时 ≈ 2.2天**

## 结论

文档的"5小时"是基于：
- 30/100 episodes（更少）
- torch.compile 3x加速（我们没达到）
- 完美的 prefetch（我们有瓶颈）

**实际可达到的时间**：
- 快速验证：**8-10 小时**（30/100 episodes）
- 平衡方案：**21 小时**（50/200 episodes）
- 高质量：**2.2天**（150/600 episodes）

建议先跑快速验证（方案A），验证整个流程，然后根据结果决定是否需要更多 episodes。
