# P2 训练调试状态

> **归档状态**：historical / non-restorable evidence｜**整理日期**：2026-10-02
> **替代入口**：[当前架构与研究结果](../../p2-project-summary-20261002.md)；运行事实与权限仅看 [current.md](../../current.md)。
> 原文中的“当前”“最终”“通过”仅代表当时的记录，未经本轮重新验收；历史命令不构成重启、部署或交易授权。

**时间**：2026-10-01 20:15  
**状态**：等待调试测试完成

---

## 当前情况

### ✅ 确认成功的部分
1. **torch.compile 启用**：`compiled: true`
2. **环境配置正确**：PyTorch + CUDA 正常
3. **训练开始**：meta.json 已创建
4. **并行脚本**：逻辑正确

### ⏳ 正在调试
**症状**：训练速度比预期慢
- 1 episode (32 世界) > 30 秒
- 预期应该是几秒钟

**可能原因**：
1. torch.compile 首次编译慢（JIT）
2. 世界生成慢
3. GPU 性能问题
4. CPU workers 瓶颈

### 🔍 已添加调试信息

修改了 `train.py` 添加时间分解：
```python
{
  "time_gen": X,      # 世界生成时间
  "time_tensor": Y,   # 转换为 tensor
  "time_env": Z,      # 创建环境
  "time_rollout": W,  # 训练循环
  "seconds": total    # 总时间
}
```

这样可以精确定位瓶颈。

---

## 当前运行的测试

### 测试 1：原始并行测试（已完成，部分失败）
- 任务：b0usrrdkb
- 结果：4个配置中有失败
- `compiled: true` 证明 torch.compile 工作

### 测试 2：单次调试测试（运行中）
- 任务：byxj9qvp2
- 配置：1 episode, 32 世界
- 目的：查看详细时间分解
- 预计：2-5 分钟完成

---

## 等待结果

### 如果世界生成慢（time_gen > 20s）
- 问题：CPU workers 不够或 C++ kernel 未生效
- 解决：增加 workers 或检查 C++ 编译

### 如果 rollout 慢（time_rollout > 30s）
- 问题：GPU 训练瓶颈
- torch.compile 第一次会慢，后续应该快
- 解决：等待后续 episodes 看是否加速

### 如果整体都慢
- 可能 RTX 4060 Laptop 比预期慢
- 调整预期时间或减少 batch_worlds

---

## 下一步（根据结果）

### 场景 A：第一个 episode 慢，后续快
✅ **这是正常的**（torch.compile 预热）
→ 继续完整搜索，时间估算仍然有效

### 场景 B：持续慢（>60s/episode）
❌ **需要调整策略**
→ 选项：
1. 降低 batch_worlds (256→128)
2. 减少 episodes (30/100 → 20/50)
3. 增加并行度补偿
4. 放弃 compile，纯并行

### 场景 C：速度合理（10-30s/episode）
✅ **可以接受**
→ 调整时间预期：3-5 小时（而不是 2.5小时）

---

## 文件位置

- 训练代码（带调试）：`src/qount/research/etf_trader/train.py`
- 并行脚本：`scripts/research/etf_trader_parallel_search.py`
- 测试输出：`/tmp/p2_test/`, `/tmp/debug_test/`
- 调试日志：`/private/tmp/claude-501/.../tasks/byxj9qvp2.output`

---

**当前动作**：等待 byxj9qvp2 任务完成，查看详细时间分解，然后决定策略。
