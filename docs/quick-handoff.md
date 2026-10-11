# qount 快速接手手册 (Vibe Coding Handoff)

> **状态**：active｜**权威**：L4 运维导航｜**最后更新**：2026-10-11
> **本文回答**：首次接手与 Vibe Coding 的最短路径、项目定位、实战策略方向与安全边界。
> **TL;DR**：生产事实只看 [current.md](current.md)。本项目定位于**个人量化交易助手**，以**个人实战盈利**为根本目标，摒弃公募基金 20 仓切碎的冗余形式主义；主攻 ETF 趋势择时与加密货币小账户，保持简洁高效敏捷开发。

---

## 🚀 5 分钟上手阅读路径 (First Five Minutes)

1. 阅读 [README.md](../README.md) 与 [docs/personal-trading-assistant-guide.md](personal-trading-assistant-guide.md) 了解个人交易助手的战略定位、策略三大支柱与 Vibe Coding 规范。
2. 阅读 [current.md](current.md) 确认当前系统状态与 owner 最新决策。
3. 了解多主机职责分工（[host runbooks](operations/host-runbooks.md)）：
   - **Mac**：编写代码、策略逻辑、文档与 Git 管理；
   - **WSL 计算节点**：CPU/GPU 深度回测与重跑（一键直连：`ssh qount-wsl`）；
   - **Windows E 盘**：历史日线、财报数据与工件存储（`/mnt/e/qount_data/`）；
   - **VPS**：只读日常看板与个人微信通知服务。
4. 本地环境自检与验证：
   ```bash
   source .venv/bin/activate
   PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -p 'test*.py'
   PYTHONPATH=src ./.venv/bin/python scripts/maintenance/repository_hygiene.py check
   ```

---

## 🎯 核心实战策略方向

1. **A 股 ETF 大周期趋势择时（最推荐 A 股实战）**：
   - 标的：沪深300ETF (`510300`)、红利低波ETF (`512890`)、纳指ETF (`513100`)；
   - 机制：MA200/MA120 趋势多头全仓吃 Beta，破位空仓 100% 现金保本；
   - 优势：免印花税、零暴雷风险、几百元起投、超低换手率（< 0.5x/年）。
2. **加密货币 (Crypto) 趋势突破**：
   - 标的：BTC / ETH；
   - 优势：无 100 股门槛、24h 交易、即时止损。
3. **极简核心高息资产底仓**：
   - 标的：精选 2~3 只极品高息股（如 长江电力）；
   - 机制：平时享受 4%~6% 股息再投资，大级别见顶时择机减仓。

---

## 🛡️ 安全与风控硬边界

- **绝不泄露凭据**：私密 Token 和密码仅保存在本地安全配置（Mac `0600`），严禁提交至 Git。
- **实盘保护**：默认所有实验为 `research_only=true` / `orders_authorized=false`，未经明确指令不得擅自调用外部实盘下单。
- **真实因果时钟**：回测严禁未来函数、严禁偷看收盘价作为开盘成交、严禁虚构零成本。
- **简洁但不过分严谨**：代码模块化，拥有单元测试；但不要为了繁琐形式主义编写数十页理论预登记合同阻塞实战推进。

---

## 📂 核心文档与资源导航

- [个人交易助手指南](personal-trading-assistant-guide.md) — 个人实战策略体系与开发指引（Vibe Coding 必读）。
- [项目规则](project-rules.md) — 代码组织与研究规则。
- [主机运行手册](operations/host-runbooks.md) — 多主机环境与连接说明。
- [配置参考](reference/configuration.md) — 配置文件与安全加载规范。
- [CLI 与脚本参考](reference/cli-and-scripts.md) — 常用工具与命令参考。
- [系统架构主设计](system-architecture-design.md) — 系统整体架构设计。
- [长期个人策略设计分析](long-run-personal-strategy-design.md) — 历史 148 次实验证伪与总结。
