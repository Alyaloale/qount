# qount 项目规则

> **状态**：active｜**权威**：L1 项目规则｜**最后更新**：2026-08-01
> **本文回答**：代码放哪里、文档怎么分、研究线如何隔离、什么可以直接删。
> **TL;DR**：生产代码、活跃研究、历史研究三层分开；脚本按线路归目录；规则以快速验证和及时删除为优先。

当前事实只看 [`current.md`](current.md)。本文件只管结构和工作方式，不重复生产版本、余额、订单或实验结果。

## 1. 目录地图

```text
src/qount/
  contracts/ execution/ governance/ halt/ ledger/ notifications/
  operations/ persistence/ portfolio/ reporting/ risk/ shadow_accounting/ venue/
      生产控制面和公共合同
  small_account/                         FOMC 与 PreEvent 事件线
  mini_trend/                            加密趋势研究与公共前向采集
  dual_engine/                           G20/C60 无订单模拟盘合同、行情与会计
  alpha_agents/                          主动 research-only 多智能体线
  research_data/                         共享市场数据、指标和研究统计
  research/sleeves/                      主动 Sleeve 研究合同
  legacy/{grid_b,rv_c,line_a,l1,l3,l4,l6,ashare_etf,x4}/ 已冻结线路实现

scripts/
  operations/                            生产/运维薄入口
  desktop/                               当前 MiniTrend 运维入口
  research/{alpha_agents,mini_trend,sleeves,small_account,governance}/
                                          活跃研究薄入口
  archive/research-legacy/{grid-b,rv-c,x4,line-a,l6,ashare-etf}/
                                          冻结线路脚本，不参与当前研究导航

docs/
  current.md project-rules.md quick-handoff.md storage-topology.md holdout.md
                                          当前事实、规则、运维和验证边界
  *-plan.md / *-study.md                 活跃研究或分析文档
  archive/                               历史正文和旧记录
```

代码的真实实现必须放在线路目录；顶层旧模块只允许是兼容转发，不得新增业务逻辑。

## 2. 线路状态

| 线路 | 状态 | 实现目录 | 脚本目录 | 权限 |
| --- | --- | --- | --- | --- |
| FOMC / PreEvent | 研究/历史事件线 | `src/qount/small_account/` | `scripts/operations/` | 当前无交易执行授权；由 `current.md` 的事实状态决定 |
| MiniTrend | 已停止的历史生产链 + research | `src/qount/mini_trend/` | `scripts/research/mini_trend/` | 不因研究结果恢复 live |
| Alpha Agents | active research-only | `src/qount/alpha_agents/` | `scripts/research/alpha_agents/` | 不写订单、目标权重或 live 配置 |
| Sleeve 1 被动配置 | preregistered research-only | `src/qount/research/sleeves/` | `scripts/research/sleeves/` | 不产生 StrategyIntent 或 scheduler |
| Liquidation cascade | public-data-only forward collection | `src/qount/mini_trend/` | `scripts/research/mini_trend/` | 不读私有账户，不下单 |
| Dual-Engine G20/C60 | deployed paper / 2026 YTD curves active | `src/qount/dual_engine/` | `scripts/operations/` | 四个独立模拟账户；YTD 曲线只代表公开行情模拟；禁止账户、订单和 broker API |
| GRID / RV / X4 / CTA-R / L1/L3/L4/L6 / A 股 | archived / frozen | `src/qount/legacy/{grid_b,rv_c,x4,line_a,l1,l3,l4,l6,ashare_etf}/` | `scripts/archive/research-legacy/` | 不恢复，不新增实验 |

## 3. 硬规则

1. `current.md` 是当前事实唯一来源；README、CLAUDE 和研究文档只做导航。
2. 生产控制面不得依赖 `scripts/research`、optional research extra 或 legacy 实现。
3. 共享纯函数放 `research_data/` 或已有公共域；不要从一条策略目录复制一份。
4. 研究脚本只解析参数、调用可测试代码、写 artifact；复杂逻辑放 `src/qount/`。
5. 每条研究线独立保存代码、配置、数据、artifact 和结论；只复用方法，不复用 promotion 资格。
6. 新研究先写一句问题、停止条件和最小验证；没有明确问题就不新建目录或文档。
7. 研究默认 `research_only=true`、`orders_authorized=false`；任何生产权限必须在 `current.md` 明确写出。
8. 发现决定性问题后，写简短弃用原因，停止拉取、回放和自动化；旧材料移入 archive，不为弃用线造防误用系统。
9. 改代码先跑最窄相关测试；改结构再跑导入扫描、架构边界和全量回归（能跑就跑）。
10. 不确定是否还需要的代码先做引用审计；无引用、无 artifact 依赖、无当前文档价值的文件直接删除。

## 4. 研究最小标准

- 时间序列实验不能使用未来数据；重叠标签使用 purged split / embargo 或等价方法。
- 参数搜索记录 trial 数；结果至少报告成本、OOS fold、DSR/PBO 或明确说明未做。
- 横截面研究报告有效广度，不把标的数量当独立样本数。
- 公开数据采集不得携带私钥；collector 不得混入订单或账户路径。
- 结果不自动升级策略；promotion、paper、live 都需要单独 owner 决策。

## 5. 文档规则

- 当前只维护：`current.md`、`project-rules.md`、`quick-handoff.md`、`storage-topology.md`、`holdout.md`、架构主设计、活跃研究文档和近期 `update-log.md`。
- 历史计划、旧运行手册、失败实验和完整记录放 `docs/archive/`；不为兼容旧链接保留大量正文副本。
- 活跃文档 H1 后必须有状态、权威、更新时间和一句 TL;DR；研究结果变更才更新研究文档，当前事实变更才更新 `current.md`。
- 记录文档只记录“做了什么、验证了什么、结论是什么”，不重新维护第二份状态表。
- 新文档先放现有分类；同一主题只有一个主文档，重复草稿直接合并或删除。

## 6. 清理流程

```text
rg 引用 -> 判断生产/活跃/历史 -> 移到线路目录或 archive -> 删除无价值文件
         -> 更新 current / docs index -> 导入扫描 + 相关测试 + git diff --check
```

删除生产入口前必须保留 fail-closed guard；删除纯研究旧代码不需要保留空壳。`qount.main` 和
`qount-monitor` 是公开入口，除非重新确认替代入口，否则不删除。
