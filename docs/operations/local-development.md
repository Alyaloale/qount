# 本地开发与验证

> **状态**：active｜**权威**：本地开发手册；遵循 [项目规则](../project-rules.md)｜**最后更新**：2026-10-12
> **适用范围**：Mac 工作区、虚拟环境、轻量研究与针对性验证。
> **TL;DR**：保留已有修改，先完成最小修复或实验，按影响范围验证；本地研究不授予生产执行权限。

## 工作区与环境

先读 [current.md](../current.md) 中与任务相关的事实和边界，再定位代码与现有证据：

```bash
git status --short
rg --files src scripts tests docs
```

使用已有 `.venv`；缺环境或依赖确有变化时再按锁文件准备：

```bash
uv sync --extra test
source .venv/bin/activate
```

Python 要求以 `pyproject.toml` 为准。普通文档、单元测试和离线算法工作不需要加载 `.env`；需要数据接口时只通过对应适配器加载授权凭据，Mac 私有文件保持 `0600`。不要在诊断输出中显示变量值。

## 按改动选择验证

**文档**：检查相关链接、事实、权限和 Markdown 结构；可用以下只读命令辅助：

```bash
PYTHONPATH=src ./.venv/bin/python scripts/maintenance/repository_hygiene.py check
git diff --check
```

**局部代码**：使用标准库 `unittest`，先运行负责该模块的测试。例如修改个人助手时：

```bash
PYTHONPATH=src ./.venv/bin/python -m unittest tests.research.test_personal_trading_assistant
```

**核心逻辑／结构变更／生产候选**：按实际影响补相关回归、导入或部署引用检查；需要全仓覆盖时使用：

```bash
PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -p 'test*.py'
PYTHONPATH=src ./.venv/bin/python -m compileall -q src scripts/maintenance
PYTHONPATH=src ./.venv/bin/python scripts/maintenance/repository_hygiene.py check
```

`tests/research/__init__.py` 已存在；旧指南“根 discover 不包含 research”的说法不再作为当前规则。新测试需核对其确被发现，不能只根据通过数量推断覆盖。编译检查不替代行为验证，全仓通过也不证明策略盈利。

**研究／训练**：先验证数据维度、时间切分、成本和指标定义，再做能回答假设的最小实验；重要候选按本线合同扩大验证。无关失败单独记录，不反复运行不相关检查。

## 输出、资源与交付

### 只读前端与确定性日报

`/assistant/daily` 只读取 `QOUNT_ASSISTANT_DAILY_RUN` 显式指定的完成包，要求 `_COMPLETE`、`manifest.json` 与 `daily-report.json` 的输出哈希匹配，并核对输入哈希、研究权限和逐资产资格。未配置时返回“最新日报未接入”，不自动寻找离线样例，也不启动日报生成。过往合格日报仍标为历史；数据资格不等于真实账户可执行资格。

前端纯计算回归可用 `node --test tests/frontend/metrics.test.cjs`；Chrome 回归入口为 `tests/frontend/browser.cjs`，需要外部安装的 `playwright`，默认仅允许访问本地 `127.0.0.1:8766`。启动 API 时设置独立 `QOUNT_DB_PATH`（例如 `/tmp/qount-ui-acceptance.db`）；截图默认写 `/tmp/qount-ui-tests`。`QOUNT_TEST_BASE_URL`、`QOUNT_BROWSER_EXECUTABLE` 与 `QOUNT_TEST_SCREENSHOTS` 仅为该测试脚本的参数，不参与服务运行。此流程不连接线上账户或修改生产服务。

账户回放默认读取部署工件目录。Mac 若仅有 `state/research_runs/personal_assistant_reconciled_20261012/`，启动本地 API 时通过 `QOUNT_ACCOUNT_SOURCE_PATH` 和 `QOUNT_ACCOUNT_TRADES_PATH` 指定该目录的 `summary.json` 与 `trades.json`；使用已有工件，不复制或覆盖冻结来源。

复用现有缓存，写入新的研究输出目录；不覆盖冻结工件、失败结果或用户工作区修改。API 摄取与回放会写数据库，轻量验证使用独立临时路径，不以正式状态库作试验场。

Mac 负责轻量实验与编排；大规模数据和模型计算按 [主机手册](host-runbooks.md)送 WSL，完整公开输入和结果留 E 盘。既有范围与预算内自主推进；不要从接手、旧 READY 或一份脚本推断新的训练／生产权限。

交付报告说明改动、实际执行的验证、结果和限制。hygiene 的已有问题与本次引入问题分开记录；未运行的测试、未检查的主机状态保持未验证。
