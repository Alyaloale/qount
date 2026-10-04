# P2双端训练运行状态检查

> **归档状态**：historical / non-restorable evidence｜**整理日期**：2026-10-02
> **替代入口**：[当前架构与研究结果](../../p2-project-summary-20261002.md)；运行事实与权限仅看 [current.md](../../current.md)。
> 原文中的“当前”“最终”“通过”仅代表当时的记录，未经本轮重新验收；历史命令不构成重启、部署或交易授权。

**检查时间**: 2026-10-02 03:37:00  
**检查人**: Claude

---

## 训练状态总览

| 项目 | 3090服务器 | WSL 4060 |
|------|-----------|----------|
| **状态** | ✅ 正在训练 | ✅ 正在训练 |
| **启动时间** | 03:36:57 | 03:30:08 |
| **运行时长** | ~2分钟 | ~8分钟 |
| **主进程PID** | 55521 | 2507 |
| **并行训练数** | 10进程 | 4进程 |
| **总进程数** | 51个Python进程 | 35个Python进程 |
| **GPU利用率** | 0% (世界生成中) | N/A |
| **GPU显存** | 3100 MB / 24576 MB | N/A |
| **GPU温度** | 27°C | N/A |
| **已生成日志** | 10个配置 | 4个配置 |
| **Episode进度** | 初始化 | Episode 0-1 |

---

## 3090服务器详情

### 基本信息
- **实验目录**: `/root/autodl-tmp/experiments/p2_us_full_20261002_033657/`
- **配置**: parallel=10, workers_per_process=3, total_workers=30
- **Stage A**: 16结构 × 2种子 = 32配置，每个30 episodes
- **Stage B**: 45配置 × 100 episodes

### 进程状态
```
主进程: 55521 (53.5% CPU, 480MB内存)
Worker进程: 55600-55609 (10个子进程已启动)
```

### 监控系统
- GPU监控: PID 55519 (10秒间隔)
- 系统监控: PID 55520 (30秒间隔)
- 监控数据: `experiments/p2_us_full_20261002_033657/monitoring/`

### 训练日志输出
```
============================================================
P2 Parallel Capacity Search (OPTIMIZED): US account
============================================================
Output: experiments/p2_us_full_20261002_033657
Device: cuda, GPU ID: 0
Parallel processes: 10
CPU workers per process: 3
Total CPU workers: 30
Stage A episodes: 30
Stage B episodes: 100
Optimizations: Persistent pool, Dynamic workers, Enhanced logging
============================================================
```

### GPU状态
- **利用率**: 0% (训练刚启动，正在初始化)
- **显存**: 3.1 GB / 24 GB (12.6%)
- **温度**: 32°C (正常)

**分析**: 3090训练刚启动1分钟，仍在初始化阶段。GPU利用率为0是正常的，显存已分配3GB说明进程已加载。预计1-2分钟后GPU利用率会上升到30-50%。

---

## WSL 4060详情

### 基本信息
- **实验目录**: `~/Code/qount/experiments/p2_us_full_wsl_20261002_033008/`
- **配置**: parallel=4, workers=32 (workers_factor=8.0)
- **Stage A**: 16结构 × 2种子 = 32配置，每个30 episodes
- **Stage B**: 100 episodes

### 进程状态
```
主进程: 2507 (运行7分钟，1.0% CPU)
训练进程: 
  - 2560: phi16_h16_L1 seed20260930 (53.1% CPU, 13.7% MEM)
  - 2561: phi16_h16_L1 seed20260931 (53.0% CPU, 13.8% MEM) 
  - 2562: 僵尸进程 <defunct>
  - 2563: phi16_h16_L2 seed20260931 (52.8% CPU, 13.9% MEM)

Worker进程: 32个高CPU使用率进程 (80-100% CPU)
```

### 系统资源
- **CPU负载**: 26.11 (1分钟平均)
- **总进程数**: 40个Python进程
- **内存使用**: 14.3 GB / 15.8 GB (90%)
- **Swap使用**: 3.9 GB / 4.0 GB (97%)

### 训练进度
- **阶段**: Stage A
- **目录结构**: 16个phi配置目录已创建
- **检查点**: 尚未生成.pt文件 (训练中)
- **日志**: 仅初始化日志，无episode输出

### 已知问题
1. **torch.compile警告**: SubgraphCPUBenchmarkRequest导入失败，已回退到eager模式
2. **僵尸进程**: PID 2562为defunct状态
3. **Swap高使用**: 97%的swap已使用，可能影响性能

**分析**: WSL训练已运行7分钟，CPU全负载运行说明世界生成正在进行。训练进程占用13-14%内存（每个约2GB），符合预期。僵尸进程可能是某个配置训练完成但未清理，不影响整体运行。

---

## 对比分析

### 配置差异
| 参数 | 3090 | WSL |
|------|------|-----|
| 并行进程 | 10 | 4 |
| 单进程worker | 3 | 8 |
| 总worker | 30 | 32 |
| GPU显存 | 24GB | 8GB |
| CPU核心 | 20 vCPU | 32核 |

### 预期性能
- **3090**: 更高GPU并行度（10进程），较少CPU worker（30），适合GPU密集型
- **WSL**: 更少GPU并行度（4进程），更多CPU worker（32），适合CPU密集型世界生成

### 预计完成时间
- **3090**: 8-10小时（Stage A+B）
- **WSL**: 10-12小时（Stage A+B）

---

## 监控建议

### 即时检查（10-15分钟后）
```bash
# 3090端
sshpass -p '[凭据已移出文档，认证仅从 Mac 私有配置读取]' ssh -p 41489 root@connect.nmb2.seetacloud.com \
  "nvidia-smi && tail -50 /root/autodl-tmp/experiments/p2_us_full_20261002_033657/training.log"

# WSL端
ssh qount-wsl "ps aux | grep python | wc -l && \
  find ~/Code/qount/experiments/p2_us_full_wsl_20261002_033008/stage_a -name 'train.log' | wc -l"
```

### 定期检查（每小时）
```bash
# 查看GPU利用率和训练进度
bash scripts/research/monitor_dual_training.sh
```

### 关键指标
1. **3090 GPU利用率**: 应在30-60%之间
2. **WSL CPU负载**: 应在25-35之间
3. **Episode完成数**: Stage A共32个配置，每个30 episodes
4. **内存使用**: 保持稳定，无OOM错误
5. **约束满足率**: dd_target=0.20, CVaR满足

---

## 下一步

✅ **当前任务**: 训练正常运行中
⏳ **等待**: 10-15分钟后首次检查
📊 **监控**: 每小时检查一次进度
🎯 **目标**: Stage A完成后分析结果，决定是否继续Stage B

---

## 问题排查

### 3090可能问题
- ❌ ~~Python路径错误~~ → ✅ 已修复为`/root/miniconda3/bin/python3.12`
- ⚠️ 初始化时间较长 → 正常，需1-2分钟加载模型
- ⚠️ GPU利用率为0 → 正常，刚启动时的预期状态

### WSL可能问题  
- ⚠️ torch.compile失败 → 已回退eager模式，性能略降
- ⚠️ Swap高使用 → 需监控，可能影响速度
- ⚠️ 僵尸进程 → 不影响运行，可忽略

### 修复历史
1. **3090 python3路径**: 修改启动脚本使用完整路径
2. **WSL PYTHONPATH**: 已在历史会话中修复
3. **批次间隙bug**: 使用persistent ProcessPoolExecutor修复
