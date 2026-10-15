# qount 快速接手手册

> **状态**：active｜**权威**：接手导航；当前事实以 [current.md](current.md) 为准｜**最后更新**：2026-10-12
> **TL;DR**：按任务读取必要上下文，核对现有改动与证据后直接推进；默认离线研究，真实资金和生产服务按已有明确授权处理。

## 按任务读取

[AGENTS.md](../AGENTS.md)是行为、科研与权限总指引。项目上下文依次按需读取：

1. [current.md](current.md)：最新运行登记、owner 决定、冻结状态、预算和下一步。
2. [个人交易助手指南](personal-trading-assistant-guide.md)：研究目标、最小实验和策略评价方法。
3. [项目规则](project-rules.md)：代码归属、验证范围与文档维护。
4. 跨主机工作补读 [主机手册](operations/host-runbooks.md)；相关模块、研究线和证据从 [研究线导航](research-lines.md)进入。

小修复不需要读完全部研究报告。遇到数据流或模块边界问题再读 [系统架构](system-architecture-design.md)；历史任务清单与旧 README 不能覆盖 current。

## 接手后直接做什么

先查看 `git status --short`，用 `rg` 找相关代码、测试与工件，保留用户已有修改。确定当前要回答的问题，选择最低成本的有效修复或实验，执行必要验证并交付实际结果。实现方式不确定时先做小对照；只有关键权限、预算或目标缺失才请求澄清。

当前接续任务从 current 的最新记录取得。2026-10-12 已登记 S1/S2 和 S3-A/B/C 交付，后续是 S3-D 连续五个完整交易日的本地记录；另有 API／模拟流水／Tiingo 缓存的本地修复待部署与线上观察。离线样例不计入前向天数，本地修改不计作线上修复。

## 容易误读的边界

| 情况 | 正确读取方式 |
| --- | --- |
| 1–3 只核心资产、年换手 <0.5x、20% 年化 | 具体方案或探索目标；不构成全项目资产数、频率限制或收益保证 |
| 麒麟／币安合约旧旗舰数字，Q-DIV-Core 与 C60 梯度失败 | 依 current 保留撤销、失败和冻结身份；不能用通用研究许可复活 |
| Dual-Engine YTD、CTA-R／C60 前瞻 | 历史回放、真实记录后的前向与实盘收益分开，不能回填独立证据 |
| P3 R3 READY、已完成 pilot、云端环境 | 单轮授权已消费、outer withheld、云端暂停；旧工件不授权重启 |
| 指数代理、选股名单、模拟持仓、真实账户 | 数据用途与时点不同；不得相加或写成当前买入指令 |
| 看板刷新、API 健康、日报成功 | 分别核对数据新鲜度、研究证据和实际运行状态；服务健康不证明策略盈利 |

## 本地验证

验证随修改范围选择，详细命令见 [本地开发](operations/local-development.md)：

```bash
git status --short
PYTHONPATH=src ./.venv/bin/python scripts/maintenance/repository_hygiene.py check
git diff --check
```

纯文档主要检查相关链接、事实一致性和 Markdown；代码先运行受影响模块测试，核心逻辑或结构变动再扩大回归。区分已有失败与本次引入的问题，不虚报未执行的测试或远端检查。

## 主机与授权

Mac 管代码、Git、文档和轻量验证；WSL 承担范围与预算内的重计算；E 盘保存大数据与不可变工件；VPS 运行既有无订单模拟、只读看板、采集和通知。`ssh qount-wsl` 是连接入口，唤醒与挂载处理按 [主机手册](operations/host-runbooks.md)执行。

默认 `research_only=true / orders_authorized=false`。授权范围内的离线 paper、回测与仿真可以直接做；实盘下单、交易定时器、生产服务与账户配置变更须有 owner 明确授权。凭据不打印、不复制、不提交、不传 WSL／E 盘，Mac 私有配置保持 `0600`。

常用导航：[配置](reference/configuration.md) · [CLI 与脚本](reference/cli-and-scripts.md) · [代码地图](reference/repository-map.md) · [修补计划](research-repair-and-consolidation-plan-2026-10.md) · [历史归档](archive/README.md)。
