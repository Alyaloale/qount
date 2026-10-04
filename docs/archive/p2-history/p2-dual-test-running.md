# P2 双端最小规模验证 - 运行状态

> **归档状态**：historical / non-restorable evidence｜**整理日期**：2026-10-02
> **替代入口**：[当前架构与研究结果](../../p2-project-summary-20261002.md)；运行事实与权限仅看 [current.md](../../current.md)。
> 原文中的“当前”“最终”“通过”仅代表当时的记录，未经本轮重新验收；历史命令不构成重启、部署或交易授权。

> **时间**：2026-10-02 06:35  
> **状态**：🟢 双端训练运行中  

---

## 当前运行状态

### ✅ 3090服务器
```
进程数：31个（主进程 + 30 workers）
GPU利用率：0%（初始化/编译阶段）
GPU显存：314 MB / 24 GB
Python：/root/miniconda3/bin/python3.12
日志：torch.compile enabled with mode=reduce-overhead
状态：✅ 正常运行
```

### ✅ WSL 4060
```
进程数：33个（主进程 + 32 workers）
Python：python3 + PYTHONPATH设置
日志：torch.compile failed, falling back to eager mode
状态：✅ 正常运行（eager mode）
```

---

## 测试配置

**测试规模**：
- 1个配置（phi16_h32_L1）
- 3个episodes
- 预计时间：20分钟

**3090配置**：
- Workers: 30
- Batch: 256
- Compile: reduce-overhead（已启用）

**WSL配置**：
- Workers: 32
- Batch: 256
- Compile: eager（编译失败回退）

---

## 进度预期

**时间线**：
```
06:35 - 训练启动
06:40 - Episode 0开始（含编译，预计6-8分钟）
06:48 - Episode 0完成
06:55 - Episode 1完成（约7分钟）
07:02 - Episode 2完成（约7分钟）
07:02 - 测试完成
```

**关键指标监控**：
- Episode速度
- GPU利用率
- 世界生成时间
- 无OOM错误
- C++引擎使用

---

## 监控命令

**实时日志**：
```bash
# 3090
sshpass -p '[凭据已移出文档，认证仅从 Mac 私有配置读取]' ssh -p 41489 root@connect.nmb2.seetacloud.com \
  'tail -f /root/autodl-tmp/experiments/p2_3090_test_*/train.log'

# WSL
ssh qount-wsl 'tail -f ~/Code/qount/experiments/p2_wsl_test_*/train.log'
```

**进度检查**：
```bash
# 3090最新episode
sshpass -p '[凭据已移出文档，认证仅从 Mac 私有配置读取]' ssh -p 41489 root@connect.nmb2.seetacloud.com \
  'tail -1 /root/autodl-tmp/experiments/p2_3090_test_*/train.log | grep episode'

# WSL最新episode
ssh qount-wsl 'tail -1 ~/Code/qount/experiments/p2_wsl_test_*/train.log | grep episode'
```

---

## 验证成功标准

### 功能性 ✓
- [x] 3090训练启动
- [x] WSL训练启动
- [x] 多进程workers运行
- [ ] 3 episodes完成

### 性能指标（待验证）
- [ ] Episode 0: 6-8分钟
- [ ] Episode 1-2: 6-7分钟
- [ ] GPU利用率 > 30%
- [ ] 无OOM错误

### 新功能验证（待验证）
- [ ] g_dd, g_cvar日志
- [ ] mean_turnover日志
- [ ] C++引擎编译成功
- [ ] Workers并行正常

---

## 已完成工作总览

### 代码优化（9个问题修复）
✅ 批次间隙消除  
✅ OOM保护  
✅ Workers优化  
✅ 对偶上界保护  
✅ 资源监控  
✅ 日志增强  
✅ 种子管理  
✅ 约束放松  
✅ C++引擎验证  

### 文件创建（17个）
- 8个脚本
- 3个代码文件
- 6个文档

### 预期效果
- Episode速度：-36%（基础优化）
- 总训练时间：58.7h → 37.4h

---

## 下一步

### 测试完成后（~30分钟）

1. **收集数据**
   - Episode实际速度
   - GPU利用率曲线
   - Workers效率
   - C++引擎日志

2. **评估结果**
   - 对比预期速度
   - 检查日志完整性
   - 确认无错误

3. **决策**
   - 如果成功：启动完整Stage A+B训练
   - 如果有问题：分析并修复

---

**更新时间**：2026-10-02 06:35  
**状态**：🟢 运行中，等待Episode 0完成  

`research_only=true / orders_authorized=false`
