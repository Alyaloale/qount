> **状态**：historical navigation / superseded｜**更新时间**：2026-10-02

> **归档状态**：historical / non-restorable evidence｜**归档日期**：2026-10-02
> **替代入口**：[当前架构与研究结果](../../../p2-project-summary-20261002.md)；运行事实及权限仅看 [current.md](../../../current.md)。
> 保留现存正文用于追溯，旧时点状态、预计完成时间和历史命令不是当前结论或重启授权。
> 以下为早期监控改动记录。时间估计和训练状态不是当前事实；最新核查见
> [研究主文档](../../../p2-project-summary-20261002.md)及 [current.md](../../../current.md)。

# 最近更新

快速了解最近的重要改动和当前状态。

---

## 2026-10-02: P2 训练监控与保存改进

### 问题
- GPU 利用率周期性归零（每 15-20 分钟）
- 训练过程无进度显示
- 无中间保存，训练中断会丢失所有结果
- 无法评估训练性能（loss、收益、回撤）

### 解决方案
1. **持久化进程池** — 从 `mp.Pool` 改为 `ProcessPoolExecutor` + `as_completed`
2. **实时日志** — 使用 `Popen` 流式写入 `train.log`
3. **自动 checkpoint** — 每 10 episodes 保存 `checkpoint_ep{N}.pt`
4. **监控脚本** — `monitor_training_progress.py` 汇总所有训练进度

### 修改文件
- `scripts/research/etf_trader_parallel_search.py` — 持久化进程池 + 实时日志
- `src/qount/research/etf_trader/train.py` — 添加 checkpoint
- `scripts/research/monitor_training_progress.py` — 新增监控脚本

### 使用方法
```bash
# 启动训练
cd /root/autodl-tmp
nohup python scripts/research/etf_trader_parallel_search.py \
  --account us --out experiments/p2_us_20261002 \
  --stage-a-episodes 30 --stage-b-episodes 100 \
  --parallel 16 --workers 20 --batch-worlds 256 \
  > train.log 2>&1 &

# 实时监控
python scripts/research/monitor_training_progress.py experiments/p2_us_20261002

# 查看单个训练
tail -f experiments/p2_us_20261002/stage_a/phi16_h16_L1_lr3e-04/seed20260930/train.log
```

### 输出结构
```
experiments/p2_us_20261002/
└── stage_a/
    └── phi16_h16_L1_lr3e-04/
        └── seed20260930/
            ├── meta.json           # 配置
            ├── train.log           # 实时日志
            ├── checkpoint_ep10.pt  # Episode 10 checkpoint
            ├── history_ep10.json   # Episode 0-10 历史
            ├── checkpoint_ep20.pt  # Episode 20 checkpoint
            ├── history_ep20.json   # Episode 0-20 历史
            ├── model.pt            # 最终模型
            └── history.json        # 完整历史
```

### 相关文档
- [p2-monitoring-improvements.md](../p2-monitoring-improvements.md) — 详细设计和实现
- [p2-execution-guide.md](../p2-execution-guide.md) — 执行指南
- [current.md](../../../current.md) — 更新了最新状态

### 预估时间
- Stage A（32 训练 × 30 episodes）: ~2 小时
- Stage A + B: ~5 小时

### 注意事项
- GPU 利用率 5-20% 是**正常的**（RL 训练 CPU-bound）
- torch.compile 首次编译需要 5-10 分钟
- 服务器信息记录在 `.claude/projects/-Users-alyaloale-Code-qount/memory/p2-3090-server.md`

---

## 如何快速接手

### 1. 查看当前状态
```bash
# 读取最新状态
cat docs/current.md | head -50

# 查看最近更新
cat docs/RECENT_UPDATES.md
```

### 2. 检查服务器训练
```bash
# SSH 连接（密码在 memory 文件中）
ssh -p 41489 root@connect.nmb2.seetacloud.com

# 查看训练进程
ps aux | grep etf_trader

# 查看 GPU 状态
nvidia-smi

# 查看最近的日志
tail -f /root/autodl-tmp/train.log
```

### 3. 分析训练结果
```bash
# 检查完成的训练
find /root/autodl-tmp/experiments -name "model.pt"

# 查看 checkpoint
find /root/autodl-tmp/experiments -name "checkpoint*.pt"

# 读取训练历史
cat experiments/.../history.json | jq '.[].ann_log_return'
```

---

## 项目文档结构

### 核心文档（必读）
- [current.md](../../../current.md) — 当前状态（L1 权威）
- [AGENTS.md](../../../../AGENTS.md) — Agent 协作规则
- [CLAUDE.md](../../../../CLAUDE.md) — Claude 接手入口
- [RECENT_UPDATES.md](RECENT_UPDATES.md) — 本文件，最近更新

### P2 训练相关
- [p2-execution-guide.md](../p2-execution-guide.md) — 执行指南
- [p2-monitoring-improvements.md](../p2-monitoring-improvements.md) — 监控改进详解
- [p2-optimization-final-summary.md](../p2-optimization-final-summary.md) — 优化历程
- [p2-hardware-analysis.md](../p2-hardware-analysis.md) — 硬件分析

### 其他研究
- [qount_strategy_master_index.md](../../../qount_strategy_master_index.md) — 策略总览
- [research-advancement-roadmap.md](../../../research-advancement-roadmap.md) — 研究路线图

### 操作手册
- [operations/local-development.md](../../../operations/local-development.md) — 本地开发
- [operations/host-runbooks.md](../../../operations/host-runbooks.md) — 主机运维手册

---

## Git 提交建议

### 本次改动
```bash
# 添加所有改动
git add scripts/research/etf_trader_parallel_search.py
git add src/qount/research/etf_trader/train.py
git add scripts/research/monitor_training_progress.py
git add docs/p2-monitoring-improvements.md
git add docs/p2-execution-guide.md
git add docs/current.md
git add docs/RECENT_UPDATES.md

# 提交
git commit -m "feat(etf_trader): add real-time monitoring and checkpoint support

- Persistent process pool (ProcessPoolExecutor + as_completed) to eliminate batch gaps
- Real-time logging with Popen streaming to train.log
- Auto checkpoint every 10 episodes (checkpoint_ep{N}.pt + history_ep{N}.json)
- New monitor_training_progress.py to aggregate all training status
- Update docs: p2-monitoring-improvements.md, p2-execution-guide.md, current.md

Fixes GPU idle gaps and enables progress tracking for 5-hour training runs.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## 联系与授权

所有改动已按 CLAUDE.md 规则进行：
- ✅ 研究模式 (`research_only=true`)
- ✅ 无订单授权 (`orders_authorized=false`)
- ✅ 不触碰真实账户、VPS 生产环境
- ✅ 所有改动在本地完成并测试
- ✅ 文档完整更新

需要 owner 授权的操作：
- [ ] 推送到 main 分支
- [ ] 部署到生产服务器
- [ ] 启动真实账户训练
