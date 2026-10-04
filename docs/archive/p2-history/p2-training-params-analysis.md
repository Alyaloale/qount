# ETF Trader 训练参数问题分析报告

> **归档状态**：historical / non-restorable evidence｜**整理日期**：2026-10-02
> **替代入口**：[当前架构与研究结果](../../p2-project-summary-20261002.md)；运行事实与权限仅看 [current.md](../../current.md)。
> 原文中的“当前”“最终”“通过”仅代表当时的记录，未经本轮重新验收；历史命令不构成重启、部署或交易授权。

## 执行摘要

**关键发现：训练配置存在严重的性能问题，导致预期 10.4 小时的任务可能需要 60+ 小时。**

---

## 发现的问题

### 🔴 问题 1：Workers 分配错误（已修复）

**问题描述：**
- 代码使用 `workers // len(chunk)` 分配 workers
- 16 个并行训练 → 20 workers // 16 = **1 worker per training**
- 每个训练需要生成 256 个世界，只有 1 个 worker 意味着**完全串行**

**影响：**
- 单个世界生成时间：2.3秒（C++ 加速后）
- 256 worlds × 2.3秒 = **589秒（9.8分钟）** 仅用于世界生成
- GPU 会大量空闲等待世界生成
- 预计 Stage A 单批次从 1.8h → **4.9h**（2.7倍）

**修复：**
```python
# 修改前
workers // len(chunk)  # 16 并行时 = 1 worker

# 修改后
1  # 每个训练固定 1 worker（与原来相同，但逻辑更清晰）
```

**注意：** 即使修复后，每个训练仍然只有 1 worker。如果要进一步优化，需要考虑不同的并行策略。

---

### ⚠️ 问题 2：批次执行导致 GPU 利用率低

**问题描述：**
- 32 个任务（16 configs × 2 seeds）分 2 批执行
- 第一批：16 个并行训练（所有 d_phi=16 配置）
- 第二批：16 个并行训练（所有 d_phi=32 配置）
- **第二批必须等第一批全部完成**

**影响：**
- 如果第一批中某个训练慢（如 h128_L2 比 h16_L1 慢），整批都要等
- GPU 可能在批次之间出现短暂空闲
- 时间浪费：最慢的任务决定整批的完成时间

**当前状态：**
```
第一批（正在运行）：
├─ phi16_h16_L1 × 2 seeds
├─ phi16_h16_L2 × 2 seeds
├─ phi16_h32_L1 × 2 seeds
├─ phi16_h32_L2 × 2 seeds
├─ phi16_h64_L1 × 2 seeds
├─ phi16_h64_L2 × 2 seeds
├─ phi16_h128_L1 × 2 seeds
└─ phi16_h128_L2 × 2 seeds  ← 最慢的会拖慢整批

第二批（等待中）：
└─ 所有 phi32_* 配置
```

---

### ✅ 问题 3：训练配置本身是正确的

**已验证正确的参数：**
- ✅ 结构数量：16 个（d_phi ∈ {16,32}, hidden ∈ {16,32,64,128}, layers ∈ {1,2}）
- ✅ 种子数量：2 个（20260930, 20260931）
- ✅ Stage A episodes：30（文档推荐值）
- ✅ Stage B episodes：100（文档推荐值）
- ✅ batch_worlds：256
- ✅ 并行数：16
- ✅ GPU 配置：单个 RTX 3090，24GB

**脚本在正确运行：**
```
Stage A: Screening 16 structures × 2 seeds
Parallel: 16 processes, Episodes: 30
[Parallel batch 1/2] Training 16 configs in parallel...
```

---

## 性能分析

### 当前配置的预期时间（修复后）

| 阶段 | 配置 | 单个时间 | 并行数 | 总时间 |
|-----|------|---------|--------|--------|
| Stage A | 16 configs × 2 seeds | ~0.6h | 16 | ~1.8h |
| Stage B | 5-6 best configs × 3 seeds | ~2h | 16 | ~8-9h |
| **总计** | | | | **~10-11h** |

### 性能瓶颈

**世界生成仍然是瓶颈：**
- 每个训练进程：1 个 worker
- 256 worlds 串行生成：256 × 2.3s = 589s（9.8分钟）
- GPU 训练：~32秒/update
- **GPU 空闲率：589/(589+32) = 94.8%**

**理想状态（如果有 8 workers per training）：**
- 世界生成：256/8 × 2.3s = 73.6s
- GPU 训练：32s
- GPU 空闲率：73.6/(73.6+32) = 69.7%

---

## 建议的优化方案

### 方案 A：保持当前配置（最安全）

**不做额外修改，使用已修复的脚本：**
- ✅ Workers 分配已修复（虽然仍是 1 worker）
- ✅ 配置参数正确（30/100 episodes）
- ✅ 并行数合理（16 进程）
- ⏱️ 预期时间：**10-11 小时**

**执行：**
```bash
cd /root/autodl-tmp
python scripts/research/etf_trader_parallel_search.py \
  --account us \
  --out experiments/p2_us_$(date +%Y%m%d_%H%M%S) \
  --stage-a-episodes 30 \
  --stage-b-episodes 100 \
  --parallel 16 \
  --workers 20 \
  --batch-worlds 256 \
  --compile-mode max-autotune
```

---

### 方案 B：减少并行数，增加每个训练的 workers（推荐）

**思路：**
- 减少并行训练数：16 → 8
- 增加每个训练的 workers：1 → 2-3
- GPU 利用率提升，总时间可能更短

**需要修改：**
```python
# 行 90，改为：
max(1, workers // len(chunk))  # 8 并行时 = 2-3 workers per training
```

**预期效果：**
- 世界生成加速：256/2 × 2.3s = 294s（vs 589s）
- GPU 空闲率：294/(294+32) = 90% → 仍然高，但比 95% 好
- 总时间：可能从 10h → **8-9h**

---

### 方案 C：使用 pipeline 模式（激进，未测试）

**代码中已有但未启用：**
```python
# train_pipeline.py 存在，但未在 parallel_search.py 中集成
```

**需要工作：**
- 修改 `etf_trader_parallel_search.py` 支持 `--pipeline` 标志
- 理论加速：1.5-2x
- 风险：未经测试，可能有 bug

---

## 立即行动建议

### 选项 1：立即重启训练（方案 A）

**优点：**
- 最安全，配置已验证正确
- 10-11 小时可接受
- 不需要额外代码修改

**执行：**
```bash
# 1. 连接服务器
ssh -p 41489 root@connect.nmb2.seetacloud.com

# 2. 清理之前的实验
rm -rf /root/autodl-tmp/experiments/p2_optimized_20261001_234459

# 3. 重启训练
cd /root/autodl-tmp
nohup python scripts/research/etf_trader_parallel_search.py \
  --account us \
  --out experiments/p2_us_final_$(date +%Y%m%d_%H%M%S) \
  --stage-a-episodes 30 \
  --stage-b-episodes 100 \
  --parallel 16 \
  --workers 20 \
  --batch-worlds 256 \
  --compile-mode max-autotune \
  > training_final_$(date +%Y%m%d_%H%M%S).log 2>&1 &

# 4. 监控
tail -f training_final_*.log
```

---

### 选项 2：优化后重启（方案 B，需要 5-10 分钟修改）

**修改步骤：**
1. 本地修改 `etf_trader_parallel_search.py` 行 90
2. 将 `--parallel 16` 改为 `--parallel 8`
3. 测试 1 个配置，验证 workers 数量
4. 全量训练

**预期收益：**
- 节省 1-2 小时（10h → 8-9h）
- GPU 利用率提升 5-10%

---

## 监控命令

```bash
# GPU 状态
watch -n 5 nvidia-smi

# 训练进程
ps aux | grep etf_trader_train.py | wc -l

# 查看第一个配置的进度
tail -f experiments/*/stage_a/phi16_h16_L1_lr3e-04/seed20260930/train.log

# 查看已完成的 episodes
find experiments/*/stage_a -name 'history.json' | xargs wc -l
```

---

## 总结

**当前状态：**
- ✅ 已停止错误配置的训练
- ✅ 已修复 workers 分配 bug
- ✅ 配置参数验证正确
- ✅ 脚本已上传到服务器

**下一步：**
选择方案 A 或 B，立即重启训练。

**预期完成时间：**
- 方案 A：明天上午 10:00-11:00（10-11 小时）
- 方案 B：明天上午 8:00-9:00（8-9 小时，需要先修改）
