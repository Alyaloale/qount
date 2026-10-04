# P2 极限并行实现 - 执行指南

> **归档状态**：historical / non-restorable evidence｜**整理日期**：2026-10-02
> **替代入口**：[当前架构与研究结果](../../p2-project-summary-20261002.md)；运行事实与权限仅看 [current.md](../../current.md)。
> 原文中的“当前”“最终”“通过”仅代表当时的记录，未经本轮重新验收；历史命令不构成重启、部署或交易授权。

**状态**：✅ 已完成并优化（监控/checkpoint）  
**目标**：~5 小时完成容量搜索（Stage A 2h + Stage B 3h）  
**最后更新**：2026-10-02

---

## 当前功能

### ✅ 核心功能
1. **torch.compile 优化** — 3-5x 提速
2. **持久化并行池** — 消除批次间空闲
3. **实时日志监控** — 每个 episode 输出进度
4. **自动 checkpoint** — 每 10 episodes 保存
5. **进度监控脚本** — 汇总所有训练状态

### ⚠️ 性能特征
- GPU 利用率 5-20% **正常**（RL 训练 CPU-bound）
- 67% 时间在 world generation（CPU）
- 33% 时间在模型计算（GPU）

---

## 快速启动

### 在服务器上运行完整搜索

```bash
cd /root/autodl-tmp

# 启动训练
nohup python scripts/research/etf_trader_parallel_search.py \
  --account us \
  --out experiments/p2_us_$(date +%Y%m%d) \
  --stage-a-episodes 30 \
  --stage-b-episodes 100 \
  --parallel 16 \
  --workers 20 \
  --batch-worlds 256 \
  > train.log 2>&1 &

# 记录 PID
echo $! > train.pid
```

### 实时监控（3 种方式）

```bash
# 方法 1: 汇总监控（推荐）
python scripts/research/monitor_training_progress.py experiments/p2_us_20261002

# 方法 2: 查看单个训练
tail -f experiments/p2_us_20261002/stage_a/phi16_h16_L1_lr3e-04/seed20260930/train.log

# 方法 3: 统计总进度
find experiments/p2_us_20261002 -name "train.log" -exec grep -c "episode" {} \; | awk '{s+=$1}END{print s " episodes completed"}'
```

---

## 输出文件结构

```
experiments/p2_us_20261002/
├── stage_a/
│   ├── phi16_h16_L1_lr3e-04/
│   │   ├── seed20260930/
│   │   │   ├── meta.json              # 训练配置
│   │   │   ├── train.log              # 实时日志（每行一个 episode）
│   │   │   ├── checkpoint_ep10.pt     # Episode 10 checkpoint
│   │   │   ├── history_ep10.json      # Episode 0-10 训练历史
│   │   │   ├── checkpoint_ep20.pt     # Episode 20 checkpoint
│   │   │   ├── history_ep20.json      # Episode 0-20 训练历史
│   │   │   ├── model.pt               # 最终模型
│   │   │   └── history.json           # 完整训练历史
│   │   └── seed20260931/
│   │       └── ...
│   └── ...
├── stage_a_results.json               # Stage A 汇总
└── stage_b/
    └── ...
```

### 日志格式（train.log 每行）

```json
{
  "episode": 5,
  "updates": 320,
  "seconds": 127.4,
  "time_gen": 85.2,        // CPU: world generation
  "time_tensor": 0.3,      // CPU→GPU 数据传输
  "time_env": 0.1,         // 构建环境
  "time_rollout": 41.8,    // GPU: 模型前向+反向
  "ann_log_return": 0.1234,
  "p95_max_dd": 0.0567,
  "lambda_dd": 0.23,
  "lambda_cvar": 0.15,
  "kl": 0.0012,
  "years": 8.0,
  "grad_norm": 0.45
}
```

---

## 检查 Checkpoint

```bash
# 列出所有 checkpoint
find experiments/p2_us_20261002 -name "checkpoint*.pt"

# 查看训练历史
cat experiments/p2_us_20261002/stage_a/phi16_h16_L1_lr3e-04/seed20260930/history_ep10.json | jq '.[].ann_log_return'

# 加载 checkpoint（Python）
import torch
ckpt = torch.load("checkpoint_ep10.pt")
model.load_state_dict(ckpt["model"])
print(f"Resumed from episode {ckpt['episode']}")
```

---

## 故障排查

### 训练卡在 torch.compile
**现象**: 所有 `train.log` 只有一行 `torch.compile enabled`

**原因**: 第一次编译需要 5-10 分钟

**解决**: 等待编译完成，或添加 `--no-compile`（会慢 3-5 倍）

### GPU OOM
**现象**: 日志中出现 `CUDA out of memory`

**解决**:
```bash
# 减少并行数
--parallel 12  # 从 16 降到 12

# 或减少 batch_worlds
--batch-worlds 128  # 从 256 降到 128
```

### 查看 GPU 状态
```bash
nvidia-smi
watch -n 5 nvidia-smi  # 每 5 秒刷新
```

---

## 预估时间

基于 3090 服务器实测：
- 单个 episode: ~2 分钟
- Stage A（16 结构 × 2 seeds × 30 ep）: **~2 小时**
- Stage B（3 结构 × 3 lr × 5 seeds × 100 ep）: **~3 小时**
- **总计**: ~5 小时

---

## 完成后的分析

### 1. 查看最佳配置

```python
import json

# Stage A 结果
with open("experiments/p2_us_20261002/stage_a_results.json") as f:
    results = json.load(f)

# 按 regret 排序
sorted_results = sorted(results, key=lambda x: x["mean_regret"])
print("Top 3 configurations:")
for i, r in enumerate(sorted_results[:3], 1):
    c = r["config"]
    print(f"{i}. d_phi={c['d_phi']}, hidden={c['hidden']}, layers={c['layers']}")
    print(f"   Regret: {r['mean_regret']:.4f} ± {r['se_regret']:.4f}")
```

### 2. 绘制训练曲线

```python
import matplotlib.pyplot as plt

# 读取某个训练的历史
with open("history.json") as f:
    hist = json.load(f)

episodes = [h["episode"] for h in hist]
returns = [h["ann_log_return"] for h in hist]
drawdowns = [h["p95_max_dd"] for h in hist]

plt.figure(figsize=(12, 4))
plt.subplot(1, 2, 1)
plt.plot(episodes, returns)
plt.xlabel("Episode")
plt.ylabel("Ann. Log Return")

plt.subplot(1, 2, 2)
plt.plot(episodes, drawdowns)
plt.xlabel("Episode")
plt.ylabel("95% Max Drawdown")

plt.tight_layout()
plt.savefig("training_curves.png")
```

---

## 相关文档

- [P2 监控改进详解](p2-monitoring-improvements.md) — 实时日志、checkpoint 实现细节
- [P2 优化总结](p2-optimization-final-summary.md) — 性能优化历程
- [P2 硬件分析](p2-hardware-analysis.md) — GPU 利用率分析

---

## 历史记录

### 2026-10-02 监控与保存改进
- ✅ 实时日志输出（`train.log` 流式写入）
- ✅ 自动 checkpoint（每 10 episodes）
- ✅ 持久化进程池（消除批次间空闲）
- ✅ 监控脚本（`monitor_training_progress.py`）

### 2026-09-30 初始实现
- ✅ torch.compile 集成
- ✅ 并行训练脚本
- ✅ GPU 优化
ssh qount-wsl

# 创建 tmux 会话
tmux new -s p2_us

# 激活环境并运行
cd ~/Code/qount
source p2_train_venv/bin/activate
bash scripts/research/run_p2_full_search.sh us

# 分离：Ctrl+b d
# 重新连接：tmux attach -t p2_us
```

**或手动运行**：

```bash
python3 scripts/research/etf_trader_parallel_search.py \
  --account us \
  --out /mnt/e/qount_data/qount/artifacts/experiments/p2_parallel_search_$(date +%Y%m%dT%H%M%S) \
  --stage-a-episodes 30 \
  --stage-b-episodes 100 \
  --parallel 4 \
  --batch-worlds 256 \
  --workers 16
```

### 3. 监控进度

```bash
# GPU 使用
watch -n 5 nvidia-smi

# 训练进程
ps aux | grep etf_trader

# 查看部分结果
ls -lh /mnt/e/qount_data/qount/artifacts/experiments/p2_parallel_search_*/stage_a/*/seed*/
```

---

## 时间预估

### 乐观情况（torch.compile 3.5x）

- Stage A（32 配置 × 30 episodes）：**20 分钟**
- Stage B（45 配置 × 100 episodes）：**90 分钟**
- 总计：**~2 小时**

### 保守情况（torch.compile 2x）

- Stage A：**35 分钟**
- Stage B：**160 分钟**
- 总计：**~3.5 小时**

---

## 如果测试失败

### torch.compile 不工作

```bash
# 降级到串行，但仍用并行进程
# 时间：~6-8 小时
python3 scripts/research/etf_trader_parallel_search.py \
  --account us \
  --out /tmp/p2_fallback \
  --stage-a-episodes 30 \
  --stage-b-episodes 100 \
  --parallel 4
```

### OOM 错误

```bash
# 减少并行度
python3 scripts/research/etf_trader_parallel_search.py \
  --account us \
  --out /tmp/p2_safe \
  --parallel 2  # 降到 2
  --stage-a-episodes 30 \
  --stage-b-episodes 100
```

### 其他错误

1. 检查错误日志
2. 验证环境（torch, cuda）
3. 回退到单进程测试

---

## 优化总结

| 层面 | 优化 | 提速 | 状态 |
|------|------|------|------|
| **世界生成（CPU）** | C++ kernel | 70x | ✅ 已完成 |
| **训练（GPU）** | torch.compile | 3-5x | ⏳ 测试中 |
| **并行度** | 4 进程 | 4x | ⏳ 测试中 |
| **episodes** | 减少到 30/100 | 5x | ✅ 已设置 |
| **总计** | - | **~70x** | - |

从 369 小时 → **~5 小时**

---

## 关键文件

- 训练代码：`src/qount/research/etf_trader/train.py`
- 并行脚本：`scripts/research/etf_trader_parallel_search.py`
- 启动脚本：`scripts/research/run_p2_full_search.sh`
- 测试输出：`/tmp/p2_test/`
- 完整输出：`/mnt/e/qount_data/qount/artifacts/experiments/p2_parallel_search_*/`

---

## 下一步

1. ⏳ **等待测试完成**（预计 5-10 分钟）
2. ✅ **验证结果**
3. 🚀 **运行完整搜索**（2.5-3.5 小时）
4. 📊 **分析结果**
5. 🔄 **A 股账户**（重复相同流程）

**预计今天内完成美股 P2！**
