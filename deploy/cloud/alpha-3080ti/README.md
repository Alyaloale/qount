# RTX3080Ti P3 独立交付

> 状态：active deployment reference｜更新：2026-10-03｜仅研究计算。
> 当前启动权限和主机状态只看仓库 `docs/current.md`；本包暂停配置会拒绝生成、标定和训练。

目标为 owner 指定的内蒙 B 区 457 机 `jn1f8a7n6z`，一张 RTX3080Ti/12GB，CPU 配额20核、内存30GiB、数据盘50GiB。
完整策略在仓库 `docs/etf-p3-research-plan-2026-10.md` §20；本文件仅说明部署接口，不维护第二份运行状态。

## 包与输入

代码包按白名单制作，只包含 P3 Python 实现、必需的共享 ETF 模拟模块、固定公开合同、针对性测试和安装说明。
不发送整个仓库、私有环境文件、git、缓存、既有模型或账户数据。`delivery-manifest.json` 保存逐文件 SHA256；gzip/tar 元数据固定，可重复构建。

另一个输入包必须从 E 盘冻结目录导出，保留原始 manifest 和所有字节：

```bash
PYTHONPATH=src python scripts/research/etf_alpha_cloud.py export-inputs \
  --data-root /mnt/e/qount_data/qount/datasets/etf_alpha_p3/m0_m1_20261002T112648Z \
  --fold-contract /mnt/e/qount_data/qount/artifacts/etf_alpha_p3/m0_m1_20261002T112648Z/m1/fold-contract.json \
  --out /mnt/e/qount_data/qount/artifacts/etf_alpha_p3/cloud-inputs-NEW.tar.gz
```

输入 manifest 的 SHA256 固定为 `bfb139712e50be05e78df4b0eb305378d37e3c8ce0cd37c15bfd8545651235bb`。
不能用重新下载的行情替代，也不能用此前中断、没有完整 manifest 的增强分片目录替代。
代码和输入分开传输，代码解压到独立 release；输入解压到 `/root/autodl-tmp/qount/`。
Python 的 `tarfile.extractall(..., filter='data')` 配合逐文件清单校验用于本工具生成的可信包，先核对整个包的 SHA256。

## 环境和检查

已有镜像和 CUDA 驱动保持原样。`setup.sh` 使用现有 Python 创建新的系统盘 venv，拒绝覆盖同名环境。
PyTorch 使用官方 cu130 wheel；核心锁为 Torch2.13.0、NumPy2.5.1、threadpoolctl3.6.0。安装时 `--no-cache-dir` 避免双份 CUDA wheel 占盘。
环境目录 `/root/qount-envs/alpha-3080ti-20261003`；失败/中断环境必须检查后决定使用新目录，不自动覆盖或续装。

```bash
bash deploy/cloud/alpha-3080ti/setup.sh
export PYTHONPATH="$PWD/src"
export CUDA_VISIBLE_DEVICES=0
task_python=/root/qount-envs/alpha-3080ti-20261003/bin/python
task_contract=config/etf-alpha-cloud-3080ti-20261003.json
"$task_python" scripts/research/etf_alpha_cloud.py inspect --contract "$task_contract"
PYTHONPATH=src:tests "$task_python" -m unittest test_etf_alpha_cloud test_etf_alpha_expanded test_etf_alpha_training test_etf_alpha_m1
```

`inspect` 检查数据盘真实挂载、空间、cgroup CPU/内存限额、唯一分配 GPU、显存及版本；缺输入报告 `inputs_ready=false`。
训练入口会进一步回读冻结数据 hash、最长标签 purge 和 embargo，缺输入立即退出。
安装只用于后续明确恢复计算后；当前暂停状态不应运行安装、GPU 标定或生成命令。

## 分阶段计算

只有当前事实和合同重新登记 owner 启动决定后才能执行以下计算命令。合同保留259 fits、五 seeds、七 folds、7,168 世界、float32/noAMP/noTF32、真实数据64日batch和预训练4096日batch，不自动追加实验。

```bash
"$task_python" scripts/research/etf_alpha_cloud.py benchmark --contract "$task_contract" \
  --out /root/autodl-tmp/qount/calibration/NEW
"$task_python" scripts/research/etf_alpha_cloud.py prepare --contract "$task_contract" \
  --out /root/autodl-tmp/qount/datasets/etf_alpha_p3/bootstrap_NEW
"$task_python" scripts/research/etf_alpha_cloud.py run --contract "$task_contract" \
  --calibration /root/autodl-tmp/qount/calibration/NEW/calibration.json \
  --bootstrap-root /root/autodl-tmp/qount/datasets/etf_alpha_p3/bootstrap_NEW
```

也可省略 `--bootstrap-root`，让一个固定 run 先完成 CPU 生成，再训练 GPU。
`prepare` 的18个 CPU-only workers 用 forkserver、BLAS1、直接 NPY 分片写入，不导入 Torch；源码、输入、过去区间、布局及全部 hash 一致才可复用。
CPU 生成保存约26.5GiB完整 float32数据。GPU 每次只载入一个约3.77GiB fold，五个 seeds 共享，全部 seeds完成后释放，再换下一fold。
GPU训练保持一个进程；四个 CPU诊断线程与训练重叠。编译线程4，编译任务上限8，共用独立磁盘缓存。
标定使用合成张量，不使用市场标签；检查预测/loss/梯度一致性，对 eager/compiled 分别测冷启动、稳定step吞吐、显存峰值，按摊销成本选择。
每个候选最多180秒；编译异常或数值不合格不参与选择。3090/P2模型和任务不在本调度范围。

长任务可放入 tmux；不安装 cron/systemd/自动重启。停止只向对应 job PID 发 SIGTERM，不能广泛杀其它用户或既有训练。
状态和进度：run 的 `status.json`、`events.jsonl`、每epoch历史、每100steps预训练吞吐，15秒GPU/温度/功耗/磁盘监控。
预训练每60秒保存 last，真实训练保存 best/last；诊断失败、非有限梯度和 owner停止保留原样失败/partial证据。

## 交付、费用和下一轮

所有七fold的选模与五seed结果冻结后才能计算 outer；最终 `REPORT.md`、选模表、全部family的1/2/3倍成本曲线、逐年/删最好年诊断、源代码、环境锁和清单写入新run。
`run` 完成后生成只含结果的 `deliveries/*-results.tar.gz`，不将26.5GiB增强数据重复压缩。失败输出也明确标注 failed/partial。
下载后用 `verify` 校验交付包，再回收到 E盘做长期保存；Mac仅保存轻量文档、代码交付包和摘要。

按 owner 提供的￥1.08/小时记录估算费用，实际以平台账单为准。35个bootstrap fits各最多600秒，预训练计算上界5小时50分；CPU、编译、真实训练和诊断另计，整轮没有8小时总限制。
固定任务完成后退出，不为保持利用率补世界、补seed或自动搜索。训练退出不等于平台实例关机；停止计费要由平台关机，付费扩容磁盘另有计费规则。
本工具不含平台账号API、自动租赁/扩容/释放或关机权限。下一轮架构变更需要新的研究问题和合同；本轮历史仍属 discovery。
