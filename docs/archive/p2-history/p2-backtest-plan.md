# P2 ETF Trader 回测计划

> **归档状态**：historical / non-restorable evidence｜**整理日期**：2026-10-02
> **替代入口**：[当前架构与研究结果](../../p2-project-summary-20261002.md)；运行事实与权限仅看 [current.md](../../current.md)。
> 原文中的“当前”“最终”“通过”仅代表当时的记录，未经本轮重新验收；历史命令不构成重启、部署或交易授权。

## 当前状态

### 训练完成情况

**WSL 4060**: 22个配置完成（30 episodes）
**3090云端**: 1个配置进行中（phi32_h16_L2, Episode 18/100）

### 已启动回测

**运行中**: phi32_h32_L2_lr3e-04 (seed 20260930) 在WSL上回测
- 期间: 2015-01-01 to 2023-12-31
- 后台任务ID: bv3ore5cs
- 使用完整的 `env.simulate()` 引擎

## 回测框架

### 已有引擎

`src/qount/research/etf_trader/env.py:simulate()`
- 完整的日频回测引擎
- 考虑交易成本、滑点、约束
- 支持T+0/T+1规则
- 支持停牌、涨跌停限制

### 创建的脚本

1. **scripts/research/etf_trader_backtest_real.py**
   - 在真实历史数据上回测单个模型
   - 使用完整的`env.simulate()`引擎
   - 输出完整性能指标
   - 与60/40基准对比

2. **scripts/research/batch_backtest_p2.sh**
   - 批量回测所有22个已完成配置
   - 自动生成汇总报告
   - 按Sharpe比率排序

## 当前限制

### Policy实现简化

当前`TorchModelPolicy`是placeholder：
```python
# 当前：返回持仓（不交易）
return Decision(target=None, band=0.0, kappa=1.0)

# 需要：完整实现
# 1. 构造WorldFeatures（价格、成交量、技术指标等）
# 2. 调用model.forward(obs, h)获取权重
# 3. 返回目标权重
```

**结果**: 当前回测实际上是"买入持有"策略，不是真实的模型策略。

### 完整实现需要

1. **WorldFeatures构造**
   - 从`features.py`中的`world_features()`
   - 需要真实市场数据的完整特征

2. **模型推理**
   ```python
   features = world_features(data, t)  # 构造特征
   obs_tensor = torch.from_numpy(features)
   alpha, h_next = model(obs_tensor, h)  # 模型输出
   weights = softmax_with_constraints(alpha)  # 转换为权重
   ```

3. **真实数据预处理**
   - 计算技术指标（MA, RSI等）
   - 计算横截面特征（相对强弱等）
   - 标准化和归一化

## 回测指标

### 性能指标
- Total Return: 总收益
- Ann. Log Return: 年化对数收益
- Ann. Volatility: 年化波动率
- Sharpe Ratio: 夏普比率
- Max Drawdown: 最大回撤

### 交易指标
- Avg Turnover: 平均换手率
- Total Costs: 总交易成本
- Voluntary vs Forced Turnover

### 基准对比
- 60/40组合（SPY 60% + IEF 40%）
- 标普500（SPY）
- 等权组合

## 数据可用性

### 真实历史数据

`data/raw/` 目录包含：
- SPY, QQQ, IWM (美股大中小盘)
- EFA, EEM (发达/新兴市场)
- IEF, TLT (债券)
- GLD (黄金)
- DBC (商品)
- 其他杠杆ETF (TQQQ, UPRO等)

**时间范围**: 不同ETF起始时间不同
- SPY: 1993年起
- QQQ: 1999年起
- 多数: 2010年后

**建议回测期间**: 2015-2023 (数据最完整)

## 下一步

### 短期（验证概念）

1. ✅ 等待当前回测完成
2. ⏳ 检查结果是否合理
3. ⏳ 如果是"持仓"策略，确认框架正确

### 中期（完整实现）

1. **实现完整Policy**
   - 从`train.py`提取特征构造逻辑
   - 实现`world_features()`的真实数据版本
   - 完整的模型推理流程

2. **批量回测所有模型**
   - 22个已完成配置
   - 2个种子各一个
   - 生成完整对比报告

3. **分析结果**
   - 识别最佳配置
   - 真实数据 vs 训练数据对比
   - 过拟合检查

### 长期（生产化）

1. **Walk-forward分析**
   - 滚动训练和测试
   - 验证时间外推广泛性

2. **交易成本敏感性**
   - 不同成本假设下的表现
   - 优化换手率

3. **风险分析**
   - 不同市场regime下的表现
   - 压力测试（2008, 2020等）

## 预期结果

### 如果回测显示买入持有

**当前限制**: Policy未实现，默认持仓
**结果**: 类似等权组合
**预期**: 8-10%年化收益，15-20%回撤

### 完整实现后

**训练表现**: 6.26%年化对数收益
**真实数据预期**: 可能更低（样本外）
- 乐观: 6-8%
- 现实: 4-6%
- 悲观: <4%（接近无风险利率）

**关键问题**: 训练用的是模拟数据，真实数据的分布可能不同。

## 技术债务

1. **WorldFeatures适配**
   - 训练用的是生成的世界
   - 需要将真实市场数据转换为相同格式

2. **特征不匹配**
   - 模拟数据的特征可能不存在于真实数据
   - 需要特征工程适配

3. **成本模型校准**
   - 训练用的成本参数需要在真实数据上验证

## 总结

**现状**: 框架就绪，等待第一个回测结果
**限制**: Policy实现是placeholder，需要完整实现才能真正测试模型
**计划**: 先验证框架，再完整实现，最后批量评估所有模型

---

**更新时间**: 2026-10-02 14:50
**后台任务**: bv3ore5cs (phi32_h32_L2回测中)
