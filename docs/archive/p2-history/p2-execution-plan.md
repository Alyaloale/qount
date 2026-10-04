# P2 训练阶段执行计划

> **归档状态**：historical / non-restorable evidence｜**整理日期**：2026-10-02
> **替代入口**：[当前架构与研究结果](../../p2-project-summary-20261002.md)；运行事实与权限仅看 [current.md](../../current.md)。
> 原文中的“当前”“最终”“通过”仅代表当时的记录，未经本轮重新验收；历史命令不构成重启、部署或交易授权。

> **状态**：active execution plan｜**日期**：2026-10-01  
> **阶段**：P2 容量搜索和策略训练（设计 §3.3, §11）  
> `research_only=true / orders_authorized=false / trial=false`

## 概述

P2 阶段使用**已完成的训练基础设施**进行容量搜索和策略训练。所有训练在生成世界中进行，不使用真实市场数据，不占用 trial。

## 已完成的基础设施（2026-10-01）

根据 `docs/etf-imitation-policy-design-2026-09.md` §11.1：

- ✓ P1 代码已完成：评分器、成本、约束、生成器、基线
- ✓ 1,000 世界验收：美股全部通过，A 股已完成先验修正
- ✓ P2 基础设施：特征计算、batched torch env、策略网络、训练循环
- ✓ C++ 内核 + ziglang：生成器性能优化（1,000 世界 22-24 秒）
- ✓ 算力实测：WSL RTX 4060 足够，单次更新约 3.6 秒

## P2 任务

### 两阶段容量搜索（§3.3）

**Stage A**：筛选阶段
- 16 个结构配置 × 2 种子
- 1/4 训练预算（150 episodes）
- 固定学习率 3e-4
- 选出遗憾值前 3 的结构

**Stage B**：精调阶段
- 前 3 结构 × 3 学习率 × 5 种子
- 完整预算（600 episodes）
- 学习率：[1e-4, 3e-4, 1e-3]
- 按 1-SE 规则选择最终配置

**搜索空间**：
```python
d_phi ∈ {16, 32}
hidden ∈ {16, 32, 64, 128}
layers ∈ {1, 2}
# 总共 16 种结构组合
```

**选择规则（1-SE rule）**：
在验证世界上，选择遗憾值在最优配置 1 个标准误以内的**最小**模型。这样可以防止大模型过拟合生成器。

### 训练协议（固定，§3.3）

- 每个世界：预热 10 年 + 交易 8 年
- 截断 BPTT：252 日一段，隐藏状态跨段传递
- 梯度裁剪：1.0
- 优化器：Adam
- 批量大小：256 个世界
- 约束目标：对偶上升自动调整 λ_dd, λ_cvar

### 时间估算（基于实测）

- 单次更新（256 世界 × 252 步）：约 3.6 秒
- 完整训练（约 4,800 次更新）：约 4.8 小时
- Stage A（16 × 2，150 episodes each）：约 48 小时（2 天）
- Stage B（3 × 3 × 5，600 episodes each）：约 216 小时（9 天）
- **总计：两个账户约 22 天**

可以并行训练多个配置来加速。

## 执行步骤

### 1. 环境准备（WSL）

```bash
# 同步代码到 WSL
bash scripts/sync-to-wsl.sh

# 设置 P2 训练环境（创建独立 venv + 安装 torch）
bash scripts/hosts/qount-wsl.sh shell -- 'cd ~/Code/qount && bash scripts/research/setup_wsl_p2_env.sh'
```

### 2. 运行容量搜索

#### 美股账户

```bash
# Stage A + B 一起运行
bash scripts/hosts/qount-wsl.sh shell -- 'cd ~/Code/qount && bash scripts/research/run_p2_capacity_search.sh us both 16 cuda'

# 或者分阶段运行
bash scripts/hosts/qount-wsl.sh shell -- 'cd ~/Code/qount && bash scripts/research/run_p2_capacity_search.sh us a 16 cuda'
# 等 Stage A 完成后
bash scripts/hosts/qount-wsl.sh shell -- 'cd ~/Code/qount && bash scripts/research/run_p2_capacity_search.sh us b 16 cuda'
```

#### A 股账户

```bash
bash scripts/hosts/qount-wsl.sh shell -- 'cd ~/Code/qount && bash scripts/research/run_p2_capacity_search.sh cn both 16 cuda'
```

### 3. 在 tmux 中运行长任务

```bash
# 进入 WSL
ssh qount-wsl

# 创建 tmux 会话
tmux new -s p2_us

# 激活环境并运行
cd ~/Code/qount
source p2_train_venv/bin/activate
bash scripts/research/run_p2_capacity_search.sh us both 16 cuda

# 分离：Ctrl+b d
# 重新连接：tmux attach -t p2_us
```

### 4. 监控进度

训练输出每个 episode 的 JSON 行：
```json
{"episode": 0, "updates": 32, "seconds": 115.2, "ann_log_return": 0.045, 
 "p95_max_dd": 0.087, "lambda_dd": 0.0, "lambda_cvar": 0.0, "kl": 0.012, ...}
```

结果保存在：
```
/mnt/e/qount_data/qount/artifacts/experiments/p2_capacity_search_YYYYMMDDTHHMMSS/
├── stage_a/
│   ├── phi16_h16_L1/
│   │   ├── seed20260930/
│   │   │   ├── meta.json
│   │   │   ├── history.json
│   │   │   └── model.pt
│   │   └── seed20260931/
│   └── ...
├── stage_b/
│   └── ...
├── stage_a_results.json
├── stage_b_results.json
└── selected_config.json  # 最终选定的配置
```

## 输出与验收

### Stage A 输出

```json
// stage_a_results.json
[
  {
    "config": {"d_phi": 32, "hidden": 64, "layers": 1, "lr": 3e-4},
    "mean_regret": 0.0842,
    "se_regret": 0.0021
  },
  ...
]
```

### Stage B 输出与最终选择

```json
// selected_config.json
{
  "config": {"d_phi": 32, "hidden": 64, "layers": 1, "lr": 3e-4},
  "mean_regret": 0.0756,
  "se_regret": 0.0015,
  "regrets": [0.0741, 0.0768, 0.0752, 0.0763, 0.0757]
}
```

### 进入 P3 的条件

- Stage A 和 Stage B 都成功完成
- 1-SE 规则成功选出最终配置
- 该配置的参数量和算力符合预期（1–3 万参数）
- 在生成世界上的遗憾值合理（相对 oracle 和 Bayes 基线）

## 注意事项

### 研究守卫（强制）

- `research_only=true`
- `orders_authorized=false`
- `trial=false`（不使用真实数据，不占 trial）
- 所有训练在生成世界中进行

### 数据边界

- **不读取**：账户、API 密钥、真实行情、paper state
- **只使用**：生成器参数、numpy 随机种子
- **写入位置**：外置盘 `/mnt/e/qount_data/qount/artifacts/`

### 算力使用

- WSL RTX 4060 8GB（默认）
- 显存峰值：约 1.2 GB（打包 1,280 世界）
- CPU：16 核用于世界生成（瓶颈在这里，不是 GPU）
- 不需要租用云 GPU（除非实测不足）

### 失败处理

如果 Stage A/B 训练失败：
1. 检查 `meta.json` 和 `history.json` 的最后几行
2. 确认是否是超时（而非错误）
3. 可以从中断点恢复（使用已完成的 episode）
4. 不要修改生成器或评分器后重试

## 后续步骤（P3）

P2 完成后，需要 owner 审批进入 P3：
1. 预登记冻结（配置、生成器、评分器、真实测试门槛）
2. 每个账户在真实历史上跑**一次**
3. 占用 trial：每个账户 1 个，全局到 153
4. 判定通过门槛（§9）
5. 通过后部署前瞻研究侧车（需 owner 授权）

## 参考文档

- 设计方案：`docs/etf-imitation-policy-design-2026-09.md`
- 当前状态：`docs/current.md`
- 主机边界：`docs/operations/host-runbooks.md`
- 存储拓扑：`docs/storage-topology.md`
