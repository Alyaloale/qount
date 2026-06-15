# qount 实时收益看板(qount.alyaloale.com)

跨线 A(A股 CTA-R)+ 线 D(加密 X4)的**只读**收益展示站。纯静态前端 + 定时推数据,
不下任何单、不碰交易逻辑。部署在 墙外 VPS(`root@8.220.130.35`,Debian 12 + Caddy v2.11)。

## 架构

```
A股 CTA-R(模拟)   WSL `home` ──ssh──> Mac ──scp──┐
加密 X4 paper(模拟)Mac 本地 state/x4/paper/ ─────┤──> VPS /var/www/qount/data/
加密 X4 live(实盘) VPS 本地(x4_live_cron 写)──cp─┘
                                                  │
   Caddy  qount.alyaloale.com  (basic_auth + 自动 HTTPS)  →  /var/www/qount
   前端   index.html + app.js + style.css,JS 每 60s 拉 data/*.json 渲染
```

三个数据文件(VPS `/var/www/qount/data/`):
- `cta.json`     — `qount.cta_portfolio status --json` 输出(A股,模拟盘,新浪实时估值)
- `x4_paper.json`— 打包 `state/x4/paper/{holdings,latest,s7_latest,combo_latest}.json`(加密模拟盘前向 3 本 book)
- `x4_live.json` — `state/x4/live/latest.json`(加密实盘小仓,真实下单)

## 文件清单(本仓库 `web/`)

| 文件 | 作用 | 部署位置 |
|---|---|---|
| `site/index.html` `site/app.js` `site/style.css` | 静态前端 | VPS `/var/www/qount/` |
| `push_dashboard.sh` | Mac 端:取 A股(WSL)+ 打包 paper → scp 上 VPS | Mac 本地运行 |
| `com.qount.dashboard.plist` | launchd:每 300s 跑 push_dashboard.sh | `~/Library/LaunchAgents/` |
| `Caddyfile.qount` | Caddy 站点块**模板**(hash 占位,真值在 VPS) | append 到 VPS `/etc/caddy/Caddyfile` |

实盘数据发布由 `scripts/desktop/x4_live_cron.sh` 末尾的 `cp ... /var/www/qount/data/x4_live.json` 完成
(VPS crontab 每天 10:30)。

## 访问

- URL: **https://qount.alyaloale.com**
- basic_auth 用户名 `qount`,密码见私密渠道(bcrypt hash 存 VPS Caddyfile,明文不入库)。
- 改密码:`ssh root@8.220.130.35 'caddy hash-password --plaintext 新密码'` → 替换 Caddyfile 里 `qount` 那行的 hash → `systemctl reload caddy`。

## 重新部署

```bash
# 前端改动后(Mac):
scp web/site/{index.html,app.js,style.css} root@8.220.130.35:/var/www/qount/
# 推送脚本/cron 改动后:
scp web/push_dashboard.sh ... ;  scp scripts/desktop/x4_live_cron.sh root@.../root/qount/scripts/desktop/
# 数据手动刷一次:
web/push_dashboard.sh
```

## 运维坑

- **DNS 前提**:`qount.alyaloale.com` 必须有 A 记录指向 `8.220.130.35`,Caddy 才能签 Let's Encrypt 证书。
- **A股取数**靠 Mac 能 `ssh home → wsl.exe`,且 WSL 上 `.venv` + `cta_portfolio` 可跑;WSL 关机时 `cta.json` 写入 `{"error":...}`,前端显示“取数失败”但其他两区照常。
- **A股只在交易时段动**:盘后 `price_source` 回退缓存收盘,前端会标注。
- 前端无外部 CDN 依赖(自带 SVG sparkline),适配境内访问。
- 不碰现有 `api.alyaloale.com`(DeepSeek 网关)块。
