# CPI / NFP 右侧锚触发复现

> **状态**：discovery / research-only｜**权威**：L3 研究｜**最后更新**：2026-07-28
> **本文回答**：CPI/NFP 1h 方向锚的触发率与后续幅度复现；不改变 FOMC 合同。

状态：discovery 级研究，2026-07-28。此文只评估 1h 方向锚；不改变 FOMC v0.2 合同，
不构成订单、paper、live、arm 或部署资格。

## 冻结方法

研究窗口为 2024-01 至 2026-06，每个事件类型 30 个 BLS 预定发布时间（08:30
`America/New_York`，含夏令时换算）。日历来源为 [CPI 发布日程](https://www.bls.gov/schedule/news_release/cpi.htm)
与 [Employment Situation 发布日程](https://www.bls.gov/schedule/news_release/empsit.htm)。行情为 OKX `BTC-USDT`
公共 1h K 线，与 [FOMC 触发研究](fomc-trigger-study-and-v03-extension.md) 使用相同的场所和简化口径。

每个发布前只使用已完成的 72 根 1h K 线冻结 `H0/L0` 与 `ATR(14)`，突破线为
`H0 + 0.25 ATR` / `L0 - 0.25 ATR`。发布后 10 小时内第一根收盘在线外的 1h K 线是方向锚；
按该方向计算 D0（10h）、D+1（34h）和 D+3（72h）的有利/不利幅度。没有复现 15m
放量、实体、CLV 或回踩确认，因此锚触发率不是实际成交率，也没有 PnL、成本或 funding 结论。

结果前冻结的门槛：锚触发率至少 40%，且 `D0 >= 2 ATR` 在已触发锚中的比例至少为 FOMC
`7/11` 的 70%，即 44.55%。弱锚定义为 D0 小于 1.5 ATR；其 D+3 反向幅度至少 2 ATR 记为反噬。

## 结果

| 事件 | 锚 | 锚触发率 | D0 >= 2 ATR（条件于锚） | 弱锚反噬 | 预登记结论 |
| --- | ---: | ---: | ---: | ---: | --- |
| CPI | 13 / 30 | 43.33% | 6 / 13 = 46.15% | 6 / 6 | 进入执行篮子 discovery 候选 |
| NFP | 8 / 30 | 26.67% | 4 / 8 = 50.00% | 3 / 3 | 关闭，不进入候选 |

CPI 两道门都只是刚过线，不能据此放宽确认、调整阈值或扩展持有。弱锚反噬在两类事件中都同向复现，
支持维持 “NO_TRADE 是正常结果” 和现有强度/保护结构。NFP 虽然已触发锚中的强突破比例通过，
但总体触发率未过 40% 门槛，按合同直接关闭，不能以条件样本表现救援。

完整逐事件表、冻结 H0/L0/ATR、锚、D0/D+1/D+3 幅度、原始行情响应哈希与可重放结果在：

- `state/research_runs/20260727T162448Z-macro-event-anchor-trigger-study-all/cpi_anchor_trigger_study.json`
- `state/research_runs/20260727T162448Z-macro-event-anchor-trigger-study-all/nfp_anchor_trigger_study.json`

两份 artifact 使用同一份 21,432 根 OKX 1h K 线缓存，市场数据 canonical SHA-256 为
`b4789ebb181ea268bd222d9c94e384d17b9767aa16b1bab95a1c3e8463874b73`。CPI report SHA-256 为
`aa2e36c6e7a438c2d47a989966cdba65f3e3b01ea9c77de84666b9d906248411`，NFP report SHA-256 为
`73a21c5f87489f6241d6e0a6f9a1ae4495872a46eedb39adfe21f871eb94bd65`。行情副本也封存于同一目录，SHA-256 为
`c4762eecbb3ae3ccc98dd2565f7b62dc0dd1f7435c6bb6f77d75583e8a7bdd06`；两份 report 的哈希均覆盖其来源元数据。

下一步只允许为 CPI 写独立的 15m 确认与成本/funding 预登记，再在未消费的前向窗口验证；在此之前，
它不是 FOMC 之外的可执行事件类型。NFP 不再调参、不再扩样本救援。
