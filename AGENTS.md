# qount agent guide (AI 个人量化交易助手开发指引)

> **Status:** active repository guidance. **Current facts:** [docs/current.md](docs/current.md) is the only current source of truth.

`qount` 是一个面向**个人实战盈利**的 AI 个人量化交易助手系统（支持 Mac 本地、WSL 算力、Windows E 盘存储多主机协作）。

---

## 🎯 核心定位与 Vibe Coding 原则

1. **唯一根本目标：个人实战盈利**
   - 策略研发必须以个人交易者（Retail/Prop Trader）的账户现实为出发点：追求**资金复利增长、绝对收益、极低交易摩擦与大回撤控制**。
   - **坚决拒绝公募基金式的学术形式主义**：个人账户资金有限，不做 20 只个股强行切碎分散、行业配额上限或过度调仓的复杂模拟。
2. **个人交易者的实战优势（“船小好掉头”）**
   - **标的精选集中**：专注于 1~3 只核心高流动性标的（如 沪深300ETF、红利低波ETF、跨境ETF、或主流加密资产 BTC/ETH）。
   - **大周期趋势择时**：多头趋势（如 MA200/MA120 之上）满仓吃 Beta，破位熊市 100% 现金空仓保本，杜绝持股硬抗大熊市。
   - **极低换手率**：年换手率保持在低频（< 0.5x~1x），最大程度降低印花税、佣金与滑点冲击。
3. **简洁但不过分严谨（Pragmatic, Concise, Disciplined）**
   - 保持工程敏捷性：重视核心逻辑与快速迭代，避免为了繁琐的形式主义编写数十页理论预登记合同而阻碍实战落地。
   - 严谨只保留在关键底线：**严禁未来函数**、**严禁偷看收盘价作为开盘成交**、**计入真实费率**、**编写清晰的单元测试**。
4. **以“为个人服务 / 个人可执行”为检验标准**
   - 策略必须符合个人真实账户操作与资金现实：低频、大周期、无需全天盯盘（例如每天收盘前监控信号、次日开盘下单，一年操作几次）。
   - **不用非得个人手动执行，为个人服务即可**：可以是为个人服务的全自动化量化助手（自动定时拉取数据、大周期趋势判定、自动风控止损、微信/看板推送）。

---

## 📖 优先阅读 (Read First)

1. [docs/current.md](docs/current.md) — 当前运行事实、owner 决策与硬边界（唯一当前事实源）。
2. [docs/personal-trading-assistant-guide.md](docs/personal-trading-assistant-guide.md) — 个人实战策略体系与开发指引。
3. [docs/project-rules.md](docs/project-rules.md) — 代码组织与研究规则。
4. [docs/operations/host-runbooks.md](docs/operations/host-runbooks.md) — 多主机分工与边界（Mac、WSL、Windows E盘、VPS）。
5. [docs/quick-handoff.md](docs/quick-handoff.md) — 快速接手指南。

冲突判定优先级：`docs/current.md` → `docs/project-rules.md` → runbooks/reference → 活动策略文档。

---

## 🛡️ 安全与风控底线 (Safety Boundaries)

- 未经 owner 明确授权，严禁启用或触发生产实盘交易、订单下单、交易定时器或生产 cron。
- 绝不打印、复制、提交、导出或同步 API Key 和密码等私有凭据。Mac 本地密钥配置必须为 `0600`。
- 所有策略回测与研究产物默认标明 `research_only=true` / `orders_authorized=false`。
- 严禁擅自复活已冻结的无效历史遗产。

---

## 🖥️ 主机职责分工

| 主机 | 允许职责 | 严禁边界 |
| --- | --- | --- |
| Mac `/Users/alyaloale/Code/qount` | 代码主仓、Git、文档、策略逻辑编写与轻量验证 | 长期海量数据存储、生产执行 |
| Windows 外置盘 `E:\qount_data` | 大数据集、不可变工件、历史行情集中存储 | 存放任何私密凭据、虚拟环境 |
| WSL `/home/alyaloale/Code/qount` | CPU/GPU 密集计算、深度回测与模型训练 | 存放私密凭据、声明为实盘真相 |
| VPS `/root/qount` | 既有只读通知服务与看板状态 | 存储海量研究数据、未授权的服务变更 |

一键连接 WSL：`ssh qount-wsl`。

---

## 🛠️ 本地常用开发与验证命令

```bash
# 激活环境
source .venv/bin/activate

# 快速运行专项单元测试
PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -p 'test*.py'

# 仓库规范检查与编译检查
PYTHONPATH=src ./.venv/bin/python scripts/maintenance/repository_hygiene.py check
PYTHONPATH=src ./.venv/bin/python -m compileall -q src scripts/maintenance
```

---

## 📝 文档更新指引

- 核心事实变动更新 [docs/current.md](docs/current.md)。
- 个人策略研究与开发沉淀至 [docs/personal-trading-assistant-guide.md](docs/personal-trading-assistant-guide.md)。
- 任何有意义的代码更改后，必须运行相关单元测试与 hygiene check，严禁宣称未跑过的测试为通过。
