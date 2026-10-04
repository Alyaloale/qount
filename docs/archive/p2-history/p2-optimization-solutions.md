# P2 性能瓶颈优化方案

> **归档状态**：historical / non-restorable evidence｜**整理日期**：2026-10-02
> **替代入口**：[当前架构与研究结果](../../p2-project-summary-20261002.md)；运行事实与权限仅看 [current.md](../../current.md)。
> 原文中的“当前”“最终”“通过”仅代表当时的记录，未经本轮重新验收；历史命令不构成重启、部署或交易授权。

## 瓶颈 1: torch.compile 加速不足

### 当前状态
- 期望：3.6秒 → 1.2秒（3x 加速）
- 实际：3.6秒 → 4秒（无加速，反而慢了）
- 原因：真实 env 有"约一百多个小 kernel"

### 为什么 compile 没用

**PyTorch compile 的局限**：
- 适合大矩阵运算（单个大 kernel）
- 不适合很多小 kernel（启动开销占主导）
- 我们的 env 每步有 100+ 小操作（约束检查、成本计算、状态更新）

### 优化方案

#### 方案 1: CUDA Graphs（最有效，但需要实现）⭐

**原理**：
- 记录整个计算图（包括所有小 kernel）
- 一次性提交到 GPU
- 减少 CPU-GPU 通信

**实现复杂度**：中等
- 需要固定输入形状
- 需要预热阶段
- 可能与 dynamic control flow 冲突

**预期加速**：2-3x

**实现步骤**：
1. 在 `run_segment` 外层包装 CUDA Graph
2. 预热 3-5 个 segment
3. 后续 segment 复用 graph

#### 方案 2: 减少 Python 开销（容易，立即可行）✅

**问题**：当前每步都有 Python 函数调用

**优化**：
1. **批量化小操作**：
   ```python
   # 当前：每天单独计算
   for t in range(T):
       constraint_check(t)
       cost_calc(t)
   
   # 优化：批量计算
   constraint_check_batch(range(T))
   cost_calc_batch(range(T))
   ```

2. **减少 .item() 调用**：
   ```python
   # 当前：频繁转 Python scalar
   if obs.equity.item() > threshold:
   
   # 优化：保持 tensor
   if obs.equity > threshold:
   ```

3. **合并小 tensor 操作**：
   ```python
   # 当前：多次小操作
   x = a + b
   y = x * c
   z = y.clamp(0, 1)
   
   # 优化：单次融合
   z = (a + b).mul(c).clamp(0, 1)
   ```

**预期加速**：1.2-1.5x
**实现时间**：2-4 小时代码审查 + 修改

#### 方案 3: 使用 torch.compile 更激进的模式（立即可行）✅

**当前配置**：
```python
model = torch.compile(model, mode='reduce-overhead')
```

**尝试配置**：
```python
# 模式 1: max-autotune（更激进优化）
model = torch.compile(model, mode='max-autotune')

# 模式 2: 指定后端
model = torch.compile(model, backend='inductor', mode='reduce-overhead')

# 模式 3: 动态形状优化
model = torch.compile(model, dynamic=True)
```

**预期加速**：可能 1.1-1.3x
**实现时间**：5 分钟修改 + 测试

#### 方案 4: 不优化，接受现状（最实际）✅

**理由**：
- 真实 env 的复杂性是固有的
- 优化投入产出比低
- 通过增加并行数补偿

**时间对比**：
- 如果加速 3x：13小时 ÷ 3 = 4.3小时
- 如果不优化但 12 并行：13小时（已经可接受）

## 瓶颈 2: 世界生成 > GPU 训练

### 当前状态
- 世界生成：40秒（256 worlds，8 workers）
- GPU 训练：32秒（8 updates）
- 瓶颈：多 8秒（25%）

### 优化方案

#### 方案 1: 增加 batch_worlds（立即可行）⭐

**原理**：增加 batch_worlds 让 GPU 训练时间变长

**计算**：
```
目标：time_rollout > time_gen

当前：
- 256 worlds: gen=40s, rollout=32s ❌
- 如果 512 worlds: gen=80s, rollout=?

rollout 时间增长（非线性）：
- 256→512: 估计 32s → 40s（+25%）
- 仍然不够！

如果 1024 worlds:
- gen=160s, rollout≈52s
- 仍然 gen > rollout！
```

**结论**：增加 batch_worlds **无法解决**这个瓶颈！

#### 方案 2: 多配置共享世界（复杂，需要重构）

**原理**：
- 不同配置（不同结构/lr）可以用相同的世界
- 生成一次，多个配置复用

**实现**：
```python
# 当前：每个配置独立生成世界
for config in configs:
    worlds = generate_worlds(256)
    train(config, worlds)

# 优化：生成一次，多次使用
worlds = generate_worlds(256 * N)  # 一次生成更多
for config in configs:
    train(config, worlds[batch_i])  # 复用
```

**预期加速**：如果 N 个配置共享，加速 ~N 倍生成时间
**实现复杂度**：高（需要重构训练流程）

#### 方案 3: 减少 workers，平衡生成和训练（反直觉但可行）✅

**原理**：
- 当前：8 workers，生成太快导致不平衡
- 如果减少到 6 workers：gen≈53s，rollout=32s
- 但总时间反而更长！

**结论**：这个方向错误

#### 方案 4: 增加更多并行进程（最实际）⭐✅

**原理**：
- 虽然单个进程有 8秒 gap
- 但多个进程并行时，gap 会被其他进程的训练填满

**示例**（3个并行进程）：
```
进程1: [生成40s][训练32s]
进程2:       [生成40s][训练32s]
进程3:             [生成40s][训练32s]

总时间: 40 + 32 + 32 + 32 = 136秒（非 216秒）
```

**结论**：并行数越多，gap 的影响越小

#### 方案 5: 接受 25% overhead（最实际）✅

**理由**：
- 世界生成是固有成本（2.3秒/world × 256 = 589秒 CPU时间）
- 已经用了 C++ 加速
- 25% overhead 在可接受范围

**计算影响**：
- 如果完全重叠：13小时
- 实际有 25% gap：13小时 × 1.25 = **16.25小时**
- 仍然可接受

## 推荐实施方案

### 立即可行（无需代码改动）

1. **使用 12-16 个并行进程**
   - 减少 gap 影响
   - 充分利用 24GB 显存

2. **尝试不同 compile 模式**
   ```bash
   # 测试 max-autotune 模式
   # 修改 train.py line 215
   model = torch.compile(model, mode='max-autotune', fullgraph=True)
   ```

### 中期优化（2-4小时工作量）

3. **优化训练循环代码**
   - 减少 Python overhead
   - 批量化小操作
   - 预期 1.2-1.5x 加速

### 长期优化（1-2天工作量）

4. **实现 CUDA Graphs**
   - 预期 2-3x 加速
   - 需要仔细测试

5. **世界共享机制**
   - 生成一次，多配置复用
   - 需要重构训练流程

## 实际建议

**不优化，直接开始训练！**

理由：
1. 当前配置（文档默认 30/100 episodes + 12并行）：
   - 预计 **16小时完成**（含 25% gap overhead）
   - 这已经非常好了！

2. 优化的投入产出比低：
   - 花 2-4 小时优化，可能省 2-3 小时
   - 不如直接开始训练

3. 如果需要更高质量：
   - 用 50/200 episodes：21小时 × 1.25 = **26小时**
   - 用 150/600 episodes：75小时 × 1.25 = **94小时 ≈ 4天**

## 快速测试不同 compile 模式

```bash
# 在服务器上测试
sshpass -p '[凭据已移出文档，认证仅从 Mac 私有配置读取]' ssh -p 41489 root@connect.nmb2.seetacloud.com << 'ENDSSH'
source /root/miniconda3/bin/activate
cd /root/autodl-tmp

# 测试 max-autotune（3 episodes 快速测试）
cat > test_compile_modes.py << 'EOF'
import sys
sys.path.insert(0, 'src')
import time
from pathlib import Path
from qount.research.etf_trader.train import train, TrainConfig

modes = ['reduce-overhead', 'max-autotune', 'default']

for mode in modes:
    print(f"\n{'='*60}")
    print(f"Testing mode: {mode}")
    print('='*60)
    
    # 修改 train.py 临时测试不同模式
    # 这里需要修改源码或传入参数
    
    cfg = TrainConfig(account="us", episodes=3, batch_worlds=256, workers=8, device="cuda")
    out_dir = Path(f"experiments/compile_test_{mode}")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    t0 = time.time()
    result = train(cfg, out_dir, log_every=1, use_compile=True)
    elapsed = time.time() - t0
    
    avg_rollout = sum(h["time_rollout"] for h in result["history"][1:]) / 2
    print(f"总时间: {elapsed:.1f}秒")
    print(f"平均 rollout: {avg_rollout:.1f}秒")
    print(f"每次 update: {avg_rollout/8:.2f}秒")
EOF

# 当前代码不支持传入 compile mode
# 需要修改 train.py 才能测试
echo "需要修改代码支持不同 compile 模式"
ENDSSH
```

## 最终建议

**现在就开始训练，不要等优化！**

使用配置：
- episodes: 30/100（文档默认）
- 并行: 12-16 进程
- 预计时间: **16小时**

如果这批结果不够好，再考虑：
1. 增加 episodes 到 50/200（26小时）
2. 或实施上述优化方案
