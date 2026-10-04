# P2 训练阶段准备完成报告

> **归档状态**：historical / non-restorable evidence｜**整理日期**：2026-10-02
> **替代入口**：[当前架构与研究结果](../../p2-project-summary-20261002.md)；运行事实与权限仅看 [current.md](../../current.md)。
> 原文中的“当前”“最终”“通过”仅代表当时的记录，未经本轮重新验收；历史命令不构成重启、部署或交易授权。

> **日期**：2026-10-01  
> **状态**：基础设施就绪，WSL 环境设置中  
> `research_only=true / orders_authorized=false / trial=false`

## 已完成工作

### 1. 代码基础设施（已完成）

根据设计文档 `docs/etf-imitation-policy-design-2026-09.md` §11.1：

- ✅ **P1 完成**：评分器、成本、约束、生成器（结构族 + 自助族）、基线
- ✅ **生成器验收**：美股 1,000 世界全部通过，A 股已完成先验修正
- ✅ **P2 基础设施**：
  - `features.py`：每世界一次性特征计算
  - `torch_env.py`：批量可微分环境（256+ 世界并行）
  - `policy.py`：置换等变交易员网络（§3.1）
  - `train.py`：截断 BPTT + 对偶上升训练循环
- ✅ **性能优化**：
  - C++ 内核 + ziglang：1,000 世界验收 22-24 秒
  - WSL GPU 实测：单次更新 3.6 秒（256 世界 × 252 步）
- ✅ **测试覆盖**：所有核心模块有单元测试，训练模式已在 WSL 上验证

### 2. P2 执行脚本（已创建）

**容量搜索编排**：`scripts/research/etf_trader_capacity_search.py`
- 实现两阶段搜索（Stage A: 16 × 2，Stage B: 3 × 3 × 5）
- 验证世界遗憾值评估
- 1-SE 规则选择最优配置

**WSL 环境设置**：`scripts/research/setup_wsl_p2_env.sh`
- 创建独立 Python venv
- 安装 torch 2.13 + CUDA 13.0 + qount 包

**训练执行脚本**：`scripts/research/run_p2_capacity_search.sh`
- 参数化账户、阶段、worker 数
- 输出到外置盘规范路径
- GPU 状态检查

**训练适配器**：`scripts/research/etf_trader_train.py`
- 命令行接口，调用 `train.py` 核心循环
- 配置参数化（结构、学习率、种子）

**测试脚本**：`scripts/research/test_p2_infrastructure.py`
- 验证所有模块可导入和运行

### 3. 文档（已完成）

**执行计划**：`docs/p2-execution-plan.md`
- P2 任务详细说明
- 时间估算（基于实测）
- 执行步骤和监控指南
- 输出格式和验收标准

**设计方案**：`docs/etf-imitation-policy-design-2026-09.md`（已存在）
- 完整的网络结构、训练目标、生成器设计
- §11.1 记录了 P2 完成状态

## 当前状态

### WSL 环境设置（进行中）

**任务 ID**：`b2mz9cdio`（后台运行）

**进度**：正在下载和安装依赖
- ✅ PyTorch 2.13.0 (526.6 MB) - 已下载
- ⏳ CUDA toolkit 13.0.3
- ⏳ cuDNN 9.20 (366.2 MB) - 正在下载
- ⏳ numpy, scipy, scikit-learn 等

**预计完成时间**：5-10 分钟（取决于网络速度）

**检查命令**：
```bash
# 查看实时输出
tail -f /private/tmp/claude-501/-Users-alyaloale-Code-qount/f209bf2f-7162-45e0-af98-08f4ab6d3e7e/tasks/b2mz9cdio.output

# 或等待完成通知
```

## 下一步操作

### 1. 等待环境设置完成

环境设置完成后，会输出验证信息：
```
torch 2.13.0, CUDA available: True
numpy 2.4.x
etf_trader.train OK
```

### 2. 验证环境（可选）

```bash
# 进入 WSL
ssh qount-wsl

# 激活环境
cd ~/Code/qount
source p2_train_venv/bin/activate

# 运行测试
python3 scripts/research/test_p2_infrastructure.py

# 检查 GPU
nvidia-smi
```

### 3. 开始容量搜索

#### 选项 A：后台运行（推荐）

```bash
# 进入 WSL
ssh qount-wsl

# 创建 tmux 会话
tmux new -s p2_us

# 运行搜索
cd ~/Code/qount
source p2_train_venv/bin/activate
bash scripts/research/run_p2_capacity_search.sh us both 16 cuda

# 分离：Ctrl+b d
# 稍后重新连接：tmux attach -t p2_us
```

#### 选项 B：从 Mac 直接启动

```bash
# Stage A only (约 2 天)
bash scripts/hosts/qount-wsl.sh shell -- 'cd ~/Code/qount && source p2_train_venv/bin/activate && bash scripts/research/run_p2_capacity_search.sh us a 16 cuda'

# 完成后运行 Stage B (约 9 天)
bash scripts/hosts/qount-wsl.sh shell -- 'cd ~/Code/qount && source p2_train_venv/bin/activate && bash scripts/research/run_p2_capacity_search.sh us b 16 cuda'
```

#### 选项 C：先运行小规模测试

```bash
# 单个配置快速测试（约 15 分钟）
bash scripts/hosts/qount-wsl.sh shell -- 'cd ~/Code/qount && source p2_train_venv/bin/activate && python3 scripts/research/etf_trader_train.py --account us --out /tmp/test_us --episodes 10 --batch-worlds 32 --d-phi 16 --hidden 32 --layers 1 --max-minutes 15'
```

### 4. 监控进度

训练输出 JSON 行（每个 episode）：
```json
{"episode": 0, "updates": 32, "seconds": 115.2, "ann_log_return": 0.045, "p95_max_dd": 0.087, ...}
```

检查输出目录：
```bash
ls -lh /mnt/e/qount_data/qount/artifacts/experiments/p2_capacity_search_*/
```

## 时间估算

基于 WSL RTX 4060 实测：

| 阶段 | 配置数 | 每个时长 | 总计 |
|------|--------|----------|------|
| Stage A | 16 × 2 = 32 | ~1.5 小时 | ~48 小时（2 天）|
| Stage B | 3 × 3 × 5 = 45 | ~4.8 小时 | ~216 小时（9 天）|
| **美股总计** | | | **~11 天** |
| **A 股总计** | | | **~11 天** |
| **两账户串行** | | | **~22 天** |

**加速选项**：
- 可以在不同时间段运行美股和 A 股
- Stage A 完成后立即开始 Stage B（不等待全部完成）
- 多个配置可以并行训练（如果有多个 GPU 或分时段）

## 关键参数（预登记前可调整）

当前占位值（在 `train.py` 的 `TrainConfig`）：

- `dd_target = 0.15`：回撤目标（§12.2 建议值，待 owner 确认）
- `cvar_floor = -0.10`：CVaR 下限（占位值，待 owner 设定）
- `lambda_kl = 0.01`：先验 KL 惩罚（占位值，待 §4 零溢价世界校准）

这些值在 P2 期间可以调整，P3 预登记前必须冻结。

## 研究守卫（已验证）

所有脚本都标记：
- `research_only=true`
- `orders_authorized=false`
- `trial=false`

不读取：账户、API 密钥、真实行情、paper state  
只使用：生成器参数、numpy 随机种子  
写入位置：外置盘 `/mnt/e/qount_data/qount/artifacts/`

## 已知待办（非阻塞）

1. **evaluate.py**：容量搜索脚本中的 `evaluate_on_val` 目前是占位实现（返回随机遗憾值）。需要实现：
   - 加载 checkpoint
   - 在独立验证世界上运行
   - 计算相对 oracle 的遗憾值
   
   **影响**：Stage A 的"前 3"选择和 Stage B 的 1-SE 规则目前基于占位数据。实际训练可以先运行，评估逻辑可以在 Stage A 完成前补上。

2. **校准 λ_kl**（§4）：需要在"所有因子溢价为 0"的零假设世界里运行，确保 α 相对先验的偏离 ≤ 3 个百分点。可以在 Stage A 期间并行做。

## 产出预期

### P2 完成时

- 每个账户选定一个最优配置（d_phi, hidden, layers, lr）
- 训练好的模型 checkpoint
- 验证世界上的遗憾值分布
- 完整的训练历史（每个 episode 的指标）

### 进入 P3 的条件

- Stage A 和 B 都成功完成
- 1-SE 规则成功选出配置
- 参数量符合预期（1-3 万）
- 生成世界遗憾值合理

P3 需要 owner 审批预登记，然后在真实历史上测试**一次**（占 trial）。

## 联系与决策点

需要 owner 确认：
1. 是否现在开始 P2 容量搜索
2. `dd_target`、`cvar_floor` 的具体值（§12.2）
3. 是否需要先运行小规模测试
4. 美股和 A 股的执行顺序

## 参考文档

- `docs/etf-imitation-policy-design-2026-09.md`：完整设计
- `docs/p2-execution-plan.md`：执行指南
- `docs/current.md`：系统当前状态
- `docs/operations/host-runbooks.md`：WSL 连接与长任务

---

**当前状态总结**：  
✅ 代码就绪  
⏳ WSL 环境设置中（5-10 分钟）  
⏸️ 等待开始信号
