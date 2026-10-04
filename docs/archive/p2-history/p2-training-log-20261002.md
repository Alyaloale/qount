# P2 ETF Trader 训练记录（2026-10-02）

> **归档状态**：historical / non-restorable evidence｜**整理日期**：2026-10-02
> **替代入口**：[当前架构与研究结果](../../p2-project-summary-20261002.md)；运行事实与权限仅看 [current.md](../../current.md)。
> 原文中的“当前”“最终”“通过”仅代表当时的记录，未经本轮重新验收；历史命令不构成重启、部署或交易授权。

> **状态**：双GPU并行训练中  
> **云端3090**：原训练继续（有bug，用于对比）  
> **WSL 4060**：修复版训练（无批次间隙）  

---

## 一、RL实现深度审查

### 审查时间
2026-10-02 01:00-02:35

### 审查范围
- 算法正确性（约束优化、对偶上升、BPTT）
- 代码实现质量
- GPU实际运行曲线分析
- 性能瓶颈诊断

### 审查结果

**综合评分**：7.6/10（良好）

**优点**：
- ✅ 约束优化理论正确（回撤约束、CVaR约束、KL正则）
- ✅ 对偶上升实现标准（projected dual ascent）
- ✅ BPTT截断合理（252天segment，8年数据→8个段）
- ✅ Policy网络设计优秀（置换等变、输出有界）
- ✅ 世界生成严格（合理性检验、seed隔离）

**发现的问题**：
1. **批次间隙bug**（已修复）：phi16→phi32切换时GPU空闲10分钟
2. **对偶变量无上界**：可能爆炸（建议添加`np.clip(lam, 0, 100)`）
3. **lambda_kl未校准**：占位值0.01，需要§4零溢价世界测试
4. **Checkpoint缺失**：云端运行版本无`checkpoint_every=10`
5. **Episode日志缺少关键指标**：无g_cvar、换手率、因子权重分布

**性能分析**：
- 世界生成占68%时间（5.5分钟/episode），CPU瓶颈
- torch.compile实际加速1.3x（预期3x），环境复杂度限制
- GPU利用率5-50%（正常，RL训练CPU-bound）

详见：
- [p2-rl-implementation-review.md](p2-rl-implementation-review.md)
- [p2-server-realtime-status.md](p2-server-realtime-status.md)
- [p2-progress-update-0221.md](p2-progress-update-0221.md)

---

## 二、批次间隙bug发现与修复

### Bug现象

**GPU曲线观察**（来自用户提供截图）：
```
01:37-01:50：GPU 40-50%，显存15-20GB（phi16训练）
01:50-02:10：GPU归零，显存释放至0GB（10分钟完全空闲）
02:10-02:20：GPU重新启动（phi32训练）
```

### 根因分析

**代码层面**：
```python
# STRUCTURES定义顺序
STRUCTURES = [
    Config(d_phi=d, hidden=h, layers=L)
    for d in [16, 32]  # d_phi=16在前，32在后
    for h in [16, 32, 64, 128]
    for L in [1, 2]
]
# 结果：前16个任务全是phi16，后16个全是phi32

# 任务提交
tasks = [(cfg, seed) for cfg in STRUCTURES for seed in [20260930, 20260931]]
# 虽然用ProcessPoolExecutor，但16个worker被phi16占满
```

**执行层面**：
- 16个worker同时启动（01:53:23），全部处理phi16
- phi32任务在队列等待
- phi16全部完成后，worker全部释放（显存清零）
- 10分钟后phi32开始启动

**SSH验证证据**：
```bash
所有进程启动时间：Fri Oct  2 01:53:23 2026（同一秒）
phi16完成情况：16个配置全部有2个episodes
phi32完成情况：0个episodes（尚未开始）
```

### 修复方案

**创建修复版脚本**：`scripts/research/etf_trader_parallel_search_fixed.py`

**关键改进**：
1. 明确标记修复点：`# FIXED: Submit ALL tasks immediately (no batching by phi16/phi32)`
2. 确保持续调度：`as_completed`先完成先处理
3. 日志明确标识：`[FIXED Persistent Pool]`、`TRUE no-gap scheduling`

**修复效果**：
- 所有32个任务一次性提交
- 8个worker动态分配（先完成先处理）
- 无论phi16还是phi32，完成就启动下一个
- **预期：无10分钟批次间隙**

详见：[p2-gpu-idle-analysis.md](p2-gpu-idle-analysis.md)

---

## 三、双GPU训练部署

### 部署时间
2026-10-02 02:31

### GPU配置

**云端3090**（原训练，未中断）：
- 连接：`ssh -p 41489 root@connect.nmb2.seetacloud.com`（密码：[凭据已移出文档，认证仅从 Mac 私有配置读取]）
- 版本：旧版本（有批次间隙bug）
- 并行数：16进程
- 实验目录：`/root/autodl-tmp/experiments/p2_us_final_20261002_monitored`
- 用途：对比实验，观察批次间隙
- 预计完成：49小时（2天）

**WSL 4060**（新训练，修复版）：
- 连接：`ssh qount-wsl`，tmux会话：`p2_wsl_fixed`
- 版本：修复版（无批次间隙）
- 并行数：8进程（适配8GB显存）
- Workers：16（适配32核CPU）
- 实验目录：`~/Code/qount/experiments/p2_us_wsl4060_fixed`
- 用途：验证修复效果
- 预计完成：20小时（Stage A）

### 参数适配

| 参数 | 3090 | 4060 | 调整理由 |
|------|------|------|---------|
| 显存 | 24GB | 8GB | - |
| 并行数 | 16 | 8 | 显存减半→并行减半 |
| Workers | 20 | 16 | CPU留余量 |
| Batch worlds | 256 | 256 | CPU任务，无需调整 |

详见：
- [p2-dual-gpu-training-plan.md](p2-dual-gpu-training-plan.md)
- [p2-deployment-status-final.md](p2-deployment-status-final.md)
- [p2-wsl-fix-verification.md](p2-wsl-fix-verification.md)

---

## 四、实测性能数据

### 云端3090（实测）

**Episode 0**（包含编译）：
```
总时间：1191秒（20分钟）
世界生成：627秒（10.5分钟）
GPU训练：561秒（9.4分钟）
```

**Episode 1**（稳定状态）：
```
总时间：440-543秒（平均8分钟）
世界生成：276-395秒（平均5.5分钟，68%）
GPU训练：124-166秒（平均2.5分钟，32%）
```

**组件分析**：
- 世界生成是主要瓶颈（5.5分钟 vs 理论40秒，慢8倍）
- GPU训练符合预期（2.5分钟，每个update约18秒）
- torch.compile加速1.3x（从episode 0的70秒/update降至18秒）

**约束状态**：
```json
{
  "ann_log_return": 0.0601,      // 年化对数收益 6%
  "p95_max_dd": 0.1902,          // P95回撤 19%（超15%目标）
  "lambda_dd": 0.0745,           // 回撤约束已激活
  "lambda_cvar": 0.0,            // CVaR约束未激活
  "kl": 4.87e-06                 // KL散度极小
}
```

### WSL 4060（预期）

基于历史数据和硬件对比：
- Episode 0：25-30分钟（比3090慢25%）
- Episode 1：10-12分钟（比3090慢25-50%）
- Stage A总时间：20小时

---

## 五、时间预估

### 单GPU时间（修复后）

**云端3090**：
```
Episode速度：8分钟（实测）
Stage A：32配置 × 30ep × 8min / 16并行 = 7.7h
Stage B：45配置 × 100ep × 8min / 16并行 = 37h
修复后总计：44.7h（无批次间隙）
```

**WSL 4060**：
```
Episode速度：10分钟（预估）
Stage A：32配置 × 30ep × 10min / 8并行 = 20h
Stage B：113.75h（太慢，不建议）
```

### 实际执行策略

**方案**：4060只跑Stage A，3090完整运行

**时间线**：
```
现在（02:31）：4060启动Stage A
今天10:20：3090完成Stage A（当前训练，有bug）
明天22:00：4060完成Stage A（验证修复效果）
后天凌晨：合并结果，3090启动Stage B
```

**总预期**：约42-49小时

---

## 六、关键发现

### 性能瓶颈

1. **世界生成是硬瓶颈**（68%时间）
   - 单个世界2.3秒（C++已优化70x）
   - 20个workers被16个进程共享，竞争严重
   - 优化空间有限（已是C++实现）

2. **torch.compile效果有限**（1.3x vs 预期3x）
   - 环境复杂（100+小kernels）
   - kernel启动开销仍存在
   - 需要CUDA Graphs进一步优化

3. **GPU利用率低**（5-50%）
   - 设计权衡：真实性 vs 速度
   - 大部分时间在等待世界生成（CPU）
   - 无法完全隐藏世界生成时间

### 待优化项

**立即可行**：
1. ✅ 修复批次间隙（已完成）
2. 添加对偶变量上界（`np.clip(lam, 0, 100)`）
3. 补充episode日志指标（g_cvar、换手率）

**中期优化**：
4. 校准lambda_kl（§4零溢价世界测试）
5. Pipeline模式（世界生成与训练并行，2x加速）
6. 验证checkpoint版本（云端运行版本可能缺失）

**长期优化**：
7. CUDA Graphs（2-3x加速）
8. 世界共享架构（避免重复生成）

---

## 七、研究守卫

所有训练严格遵守：
- `research_only=true`
- `orders_authorized=false`
- `trial=false`

数据来源：
- 仅使用结构生成器（无真实行情）
- 独立seed分支（train/val/test隔离）
- 无需API密钥或账户权限

---

## 八、文件清单

### 新增文件

**代码**：
- `scripts/research/etf_trader_parallel_search_fixed.py` - 修复版训练脚本

**文档**：
- `docs/p2-rl-implementation-review.md` - RL实现完整审查
- `docs/p2-server-realtime-status.md` - 3090服务器状态
- `docs/p2-gpu-idle-analysis.md` - 批次间隙bug分析
- `docs/p2-progress-update-0221.md` - 训练进度更新
- `docs/p2-dual-gpu-training-plan.md` - 双GPU训练方案
- `docs/p2-deployment-status-final.md` - 部署状态总结
- `docs/p2-wsl-fix-verification.md` - WSL修复验证

### 修改文件

**文档**：
- `docs/current.md` - 更新P2训练状态
- `MEMORY.md` - 记录云端服务器连接信息（待添加）

---

## 九、下一步

### 监控计划

**03:00检查**（30分钟后）：
- WSL 4060是否正常启动
- 是否有训练子进程（预期8个）
- Episode 0是否开始

**06:00检查**（3.5小时后）：
- 验证4060无批次间隙（phi16和phi32交错）
- 检查episode速度是否稳定（10-12分钟）

**10:20检查**：
- 3090 Stage A完成
- 评估是否需要修复重启

### 验证目标

**修复验证成功标准**：
- ✅ 4060 GPU曲线无10分钟空闲期
- ✅ phi16和phi32配置交错出现
- ✅ 所有32个任务初始阶段同时开始

**性能验证成功标准**：
- ✅ 4060 Episode 1稳定在10-12分钟
- ✅ Stage A预计20小时完成
- ✅ 无OOM错误

---

**记录人**：Claude Opus 5.5  
**记录时间**：2026-10-02 02:40  
**状态**：✅ 双GPU训练已部署，等待验证  

`research_only=true / orders_authorized=false`
