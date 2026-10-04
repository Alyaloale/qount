# R3 残差训练引擎

`research_only=true / orders_authorized=false / holdout_role=discovery`

这是 P3 §21 残差方案的独立实现；开训前复审和改进取舍见 [P3 §23](../../../docs/etf-p3-research-plan-2026-10.md#23-r3开训前复审修正与创新取舍2026-10-03)。部署与数据准备已获授权；真正训练必须等 owner 后续明确说“训练”。公开代码装入独立 WSL ext4 目录，使用已有独立 Torch2.13/cu130 环境；准备数据、源码快照、环境记录和最终结果归 E 盘。不得加载或传输 `.env`，不得改服务、定时器、P2 或云端任务。

## 部署和准备

在 Mac 用 `PYTHONPATH=src .venv/bin/python scripts/research/etf_alpha_residual.py pack --contract config/etf-alpha-residual-reviewed-20261003.json --out NEW_PUBLIC_CODE.tar.gz` 生成公开白名单包。按整包及逐文件 manifest 验证后安全解包到新的 WSL 代码目录。不要覆盖旧 v2 代码或结果。原 `etf-alpha-residual-ready-20261003.json` 和 §22 待命包保留为首版实施证据；当前使用 schema-v2 复审合同，绑定原提案及首版合同 hash。

在该 WSL 目录，设置 `PYTHONPATH=src`，使用 `/home/alyaloale/.cache/qount-compute/venvs/etf-alpha-20261003/bin/python`：

```bash
python scripts/research/etf_alpha_residual.py prepare --contract config/etf-alpha-residual-reviewed-20261003.json --out /mnt/e/qount_data/qount/artifacts/etf_alpha_p3/NEW_READY
python scripts/research/etf_alpha_residual.py check --ready /mnt/e/qount_data/qount/artifacts/etf_alpha_p3/NEW_READY
python scripts/research/etf_alpha_residual.py status --path /mnt/e/qount_data/qount/artifacts/etf_alpha_p3/NEW_READY
```

实际命令须用上述 venv Python 的完整路径。`prepare` 验证六个冻结输入和原切分，生成九个 inner / 七个 final 数据槽，检查目标与两种打乱置换，保存训练期均值、中心化量与尺度。final 数据槽不保存 outer 标签。CUDA 数值探针只前向/反向，权重不变，optimizer steps=0，不生成模型。`READY.json` 与 manifest 完成后即为 `ready_waiting_owner`。

当前准备位置、代码位置及 fingerprints 以 `docs/current.md` 和 Mac 的 `latest-ready.json` 指针为准。准备失败必须保留失败目录，修复后用新目录重做，不将半成品声明为 ready。

## 后续启动

owner 后续明确说“训练”时，将该决定登记到 `docs/current.md`，再次 `check`，写入新激活回执，再运行：

```bash
python scripts/research/etf_alpha_residual.py launch --ready READY_DIRECTORY --authorization NEW_OWNER_ACTIVATION.json --out /mnt/e/qount_data/qount/artifacts/etf_alpha_p3/NEW_RUN
```

激活 JSON 必须含 `training_start_authorized=true`、`owner_instruction="训练"`（也接受“开始训练”/“启动训练”）、`decision_reference="docs/current.md"`、晚于 READY 的带时区 `issued_at`、新的 `activation_nonce`，以及 `check` 返回的 `ready_directory/prepared_manifest_sha256/runtime_contract_sha256/deployment_manifest_sha256`，并将 `output_directory` 绑定到这次新结果目录。部署指令、等待文字和旧 v2 授权均不能代替回执。仓库和公开交付包中不提供可用的预授权回执。

`launch` 启动脱离 SSH 的单次 supervisor，保存 sibling `.launch.json/.pid.json/.supervisor.log/.exit.json`。不安装常驻监听、tmux 待命任务、调度器或自动重试。重复启动由新目录占用和共享 `/home/alyaloale/.cache/qount-compute/locks/etf-alpha-cuda.lock` 拒绝；失败/中断不自动续训。

前三个 inner 槽共 51 fits：45 神经 / 6 确定性 Ridge。无合格增量则 `pilot_no_increment`，outer 保持 withheld，任务正常退出。通过则复用 pilot，补齐九个 inner 槽，在 153 fits 后冻结全部七年选择及每 seed 的 final epochs，再完成七个 final 槽，总计至多 272 fits（240 神经 / 32 Ridge，含 pilot）。十 seed 扩展仍未授权。

## 固定实现与观测

共享 8→16→1 GELU/dropout0.1 模型恰为 161 参数；不含资产 ID 或市场 encoder。AdamW matrix weight decay0.001，bias 不衰减，betas0.9/0.999、epsilon1e-8，grad clip1，FP32、TF32/AMP/compile 关闭。checkpoint 只用 preceding year 的残差 Huber；final 只用已冻结 epochs。20 日标签 end 严格早于下一分区开始减五个 session；inner 评估尾部标签也须在下一年之前已实现。全年交易日保留。全球 21 日再平衡相位固定为数据中首个 2015 session，inner/outer 使用同一相位。

时间对照联合移动全部资产标签/掩码，60 日完整日期块排列。复审合同要求每个标签日期至少移动 25 个交易日（20 日标签＋5 日间隔），同时满足零原日期配对；拒绝不完整尾块造成的近日期重叠，并保存实际最小位移回执。强对照再逐块独立排列八个非 SPY 资产列。选择只读 outer 年之前三个 inner 年，MLP 先平均五份预测再执行连续账本。各年预测先按原连续日期拼接，再执行一个账户；年末收盘使用当年的预测，在次年开盘成交，不跳过边界再平衡或提前使用新年模型。信号区间为固定 500 次日期块扰动，winner 稳定性固定 400 次；40/60/120 日块均须合格。全部选模、epoch 与 gate 在 outer 发布前冻结，不因 test 结果追加试验。

确定性 Ridge 的逐年配对证据落实为至少2/3过去 inner 年相对 Ridge 时间空对照的残差 RankIC 增量为正，另须通过 pooled 增量及三种区间门；不制造五seed投票。MLP 保持五seed的逐对照共识门。

运行日志含 `status.json/events.jsonl`、每 fit 的输入绑定、置换回执、`history.json/best.pt/last.pt/fit.json`、预测、验证选择、outer 1×/2×/3× 连续曲线和指标、`REPORT.md/summary.json/manifest.json`。手动 SIGINT/SIGTERM 会保存当前 partial checkpoint 并退出；未设置整轮时间上限。`status --path RUN` 可读进度。结果仍是 discovery research，不能影响生产。
