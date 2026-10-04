# WSL自动连续训练配置完成

> **归档状态**：historical / non-restorable evidence｜**整理日期**：2026-10-02
> **替代入口**：[当前架构与研究结果](../../p2-project-summary-20261002.md)；运行事实与权限仅看 [current.md](../../current.md)。
> 原文中的“当前”“最终”“通过”仅代表当时的记录，未经本轮重新验收；历史命令不构成重启、部署或交易授权。

**配置时间**: 2026-10-02 04:11  
**状态**: ✅ 自动训练脚本已启动并运行中

---

## 配置概览

### 自动训练流程

1. **监控当前训练** (进程PID 2507)
   - 每10分钟报告一次进度
   - 等待训练自然完成
   
2. **当前训练完成后**
   - 等待5秒
   - 自动启动完整Stage A+B训练

3. **新训练配置**
   - Stage A: 32配置 × 30 episodes
   - Stage B: 45配置 × 100 episodes
   - parallel=4, workers=8
   - 预计8-10小时完成

---

## 当前状态

### WSL训练进度

- **当前**: Episode 11/30 (36.7%)
- **剩余**: 19 episodes
- **预计完成**: 04:48 (38分钟后)
- **内存**: 12GB/15.8GB (76%)
- **负载**: 20.01

### 自动脚本状态

- **进程**: PID 4795 ✅ 运行中
- **日志**: `~/Code/qount/experiments/auto_continue.log`
- **监控**: 每10分钟报告进度

---

## 时间规划

### 当前训练 (Stage A首个配置)

- **开始**: 03:30
- **当前**: 04:11 (运行41分钟)
- **进度**: 11/30 episodes
- **预计完成**: 04:48

### 自动启动完整训练

- **开始**: ~04:48 (当前训练完成后)
- **内容**: Stage A (32配置) + Stage B (45配置)
- **预计时长**: 8-10小时
- **预计完成**: 12:48 - 14:48

### 您的休息时间

- **睡眠**: 04:15 - 12:15 (8小时)
- **训练状态**: 后台自动运行
- **醒来时**: 训练应已完成或接近完成

---

## 监控方式

### 查看自动脚本日志
```bash
ssh qount-wsl "tail -f ~/Code/qount/experiments/auto_continue.log"
```

### 查看当前训练进度
```bash
ssh qount-wsl "tail -1 ~/Code/qount/experiments/p2_us_full_wsl_20261002_033008/stage_a/phi16_h16_L1_lr3e-04/seed20260930/train.log | python3 -c 'import sys,json; d=json.load(sys.stdin); print(f\"Episode {d[\"episode\"]}/30\")'"
```

### 查看新训练进度（04:48后）
```bash
ssh qount-wsl "ls -lt ~/Code/qount/experiments/ | head -5"
ssh qount-wsl "tail -20 ~/Code/qount/experiments/p2_us_complete_auto_*/training.log"
```

---

## 双端训练状态

### WSL 4060 ✅ 自动训练已配置

- **当前**: Episode 11/30
- **自动脚本**: 运行中
- **预计完整完成**: 12:48 - 14:48
- **状态**: 可放心休息 ✅

### 3090服务器 ⚡ 优化配置运行中

- **状态**: 初始化中（运行8分钟）
- **配置**: parallel=5, workers=6
- **预计完成**: 10:27 - 13:03
- **状态**: 自动运行 ✅

---

## 成功标志

### 当前训练完成标志

- 进程PID 2507退出
- `auto_continue.log`显示"✓ 当前训练已完成！"

### 新训练启动标志

- 出现新目录: `experiments/p2_us_complete_auto_*`
- 新进程启动，PID记录在`train.pid`
- `training.log`开始写入

### 完整训练完成标志（醒来后检查）

- Stage A: 32个配置目录
- Stage B: 45个配置目录
- 所有配置都有30/100个episodes完成

---

## 异常处理

### 如果当前训练提前失败

- 脚本会检测到进程退出
- 立即启动新训练
- 查看`auto_continue.log`了解详情

### 如果新训练启动失败

- 检查`auto_continue.log`错误信息
- 手动启动训练:
```bash
ssh qount-wsl "cd ~/Code/qount && python3 scripts/research/etf_trader_parallel_search_optimized.py --account us --out experiments/p2_manual --stage-a-episodes 30 --stage-b-episodes 100 --batch-worlds 256 --parallel 4 --workers-factor 8.0 --device cuda"
```

### 如果内存不足

- WSL当前76%，有足够缓冲
- 完整训练配置相同，内存使用应相似
- 若OOM，脚本会自然停止，无需担心

---

## 醒来后检查清单

### 1. 检查训练状态
```bash
ssh qount-wsl "ps aux | grep python | grep etf_trader"
```

### 2. 查看完成进度
```bash
ssh qount-wsl "find ~/Code/qount/experiments/p2_us_complete_auto_*/stage_a -name 'train.log' | wc -l"
ssh qount-wsl "find ~/Code/qount/experiments/p2_us_complete_auto_*/stage_b -name 'train.log' | wc -l"
```

### 3. 检查约束满足
```bash
ssh qount-wsl "grep p95_max_dd ~/Code/qount/experiments/p2_us_complete_auto_*/stage_a/*/seed*/train.log | tail -20"
```

### 4. 查看3090状态
```bash
sshpass -p '[凭据已移出文档，认证仅从 Mac 私有配置读取]' ssh -p 41489 root@connect.nmb2.seetacloud.com "nvidia-smi && tail -20 /root/autodl-tmp/experiments/p2_us_optimized_20261002_040315/training.log"
```

---

## 预期结果

### 乐观情况（最可能）

- WSL: Stage A+B全部完成，12:48完成
- 3090: Stage A完成或接近完成
- 约束满足率: >95%
- 无OOM或崩溃

### 保守情况

- WSL: Stage A完成，Stage B进行中
- 3090: Episode 10-20/30
- 可能需要继续运行2-4小时

### 悲观情况（不太可能）

- 内存不足导致某些进程失败
- 但至少部分配置会完成
- 可以从失败处继续

---

## 文件和日志位置

### WSL

**自动脚本日志**:
```
~/Code/qount/experiments/auto_continue.log
```

**当前训练**:
```
~/Code/qount/experiments/p2_us_full_wsl_20261002_033008/
```

**新训练** (04:48后):
```
~/Code/qount/experiments/p2_us_complete_auto_20261002_HHMMSS/
├── stage_a/
├── stage_b/
├── training.log
└── train.pid
```

### 3090

**优化训练**:
```
/root/autodl-tmp/experiments/p2_us_optimized_20261002_040315/
├── stage_a/
├── monitoring/
├── training.log
└── train.pid
```

---

## 总结

✅ **WSL自动训练已配置**
- 监控脚本运行中
- 当前训练还需38分钟
- 完成后自动启动完整训练

✅ **可以安心休息**
- 所有训练在后台运行
- 8小时后醒来时应已完成或接近完成
- 所有日志和结果都会保存

✅ **双端训练进行中**
- WSL: 自动连续训练
- 3090: 优化配置训练
- 预计同时段完成

🎯 **醒来后检查**
- WSL完整训练结果
- 3090优化效果
- 约束满足率和性能对比

**祝休息愉快！训练会自动完成。** 😴
