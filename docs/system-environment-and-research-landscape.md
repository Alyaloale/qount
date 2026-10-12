# qount 系统环境、多主机分工与研究全景手册

> **状态**：active｜**权威**：系统环境、多主机分工与全景研究参考｜**最后更新**：2026-10-11
> **TL;DR**：服务个人实战盈利；本页提供主机分工、研究导航和排障，结论只看 current。Mac 开发、WSL 计算、E 盘保存完整公开工件、VPS 维护既有服务；旧高收益和历史方案不作为当前能力。

---

## 一、研究线导航与证据范围

当前裁决只在 [current.md](current.md)，本页说明研究职责与接手方向，不维护第二份收益表。2026-10-11 的 [修补整理计划](research-repair-and-consolidation-plan-2026-10.md)统一问题与后续顺序；历史 formal trial、局部候选、曲线和模型 fits 不是同一计数，全局账本未核对前不合并。

### 1. A 股 ETF 与个股

全市场补采提高了研究输入覆盖，不能自动认证历史公告版本、证券身份或可执行性。Q-DIV-Core 已完成并门槛失败，原 20 仓不调参救援；低波候选待新鲜确认，其他失败价格实现保持。赛道轮动／综合 C／EKF-MPC／麒麟的旧高收益结论撤销并封存；ETF 趋势盾牌仍是代理研究，真实 ETF、费用与现金口径待核。

主航道是少量核心资产的个人助手。低换手和回撤控制属于待验证目标，不从代码或历史指标推定实盘能力。

### 2. Crypto 与事件

C60 的稳定选币优势经时点宇宙诊断撤回，梯度与不交易带候选失败；v1／v2 保留各自无订单模拟和前瞻身份。币安多资产合约旧旗舰结论撤销并封存，费用／撮合情景收据待统一。

旧 MiniTrend 实盘已停止，FOMC live 部署已取消。小时主动流候选停止，业绩上修数据门待补；稳定币 G0 只提供来源资格，清算级联按 current 有效窗口积累，不能提前读收益。

### 3. ETF Trader／P3 Alpha

P2 停训回收、Stage B 未完成。P3 v2 未证明神经／增强模型相对简单基线的增量；R3 51-fit pilot 已以 pilot_no_increment 结束，outer withheld，单轮授权已消费。旧 READY 或云端环境不构成继续训练权限。

### 4. 跨资产模拟与助手工具

Dual-Engine 四账户是公共数据无订单模拟，YTD 包含回放，离线领先尚待新鲜确认。CTA-R 冻结规则通过跨市场最低研究门，防御证据值得保留，收益／Sharpe 未超过 60/40 且未获晋级。

Alpha Agents／日报／看板服务于资料、解释与审计，管线健康、来源新鲜度和研究结论分别评价。弃用的 L1-S2 与其他 legacy 只作历史，不继承收益、配比或运行权限。

逐线主文档与源码入口见 [research-lines.md](research-lines.md)，读旧申报时先看各专题封面的历史／撤销说明。

---

## 二、 本项目配置与安全体系

### 1. 配置文件体系
- **[config/environment-contract.toml](../config/environment-contract.toml)**：声明全仓库唯一合法的环境变量名列表，任何未在合同声明的变量都会被 hygiene check 拦截。
- **Mac 本地凭据安全区**：
  - `~/.config/qount/tushare.env`：保存 Tushare Token，文件权限必须为 `chmod 0600`，仅在 Mac 进程内存中加载，**严禁传往 WSL、E 盘、VPS 或 Git**。
  - `<repo>/.env`：Mac 本地私有环境变量，已被 `.gitignore` 严格忽略。
- **研究合同样本 (`config/*.json`)**：
  - 记录每次实验的静态规则快照（如 `ashare-q-div-core-design-20261011.json`、`c60-gradient-20261011.json`），保证历史可溯。

### 2. 安全预检命令
在 Mac 本地，可使用内置工具进行只读、值隐藏的安全预检：
```bash
qount-run config-check --profile mac
```
该命令只检查变量名称、主机边界和文件权限，不联网、不输出任何真实密钥片段。

---

## 三、 四大主机分工与角色定位

```text
                  ┌─────────────────────────────────────┐
                  │          Mac (开发与指挥中枢)         │
                  │   - 代码主仓、Git、文档、策略逻辑编写   │
                  │   - 轻量级单元测试 (0.07s)            │
                  │   - 私有 Tushare 凭据隔离存储 (0600)   │
                  └──────────────────┬──────────────────┘
                                     │ Tailscale 专网
         ┌───────────────────────────┼───────────────────────────┐
         ▼                           ▼                           ▼
┌──────────────────┐       ┌──────────────────┐       ┌──────────────────┐
│   WSL (算力机)    │       │ Windows 外置 E:  │       │  VPS (云端节点)   │
│ - AMD 7945HX 32核│       │ (存储真相磁盘)    │       │ - 只读 Dashboard │
│ - RTX 4060 8G GPU│◄─────►│ - 全量行情/财报  │       │ - 个人微信推送   │
│ - 深度回测/模型训练│ (挂载)│ - 永久沉淀工件   │       │ - 定时日报调度   │
└──────────────────┘       └──────────────────┘       └──────────────────┘
```

| 主机节点 | 路径 / 硬件 | 角色定位与允许职责 | 严禁边界 (Non-negotiable) |
|---|---|---|---|
| **Mac** | `/Users/alyaloale/Code/qount` (Apple Silicon) | **开发与指挥中枢**：代码主仓、Git 管理、文档编写、策略原型开发、轻量级测试与任务编排、Tushare 令牌本地私存。 | 长期保存海量数据（几十 GB）、执行实盘生产下单。 |
| **Windows 外置盘** | `E:\qount_data\qount` (NTFS 外置 SSD) | **存储真相磁盘**：全量历史日线（1200万行）、财报（390万行）、分红数据、回测 artifacts、模型权重与不可变备份。 | 存放 API Key、私密配置、活跃 SQLite 数据库或虚拟环境。 |
| **WSL** | `/home/alyaloale/Code/qount` (AMD 7945HX 32线程, RTX 4060 Laptop 8GB, 16GB 内存) | **重型计算节点**：CPU/GPU 密集算力、大规模特征计算、深度历史回测（如 11.75 年全历史回测）与模型训练。 | 存放私密凭据、声明为实盘真相、修改持久配置。 |
| **VPS** | `/root/qount` (云端 Linux) | **监控与中继中枢**：运行只读 Dashboard 看板、腾讯个人微信 iLink 官方推送通道、每日定时日报任务、无订单模拟。 | 存储批量研究数据、未授权修改服务或启用实盘。 |

- **一键直连 WSL 计算节点**：`ssh qount-wsl`（自动通过 Tailscale 握手唤醒）。

---

## 四、 基本环境与基础设施

1. **操作系统与内核**：
   - Mac: macOS (Darwin arm64)
   - WSL: Ubuntu Linux on WSL2 (`6.18.40.1-microsoft-standard-WSL2`, x86_64)
   - VPS: Ubuntu Linux (64位)
2. **Python 运行环境**：
   - 统一采用 **Python 3.12**。
   - 包管理与工具：`uv`、标准 `venv`。
3. **网络拓扑与通信**：
   - 全网通过 **Tailscale** 建立虚拟专网互联：
     - Mac 节点：本地 Tailscale Client
     - WSL 节点：`100.105.105.56`
     - Windows 宿主：`100.86.117.34`
     - VPS 节点：通过安全中继连接

---

## 五、 五大高频踩坑问题与排障手册 (Troubleshooting)

### 踩坑 1：WSL 访问 `/mnt/e` 报错 `No such device` 或 `external_disk=missing`
- **症状**：WSL SSH 登录后，访问 `/mnt/e/qount_data` 报错 `OSError: [Errno 19] No such device`，或者 `scripts/hosts/qount-wsl.sh status` 报告 `external_disk=missing`。
- **原因**：Windows 发生过睡眠/唤醒、或外置移动硬盘断开重连，导致 WSL 的 9p/drvfs 挂载断开，但 systemd 进程命名空间未自动更新。
- **秒级解法**：在 Mac 终端通过 `ssh qount-win` 让 Windows 宿主以 root 身份重新向 systemd 命名空间执行挂载：
  ```bash
  ssh qount-win 'wsl.exe -d Ubuntu -u root --exec /bin/bash -c "nsenter --target 1 --mount umount -l /mnt/e ; nsenter --target 1 --mount mount -t drvfs E: /mnt/e -o metadata,uid=1000,gid=1000,umask=22,fmask=11"'
  ```
  或者运行自动化维护脚本：`scripts/hosts/qount-wsl.sh ensure`。

### 踩坑 2：WSL SSH 连接超时、Tailscale 状态显示 `offline`
- **症状**：`ssh qount-wsl` 提示超时，`tailscale status` 看到 WSL 节点处于离线状态。
- **原因**：Windows 默认策略是在没有前台终端窗口活动时自动冻结停止 WSL VM。
- **解法**：Windows 上已部署计划任务 `qount-wsl-keepalive`（开机常驻 `/bin/sleep infinity`）。若意外挂起，Mac 运行 `scripts/hosts/qount-wsl.sh ensure` 即可自动通过 Windows 唤醒拉起 WSL。

### 踩坑 3：Mac 本地网络代理（Clash/VPN）导致 SSH 挂起或断连
- **症状**：执行 SSH 或 Git 时无响应，提示 `kex_exchange_identification: Connection closed`。
- **原因**：系统代理开启了全局 TUN 模式，把 `100.x` 的 Tailscale 流量错误劫持到了本地代理虚拟网卡（`198.18.0.1`）。
- **解法**：确保 Tailscale 启用 `--accept-routes`，在代理软件中将 `100.64.0.0/10` 设置为直连（Direct），或运行 `ssh -O exit qount-wsl` 清理陈旧的 ControlMaster socket。

### 踩坑 4：误把密钥提交到 Git 或同步到 WSL
- **症状**：在脚本输出或 Git diff 中看到了 Token。
- **防护与恢复**：
  - Tushare Token 仅在 Mac 本地 `~/.config/qount/tushare.env` 存储，权限为 `0600`；
  - 采集脚本仅在 Mac 发起网络请求，公开响应清洗脱敏后才写入 E 盘；
  - 提交前必须运行 `python scripts/maintenance/repository_hygiene.py check`，任何未在合同备案的环境变量都会触发警报。

### 踩坑 5：策略回测中的“隐形未来函数”与虚假收益
- **症状**：策略回测年化收益极其夸张，但实盘必亏。
- **排查清单**：
  - ① 是否偷看收盘价？（**严禁**把当天收盘价当作开盘成交价；收盘生成的信号只能在次日开盘买入）；
  - ② 是否偷看开盘涨跌停？（开盘涨停一字板不可买入，跌停一字板不可卖出）；
  - ③ 是否把分红预案当作真金到账？（必须以除息日作为应收确认日、派息日作为现金到账日）；
  - ④ 是否漏扣交易摩擦？（股票买卖必须扣除佣金、过户费、印花税与合理滑点；ETF 免印花税但需计佣金与滑点）。
