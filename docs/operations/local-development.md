# 本地开发与验证

> **状态**：active｜**权威**：本地开发手册；遵循 [项目规则](../project-rules.md)｜**最后更新**：2026-10-15
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

## 本地统一凭据与同花顺研究数据

新增研究数据密钥统一放在 Mac 仓库外的 `~/.config/qount/`（目录 `0700`、私有文件 `0600`），不写入 Git、命令行参数、研究输出或跨主机包。现有生产凭据位置与使用方式保持原状。

| 数据源 | 本地私有文件 | 文件中的变量名 |
| --- | --- | --- |
| 同花顺 Fuyao | `~/.config/qount/fuyao.env` | `FUYAO_API_KEY` |
| Tushare | `~/.config/qount/tushare.env` | `TUSHARE_TOKEN` |

两个文件分别只存一行 `变量名=密钥`。公共读取器 [local_credentials.py](../../src/qount/local_credentials.py) 验证 Mac、文件所有者、普通文件及 `0600`，拒绝符号链接，不执行 shell 或向进程环境导出内容。Fuyao 客户端与现有 Q-DIV Tushare 采集器共用它。

Fuyao [官方文档](https://fuyao.aicubes.cn/docs/introduction/)与[完整接口定义](https://fuyao.aicubes.cn/llms-full.txt)为接口来源。[客户端](../../src/qount/research_data/fuyao.py) 固定 HTTPS 主机、仅 GET、通过请求头认证，拒绝重定向及含密钥的响应；默认串行间隔 1 秒、单实例最多 20 请求，每响应上限 16 MiB，不自动重试。客户端同时检查 HTTP 和业务错误码，限流立即返回错误。可复用的命令入口为 [fuyao.py](../../scripts/research/fuyao.py)：

```bash
# 十项小范围只读验证；不加载仓库 .env。
PYTHONPATH=src ./.venv/bin/python scripts/research/fuyao.py probe

# ISO 日期按上海时区转换为毫秒戳，end 日期包含当日；股票默认未复权。
PYTHONPATH=src ./.venv/bin/python scripts/research/fuyao.py query historical \
  --param thscode=600519.SH --param start=2026-10-01 --param end=2026-10-14 \
  --output state/research_runs/fuyao_example/maotai_daily.json

# 三表接口为 income / balance / cashflow；null 保留为未知。
PYTHONPATH=src ./.venv/bin/python scripts/research/fuyao.py query cashflow \
  --param thscode=600519.SH --param period=quarterly --param limit=4
```

其他已接入能力为 `calendar`、`search`、`tickers`、`snapshot`、`actions`、`valuations`、`constituents`、`index_catalog`、`index_snapshot`、`index_historical`、`fund_snapshot`、`fund_historical`，命令 `query --help` 可查看名称。输出保留原响应、参数、来源和 UTC 抓取时间，附 `research_only=true / orders_authorized=false`；`--output` 拒绝覆盖已有文件。`tickers` 与无指定标的的股票快照一次只返回一页，需显式以 `limit`／`offset` 继续，不能把第一页称作完整市场。

研究口径：股票日线窗口最多 10 年，指数／ETF 最多 5 年；ETF 历史接口固定为供应商前复权。财务 `data.timestamp` 为最新报告期末，不能当成披露时间；`report_date_ms` 为披露日期，不保证日内公布时刻或历史修订版本。估值、名单与成分股为当前快照，日历仅滚动一年，除权事件不含付款日，不据此认证 PIT 或现金总回报；不把 Fuyao 价格与另一供应商复权因子直接拼接。小样本可本地保存，大规模公开行情按主机手册留 E 盘，凭据始终留 Mac。

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

账户页面只读取 Binance USD-M 观察快照。Mac 本地没有 VPS 观察文件时，API 明确返回缺失状态和零数值；不要用历史研究工件填充账户余额。纸面前向研究通过 `/paper` 单独读取，并且只接受带 Binance USD-M 来源证明的线路。

复用现有缓存，写入新的研究输出目录；不覆盖冻结工件、失败结果或用户工作区修改。API 摄取与回放会写数据库，轻量验证使用独立临时路径，不以正式状态库作试验场。

Mac 负责轻量实验与编排；大规模数据和模型计算按 [主机手册](host-runbooks.md)送 WSL，完整公开输入和结果留 E 盘。既有范围与预算内自主推进；不要从接手、旧 READY 或一份脚本推断新的训练／生产权限。

交付报告说明改动、实际执行的验证、结果和限制。hygiene 的已有问题与本次引入问题分开记录；未运行的测试、未检查的主机状态保持未验证。
