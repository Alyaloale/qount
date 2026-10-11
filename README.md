# qount: 个人量化交易助手 (Personal AI Quant Assistant)

> **核心目标**：构建务实、简洁、以**个人实战盈利**为根本目标的个人量化交易助手。  
> **权威事实**：[docs/current.md](docs/current.md) 是项目当前运行事实与决策的唯一来源。

---

## 🎯 项目定位与理念

`qount` **不是**公募基金式的学术仿真系统，**不是**搞 20 只股票过度分散、行业配额和繁琐理论门槛的研究所玩具，而是服务于**个人交易者（Retail/Prop Trader）**的实战量化助手。

### 个人交易者的核心优势（“船小好掉头”）
1. **集中而非过度分散**：个人账户资金有限，不做公募基金式的 20~50 只个股切碎配置。专注于 **1~3 只核心高流动性标的**（核心 ETF、极品高股息现金牛或主流加密货币）。
2. **极低摩擦与极低换手**：拒绝月度频繁洗牌（年换手率从 200%+ 降至 < 0.5x）。拥抱免印花税载体（ETF）与低费率工具。
3. **大周期趋势择时（牛市吃肉，熊市保命）**：个人账户没有最低仓位限制。大盘在多头趋势（MA200/MA120 之上）时满仓吃 Beta，破位进入系统性熊市时 100% 现金空仓避险，彻底避开 2018、2022 年式的惨烈回撤。
4. **简洁而不过分严谨**：代码模块化、注重单元测试与真实净值回报，拒绝无休止的形式主义与理论自嗨。

---

## 🧭 支持的交易主战场

| 战场 | 交易载体 | 核心模式 | 个人优势 |
|---|---|---|---|
| **A 股 ETF** | 沪深300ETF、红利低波ETF、跨境ETF等 | 大周期均线趋势跟随 + 动量轮动 | 免印花税、无个股暴雷退市雷、门槛低（几百元起一手） |
| **加密货币 (Crypto)** | BTC / ETH 现货与低杠杆永续 | 24h 波动突破 + 宏观事件驱动 | 无 100 股限制（精确到小数）、双向交易、高流动性 |
| **A 股核心资产** | 2~3 只极品高股息现金牛 | 核心底仓分红 + 宏观顶部防守 | 股息再投资、穿越周期、精力消耗低 |

---

## ⚡ 开发者与 Vibe Coding 快速上手

### 1. 运行环境与预检 (Mac)
```bash
# 激活环境与依赖
source .venv/bin/activate

# 快速运行单元测试
PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -p 'test*.py'

# 仓库规范检查
PYTHONPATH=src ./.venv/bin/python scripts/maintenance/repository_hygiene.py check
```

### 2. 算力与计算环境连接
- **Mac 本机**：代码开发、策略逻辑编写、轻量验证与 Git 托管。
- **WSL 计算节点**：CPU/GPU 深度计算与回测重跑（一键连接：`ssh qount-wsl`）。
- **Windows E 盘**：历史数据与沉淀工件集中存储（`/mnt/e/qount_data/`）。

---

## 🛡️ 安全与风控底线 (Non-negotiable Guardrails)

- **绝不泄露凭据**：私有 Token/密钥仅保存在本地安全配置（如 `~/.config/qount/`），严禁提交 Git 或同步到不可信环境。
- **实盘保护**：默认所有新策略与实验均为 `research_only=true` / `orders_authorized=false`，未经明确指令不得擅自调用外部实盘下单接口。
- **真实因果时钟**：回测严禁未来函数、严禁偷看收盘价作为开盘成交、严禁虚构零成本。

---

## 📚 核心文档导航

- [当前事实与状态](docs/current.md) — 唯一当前事实源。
- [个人交易助手开发指南](docs/personal-trading-assistant-guide.md) — 个人实战策略体系与开发指引（Vibe Coding 必读）。
- [快速接手手册](docs/quick-handoff.md) — 5 分钟上手说明。
- [架构设计](docs/system-architecture-design.md) — 整体系统架构与通知、执行链路。
- [长期个人组合策略设计](docs/long-run-personal-strategy-design.md) — 148 次历史实验经验总结。
- [主机运行手册](docs/operations/host-runbooks.md) — 多主机环境与连接说明。
