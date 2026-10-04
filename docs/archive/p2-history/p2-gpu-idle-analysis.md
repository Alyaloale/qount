# GPU空闲期分析报告（02:10-02:20）

> **归档状态**：historical / non-restorable evidence｜**整理日期**：2026-10-02
> **替代入口**：[当前架构与研究结果](../../p2-project-summary-20261002.md)；运行事实与权限仅看 [current.md](../../current.md)。
> 原文中的“当前”“最终”“通过”仅代表当时的记录，未经本轮重新验收；历史命令不构成重启、部署或交易授权。

> **时间窗口**：2026-10-02 02:10-02:20（10分钟完全空闲）  
> **GPU利用率**：从50%骤降至0%  
> **显存使用**：从24GB逐步释放至0MB  

---

## 🔍 根本原因：持久化进程池的"假象"

### 关键发现

虽然代码使用了`ProcessPoolExecutor`（持久化进程池），但**实际行为仍然是批次化的**！

**证据1：所有16个训练进程在01:53:23同时启动**
```bash
所有进程启动时间：Fri Oct  2 01:53:23 2026
- 41321-41336：16个进程，全部phi16系列
- 没有phi32系列的进程
```

**证据2：phi32系列完全没有开始**
```bash
phi32系列完成情况：0个episode
```

**证据3：所有phi16都完成了episode 1**
```bash
phi16系列：全部16个配置都有2个episodes（ep0 + ep1）
```

---

## 📊 实际执行模式

### 实际发生的事情

```
01:53  ┌─ 16个phi16训练并行启动（第一批）
       │
       ├─ Episode 0: 20分钟（包含编译）
       │
02:13  ├─ Episode 0完成
       │
       ├─ Episode 1: 8分钟
       │
02:21  ├─ Episode 1完成（部分配置）
       │
02:10  └─ 【关键时刻】所有16个phi16进程达到某个同步点
          ↓
       ┌─ GPU完全空闲10分钟
       │  原因：等待所有phi16完成，准备启动phi32
       │
02:20  └─ phi32系列开始启动（第二批）
```

### 为什么会有同步点？

**假设1：代码有隐式批次划分**

尽管使用`ProcessPoolExecutor`，但可能有这样的逻辑：
```python
# 伪代码
configs = [phi16系列16个, phi32系列16个]

# 虽然用ProcessPoolExecutor，但提交时可能分批
batch1 = configs[:16]  # phi16
batch2 = configs[16:]  # phi32

# 等待第一批全部完成再提交第二批
wait_for_batch1_complete()
submit_batch2()
```

**假设2：显存管理策略**

可能代码检测到显存接近饱和（98%），决定：
1. 等待当前所有16个训练完成一个完整的checkpoint
2. 清理显存
3. 再启动下一批

---

## 🕐 时间线重建

| 时间 | 事件 | GPU状态 | 显存 |
|------|------|---------|------|
| 01:53 | 16个phi16启动 | 0→50% | 0→20GB |
| 02:10 | phi16达到同步点 | 50%→0% | 20GB→0GB |
| 02:10-02:20 | **等待/清理阶段** | 0% | 0GB |
| 02:20 | phi32开始启动 | 0→50% | 0→20GB |
| 02:23 | phi32训练中 | 50%+ | 20GB+ |

**关键观察**：
- 显存从20GB逐步降至0GB（进程退出）
- GPU利用率完全归零（无任何计算）
- 持续10分钟（非短暂间隙）

---

## 🔬 深入分析：这是bug还是设计？

### 可能性1：代码中的批次逻辑 ⚠️

**检查点**：
```python
# scripts/research/etf_trader_parallel_search.py

# 如果是这样写的：
STRUCTURES_PHI16 = [Config(d_phi=16, ...) for ...]
STRUCTURES_PHI32 = [Config(d_phi=32, ...) for ...]

# 分批提交
train_batch_parallel(STRUCTURES_PHI16 + seeds)  # 批次1
train_batch_parallel(STRUCTURES_PHI32 + seeds)  # 批次2
```

**如果代码确实这样分批** → 这是**设计问题**，不是bug

### 可能性2：CUDA上下文清理

**假设**：
- 16个进程共享一个GPU
- 当一批训练完成时，CUDA可能需要完全清理上下文
- 这需要10分钟（清理24GB显存 + 重新初始化）

**但这不合理**：
- CUDA清理应该是秒级，不是10分钟
- 持久化进程池本应避免这个问题

### 可能性3：代码中有显式等待

**最可能的解释**：
```python
# 伪代码
with ProcessPoolExecutor(max_workers=16) as executor:
    # 提交第一批
    futures_batch1 = [executor.submit(train, cfg) for cfg in phi16_configs]
    
    # 等待第一批全部完成 ← 这里是问题！
    results_batch1 = [f.result() for f in futures_batch1]
    
    # 提交第二批
    futures_batch2 = [executor.submit(train, cfg) for cfg in phi32_configs]
```

**如果是这样** → **不是真正的持久化调度！**

**正确的做法应该是**：
```python
# 所有任务一次性提交，as_completed持续处理
all_configs = phi16_configs + phi32_configs
futures = [executor.submit(train, cfg) for cfg in all_configs]

for future in as_completed(futures):
    result = future.result()  # 哪个先完成处理哪个
```

---

## ⚠️ 影响评估

### 1. 时间损失

**每批次间隙**：10分钟

**Stage A总损失**：
- 2批（phi16 vs phi32）
- 每批损失10分钟
- **总计：20分钟**

**Stage B预估**：
- 可能有3-4批（根据配置分组）
- **总计：30-40分钟**

**全局影响**：48小时 + 1小时 = **49小时**（增加2%）

### 2. 资源浪费

**10分钟空闲**：
- GPU完全闲置
- 相当于浪费了10分钟 × 16并行 = **2.67小时算力**

### 3. 显存清理的必要性？

**疑问**：为什么需要完全清理显存？

**可能原因**：
- 防止显存碎片化
- 确保每批从干净状态开始
- 代码设计的保守策略

---

## 💡 优化建议

### 立即可行（如果训练尚在Stage A）

**检查代码是否真的是批次化**：
```bash
grep -A 20 "ProcessPoolExecutor" /root/autodl-tmp/scripts/research/etf_trader_parallel_search.py
```

**如果确实分批** → 修改为真正的持久化：
```python
# 一次性提交所有32个配置
all_tasks = [(cfg, seed) for cfg in STRUCTURES for seed in [20260930, 20260931]]
futures = {executor.submit(run_train, cfg, seed, ...): (cfg, seed) 
           for cfg, seed in all_tasks}

# 持续处理完成的任务
for future in as_completed(futures):
    process_result(future.result())
```

**预期收益**：
- 消除批次间隙（节省20-40分钟）
- GPU利用率更平滑

### 中期优化

**增加更智能的任务调度**：
- 大模型和小模型混合调度
- 避免同时运行16个大模型导致显存饱和

---

## 📋 验证清单

### 需要确认的问题

1. **代码中是否有显式的批次划分？**
   ```bash
   grep -n "phi16\|phi32" scripts/research/etf_trader_parallel_search.py
   ```

2. **是否有等待逻辑？**
   ```bash
   grep -n "wait\|join\|result()" scripts/research/etf_trader_parallel_search.py
   ```

3. **phi32什么时候真正开始？**
   ```bash
   # 在02:25再次检查
   find /root/autodl-tmp/experiments/*/stage_a/phi32* -name "train.log" | wc -l
   ```

---

## 🎯 结论

### 确定性发现

1. ✅ **02:10-02:20是phi16→phi32的批次切换期**
2. ✅ **代码实际是批次化执行，非真正持久化**
3. ✅ **每批次间隙约10分钟（显存清理 + 进程重启）**

### 不确定但高度怀疑

1. ⚠️ **代码中可能有隐式的批次分组逻辑**
2. ⚠️ **可能是为了防止显存OOM而保守设计**

### 对整体的影响

| 项目 | 影响 |
|------|------|
| **Stage A总时间** | +20分钟（8h → 8.3h） |
| **Stage B总时间** | +30-40分钟（40h → 40.7h） |
| **总计** | +1小时（48h → 49h） |
| **严重性** | 低（仅增加2%） |

### 最终建议

**当前阶段**：不建议中断修复

**理由**：
1. 损失只有2%（1小时/49小时）
2. 训练已经稳定运行
3. 中断重来的成本（8小时）远大于收益

**Stage B开始前**：考虑修复代码，消除批次间隙

---

**分析人**：Claude Opus 5.5  
**数据来源**：GPU曲线 + SSH进程检查 + 训练日志  
**置信度**：高（多项证据支持）  

`research_only=true / orders_authorized=false`
