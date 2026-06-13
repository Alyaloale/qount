# CLAUDE.md

本文件给在本仓库工作的 Claude Code 使用。

## 交流约定

- **始终用中文回答。** 除非用户显式要求换语言,所有回复一律中文。
  （代码、命令、commit message、英文专有名词保持原样,不必硬翻译。）

## 文档地图(两条隔离的项目线)

本仓库现有**两条互相隔离的项目线**,纪律与边界各自独立,不要混用:

### 线 A — qount CTA 研究线(主线,纪律冻结)

- `docs/current.md`：当前事实入口与硬边界。
- `docs/holdout.md`：`discovery_pool` / `validation_pool_v1` 与 `G_paper` / `G_live`。
- `docs/quick-handoff.md`：接手命令、跨主机操作、运维坑点。
- `docs/update-log.md`：近期变更与证据链。
- `docs/optimization-plan.md`：T-A..T-J 架构评审路线。
- `docs/profit-research-plan.md`：WS-1..WS-4 盈利研究历史路线。
- `docs/profit-engineering-plan.md`：盈利工程主线(S0–S5);§11 是计划与现实的对账。
- `docs/rebuild-plan.md`：CTA-R 跨资产重构线(主线下的授权重构)。
- `docs/l1-*/l3-*/l4-*/l6-*-plan.md`：四条重启线计划。

### 线 B — GRID-B 实验性虚拟货币网格线(隔离,约束放松;**彻底收口 2026-06-11**)

- **状态:S1/S1c/S1d/S1e + H3 全部跑完证伪 → 线 B 彻底收口(2026-06-11)**。前四轮:H1/H2 双死,网格
  扣费后无法对「站上 200MA 就持有」产生正增量。收口纪律允许带**新假设**重启,H3 即此:**delta-neutral
  资金费 carry**(剥掉网格皮,真身=资金费 carry + 卖方差;新结构=永续对冲库存 Δ,新市场=山寨永续;
  Tier-2 禁令对 H3 解除)。**H3 终判 = FAIL**:① 网格本体判死(H3-B≪H3-A,同 ETH static funding +220.71%
  vs grid +7.36%,洞1 铁证);② carry 真身 equity-normalized 上界仅 **+4.70%/yr 薄 carry**,物理清算尾部门
  (膨胀空头 pump 挤爆)在 L≥3 把它吃光(L=3:年化 −0.83%、3/6 年 → 三判据全不过)。= 线 A「sub-gate
  carry / edge 量级 ~0」在加密 delta-neutral carry 重演。**「网格从来不是 alpha,真身是 carry;但 carry
  扣真实尾部后不够活」。不再开新网格/carry 变体研究**;代码(`src/qount/grid/`,103 单测:perp 账本 /
  run_h3 / run_h3_carry / universe)定性为可复用 delta-neutral/carry 研究资产,不删除。重启须带**再新**假设。
- `docs/grid-binance-h3-plan.md`：**v0.6 H3 已实现 + 已判生死**——§8.3 上界、§8.4 洞1(H3-B 死)、§8.5
  框架缺陷(notional 膨胀,首次 sweep 无效)、§8.6 equity-normalized 终判(H3-A FAIL,收口)。
- `docs/grid-binance-plan.md`：v0.1 基线设计(单边做多网格 + 趋势滤网),本线事实入口;含 S1 证伪结果。
- `docs/grid-binance-optim.md`：v0.2 四个进攻性优化(高斯分配 / 追踪网格 / ATR 间距 / 生息叠加)——已随收口冻结。
- `docs/grid-binance-next.md`：v0.3 S1 证伪后推进方向(H1/H2 预注册判生死);§5/§8 D3 记录最终收口结论。
- `docs/grid-binance-optim2.md`：v0.4 条件化优化——宿主(S1e/ETHBTC)双死,已随收口全冻结。
- `docs/grid-binance-s1e-plan.md`：v0.5 S1e 三态混合构型;§9 实测结果(含播种 phantom bug 的发现与修复)与最终判据对账。

### 线 C — RV-C 实验性硬锚相对价值线(隔离,约束放松;**已实现 + 五轮检验认证,2026-06-11 立线**)

- **状态:已实现并跑完五轮检验 = 跨线 A/B/C 唯一过多重检验认证的可交易正 edge,但窄而薄**。承线 B 元结论
  (网格=劣质执行皮,真身是 carry/RV,但软对/永续 carry 扣真实尾部后 sub-gate),owner 选**硬锚对优先**。
  第一刀(H-RV)= **dated quarterly futures 基差收敛 cash-and-carry**:现货多 + 季度合约空,Δ≈0;与 H3 永续的
  关键区别=**季度合约到期契约性强制收敛 = 真锚**(H3 永续无到期锚,死在尾部)。复用 `run_h3_carry` 的
  equity-normalized + 物理清算尾部门 + `perp.py` 账本;代码落独立命名空间 `src/qount/rv/`(`basis.py`/`backtest.py`/
  `data.py`/`stats.py`),不改线 B 模块。**结果**:五轮检验(inverse 硬化 / hourly 清算精度 / 广度面板 / maker /
  DSR+PBO 去多重检验)后,**认证 edge 仅预注册 BTC/ETH**(BTC always-on maker 净 ~+6.4%/yr、Sharpe +1.41、
  PSR 0.998;ETH SR +0.87、PSR 0.974;PBO/CSCV=0 排名不过拟合);**广度证伪**(非宽风险溢价,LINK/LTC 扛不住
  N=8 去膨胀);**A1 基差条件化建仓证伪**(always-on 即最优,基差水平非择时信号)。**窄、薄、真**——可独立小
  资金实操的真 edge。
- `docs/rv-c-plan.md`:§0-6 是 v0.1 预注册计划(四杀手防御 + 三判据 + 工程落点);**§7 是 v0.2-v0.8 实现 + 五轮
  实测结果**(7.2 第一刀过 gate、7.6 广度证伪、7.8 DSR/PBO 认证收窄到 BTC/ETH、7.9 A1 条件化证伪)。

### 线 D — X4 四策略加密 bake-off(隔离,约束最大放松;**赛马答尽 + 双 paper track 前向运营,2026-06-12 立线**)

- **状态:bake-off 答尽、样本外验证完成、两条模拟盘 forward 化运营中**。与线 B/C 的 kill-test 不同——owner 显式
  放松到**不要求证伪/验证门**:四类经典加密策略各做到「回测好看」再用**同等本金($100k/策略)**跑模拟盘横比。
  四策略=网格(S1)/ BTC-ETH 配对(S2)/ 双均线-布林趋势(S3)/ 价量-OI 动量突破(S4),统一标的/窗口(2021-26)/
  费用/本金/指标(公平性是本线的命)。**主要结果**:① **趋势族 S3/S4 = 整轮唯一过样本外的真 edge**(walk-forward
  0.70、泛化 ETH 0.53-0.55),**S2 walk-forward FAIL=过拟合剔除**,S1 网格=费用中性器非 alpha;② 支线全证伪
  (S5 分钟 scalper 散户 taker 不可兑现、S6 截面选币 −86% 尾=负 alpha);③ **S7 多币趋势组合**(把验证过的 S3 铺
  14 币 + 逆波动率 + BTC 大盘闸):Sharpe 0.88 决定性打过 S3 与等权持有=分散>选择命题成立,但 −30% 尾砍不掉
  (crypto-beta 一起跌),可部署档 vol_target=2% → +80%/0.87/−21%。**头条 Sharpe 均被近期牛灌高,诚实前向锚 ~0.70。**
  **运营态**:launchd 每日 10:00 推进两条纯模拟 paper——3 腿 BTC 组合(§18,S1+S3+S4 剔 S2)+ S7 多币趋势组合
  (§19.7);快照落 `state/x4/paper/`(`snapshots.jsonl` + `s7_snapshots.jsonl`)。**下一步纯 OOS 运营。**
- `docs/crypto-x4-plan.md`:**事实入口,§8 变更记录 v0.1→v1.8 是完整证据链**——§9-16 bake-off + 优化 + S6 证伪、
  §17 walk-forward 验证(里程碑)、§18 3 腿 paper 部署 + 日包 fallback、**§19 S7 多币趋势组合(命题/杀线/可部署
  size/forward 化)**。工程落点 `src/qount/x4/`(复用 grid/rv 纯件不改其模块)。

> **隔离边界(线 B / 线 C / 线 D 通用)**:线 B/C/D 是**实验性**项目,所有者已明确多数约束可按需放松——可追
> 盈利、可自行推进 paper/live(小资金实验可接受)、不受线 A 的 §7 止盈与 once-only 验证门约束。线 D 更进一步:
> owner 显式免去证伪要求(赛马而非 kill-test)。它们只向线 A **借教训**(已证伪结论、已验证方法),不借纪律;
> 变更写回本线自己的文档,**不写 current.md / update-log.md**。线 C/D 复用线 B 收口代码(`grid/perp.py` 等)但各
> 落独立命名空间(`src/qount/rv/`、`src/qount/x4/`),不改线 B 模块。下面「推进铁律」只约束**线 A**。

## 推进铁律(仅约束线 A — qount CTA 研究线)

- 一轮只改一处(entry / management / model / prompt 不同时改),先写单测。
- 验证流程：本地 unittest → `scripts/sync-to-wsl.sh --install` → `scripts/run-wsl-tests.sh`
  → 跑对应研究命令 → artifact 落 `state/research_runs` → 写回 current.md / update-log.md。
- live 必须保持关闭(`QOUNT_LIVE_ENABLE=false`);不 forward paper、不放宽 broad gate、
  不在 `discovery_pool` 上调参后当 promotion、Kronos / 外部模型不进 candidate/risk/live。
- Mac(`/Users/alyaloale/Code/qount`)是编辑和 git 表面;WSL
  (`/home/alyaloale/Code/qount`)是生产和回测真相。

> 线 B(GRID-B)的工程理性仍保留(kill-test、扣费建模、与持有基线对比),但那是「怎么知道它
> 真的 work」的方法,不是上面这套冻结纪律;线 B 不强制走 WSL 生产真相链路,可在 Mac 本地直接迭代。
