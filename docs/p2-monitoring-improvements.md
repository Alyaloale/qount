# P2 训练监控与保存改进

**日期**: 2026-10-02  
**状态**: ✅ 已实施  
**目标**: 解决训练过程无进度显示、无中间保存的问题

## 背景问题

### 原始问题
1. **GPU 间断执行** — 监控显示 GPU 利用率周期性归零（每 15-20 分钟）
2. **无进度显示** — 训练过程中看不到任何输出，不知道进度和性能
3. **无中间保存** — 训练只在完全结束时保存，中途中断会丢失所有结果
4. **无法评估性能** — 看不到 loss、收益、回撤等指标

### 根本原因分析

#### 1. GPU 间断执行
**原因**: 批次化训练设计
```python
# 原始代码 (scripts/research/etf_trader_parallel_search.py:71-111)
for i in range(0, len(configs), parallel):
    chunk = configs[i:i+parallel]
    with mp.Pool(processes=len(chunk)) as pool:
        # 训练这批
        for task in tasks:
            result = task.get()  # 等待全部完成
    # Pool 销毁并重建 ← 批次间空闲
```

**问题**:
- 每批训练完成后销毁并重建进程池 → 15-20 分钟空闲
- 批内等待最慢任务 → 部分 GPU 空闲

#### 2. 无进度显示
**原因**: subprocess 输出缓存
```python
# 原始代码 (scripts/research/etf_trader_parallel_search.py:63)
res = subprocess.run(cmd, capture_output=True, text=True, check=True, ...)
result = json.loads(res.stdout.strip().splitlines()[-1])
```

**问题**:
- `capture_output=True` 缓存所有输出直到训练完成
- 30 episodes × ~2 分钟 = ~60 分钟内看不到任何输出

#### 3. 无中间保存
**原因**: 训练脚本只在结束时保存
```python
# 原始代码 (src/qount/research/etf_trader/train.py:310)
torch.save({"model": model.state_dict(), ...}, out_dir / "model.pt")
```

**问题**:
- 训练中断（服务器重启、OOM、网络断开）会丢失所有进度
- 无法提前评估模型性能

## 解决方案

### 1. 持久化进程池（消除批次间空闲）

**改进**: 使用 `ProcessPoolExecutor` + `as_completed`

```python
# 新代码 (scripts/research/etf_trader_parallel_search.py:71-112)
def train_batch_parallel(configs, ...):
    from concurrent.futures import ProcessPoolExecutor, as_completed
    
    # 单个持久化进程池
    with ProcessPoolExecutor(max_workers=parallel) as executor:
        # 一次性提交所有任务
        future_to_config = {}
        for cfg, seed in configs:
            future = executor.submit(run_train, ...)
            future_to_config[future] = (cfg, seed)

        # 任务完成一个处理一个（无批次等待）
        completed = 0
        for future in as_completed(future_to_config):
            cfg, seed = future_to_config[future]
            completed += 1
            result = future.result()
            print(f"[{completed}/{total}] ✓ {cfg.key} ...")
```

**效果**:
- ✅ 消除批次间进程池重建开销
- ✅ 任务完成一个立即启动下一个
- ✅ GPU 持续饱和（但 RL 训练本身 GPU 利用率低是正常的）

### 2. 实时日志输出

**改进**: 使用 `Popen` 流式写入日志

```python
# 新代码 (scripts/research/etf_trader_parallel_search.py:48-88)
def run_train(cfg, account, out, ...):
    # 实时日志文件
    log_file = out / "train.log"
    out.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    with open(log_file, "w") as f:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, 
                               stderr=subprocess.STDOUT, text=True, bufsize=1)
        
        lines = []
        for line in proc.stdout:
            f.write(line)
            f.flush()  # 立即写入磁盘
            lines.append(line)
        
        proc.wait()
```

**效果**:
- ✅ 训练输出实时写入 `train.log`
- ✅ 可以用 `tail -f` 实时查看进度
- ✅ 每个 episode 一行 JSON，包含所有指标

**日志内容示例**:
```json
{
  "episode": 5,
  "updates": 320,
  "seconds": 127.4,
  "time_gen": 85.2,
  "time_tensor": 0.3,
  "time_env": 0.1,
  "time_rollout": 41.8,
  "ann_log_return": 0.1234,
  "p95_max_dd": 0.0567,
  "lambda_dd": 0.23,
  "lambda_cvar": 0.15,
  "kl": 0.0012,
  "years": 8.0,
  "grad_norm": 0.45
}
```

### 3. 中间保存（Checkpoint）

**改进**: 每 N 个 episodes 自动保存

```python
# 新代码 (src/qount/research/etf_trader/train.py:205-312)
def train(cfg, out_dir, *, log_every=1, checkpoint_every=10, ...):
    # ...训练循环...
    for ep in range(cfg.episodes):
        # ...episode 训练...
        hist.append(rec)
        
        # 实时日志
        if ep % log_every == 0:
            print(json.dumps(rec), flush=True)
        
        # 中间保存
        if ep > 0 and ep % checkpoint_every == 0:
            checkpoint_path = out_dir / f"checkpoint_ep{ep}.pt"
            torch.save({
                "model": model.state_dict(),
                "config": asdict(cfg),
                "lambda": lam,
                "episode": ep
            }, checkpoint_path)
            (out_dir / f"history_ep{ep}.json").write_text(
                json.dumps(hist, indent=2)
            )
```

**保存内容**:
- `checkpoint_ep10.pt` — 模型权重 + 配置 + 对偶变量
- `history_ep10.json` — 前 10 个 episodes 的完整训练历史
- `checkpoint_ep20.pt`, `history_ep20.json` ...

**效果**:
- ✅ 每 10 episodes 自动保存（30 episodes 训练有 3 个 checkpoint）
- ✅ 训练中断可以恢复或分析中间结果
- ✅ 可以提前评估模型性能，决定是否继续训练

### 4. 监控脚本

**新增**: `scripts/research/monitor_training_progress.py`

```python
def monitor_training(root_dir: Path):
    """Monitor all training processes under root_dir."""
    while True:
        log_files = list(root_dir.rglob("train.log"))
        
        # 解析每个日志的最新进度
        progress = []
        for log_file in log_files:
            # 读取最后一个有效的 JSON 行
            last_rec = parse_last_json(log_file)
            if last_rec:
                progress.append({
                    "config": ...,
                    "episode": last_rec["episode"],
                    "return": last_rec["ann_log_return"],
                    "drawdown": last_rec["p95_max_dd"],
                    ...
                })
        
        # 显示汇总
        print(f"Total running: {len(progress)} / 32")
        print(f"Average progress: {avg_ep:.1f} / 30 ({pct:.1f}%)")
        for p in progress:
            print(f"{p['config']:<25} Ep {p['episode']:<5} "
                  f"Return {p['return']:>8.4f} DD {p['drawdown']:>8.4f}")
        
        time.sleep(10)
```

**使用方法**:
```bash
# 服务器上运行
cd /root/autodl-tmp
python scripts/research/monitor_training_progress.py experiments/p2_us_final_20261002_monitored
```

**输出示例**:
```
Training Progress - 01:45:23
================================================================================
Config                    Seed            Ep    Return       DD       KL  Time/ep
--------------------------------------------------------------------------------
phi16_h16_L1_lr3e-04      seed20260930    12   0.1234   0.0567   0.0012   125.3s
phi16_h16_L1_lr3e-04      seed20260931    11   0.1189   0.0623   0.0015   132.1s
phi16_h16_L2_lr3e-04      seed20260930    13   0.1456   0.0489   0.0009   118.7s
...
--------------------------------------------------------------------------------
Total running: 16 / Expected: 32 (Stage A)
Average progress: 12.3 / 30 episodes (41.0%)
```

## 性能分析

### GPU 利用率低的原因

监控显示 GPU 利用率只有 5-20%，这是**正常的**：

1. **RL 训练是 CPU-bound** — 大部分时间在生成环境（世界模拟）
2. **模型很小** — 只有 3k-12k 参数，前向/反向传播很快
3. **batch_worlds=256** — 需要大量 CPU 时间生成 256 个并行世界

**时间分解**（从日志中可见）:
```
time_gen: 85.2s      # CPU 密集：生成 256 个世界
time_tensor: 0.3s    # CPU→GPU 数据传输
time_env: 0.1s       # 构建 TorchEnv
time_rollout: 41.8s  # GPU：模型前向 + 反向传播
```

**结论**: `time_gen` 占 67%，`time_rollout`（GPU 部分）只占 33%。这是 RL 训练的典型特征。

### 预估完成时间

基于实际运行数据：
- 单个 episode: ~2 分钟
- 单个训练（30 episodes）: ~60 分钟
- Stage A（32 训练 × 16 并行）: ~120 分钟（2 小时）
- Stage B（45 训练 × 16 并行）: ~180 分钟（3 小时）
- **总计**: ~5 小时

## 文件结构

### 训练输出目录
```
experiments/p2_us_final_20261002_monitored/
├── stage_a/
│   ├── phi16_h16_L1_lr3e-04/
│   │   ├── seed20260930/
│   │   │   ├── meta.json              # 训练配置
│   │   │   ├── train.log              # 实时训练日志（每行一个 episode）
│   │   │   ├── checkpoint_ep10.pt     # Episode 10 checkpoint
│   │   │   ├── history_ep10.json      # Episode 0-10 历史
│   │   │   ├── checkpoint_ep20.pt     # Episode 20 checkpoint
│   │   │   ├── history_ep20.json      # Episode 0-20 历史
│   │   │   ├── model.pt               # 最终模型
│   │   │   └── history.json           # 完整训练历史
│   │   └── seed20260931/
│   │       └── ...
│   ├── phi16_h16_L2_lr3e-04/
│   │   └── ...
│   └── ...
├── stage_a_results.json               # Stage A 汇总结果
└── stage_b/
    └── ...
```

## 使用指南

### 1. 启动训练
```bash
cd /root/autodl-tmp
nohup python scripts/research/etf_trader_parallel_search.py \
  --account us \
  --out experiments/p2_us_final_20261002_monitored \
  --stage-a-episodes 30 \
  --stage-b-episodes 100 \
  --parallel 16 \
  --workers 20 \
  --batch-worlds 256 \
  > train_monitored.log 2>&1 &
```

### 2. 实时监控（推荐）
```bash
# 方法 1: 使用监控脚本（汇总所有训练）
python scripts/research/monitor_training_progress.py \
  experiments/p2_us_final_20261002_monitored

# 方法 2: 查看单个训练
tail -f experiments/p2_us_final_20261002_monitored/stage_a/phi16_h16_L1_lr3e-04/seed20260930/train.log

# 方法 3: 统计总体进度
find experiments/p2_us_final_20261002_monitored -name "train.log" \
  -exec grep -h "episode" {} \; | wc -l
```

### 3. 检查 Checkpoint
```bash
# 列出所有 checkpoint
find experiments/p2_us_final_20261002_monitored -name "checkpoint*.pt"

# 查看某个训练的历史
cat experiments/p2_us_final_20261002_monitored/stage_a/phi16_h16_L1_lr3e-04/seed20260930/history_ep10.json

# 加载 checkpoint（Python）
import torch
ckpt = torch.load("checkpoint_ep10.pt")
model.load_state_dict(ckpt["model"])
print(f"Resumed from episode {ckpt['episode']}")
```

### 4. 分析训练曲线
```python
import json
import matplotlib.pyplot as plt

# 读取训练历史
with open("history.json") as f:
    hist = json.load(f)

episodes = [h["episode"] for h in hist]
returns = [h["ann_log_return"] for h in hist]
drawdowns = [h["p95_max_dd"] for h in hist]

# 绘制收益曲线
plt.figure(figsize=(12, 4))
plt.subplot(1, 2, 1)
plt.plot(episodes, returns)
plt.xlabel("Episode")
plt.ylabel("Ann. Log Return")
plt.title("Training Return")

plt.subplot(1, 2, 2)
plt.plot(episodes, drawdowns)
plt.xlabel("Episode")
plt.ylabel("95% Max Drawdown")
plt.title("Training Drawdown")

plt.tight_layout()
plt.savefig("training_curves.png")
```

## 故障排查

### 训练卡在 torch.compile
**现象**: 所有 `train.log` 只有一行 `torch.compile enabled with mode=reduce-overhead`

**原因**: 第一次编译需要 5-10 分钟

**解决**: 等待编译完成，或使用 `--no-compile` 跳过编译（会慢 3-5 倍）

### 训练进程僵死
**现象**: GPU 内存已占用，但没有新的日志输出

**诊断**:
```bash
# 检查进程状态
ps aux | grep etf_trader_train.py

# 检查是否有错误
tail -50 train_monitored.log
```

**解决**: 
```bash
# 停止所有训练
pkill -9 -f etf_trader

# 检查最新的 checkpoint
find experiments -name "checkpoint*.pt" -mmin -30

# 从 checkpoint 恢复（TODO: 需要实现恢复逻辑）
```

### GPU OOM
**现象**: 日志中出现 `CUDA out of memory`

**解决**:
1. 减少并行数: `--parallel 16` → `--parallel 12`
2. 减少 batch_worlds: `--batch-worlds 256` → `--batch-worlds 128`
3. 减少 DataLoader workers: `workers=2` → `workers=1`

## 后续改进 TODO

- [ ] 实现从 checkpoint 恢复训练
- [ ] 添加 TensorBoard 支持（实时可视化）
- [ ] 自动生成训练报告（汇总所有指标）
- [ ] 添加早停机制（性能不收敛时自动停止）
- [ ] GPU 利用率进一步优化（pipeline CPU+GPU）

## 相关文档

- [P2 执行指南](p2-execution-guide.md)
- [P2 优化总结](p2-optimization-final-summary.md)
- [P2 硬件分析](p2-hardware-analysis.md)
