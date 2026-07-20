# qount Dashboard v1

`qount.alyaloale.com`的只读运维控制台。前端只展示后端发布的权威read model，不访问交易所、生产SQLite或私有API，
不在浏览器重算PnL，也不提供arm、resume、改单或撤单能力。

## 当前状态

- Dashboard有`overview`、`positions`、`orders`、`strategies`、`decisions`、`risk`、`readiness`、`system`、
  `alerts`和`reports`十份read model；默认入口为`#/live`，非法或旧hash会无刷新归一到该入口。
- publisher必须输入完整`VerifiedDecisionBatch`和治理`StrategyRegistry`，并可接收自验证的
  `RuntimeLedgerSnapshot`、`NotificationSnapshot`、`SystemHealthSnapshot`和确定性`DailyBrief`。
- `RuntimeLedgerSnapshot` schema v3只从同一SQLite读事务和hash-linked audit读取仓位、订单、成交、现金、NAV、账户观测、
  recovery及三方对账。balance、available、actual gross、margin、current/peak drawdown均为账本事实或账本派生事实。
- `positions`显示实际/预期/目标差异并链接`#/decisions?trace=<id>`；`decisions`固定展示
  `batch -> snapshot -> intents -> portfolio -> risk -> order plan -> ledger -> reconciliation`证据链。
- `system`只接受显式`clock/disk/service/backup`健康观测；clock/disk观测失败时以`unavailable + null`显示，不伪造偏差或容量。
  它有独立source/freshness，不能用新健康观测刷新陈旧账户事实。
- alerts与reports也各自使用独立source/freshness。通知成功不代表交易成功，日报永不产生订单权限。
- 没有完整`data/v1` release时页面显示`PRODUCTION STOPPED`、publisher unavailable、execution disabled和legacy fallback removed。
- 旧`cta.json/x4_live.json/x4_paper.json/cxd_live.json`前端读取和VPS cron展示写入均已移除。
- 界面为中文优先：CJK字体优先使用苹方/冬青黑体/微软雅黑/思源黑体，正文`14px`、导航`13px`、标题`20-22px`、指标`18-21px`，
  证据链固定节点也做展示层中文化；策略ID、reason code、hash和RuntimeLedger等审计原值保持不变。

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
            └── reports.json
```

`publish_dashboard_v1()`先写`0755`临时release，11个文件使用`0644` canonical JSON并逐个fsync/readback，再以相对
symlink原子切换`v1`。半写失败删除临时目录并保留旧指针。`read_dashboard_v1()`拒绝额外或缺失文件、路径逃逸、非预期
symlink、权限异常、重复key、非canonical JSON以及source/model/publication hash错配。

静态Draft 2020-12合同位于`web/schemas/`，共13份：envelope、十份read model、publication和DailyBrief。
完整ledger + notification + health + brief fixture已用`jsonschema 4.25.1`对10个model、publication和brief共12个实例验证。

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

2026-07-20结果：operations/health/publisher聚焦`34 OK`，全仓最新`1468 OK`。Playwright/Chromium完成桌面`1440x1000`和移动
`390x844`的Live、Positions、Decisions、System、移动菜单与offline长页检查；点击仓位可进入并高亮decision trace，页面无
文档级横向溢出、控制台异常、重叠或非预期裁切。移动仓位表按设计在面板内横向滚动。

## 生产边界

- `https://qount.alyaloale.com/#/live`已部署新静态前端；Caddy HTTPS、Basic Auth、`no-store`和安全响应头保留。
- served root当前只有`index.html/app.js/style.css`，没有`data/`。因此在真实v1 publisher接入前，认证后页面必须失败关闭，
  不能显示本地fixture或旧账户状态。
- 旧站完整备份位于`/root/qount-dashboard-backup-20260719T183341Z`；qount生产cron保持停用，没有恢复策略、订单或publisher调度。
- production publisher 的前置输入现在有只读 `qount.reporting.read_vps_authority_bundle()` 边界：它要求同一目录中完整的
  `decision_batch/<batch_id>/`、`strategy_registry.json`、`runtime_ledger_snapshot.json`、`notification_snapshot.json`、
  `system_health_snapshot.json` 和 `daily_brief.json`，并拒绝额外 legacy state、symlink、非 canonical JSON、权限错误和跨源 hash
  不一致。该 importer 只读，不查询网络/交易所/SQLite，也不直接发布 release。
- 真实notification transport尚未实现。legacy `Notifier`和shell ServerChan发送不具备新outbox的幂等、响应验证和审计合同，
  不得直接接入。
- 本地`qount.operations.dashboard_publisher`已完成production-shaped单写者：只读VPS authority bundle、四项真实OS探针、同盘
  原子release、逐文件备份/恢复演练和release保留；`deploy/systemd/qount-dashboard-publisher.service/.timer`仅为未启用模板。
  它不得直接读取legacy state JSON、查询交易所或复制测试release；VPS production接入仍需独立owner授权和真实source演练。
