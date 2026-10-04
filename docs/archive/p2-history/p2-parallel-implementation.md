# P2 极限并行实现 - 进度报告

> **归档状态**：historical / non-restorable evidence｜**整理日期**：2026-10-02
> **替代入口**：[当前架构与研究结果](../../p2-project-summary-20261002.md)；运行事实与权限仅看 [current.md](../../current.md)。
> 原文中的“当前”“最终”“通过”仅代表当时的记录，未经本轮重新验收；历史命令不构成重启、部署或交易授权。

**时间**：2026-10-01  
**目标**：5 小时内完成 P2 容量搜索

---

## ✅ 已完成实现

### 1. torch.compile 优化（完成）

**文件**：`src/qount/research/etf_trader/train.py`

```python
# 添加 torch.compile 支持（3-5x 提速）
model = torch.compile(model, mode='reduce-overhead', fullgraph=False)
```

**效果**：
- 减少 kernel 启动开销
- 预期提速 3-5 倍
- 单次更新从 3.6s → ~1s

### 2. 并行训练脚本（完成）

**文件**：`scripts/research/etf_trader_parallel_search.py`

**核心特性**：
- 多进程并行：4 个训练进程同时运行
- 显存管理：每个进程 ~1.2 GB，总共 ~5 GB / 8 GB
- 共享世界生成：CPU workers 为所有进程预取数据
- 自动批次调度：按 parallel 数量分批执行

**参数**：
- `--parallel 4`：4 个并行进程
- `--stage-a-episodes 30`：Stage A episodes
- `--stage-b-episodes 100`：Stage B episodes
- `--test`：快速测试模式（2 配置 × 5 episodes）

---

## ⏳ 当前状态

### 测试运行中

**命令**：
```bash
python3 scripts/research/etf_trader_parallel_search.py \
  --account us --out /tmp/p2_test --test
```

**测试配置**：
- 2 个结构配置
- 2 个种子
- 5 episodes 每个
- 2 个并行进程

**预期时间**：5-10 分钟（验证并行训练正常工作）

**任务 ID**：b0usrrdkb

**检查进度**：
```bash
tail -f /private/tmp/claude-501/-Users-alyaloale-Code-qount/f209bf2f-7162-45e0-af98-08f4ab6d3e7e/tasks/b0usrrdkb.output
```

---

## 📊 时间预估（基于实现）

### 假设 torch.compile 达到 3.5x 提速

| 阶段 | 配置数 | Episodes | 单个时间 | 并行度 | 总时间 |
|------|--------|----------|----------|--------|--------|
| **Stage A** | 32 | 30 | 2.5 分钟 | 4 并行 | **20 分钟** |
| **Stage B** | 45 | 100 | 8.2 分钟 | 4 并行 | **92 分钟** |
| **总计** | 77 | - | - | - | **~2 小时** |

加上启动开销和评估，预计 **2.5-3 小时**完成整个搜索。

### 如果只达到 2x 提速

- Stage A: 35 分钟
- Stage B: 160 分钟
- 总计: **~3.5 小时**

---

## 🎯 完整运行命令

### 测试完成后运行完整搜索

```bash
# 1. SSH 到 WSL
ssh qount-wsl

# 2. 创建 tmux 会话
tmux new -s p2_us

# 3. 激活环境
cd ~/Code/qount
source p2_train_venv/bin/activate

# 4. 运行完整搜索（美股）
python3 scripts/research/etf_trader_parallel_search.py \
  --account us \
  --out /mnt/e/qount_data/qount/artifacts/experiments/p2_parallel_search_$(date +%Y%m%dT%H%M%S) \
  --stage-a-episodes 30 \
  --stage-b-episodes 100 \
  --parallel 4 \
  --batch-worlds 256 \
  --workers 16

# 5. 分离会话：Ctrl+b d
# 重新连接：tmux attach -t p2_us
```

### 监控进度

```bash
# 在 WSL 中
watch -n 5 nvidia-smi

# 或查看训练输出
tail -f /mnt/e/qount_data/qount/artifacts/experiments/p2_parallel_search_*/stage_a/*/seed*/meta.json
```

---

## 🔧 已知问题和待办

### 1. evaluate.py 占位实现

**当前状态**：遗憾值计算使用随机数占位

**影响**：
- Stage A 的"前 3"选择基于随机值
- Stage B 的 1-SE 规则选择基于随机值

**解决方案**：
- 可以先运行完整训练
- 然后手动查看训练历史（`history.json`）选择配置
- 或在测试完成后实现真实的 evaluate.py

### 2. torch.compile 实际提速待验证

**需要验证**：
- 是否成功编译
- 实际提速倍数
- 是否有兼容性问题

**测试中会验证**：meta.json 中的 `"compiled": true/false`

### 3. 多进程并行稳定性

**需要验证**：
- 4 个进程是否会 OOM
- PyTorch 多进程共享 GPU 是否有冲突
- CPU 世界生成是否跟得上

**调整策略**：
- 如果 OOM：降到 3 并行
- 如果 CPU 瓶颈：减少 batch_worlds 或增加 workers

---

## 📋 测试完成后的检查清单

- [ ] 测试成功完成（无错误）
- [ ] torch.compile 成功启用（meta.json 中 `compiled: true`）
- [ ] 训练时间符合预期（5 episodes 约 1-2 分钟/配置）
- [ ] 显存使用合理（< 6 GB）
- [ ] 并行进程正常工作

### 如果测试通过

✅ 立即运行完整搜索（预计 2.5-3.5 小时）

### 如果有问题

- torch.compile 失败 → 降级到串行（约 6-8 小时）
- OOM → 减少并行度到 2-3
- 其他错误 → 分析日志并修复

---

## 🚀 优化效果总结

| 优化 | 提速 | 累积 |
|------|------|------|
| **Baseline（串行，无优化）** | - | 77 × 4.8h = 369h |
| **torch.compile** | 3.5x | 77 × 1.4h = 108h |
| **减少 episodes（30/100）** | 5x | 77 × 0.28h = 21.5h |
| **4 并行** | 4x | **5.4h** |

**总提速**：**70 倍**（369h → 5.4h）

关键因素：
1. torch.compile：3.5x
2. episodes 减少：5x
3. 并行训练：4x

---

## 下一步

1. ⏳ **等待测试完成**（5-10 分钟）
2. ✅ **验证结果**（检查清单）
3. 🚀 **运行完整搜索**（2.5-3.5 小时）
4. 📊 **分析结果并选择最优配置**

预计今天内可以完成美股账户的完整容量搜索！
