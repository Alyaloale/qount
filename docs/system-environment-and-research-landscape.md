# qount 系统环境与研究全景手册

> **状态**：active｜**权威**：环境与研究导航；遵循 [AGENTS.md](../AGENTS.md) 与项目规则｜**最后更新**：2026-10-12
> **TL;DR**：按任务选择研究线与计算节点；完整数据和工件留 E 盘，凭据留授权位置，运行状态以 current 和有日期的证据核对。

## 一、研究与架构入口

[current.md](current.md)集中维护研究结论、owner 决定、冻结状态、资源预算与下一步。本页不维护第二份收益、部署或训练进度表。

| 问题 | 阅读入口 |
| --- | --- |
| 如何设计最小实验，比较规则、Transformer、RL 或配置策略 | [个人交易助手指南](personal-trading-assistant-guide.md) |
| 某条线的当前决定、源码与原结果在哪里 | [研究线导航](research-lines.md)，再核对 current |
| 数据怎样进入模型、助手、API 和执行层 | [架构主设计](system-architecture-design.md) |
| 原修补任务有哪些依赖 | [修补整理计划](research-repair-and-consolidation-plan-2026-10.md)，进度以 current 最新记录为准 |
| 如何避免测试集污染，怎样使用旧 holdout | [验证边界](holdout.md) |
| 代码归属、测试范围和文档维护 | [项目规则](project-rules.md)、[本地开发](operations/local-development.md) |

资产数量、频率、集中度和模型方法由经济假设与实验证据决定。旧失败实现与明确冻结线保留原裁决；新研究不继承旧 promotion 资格。formal trial、参数候选、曲线与模型 fit 是不同计数，不直接相加。

## 二、主机与存储职责

| 节点 | 稳定入口 | 责任与边界 |
| --- | --- | --- |
| Mac | `/Users/alyaloale/Code/qount` | 代码、Git、设计、文档、轻量实验与编排；不长期保存海量数据或执行生产交易 |
| Windows E | `E:\qount_data\qount`，WSL 为 `/mnt/e/qount_data/qount` | 大规模公开输入、完成工件与备份；不保存凭据、虚拟环境或活跃 SQLite |
| WSL | `/home/alyaloale/Code/qount`，`ssh qount-wsl` | CPU/GPU 训练、特征计算与深度回测；遵守任务预算，不存凭据或声明实盘事实 |
| VPS | `/root/qount` | 既有采集、无订单模拟、只读账户、看板与通知；服务变更按明确授权处理 |

硬件、内存额度、挂载类型和服务状态可能变化；执行依赖它们的任务前做有界核对，不把旧配置快照当作当前可用容量。先用现有缓存与小实验获取信息，再决定是否扩大计算。云端暂停和已消费的单轮训练授权以 current 为准。

连接、唤醒、同步与长任务操作统一在 [主机手册](operations/host-runbooks.md)，目录和工件归属见 [存储拓扑](storage-topology.md)。不在多份指南重复维护 SSH 地址和恢复命令。

## 三、配置与凭据

- 项目 Python 版本要求以 [pyproject.toml](../pyproject.toml) 为准，当前声明 `>=3.11`；不同计算环境另核对各自环境锁，不统一宣称全部主机为 Python 3.12。
- 非密环境变量名和主机合同维护于 [environment-contract.toml](../config/environment-contract.toml)；hygiene 检查可发现未登记引用，但不能替代凭据隔离或泄漏检查。
- Mac 本地私有 `.env` 及 `~/.config/qount/tushare.env` 保持 `0600`。凭据不打印、不复制、不提交、不导出或同步至 WSL／E 盘；公开响应按任务范围脱敏后归档。
- 研究参数与来源写入相应配置，冻结结果和代码版本不能原地覆盖。共享 API 的请求预算、缓存与退避须跨消费者核对，Tiingo 项目预算见 [项目规则](project-rules.md#6-数据主机与凭据)。

需要配置预检时，在对应已准备好的本地环境使用：

```bash
qount-run config-check --profile mac
```

该预检不联网且隐藏值；普通文档、离线计算与单元测试无需先加载凭据。

## 四、常见问题的定位顺序

| 现象 | 先查什么 | 后续处理 |
| --- | --- | --- |
| `/mnt/e` 不可用或 `No such device` | Windows 是否看到盘、WSL SSH 与训练进程所处挂载命名空间 | 依主机手册确认数据消费者与授权再恢复挂载，不强制卸载正在使用的盘，不写入替代目录 |
| WSL SSH 超时／offline | Tailscale、WSL 在线状态与已有 keepalive 任务 | `ssh qount-wsl` 是普通连接；helper 的 `ensure` 可唤醒节点，但不修复所有挂载问题 |
| 网络切换后 SSH 挂起 | Tailscale 路由、代理接管与过期 ControlMaster | 按主机手册处理连接；不顺带修改共享代理或 VPS 服务 |
| 看板数字陈旧／缺失 | 原工件时点、适配结果、摄取记录和部署版本 | 重新发布不等于来源更新；缺源显示未知，不填预置数字 |
| 回测异常高收益或样本外下降 | 信息时钟、股票池、数据切分、成本、会计、奖励与动作空间 | 固定其余条件做小对照；保留失败，不先扩大搜索或建立无关门禁 |
| 配置或日志出现秘密 | 立即停止回显与传播，确定泄漏位置 | 敏感权限变更按授权处理；不能把环境合同检查通过当作无泄漏证明 |

`ensure` 的自愈范围以 [脚本](../scripts/hosts/qount-wsl.sh)与[主机手册](operations/host-runbooks.md)为准；它没有自动卸载／重挂 E 盘的实现。需要涉及共享挂载、生产服务或新增权限时，先核对现有授权与使用状态。

## 五、报告证据

交付区分本地实现、实际运行、已验证范围与已部署状态。新 API、适配器或缓存源码不能证明线上已更新；单元测试不证明交易可成交，前向工程记录不证明盈利。保留关键配置、命令、输入版本和输出位置即可，不为每次小改动增加一份长报告。
