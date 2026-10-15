# qount 样本使用与验证边界

> **状态**：active（通用原则与历史冻结合同分开）｜**权威**：研究验证参考；遵循 [AGENTS.md](../AGENTS.md)｜**最后更新**：2026-10-12
> **本文回答**：如何区分探索、验证与前向证据，以及旧样本池和准入门适用于哪里。
> **TL;DR**：已用于调参的数据不能再宣称独立检验；验证深度随结论强度提高，旧 ETH-only 的样本池与门槛不套用所有新研究。

## 通用研究原则

- 探索可以复用历史数据、快速消融和局部实验，但保留真实的样本使用身份。探索结果不能直接证明稳定样本外表现。
- 时间序列按时间切分；预处理、归一化、特征选择与标签构造不得泄漏未来。重叠标签按实际跨度采用 purge、embargo 或等价隔离。
- 验证集用于选择方案，测试集用于检验冻结方案。看过测试结果再选模型或调阈值，该样本已经被消费，后续结果按 discovery／selection 解释。
- 研究候选采用适用的 walk-forward、参数敏感性、随机种子与消融验证；与同时间窗、同成本口径的简单基准比较，披露失败窗口。
- 重要结论记录样本范围、标的、初始资金／规模、成本、收益与回撤、基准、搜索范围和关键限制；DSR/PBO 等方法按统计问题适用性选择，不设统一开工门。
- 前向记录从实际开始记录后的合格数据计入。回填数据与历史回放保留各自身份，不能延长独立前向窗口。

## 验证深度与冻结边界

最小实验用简短问题、配置和输出就可以开始；候选结论再补足可复现和样本外证据。数据缺口应限制受影响的结论，不成为所有离线研究的前置阻塞。一次实验失败后可分析原因、提出新机制，不能改写原失败或恢复 owner 明确封存的实现。

[current.md](current.md)记录的具体约束仍有效，例如清算级联的禁止提前读收益窗口、R3 outer withheld 和已消费的单轮训练授权。通用自主研究不解除这些限制；纸面交易与离线仿真也不授予生产部署或实盘订单权限。

## 历史 ETH-only 合同（2026-05-31）

以下保留原 `discovery_pool / validation_pool_v1 / G_paper / G_live` 正文，便于追溯旧工件。它定义的是当时 ETH-only 研究线，**不是当前所有策略的统一样本池、资产范围、样本数量或准入流程**。旧窗口的消费身份和适用冻结约束保留；新研究按本线数据使用记录划分样本，不能把“晚于 2026-06-01”视为今天尚未消费的独立样本。旧文中的 WSL live 检查及运行措辞不是现行主机职责或启动许可。

原合同创建时间：2026-05-31。下方“当前”均指原记录日期。

## 样本池

### discovery_pool

从 2026-05-31 起，以下所有已反复回看、调参、复扫、shadow proof 过的窗口都只能作为
`discovery` / `tuning` 样本：

```text
wf-feb27
wf-mar06
wf-mar11
wf-apr15
wf-may06
wf-may23
wf-may26
wf-may26pm
wf-may27am
wf-may27-latest
wf-may28-latest
wf-may29-latest
wf-may29-next
wf-may29-pm
wf-may29-afterpm
wf-may30-latest
wf-may30-postlatest
```

这些窗口可以继续用于：

- 形成假设
- debug 工具链
- 估算覆盖率、hold rate、candidate reason 分布
- 训练 discovery_pool 模型

这些窗口不能再用于：

- 宣称 promotion 通过
- 在调完阈值后再当 OOS
- 作为 `G_live` 或 once-only validation 证据

### validation_pool_v1

`validation_pool_v1` 从 2026-06-01T00:00:00Z 之后的新市场数据开始。原则：

- 先写假设、prompt/model/gate 版本和命令，再跑验证。
- 每个验证窗口只允许 once-only 读数；读数后调阈值会把该窗口降级回 `discovery`。
- artifact 必须写 `holdout_role=validation_v1`。
- `validation_v1` 只允许 forward paper 以前的研究验证，不等于 live 许可。

## Artifact 字段

新的研究命令必须记录：

```text
holdout_role=discovery | validation_v1 | unknown
```

默认是 `unknown`，但 promotion 级读数不能使用 `unknown`。

## Promotion Gate

原 G1/G2 的“窗口数 + 有成交窗口比例”在当前 ETH-only alpha 密度下不可达，因此拆成
`G_paper` 和 `G_live` 两级。

### G_paper

只允许进入 forward paper 评估，不允许 live。

```text
P1  只使用 holdout_role=validation_v1 的 artifact。
P2  累计 fresh traded 样本 >= 20。
P3  sum_realized_return_pct > 0。
P4  traded-sample-weighted avg_realized_return_pct > +0.10%。
P5  去掉贡献最大的单个窗口后，sum_realized_return_pct 仍 > 0。
P6  total_review_missed_candidate_move == 0。
P7  windows_with_open_positions == 0。
P8  相关代码有单测，本地和 WSL unittest 全绿。
P9  没有在 validation_v1 上调参后复用同一窗口。
```

### G_live

只有 `G_paper` 已通过并完成 forward paper 后才评估。

```text
L1  forward paper 样本完全晚于 discovery_pool 和 validation_pool_v1 的调参窗口。
L2  forward paper 上仍满足 G_paper 的 P2-P8。
L3  WSL preflight-live 通过。
L4  没有 unmanaged live position。
L5  live stop / rollback 规则已写进 current.md 或 quick-handoff.md。
L6  QOUNT_LIVE_ENABLE 仍由人工显式切换；任何研究命令不能切 live。
```

结论：截至 2026-05-31，当前状态仍是 `ETH-only research-only`。任何已看过窗口上的正收益
只能说明 discovery 假设存在，不能说明可 forward paper / live。
