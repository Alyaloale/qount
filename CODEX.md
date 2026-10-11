# Codex / Copilot Agent Guide (AI 个人量化交易助手)

本文件为 OpenAI Codex、GitHub Copilot 及各类通用 AI 编程助手专用的接手入口与规则说明。

---

## 🎯 核心定位与检验标准

1. **唯一根本目标：个人实战盈利**
   - 本项目是为个人服务的 AI 量化交易助手系统（支持自动化全流程与半自动化决策参考）。
   - **以“为个人服务 / 个人可执行”为检验标准**：
     - 策略必须符合个人真实账户操作与资金现实（低频、大周期、无需全天盯盘，例如每日收盘前监控信号、次日开盘下单，一年操作几次）；
     - 可以是为个人服务的全自动化量化助手（自动数据抓取、大周期趋势判定、自动风控止损、微信/看板推送）。
2. **拒绝公募基金式的学术形式主义**：
   - 不做资金切碎成 20 只个股的超额分散、不做繁琐行业配额限制、不做高换手月度频繁洗牌；
   - 个人交易者的核心优势是“船小好掉头”：标的精选集中（1~3 只核心 ETF 或主流加密资产）、大周期多头满仓吃 Beta、破位 100% 现金空仓避险、极低交易摩擦。
3. **简洁但不过分严谨（Pragmatic, Concise, Disciplined）**：
   - 保持工程敏捷性：重视核心逻辑与快速迭代，避免繁琐的多层预登记合同阻碍实战落地；
   - 底线原则坚不可摧：**严禁未来函数**、**严禁偷看收盘价作为开盘成交**、**计入真实费率**、**编写清晰的单元测试**。

---

## 📖 优先阅读路径

1. [AGENTS.md](AGENTS.md) — 统一 AI Agent 开发总览与多主机分工。
2. [docs/current.md](docs/current.md) — 当前运行状态与唯一事实源。
3. [docs/personal-trading-assistant-guide.md](docs/personal-trading-assistant-guide.md) — 个人实战策略体系与开发指引（三大支柱与 Vibe Coding 规范）。
4. [docs/quick-handoff.md](docs/quick-handoff.md) — 5 分钟上手说明。

---

## 🛡️ 安全与风控硬边界

- 除非 owner 明确授权，不碰真实账户实盘交易、下单、生产 cron 或交易 timer。
- 研究与回测默认 `research_only=true` / `orders_authorized=false`。
- 绝不打印、复制、提交或导出现有私密凭据（API Token/密钥本地存储需为 `0600`）。

---

## 🛠️ 常用开发与测试命令

```bash
# 激活虚拟环境
source .venv/bin/activate

# 运行单元测试
PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -p 'test*.py'

# 仓库规范检查
PYTHONPATH=src ./.venv/bin/python scripts/maintenance/repository_hygiene.py check

# 编译检查
PYTHONPATH=src ./.venv/bin/python -m compileall -q src scripts/maintenance
```
