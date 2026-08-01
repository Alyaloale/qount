# qount Dashboard v1

`qount.alyaloale.com`的只读运维控制台。前端只展示后端发布的权威read model，不访问交易所、生产SQLite或私有API，
不在浏览器重算PnL，也不提供arm、resume、改单或撤单能力。

## 当前状态

- 当前代码有`overview`、`positions`、`orders`、`strategies`、`decisions`、`risk`、`readiness`、`system`、
  `alerts`、`reports`、`intelligence`和`paper`十二份read model；默认入口为`#/live`，非法或旧hash会无刷新归一到该入口。
  VPS 生产已发布十二份版本；`paper` 已上线 2026 YTD 四账户曲线，每账户当前 217 点。
- publisher必须输入完整`VerifiedDecisionBatch`和治理`StrategyRegistry`，并可接收自验证的
  `RuntimeLedgerSnapshot`、`NotificationSnapshot`、`SystemHealthSnapshot`、确定性`DailyBrief`和只读`DailyIntelligenceReport`。
- `RuntimeLedgerSnapshot` schema v3只从同一SQLite读事务和hash-linked audit读取仓位、订单、成交、现金、NAV、账户观测、
  recovery及三方对账。balance、available、actual gross、margin、current/peak drawdown均为账本事实或账本派生事实。
- `positions`显示实际/预期/目标差异并链接`#/decisions?trace=<id>`；`decisions`固定展示
  `batch -> snapshot -> intents -> portfolio -> risk -> order plan -> ledger -> reconciliation`证据链。
- `system`只接受显式`clock/disk/service/backup`健康观测；clock/disk观测失败时以`unavailable + null`显示，不伪造偏差或容量。
  它有独立source/freshness，不能用新健康观测刷新陈旧账户事实。
- alerts、reports、intelligence与paper各自使用独立source/freshness。paper 只接收四账户无订单模拟快照；通知成功不代表交易成功，日报和模拟盘都不产生订单权限。
- 没有完整`data/v1` release时页面以中文显示生产数据不可用、发布器不可用、订单执行已禁用和旧数据回退已移除。
- 旧`cta.json/x4_live.json/x4_paper.json/cxd_live.json`前端读取和VPS cron展示写入均已移除。
- 界面为中文优先：CJK字体优先使用苹方/冬青黑体/微软雅黑/思源黑体，正文`14px`、导航`13px`、标题`20-22px`、指标`18-21px`，
  证据链固定节点也做展示层中文化；策略ID、reason code、hash和标的代码等审计原值保持不变。模拟盘总图提供中文策略名、
  净值/日期坐标轴、1.000 基准线、可区分线型和移动端单列布局；数据待更新使用琥珀色，不与生产不可用混淆。

## 数据合同

前端每30秒读取同一原子release：

```text
/var/www/qount/
├── index.html
├── app.js
├── style.css
└── data/
    ├── v1 -> releases/<publication_id>
    └── releases/
        └── <publication_id>/
            ├── publication.json
            ├── overview.json
            ├── positions.json
            ├── orders.json
            ├── strategies.json
            ├── decisions.json
            ├── risk.json
            ├── readiness.json
            ├── system.json
            ├── alerts.json
            ├── reports.json
            ├── intelligence.json
            └── paper.json
```

`publish_dashboard_v1()`先写`0755`临时release，13个文件使用`0644` canonical JSON并逐个fsync/readback，再以相对
symlink原子切换`v1`。半写失败删除临时目录并保留旧指针。`read_dashboard_v1()`拒绝额外或缺失文件、路径逃逸、非预期
symlink、权限异常、重复key、非canonical JSON以及source/model/publication hash错配。
浏览器 `fetchJSON()` 返回 `{value,fileSha256}` 供逐文件校验；校验通过后 `state.models` 只能接收 `response.value`，
不能把下载包装对象交给渲染器，否则必须全站失败关闭。

静态Draft 2020-12合同位于`web/schemas/`，当前共17份（含两个 DailyIntelligence schema 版本）：envelope、十二份read model、publication、DailyBrief和DailyIntelligence。
当前测试会用`jsonschema` registry验证十二份model、publication及DailyIntelligence实际实例。

## 本地验证

```bash
PYTHONPATH=src ./.venv/bin/python -m unittest \
  tests.test_architecture_boundaries \
  tests.test_runtime_ledger \
  tests.test_legacy_dispatch_replay \
  tests.test_ledger_dashboard_bridge \
  tests.test_dashboard_read_models \
  tests.test_notifications \
  tests.test_notification_producers \
  tests.test_daily_brief \
  tests.test_system_health

PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -p 'test*.py'
node --check web/site/app.js
for f in web/schemas/*.json; do jq -e . "$f" >/dev/null || exit 1; done
```

2026-07-22结果：免费官方feed、详情复抓、TOP3行情、六角色中文Responses、账本摘要、不可覆盖归档、个人微信和Dashboard已完成生产E2E。
最新日报ID为`24defae6...6adc`、report hash为`f4d90e84...63a94`，`intelligence.summary.status=available`并精确绑定该hash；
3份feed、8份详情、2份行情及六角色报告均可重放。报告状态`incomplete`来自证据不足的`needs_research`，不是页面或基础设施不可用。
日报timer现为`enabled/active`；Mac/VPS相关聚焦测试各`45 OK`。公网匿名访问继续按设计返回Basic Auth `401/no-store`。

2026-07-21结果：全仓`1508 OK`，VPS生产聚焦`25/12 OK`；`app.js`语法、15份Schema JSON、Python compileall、
`systemd-analyze verify`和`git diff --check`通过。Chromium通过只读SSH隧道检查真实生产release的`#/intelligence`桌面
`1440x1000`和移动`390x844`，文档宽度等于viewport，无可见元素越界、重叠或裁切。生产数据不是fixture：normalizer上线后，
`gpt-5.6-sol`通过Responses严格Schema完成了一个真实中文TOP3首角色报告；个人微信iLink已完成一次独立真实投递并通过本地审计重放，
当时只缺Brave Key，因此尚无完整六角色日报，页面按合同显示`unavailable_until_daily_intelligence`；该状态已由上方2026-07-22的
免费官方feed E2E取代。临时隧道及远端HTTP server已关闭。

2026-07-20结果：operations/health/publisher聚焦`34 OK`，当时全仓`1468 OK`。Playwright/Chromium完成桌面`1440x1000`和移动
`390x844`的Live、Positions、Decisions、System、移动菜单与offline长页检查；点击仓位可进入并高亮decision trace，页面无
文档级横向溢出、控制台异常、重叠或非预期裁切。移动仓位表按设计在面板内横向滚动。

## 生产边界

- `https://qount.alyaloale.com/#/live`已部署新静态前端；Caddy HTTPS、Basic Auth、`no-store`和安全响应头保留。
- served root已有真实`data/v1`原子release：12份业务read model加`publication.json`，由order-free authority和publisher生成；
  `intelligence`当前发布上述真实日报；只有归档确实缺失时才显式发布`unavailable_until_daily_intelligence`，不复制本地fixture。
- 第12份`paper`与`#/paper`已和 12-model release 同步部署；owner 授权的 2026 YTD 公共行情回放显示四账户
  Executable NAV 总图与 Signal/Executable 小图，并固定标记为模拟而非真实收益。paper 源缺失或无合法快照时仍只降级该页。
- 旧站完整备份位于`/root/qount-dashboard-backup-20260719T183341Z`；qount生产cron保持停用，没有恢复策略、订单或publisher调度。
- production publisher 的前置输入现在有只读 `qount.reporting.read_vps_authority_bundle()` 边界：它要求同一目录中完整的
  `decision_batch/<batch_id>/`、`strategy_registry.json`、`runtime_ledger_snapshot.json`、`notification_snapshot.json`、
  `system_health_snapshot.json` 和 `daily_brief.json`，并拒绝额外 legacy state、symlink、非 canonical JSON、权限错误和跨源 hash
  不一致。该 importer 只读，不查询网络/交易所/SQLite，也不直接发布 release。
- 腾讯官方个人微信iLink adapter已在VPS复用OpenClaw账号并完成接入通知和真实日报通知：新日报job `DELIVERED`、attempt
  `SUCCEEDED`、12行audit chain通过；凭据和源context token均为`0600 root:root`。WeCom adapter保留但production unit不使用，legacy `Notifier`和shell
  ServerChan仍不得接入；外部接受后、本地落标前的崩溃窗口存在，不能声称exactly-once。
- Daily Intelligence生产默认使用Binance公告API、Fed RSS和SEC RSS，单独调用`gpt-5.6-sol /v1/responses`；通用Alpha Agent研究默认仍为
  `gpt-5.6-terra`。生产TokenRouter经Docker内网`aishenji-normalizer`重建可通过WAF的请求特征，本轮六个13.4-40.2KB非流式请求均完成，
  account 25保持`active/schedulable`。历史长流式`524`风险仍由有限重试和失败关闭处理，前端必须区分基础设施失败与`needs_research`。
- `qount.operations.dashboard_publisher`已作为生产单写者运行：只读VPS authority bundle、四项真实OS探针、同盘原子release、逐文件
  备份/恢复演练和release保留；timer为`enabled/active`。它不得直接读取legacy state JSON、查询交易所或复制测试release。
