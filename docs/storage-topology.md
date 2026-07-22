# qount 存储与计算拓扑

更新时间：2026-07-22

这份文档定义跨主机职责、权威数据位置、WSL计算流程和清理规则。策略结论仍以
[current.md](current.md)为准，生产运行仍以VPS为准。

本文后续实验路径和300 USDT/旧paper artifact均为存储历史。当前源码候选为`0.2.13`且尚未部署；VPS生产仍为
`0.2.12`，MiniTrend Base固定100 USDT，live timer为`enabled/active`，forward timer为`disabled/inactive`。
2026-07-22外置`E:`已完成保护性备份、文件系统修复和修复后逐文件校验。全新备份目录
`D:\qount_data-recovery-20260722T120000Z`含`14,214`个文件、`34,096,177,913` bytes，源/目标SHA-256
manifest自身hash均为`a31da6af...b9339`；`robocopy`返回码`1`表示成功复制新文件，`FAILED=0`、`Mismatch=0`。
`chkdsk E: /f`报告未发现文件系统问题且`0 KB` bad sectors，卷最终为`Healthy/OK`、dirty bit未设置。修复后再次逐文件
读取`E:\qount_data`，文件数、字节数、路径和SHA-256相对修复前manifest均为零差异；审计位于
`D:\qount_data-recovery-20260722T120000Z.post-chkdsk-audit.json`。`/mnt/e`已恢复为可写`9p`挂载，WSL ext4代码、
`qount 0.2.13`环境、scratch marker和`state`链接均正常，大型研究可以重新按本文件的stage/compute/publish流程运行。
`D:`恢复备份和两份canonical manifest必须保留，不能作为scratch清理。

## 1. 当前职责

| 节点 | 路径/硬件 | 职责 | 不应长期保存 |
| --- | --- | --- | --- |
| Mac | `/Users/alyaloale/Code/qount` | 研究设计、代码主仓、git、文档、轻量测试和任务编排 | 全量行情、训练集、模型批次、历史artifact |
| Windows外置盘 | `E:\qount_data`；WSL见`/mnt/e/qount_data` | 大数据、不可变输入、最终artifact、环境锁和节点备份的存储真相 | `.env`、API密钥、活跃SQLite、venv |
| WSL | `/home/alyaloale/Code/qount`；7945HX 32线程、RTX 4060 8GB | 大型CPU特征工程、表格模型、HMM、GPU训练和权威复跑 | 完成后的大数据副本、长期artifact、生产状态 |
| VPS | `/root/qount` | `0.2.12` MiniTrend Base 100 USDT minimal-live、dashboard和最小runtime state | 研究缓存、历史训练集、批量artifact |
| 临时云GPU | disposable | 仅在4060显存或吞吐实测不足时临时训练 | 唯一数据副本、生产密钥、live state |

WSL是正式计算节点，但不是实盘生产真相。Mac和WSL不要求每次全仓镜像；WSL基础计算接口变化时才显式
更新代码，具体实验通过带代码hash、配置和数据manifest的实验合同交接。

## 2. 外置盘目录合同

qount的新根目录是`E:\qount_data\qount`：

```text
qount/
  datasets/             # 长期数据集和不可变输入
  artifacts/            # 完成的研究/训练artifact
  environments/         # Python/CUDA/驱动/代码hash锁
  manifests/            # 文件树SHA-256和迁移校验
  migrations/           # 迁移期按节点隔离的源快照
  runtime-backups/      # 节点runtime压缩备份，不作为运行目录
  scratch/              # 外置盘传输临时区；完成后清理
```

既存23G L2归档已于2026-07-18在同一ExFAT盘内原子移动到
`E:\qount_data\qount\datasets\l6_l2_archive`，旧`E:\qount_data\qount_l2_archive`不再保留。

2026-07-18新增的Coin Metrics BTC日频链上原始响应直接由WSL写入
`datasets/coinmetrics/btc_asset_metrics_daily/v1/raw/`，没有Mac/VPS副本；`2373`行、`1,057,022` bytes，
dataset tree content hash为`e1614707...1f4a9`。最终regime/on-chain artifact位于`artifacts/experiments/`，
对应manifest位于`manifests/{datasets,experiments}/`；最新WSL环境锁为
`environments/wsl/20260718T045100Z-qount-compute.json`，manifest/code bundle hash为
`752f2b59...b139`/`94ccc633...5ea0`。发布、复跑和回读完成后，WSL scratch已由marker保护脚本清空，
只留marker和空`state/`。

同日新增H.4.1官方历史release树`datasets/fed_h41/raw/`，为`406 files/252,249,757 bytes`，manifest
content hash `d0f939db...4592`；最终稳定dataset hash为`8af65a47...cb02`。Coin Metrics future vintage链位于
`datasets/coinmetrics/vintages/btc/raw/`，首个raw manifest为`1 file/463 bytes`、content hash
`fe7bb1e9...7c0c4`。两者均由WSL直连写外置盘，不经Mac/VPS或代理；Mac当前`state/`约12KiB，仅保留
小型运维日志和零字节锁。

H.4.1事件闸门最终artifact位于
`artifacts/experiments/20260718T052500Z-h41-event-ablation-rerun/`，manifest content hash为
`f36a1e63...520a`；最新WSL环境锁为`environments/wsl/20260718T052600Z-qount-compute.json`，
manifest/code bundle hash为`71ffd6cf...5e36`/`cd96da83...c5c5`。计算发布后仍只保留外置盘最终证据。

后续H.4.1边际boost否决的预登记/最终复跑分别位于
`artifacts/experiments/20260718T054840Z-h41-boost-veto-preregistration/`和
`20260718T055103Z-h41-boost-veto-ablation-rerun/`；manifest content hash为
`941fa2c2...beab`/`566bdaa9...71f8`。最新WSL环境锁
`environments/wsl/20260718T055231Z-qount-compute.json`的manifest/code bundle hash为
`fe69531a...cc3b`/`5dfdd3b8...07ec`。本轮没有下载或在Mac保留市场数据。

Base episode最终复跑与信号退出冷却最终复跑分别位于
`artifacts/experiments/20260718T061138Z-base-episode-attribution-rerun/`和
`20260718T062126Z-signal-exit-cooldown-ablation-rerun/`，manifest content hash为
`bf806d24...ebf2`/`1a87b5e9...e5f3`。最新WSL环境锁
`environments/wsl/20260718T062306Z-qount-compute.json`的manifest/code bundle hash为
`1e027a5c...1054`/`61817b67...5270`。全部输入仍来自外置盘既有缓存，WSL scratch在发布后清理。

UM双状态shadow的公开输入现集中在`datasets/binance_um_shadow/v1/`，网络刷新和策略回放已隔离。首次刷新
直接由WSL写外置盘，复用已迁移warmup缓存并补齐2026-06月包、2026-07-01..17 TOP3 UM日包，共
`93 files/80,144 bytes`，dataset manifest content hash为`8dcce911...13746`；刷新与离线shadow artifact
分别位于`artifacts/experiments/20260718T081136Z-um-shadow-input-refresh-v02/`和
`20260718T080849Z-um-funding-veto-shadow-forward/`，manifest content hash为
`654926e5...383b`/`c1f91959...2828`。最新环境锁`environments/wsl/20260718T081243Z-qount-compute.json`
的manifest/code bundle hash为`03be436e...7823`/`ff78f5e8...bbc6`。当月funding公开REST直连不可达，
未生成伪快照；代理只允许由仓库外环境变量提供，URL/token不进入数据集或artifact。

磁盘修复后的追加刷新把同一cache推进到`2026-07-21`，为`105 files/84,368 bytes`，manifest content hash
`30fab795...66da`；输入刷新与冻结shadow artifact分别位于
`artifacts/experiments/20260722T123145Z-um-shadow-input-refresh-post-recovery/`和
`20260722T123559Z-um-funding-veto-shadow-forward-post-recovery/`，manifest content hash为
`3e9c315b...1aaa`/`0ae2cc8d...0265`。当月funding仍0/3完整，shadow未读取收益。
冻结历史beta残差复跑与5000路径Bootstrap位于`20260722T124533Z-um-funding-veto-frozen-beta-residual-rerun/`
和`20260722T124742Z-um-funding-veto-frozen-bootstrap-rerun/`，manifest content hash为
`0e384cf7...f6e6`/`9e5c8159...43d4`；环境锁
`environments/wsl/20260722T124742Z-qount-funding-veto-frozen-rerun.json`的manifest/code bundle hash为
`5054dc53...0a3d`/`afc51389...d1ae`。上述manifest均已从外置盘重算回读，最终JSON已stage到ext4解析后清理scratch。

300 USDT一个月UM试点的最终readiness artifact位于
`artifacts/experiments/20260718T100615Z-um-live-pilot-readiness-v04/`，manifest content hash为
`7d4de1b8...f5594`。它只含合同、布尔证据与blocker，不含API key、余额明细或订单；readiness hash为
`2b072733...a8b1e`，明确`live_orders_allowed=false`。

独立UM paper runtime的当前只读artifact位于
`artifacts/experiments/20260718T100615Z-um-pilot-paper-v02/`，manifest content hash为
`051dc16f...4f463`。它只读外置盘canonical缓存并写最终report；300 USDT首跑0个eligible pair且未产生journal行。
WSL中的journal路径只是ext4 scratch占位，首次真实行必须在VPS最小runtime state中追加，不能把高频写入放在
ExFAT；本轮清理后WSL scratch不保留副本。

300 USDT四候选历史比较位于
`artifacts/experiments/20260718T100615Z-um-pilot-300-research-v02/`，manifest content hash为
`1da97a84...388b1d`。它是已消费历史discovery，含59个不重叠30天试点窗口，不是promotion证据。

一次性迁移已完成：

- WSL旧state：`6974 files/1,280,658,614 bytes`，content hash
  `fab498093e6b47ecb5a43d8d7c7e2ca9a833303712a76cc93842c892f45ac412`。
- Mac旧state：`11,968 files/8,101,349,852 bytes`，content hash
  `2bdf6c621ae321d397bb2de50badb2ee24e97f353fd85c72f007bd03d21eb74c`。
- 两侧源/目标manifest、文件数、字节数和content hash一致，且各完成dataset/artifact外置盘回读；源大副本
  已删除。Mac `state/`只允许小型运维日志，WSL `state`指向ext4 scratch。
- 最终卫生检查另发现Mac残留一份`178,026,679` bytes的2026-07-14 collector压缩段；与外置盘
  `artifacts/imports/mac-20260718/`副本的SHA-256 `4b8d1cef...757f`、字节数完全一致且外置副本通过
  `gzip -t`后，已删除Mac源。Mac `state/`现约12KiB，只剩小型运维日志和零字节锁。
- 残留文件曾被`com.qount.alpha-collector-offload` LaunchAgent每30分钟重新生成；该任务累计运行105次，
  已从当前GUI domain卸载并删除`~/Library/LaunchAgents/com.qount.alpha-collector-offload.plist`。复核时
  服务与plist均不存在，Mac `state/`保持约12KiB，不再自动回填collector数据。
- Mac/WSL旧runtime只保留`runtime-backups/archives/`下经过gzip、tar目录和SHA-256验证的压缩包；展开目录
  已删除。VPS完整迁移归档放在`migrations/20260718/sources/vps/`，`runtime-backups/vps/`保存分类备份。
- VPS只删除明确非runtime研究数据，运行目录约16MiB；生产crontab继续停用。

## 3. ExFAT与WSL边界

外置盘物理格式是ExFAT，在WSL中表现为`drvfs/9p`。雷电4链路可以提供高顺序吞吐，但大量小文件会受9p
元数据操作限制。第一次WSL状态迁移的实测约为`1.28GB/6974 files`，平均约`5.3MB/s`，这不代表硬盘顺序性能。

因此固定以下规则：

- 代码、`.venv`、活跃SQLite、训练中间张量和高频小文件留在WSL ext4。
- 大数据在外置盘按数据集/实验批次归档，优先Parquet、压缩tar/zip或少量大文件。
- 计算前把需要的只读输入stage到`QOUNT_WSL_SCRATCH_ROOT`；完成后只发布最终artifact和manifest，再清空scratch。
- 不在ExFAT上依赖Unix权限、硬链接、文件锁或原子SQLite语义。
- 外置盘未挂载时任务必须fail closed，不能退回Mac、VPS或WSL项目目录悄悄写大数据。
- 新增大数据只在Windows/WSL侧获取并直接落外置盘；直连或仓库外配置的良心云代理均可。Mac/VPS和苏菲
  家宽代理不得承担批量下载或中转。

## 4. 默认配置

```bash
QOUNT_EXTERNAL_DATA_ROOT=/mnt/e/qount_data/qount
QOUNT_WSL_SCRATCH_ROOT=/home/alyaloale/.cache/qount-compute
QOUNT_PROJECT_ROOT=/home/alyaloale/Code/qount
QOUNT_STATE_DIR=/home/alyaloale/.cache/qount-compute/state
```

`QOUNT_STATE_DIR`适用于使用`Settings`和统一artifact helper的代码。仍使用相对`state/...`的历史研究脚本必须
由实验合同显式传`--cache-dir/--output-path`，或在WSL scratch工作目录中运行；不能直接指向外置盘活跃写入。

初始化和检查：

```bash
ssh -o ClearAllForwardings=yes home \
  'wsl.exe bash -lc "cd /home/alyaloale/Code/qount && scripts/storage/wsl_compute_storage.sh init"'
```

生成内容manifest：

```bash
PYTHONPATH=src ./.venv/bin/python scripts/storage/state_manifest.py \
  --root /path/to/tree \
  --source-node wsl \
  --output /mnt/e/qount_data/qount/manifests/example.json
```

## 5. 计算与发布流程

1. Mac写研究合同、代码和轻量测试，记录代码commit或source hash。
2. 仅当WSL基础计算接口变化时执行`scripts/sync-to-wsl.sh [--install]`；不要把它放进每次实验前置步骤。
3. WSL检查外置盘，按manifest把本次输入stage到本地scratch。
4. 在7945HX/4060上运行特征构建、回测或训练；日志也先写scratch。
5. 将最终dataset版本、model、metrics、日志和环境锁发布到外置盘`artifacts/`，再生成内容manifest。
6. 校验发布内容后执行`wsl_compute_storage.sh clean-scratch`。
7. Mac只读取指标摘要并更新文档；不长期拉回全量artifact。

### 长任务

从Mac经Windows SSH直接启动WSL的`tmux/nohup/systemd --user`会在`wsl.exe`退出后被回收。当前可靠方式是让
Mac的detached `screen`持有前台SSH，SSH再持有`wsl.exe`：

```bash
screen -S qount-wsl-job -dm \
  ssh -o ClearAllForwardings=yes home \
  wsl.exe bash /home/alyaloale/Code/qount/scripts/storage/wsl_long_job.sh \
  JOB_NAME manifest ROOT SOURCE_NODE OUTPUT
```

WSL任务日志和退出码在`$QOUNT_WSL_SCRATCH_ROOT/jobs/JOB_NAME.{log,exit}`。退出文件不存在只代表仍在运行，
不能把systemd/tmux会话消失或空日志解释为成功。

## 6. 迁移与删除门

任何源数据删除前必须同时满足：

- 外置盘源快照复制完成，传输进程退出码为0。
- 源和目标manifest的`file_count`、`total_bytes`和`content_hash`一致。
- 至少完成一次从外置盘stage到WSL scratch的读取/计算smoke test。
- 冲突文件已按节点和相对路径隔离，未被静默覆盖。
- VPS只删除明确非runtime的数据；`x4/`、`cxd/`、`rv/`、日志和审计状态按运行合同保留。

`.env`、API密钥和旧密钥备份不进入ExFAT迁移仓。密钥只留在节点私有配置或系统钥匙串；不需要的备份在
确认主配置有效后直接删除。外置盘如含账户审计或VPS runtime备份，应启用Windows侧磁盘加密。

本次迁移已满足上述删除门。以后任何新数据集、训练批次或节点清理仍逐批重新执行这些检查，不能把本次通过
视为永久授权。
