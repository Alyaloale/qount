# P2 双端完整训练 - 启动记录

> **归档状态**：historical / non-restorable evidence｜**整理日期**：2026-10-02
> **替代入口**：[当前架构与研究结果](../../p2-project-summary-20261002.md)；运行事实与权限仅看 [current.md](../../current.md)。
> 原文中的“当前”“最终”“通过”仅代表当时的记录，未经本轮重新验收；历史命令不构成重启、部署或交易授权。

> **启动时间**：2026-10-02 07:05  
> **状态**：🟢 双端训练已启动  

---

## 训练配置

### 3090服务器
```
Stage A: 32 configs × 30 episodes
Stage B: 45 configs × 100 episodes
Parallel: 10
Workers: 30 (workers-factor=3.0)
Batch: 256
预计时间: 8-10小时
```

### WSL 4060
```
Stage A: 32 configs × 30 episodes  
Stage B: 45 configs × 100 episodes
Parallel: 4
Workers: 32 (workers-factor=8.0)
Batch: 256
预计时间: 10-12小时
```

---

## 监控系统

### GPU监控（10秒间隔）
- utilization.gpu
- utilization.memory
- memory.used/total
- temperature
- power.draw

### 系统监控（30秒间隔）
- CPU使用率
- 内存使用量
- 内存使用率

---

## 监控命令

### 实时日志
```bash
# 3090
sshpass -p '[凭据已移出文档，认证仅从 Mac 私有配置读取]' ssh -p 41489 root@connect.nmb2.seetacloud.com \
  'tail -f /root/autodl-tmp/experiments/p2_us_full_*/training.log'

# WSL
ssh qount-wsl 'tail -f ~/Code/qount/experiments/p2_us_full_wsl_*/training.log'
```

### 综合监控
```bash
cd /Users/alyaloale/Code/qount
bash scripts/research/monitor_dual_training.sh
```

### GPU状态
```bash
# 3090
sshpass -p '[凭据已移出文档，认证仅从 Mac 私有配置读取]' ssh -p 41489 root@connect.nmb2.seetacloud.com \
  'tail -f /root/autodl-tmp/experiments/p2_us_full_*/monitoring/gpu_monitor.csv'

# WSL
ssh qount-wsl 'tail -f ~/Code/qount/experiments/p2_us_full_wsl_*/monitoring/gpu_monitor.csv'
```

---

## 预期时间线

**3090**：
```
07:05 - 启动
07:20 - Stage A开始
08:50 - Stage A完成（预计1.5小时）
15:50 - Stage B完成（预计7小时）
总计：8.75小时
```

**WSL**：
```
07:05 - 启动
07:20 - Stage A开始
09:20 - Stage A完成（预计2小时）
17:20 - Stage B完成（预计8小时）
总计：10小时
```

---

## 成功标准

### 功能性
- [ ] 无OOM错误
- [ ] 无进程崩溃
- [ ] checkpoint正常保存
- [ ] 日志完整

### 性能
- [ ] Episode速度稳定在1-2分钟
- [ ] GPU利用率 > 30%
- [ ] 无明显减速

### 约束
- [ ] 约束满足率 > 50%
- [ ] 对偶变量健康（< 50）
- [ ] 回撤在合理范围

---

**启动人**：Claude Fable 5.1  
**状态**：🟢 运行中，等待监控数据  

`research_only=true / orders_authorized=false`
