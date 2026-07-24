# qount Holdout 与 Promotion Gate

> **状态**：active（冻结边界）｜**权威**：L1 验证边界｜**最后更新**：2026-05-31
> **本文回答**：discovery_pool / validation_pool_v1 与 G_paper / G_live 的边界与 once-only 规则。
> **TL;DR**：已看过窗口只算 discovery；promotion 必须从 validation_pool_v1 once-only 验证。

创建时间：2026-05-31

这份文档冻结 research-only 工作的发现/验证边界。它不替代
[current.md](current.md)，只定义后续实验如何避免把已经看过的窗口继续当验证样本。

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
