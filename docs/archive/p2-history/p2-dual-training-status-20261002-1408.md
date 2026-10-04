# P2 双GPU训练状态报告

> **归档状态**：historical / non-restorable evidence｜**整理日期**：2026-10-02
> **替代入口**：[当前架构与研究结果](../../p2-project-summary-20261002.md)；运行事实与权限仅看 [current.md](../../current.md)。
> 原文中的“当前”“最终”“通过”仅代表当时的记录，未经本轮重新验收；历史命令不构成重启、部署或交易授权。

**检查时间**: 2026-10-02 14:08 CST  
**报告**: 双端训练均正常运行，但训练任务与CLAUDE.md记录不符

---

## 云端 3090 服务器状态

**连接**: `ssh -p 41489 root@connect.nmb2.seetacloud.com` (密码: [凭据已移出文档，认证仅从 Mac 私有配置读取])  
**运行时间**: 83天3小时，负载 50.42  
**GPU**: RTX 3090 24GB, CUDA 13.2, Driver 595.71.05

### 当前训练任务
- **实验目录**: `/root/autodl-tmp/experiments/p2_us_optimized_20261002_040315`
- **任务**: Stage B - phi32_h16_L2_lr1e-04 (5个seeds并行)
- **配置**: d_phi=32, hidden=16, layers=2, lr=0.0001
- **Episodes**: 100, batch_worlds=256, workers=6

### 进程状态
- **主进程**: 5个 (seeds: 20260930, 20260931, 20260932, 20260933, 20260934)
- **工作进程**: 30个 (每个seed 6个workers)
- **GPU显存**: 5551 MiB / 24576 MiB (23%)
- **GPU利用率**: 2% (当前处于世界生成阶段)

### 训练进度
```
所有5个seeds均已启动，但日志只显示torch.compile警告
未找到Episode进度日志
训练刚开始 (14:02启动，运行约5分钟)
```

### 自动监控日志
- 监控脚本持续运行9.5小时
- 之前监控Stage A训练 (16/32配置完成)
- GPU利用率波动: 0-99%，显存6-9GB

---

## WSL 4060 本地状态

**连接**: `ssh qount-wsl` (100.105.105.56, Tailscale)  
**GPU**: RTX 4060 (nvidia-smi命令不可用，使用CPU fallback)

### 当前训练任务
- **实验目录**: `~/Code/qount/experiments/p2_us_full_wsl_20261002_033008`
- **任务**: Stage A - 多配置并行测试
- **活跃配置**: 
  - phi16_h16_L2 (seed 20260930, 运行10.5小时, 8 workers, 低CPU)
  - phi32_h32_L2 (seed 20260931, 运行50分钟, 8 workers, **高GPU负载**)
  - phi32_h64_L1 (seed 20260930, 运行50分钟, 8 workers, 高CPU)
  - phi32_h64_L1 (seed 20260931, 运行48分钟, 8 workers, 高CPU)

### 进程状态
- **总进程**: 35个Python进程
- **主配置**: 4个不同结构同时训练
- **资源使用**:
  - phi32_h32 主进程: 93.7% CPU, 2.0GB RAM
  - phi32_h64 主进程: 91-94% CPU, 2.4-2.5GB RAM
  - 工作进程: 60-75% CPU

### 训练进度
**phi32_h32_L2 (seed 20260931)**: Episode 12/30
```json
{"episode": 12, "updates": 104, "seconds": 233.76, 
 "ann_log_return": 0.06586305, "p95_max_dd": 0.1889, 
 "lambda_dd": 0.2345, "kl": 0.1152, "grad_norm": 0.00876}
```

**phi32_h64_L1 (seed 20260930)**: Episode 12/30
```json
{"episode": 12, "updates": 104, "seconds": 207.57,
 "ann_log_return": 0.06345416, "p95_max_dd": 0.1680,
 "lambda_dd": 0.2094, "kl": 0.0828, "grad_norm": 0.0137}
```

### 自动监控
- 监控脚本运行59分钟
- 原计划在04:48完成当前训练
- 进度提取异常 (显示 "Episode /30")

---

## 关键发现

### ⚠️ 训练任务不匹配
**CLAUDE.md声称**:
- 3090: `p2_us_final_20261002_monitored` (原训练，有批次间隙bug)
- WSL: `p2_us_wsl4060_fixed` (修复版训练，无批次间隙)

**实际运行**:
- 3090: `p2_us_optimized_20261002_040315` - Stage B测试
- WSL: `p2_us_full_wsl_20261002_033008` - Stage A并行测试

### 训练特征对比

| 维度 | 3090 | WSL 4060 |
|------|------|----------|
| 阶段 | Stage B (phi32_h16_L2) | Stage A (多配置) |
| 并行数 | 5 seeds | 4 configs × seeds |
| Episodes | 100 | 30 |
| Workers | 6 | 8 |
| Batch worlds | 256 | 256 |
| torch.compile | 成功 (reduce-overhead) | 失败 (eager fallback) |
| 启动时间 | 14:02 (5分钟前) | 03:29-13:19 (多批次) |
| 可见进度 | 无 (刚启动) | Episode 12/30 |

### WSL torch.compile失败
```
Warning: torch.compile failed (cannot import name 'SubgraphCPUBenchmarkRequest' 
from 'torch._inductor.autotune_process'), falling back to eager mode
```
这会导致性能下降，但不影响正确性。

---

## 资源利用

### 3090
- **GPU显存**: 5.5 GB / 24 GB (23%, 5个并行训练)
- **GPU利用率**: 2% (世界生成阶段)
- **负载**: 50.42 (高CPU负载，多进程世界生成)

### WSL 4060
- **CPU**: 多个90%+ 进程 (世界生成瓶颈)
- **内存**: 每主进程 2-2.5GB
- **负载**: 高 (4个配置同时训练)

---

## 建议

1. **更新CLAUDE.md**: 修正实验目录名称和训练阶段
2. **检查3090日志**: 等待Episode 0完成查看完整日志
3. **修复WSL torch.compile**: 解决SubgraphCPUBenchmarkRequest导入错误
4. **监控WSL完成**: phi32配置预计再15-18 episodes完成
5. **验证批次间隙修复**: 在实际checkpoint保存时验证

---

## 下一步行动

- [ ] 等待3090完成Episode 0 (~5-10分钟)
- [ ] 检查WSL phi32训练结果 (~2-3小时)
- [ ] 对比两端相同配置的性能差异
- [ ] 确认哪个实验目录对应"修复版"训练
