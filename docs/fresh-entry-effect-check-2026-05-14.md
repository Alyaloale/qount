# qount fresh entry 上线后验证与下次复查清单（2026-05-14）

这份文档只做两件事：

1. 记录 `2026-05-14` 这次 fresh entry 调整上线后的**当前真实状态**
2. 给下次复查时一个固定检查口径，避免又从零开始想“该看什么”

配套方案文档见：

- [strategy-optimization-design.md](strategy-optimization-design.md)

如果你这次先要确认生产当前到底在跑什么、现在持什么仓、当前 live 是否健康，先看：

- [live-baseline-and-strategy-current.md](live-baseline-and-strategy-current.md)

这份文档现在也是 **fresh entry timing fix 修复版** 的复查入口。

下次如果你问“修复版效果怎么样”，直接继续用这份，不需要再找第二份说明。

补充一条口径约束：

- `blocked_sell` 仍然有用，但它只是 **short 侧辅助切片**
- 因为这第一批同时在修：
  - `XRP` late short
  - `XRP` late long
  - `SOL` flat-bias short
- 所以下次不能只看 `blocked_sell`，还要一起看：
  - `by_lifecycle.fresh_entry`
  - `by_blocked_group.blocked_entry`
  - 按 `decision_action=buy/sell` 拆开的 blocked entry 明细

## 2026-05-14 16:35 CST 第一轮同步结论

这次文档同步已经不再沿用“刚部署完时的判断”，而是按 `2026-05-14 16:35 CST` 的远端 WSL 真实状态更新。

这一段保留第一次同步时的原始判断。

如果你这次只是想看最新状态，直接跳到后面的：

- `2026-05-15 09:57 CST 续查更新`

当前结论先说：

- 修复版运行链路健康
- 但 post-fix 到现在还**没有新的 actionable / fresh_entry 成交样本**
- 所以这份文档当前的重点，不再是“直接判断修复有没有改善 fresh_entry 质量”
- 而是先判断：
  - 为什么还没有新样本
  - 当前是 candidate 没送进来，还是 AI 给了方向又被 risk 压回 `hold`

## 当前已验证状态

检查时间：

- `2026-05-14 16:35 CST`

当前确认结果：

- `qount-runner.timer`
  - `active (waiting)`
  - 下次触发为 `2026-05-14 16:35:00 CST`
- `runtime-status`
  - `mode=live`
  - `exchange_id=binance`
  - `market_type=future`
  - `halted=false`
  - `ai_failure_streak=0`
  - `day_start_equity=161.45633953`
- `preflight-live` 当前全绿
  - `public_api.ok=true`
  - `symbols_ok.ok=true`
  - `credentials.ok=true`
  - `position_mode.ok=true`
  - `balance_guard.ok=true`
  - `live_guard.ok=true`
- 当前账户可用性
  - `quote_total=161.09543868`
  - `quote_free=161.09543868`
  - `available_notional_quote=483.28631604`
  - `planned_entry_quote=48.328631604`
- `live-guard-status`
  - `ok=true`
  - `armed=true`
  - `persistent=true`

## 当前已经证明了什么

已经证明：

- 修复版代码已经同步到生产 WSL
- 当前 timer / runtime / preflight / live guard 都正常
- 新代码没有把 live 链路跑坏
- 当前问题不是“系统没在跑”

还**没有**证明：

- `fresh_entry` 质量已经改善
- `XRP` 末端追单问题已经在真实样本里明显下降
- `SOL flat-bias short` 是否已经在真实运行里更容易被放出来

更准确地说：

- 当前不是“修复版已经跑出一批 fresh-entry 样本，等着评估好坏”
- 而是“修复版到现在还没跑出新的 fresh-entry 成交样本”

## 当前复查基线

修复版部署后，第一轮真实 timer run 是：

- `run_id=1175`
- 时间：`2026-05-14 11:35 CST`
- `symbol=SOL/USDT:USDT`
- `action=hold`
- `order_status=noop`

这个 `1175` 仍然是 post-fix 样本切点：

- **从这份文档开始，默认把 `run_id >= 1175` 当成 post-fix 样本**

截至 `2026-05-14 16:35 CST`：

- `post-fix reviewed = 26`
- `post-fix actionable reviewed = 0`
- `post-fix fresh_entry reviewed = 0`
- `post-fix management_hold reviewed = 13`
- `post-fix missed_move reviewed = 1`
- `post-fix avg_net_edge_pct = 0.0`

这组数字的含义很直接：

- 样本数已经足够说明“修复版在持续运行”
- 但还**不够**说明“fresh-entry 修复有没有改善质量”
- 原因不是 reviewed 太少，而是 `fresh_entry reviewed = 0`

## 当前真正的阻塞点

这是这次同步最重要的新判断。

### 1. 新 reason 还没有开始命中 live

在最近 `120` 个 live run 里，下面这些新 reason 目前还是：

- `short_setup_pre_breakdown_watch`
- `short_setup_late_breakdown_soft_penalty`
- `long_setup_pre_breakout_watch`
- `long_setup_late_breakout_soft_penalty`

返回结果是：

- `[]`

也就是：

- first batch 的新 reason 还没有在真实 live 样本里开始打出来

### 2. post-fix blocked entry 当前全部是 `buy`

当前 post-fix `blocked_entry` 里：

- `buy.reviewed = 8`
- `sell.reviewed = 0`

所以现阶段不能把复查重点继续放在：

- `blocked_sell`
- short 被误伤

当前更真实的阻塞点是：

- long 侧 candidate/AI 已经偶尔想开
- 但 risk 把它们压回去了

### 3. 当前主要卡在 risk，不是 fresh-entry 新规则

这 `8` 个 post-fix `blocked_entry buy` 的原因分布是：

- `expected_edge_below_minimum = 7`
- `open_signal_return_24bars_too_weak = 1`

candidate 原因分布是：

- `candidate_ok = 5`
- `low_volatility_soft_penalty = 3`

这说明当前最近几轮更像是：

1. `candidate_filter` 已经选出了 symbol
2. AI 已经给了 `buy`
3. risk 因 `expected_edge_below_minimum` 或 `open_signal_return_24bars_too_weak` 压回 `hold`

所以如果下一轮还没有新的 fresh-entry 成交样本，优先要复查的是：

- `expected_edge_pct`
- `open_signal_return_24bars`

而不是先继续细化：

- `late_breakdown / late_breakout`

## 下次复查先看什么

下次不要重新想检查路径，直接按下面顺序走。

### 0. 先过样本门槛，再谈“效果”

如果你这次要下“修复版已经有效/无效”的结论，先确认至少满足：

- `post-fix reviewed >= 12`
- `post-fix fresh_entry reviewed >= 6`

当前实际状态是：

- `post-fix reviewed = 26`
- `post-fix fresh_entry reviewed = 0`

也就是：

- 第一条已经满足
- 第二条完全没满足

所以当前上限只能写成：

- `修复版运行健康`
- `当前还没有新的 fresh-entry 成交样本`
- `当前主要阻塞点更像 risk hold，而不是 first-batch 新 reason`
- `暂时还不能判定 fresh-entry 质量是否改善`

### 1. 先确认 runtime 还是健康的

```bash
ssh home "wsl.exe bash -lc 'date \"+%F %T %Z\"; systemctl --user status qount-runner.timer --no-pager --full'"
ssh home "wsl.exe bash -lc 'cd /home/alyaloale/Code/qount && set -a && source .env && set +a && ./.venv/bin/python -m qount.main runtime-status | python3 -m json.tool'"
ssh home "wsl.exe bash -lc 'cd /home/alyaloale/Code/qount && set -a && source .env && set +a && ./.venv/bin/python -m qount.main preflight-live | python3 -m json.tool'"
```

先保证：

- timer 还在 `active (waiting)`
- 最新 run 还能持续完成
- `halted=false`
- `ai_failure_streak=0`
- `preflight-live` 仍然全绿

### 2. 再看最近几轮 live run 到底发生了什么

```bash
cat <<'PY' | ssh home 'wsl.exe bash -lc "cd /home/alyaloale/Code/qount && python3 -"'
import sqlite3, json
con = sqlite3.connect('state/qount.db')
con.row_factory = sqlite3.Row
rows = con.execute("""
select id, started_at, finished_at, mode, status, summary_json
from runs
where mode='live'
order by id desc
limit 12
""").fetchall()
out = []
for r in rows:
    s = json.loads(r["summary_json"] or "{}")
    out.append({
        "id": r["id"],
        "started_at": r["started_at"],
        "finished_at": r["finished_at"],
        "status": r["status"],
        "symbol": s.get("symbol"),
        "action": s.get("action"),
        "order_status": s.get("order_status"),
        "candidate_filter": s.get("candidate_filter"),
        "error": s.get("error"),
    })
print(json.dumps(out, ensure_ascii=False, indent=2))
PY
```

这里重点看三件事：

1. 有没有新的 failed run
2. 最新 candidate filter 里有没有开始出现：
   - `short_setup_pre_breakdown_watch`
   - `short_setup_late_breakdown_soft_penalty`
   - `long_setup_pre_breakout_watch`
   - `long_setup_late_breakout_soft_penalty`
3. 有没有新的 post-fix `fresh_entry`
   - 尤其是 `run_id >= 1175` 之后的 `SOL` / `XRP`
4. 如果没有新的 `fresh_entry`
   - 那最近 selected candidate 是被哪一层压成了 `hold`

### 2.1 先单独查新 reason 有没有开始出现

如果你这次只想先回答一句“修复版有没有开始打出新 reason”，直接跑这个：

```bash
cat <<'PY' | ssh home 'wsl.exe bash -lc "cd /home/alyaloale/Code/qount && python3 -"'
import sqlite3, json

WATCH = {
    "short_setup_pre_breakdown_watch",
    "short_setup_late_breakdown_soft_penalty",
    "long_setup_pre_breakout_watch",
    "long_setup_late_breakout_soft_penalty",
}

con = sqlite3.connect('state/qount.db')
con.row_factory = sqlite3.Row
rows = con.execute("""
select id, started_at, finished_at, status, summary_json
from runs
where mode='live'
order by id desc
limit 80
""").fetchall()

out = []
for row in rows:
    summary = json.loads(row["summary_json"] or "{}")
    candidate_filter = summary.get("candidate_filter") or {}
    for symbol_summary in candidate_filter.get("symbols") or []:
        reasons = symbol_summary.get("reasons") or []
        matched = [reason for reason in reasons if reason in WATCH]
        if matched:
            out.append({
                "run_id": row["id"],
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
                "status": row["status"],
                "run_symbol": summary.get("symbol"),
                "run_action": summary.get("action"),
                "candidate_symbol": symbol_summary.get("symbol"),
                "matched_reasons": matched,
                "all_reasons": reasons,
            })

print(json.dumps(out, ensure_ascii=False, indent=2))
PY
```

这条命令的解释：

- 返回 `[]`
  - 说明修复版到当前为止还没遇到能触发这些 reason 的真实 live 样本
  - 如果最近很多 run 已经 `candidate_ok` 或进入 AI，但这里长期还是 `[]`
    - 说明当前 live 的真实阻塞点不在 first-batch 新 reason，而更可能在后面的 risk gate
- 开始出现 `short_setup_pre_breakdown_watch`
  - 说明 `SOL` 一类“早段 continuation short”开始被 candidate 层明确标出来了
- 开始出现 `short_setup_late_breakdown_soft_penalty`
  - 说明末端追空样本终于开始被识别，而不是继续当成 `candidate_ok`
- 开始出现 `long_setup_pre_breakout_watch` / `long_setup_late_breakout_soft_penalty`
  - 说明 long 侧的新 timing 规则也开始进入真实样本
- 如果这类 reason 很快出现很多，但后面仍全是 `hold`
  - 说明 prompt / risk 仍然太保守，下一轮再查为什么没出手

### 3. 再跑 signal-review 看“效果”，不要只看最近一轮

```bash
ssh home "wsl.exe bash -lc 'cd /home/alyaloale/Code/qount && set -a && source .env && set +a && ./.venv/bin/python -m qount.main signal-review --limit 220 --horizon-bars 3 --threshold-pct 0.003'"
```

如果想把重点摘要直接拉出来：

```bash
ssh home "wsl.exe bash -lc 'cd /home/alyaloale/Code/qount && set -a && source .env && set +a && ./.venv/bin/python -m qount.main signal-review --limit 220 --horizon-bars 3 --threshold-pct 0.003'" > /tmp/qount-signal-review-next.json
python3 - <<'PY'
import json
obj = json.load(open('/tmp/qount-signal-review-next.json'))
agg = obj["aggregate"]
summary = {
    "overall": agg["overall"],
    "hold": agg["hold"],
    "actionable": agg["actionable"],
    "by_lifecycle_fresh_entry": agg["by_lifecycle"].get("fresh_entry"),
    "by_lifecycle_management_hold": agg["by_lifecycle"].get("management_hold"),
    "by_symbol": agg["by_symbol"],
    "by_blocked_group": agg["by_blocked_group"],
    "blocked_sell": agg["blocked_sell"],
}
print(json.dumps(summary, ensure_ascii=False, indent=2))
PY
```

上面这里把 `--threshold-pct 0.003` 显式写死，是为了保证：

- `good_hold / missed_move / good / bad`
- `hold.good_hold`
- `hold.missed_move`

的前后对比口径不被默认值漂移污染。

### 3.1 如果只想看修复版样本，不要再混入旧 run

上面的整窗 review 会混入更早的样本。  
如果你这次问的是“修复版有没有开始起作用”，直接把 `run_id >= 1175` 当作 post-fix 样本：

```bash
python3 - <<'PY'
import json

POST_FIX_MIN_RUN_ID = 1175

obj = json.load(open('/tmp/qount-signal-review-next.json'))
reviews = [
    r for r in obj["reviews"]
    if r.get("status") == "reviewed" and (r.get("run_id") or 0) >= POST_FIX_MIN_RUN_ID
]

def avg(values):
    values = [v for v in values if v is not None]
    return None if not values else sum(values) / len(values)

summary = {
    "post_fix_run_cutoff": POST_FIX_MIN_RUN_ID,
    "reviewed": len(reviews),
    "actionable_reviewed": sum(r.get("review_action") != "hold" for r in reviews),
    "fresh_entry_reviewed": sum(r.get("decision_lifecycle") == "fresh_entry" for r in reviews),
    "management_hold_reviewed": sum(r.get("decision_lifecycle") == "management_hold" for r in reviews),
    "blocked_entry_reviewed": sum(r.get("decision_lifecycle") == "blocked_entry" for r in reviews),
    "missed_move_reviewed": sum(r.get("outcome") == "missed_move" for r in reviews),
    "avg_net_edge_pct": avg([r.get("net_edge_pct") for r in reviews]),
    "fresh_entry_avg_net_edge_pct": avg([
        r.get("net_edge_pct")
        for r in reviews
        if r.get("decision_lifecycle") == "fresh_entry"
    ]),
    "actionable_avg_net_edge_pct": avg([
        r.get("net_edge_pct")
        for r in reviews
        if r.get("review_action") != "hold"
    ]),
    "by_symbol": {},
}

for symbol in sorted({r.get("symbol") for r in reviews if r.get("symbol")}):
    items = [r for r in reviews if r.get("symbol") == symbol]
    summary["by_symbol"][symbol] = {
        "reviewed": len(items),
        "fresh_entry": sum(r.get("decision_lifecycle") == "fresh_entry" for r in items),
        "missed_move": sum(r.get("outcome") == "missed_move" for r in items),
        "avg_net_edge_pct": avg([r.get("net_edge_pct") for r in items]),
    }

print(json.dumps(summary, ensure_ascii=False, indent=2))
PY
```

这一步很容易忘，但修复版复查时必须做：

- 如果你不切 `run_id >= 1175`
- 很容易把 `1038`、`924`、`1166` 这些修复前坏样本又算进去
- 然后误以为“修复版没有变好”
- 如果切完之后还是 `fresh_entry_reviewed = 0`
  - 当前问题就不是“修复后的 fresh-entry 好不好”
  - 而是“为什么修复后根本没有新的 fresh-entry 成交样本”

### 3.2 不要只看 blocked_sell，再补一层 blocked entry 双向拆分

`blocked_sell` 只能看：

- `decision_action=sell`
- 但最终被 risk 压成 `hold`

这对 short 侧很有用，但这第一批还同时修了 late long，所以还要把 `blocked_entry` 再按 `buy/sell` 拆一遍。

当前这一步最重要的判断是：

- 如果 `sell.reviewed` 还是 `0`
  - 就不要继续把注意力放在 `blocked_sell`
- 如果 `buy.reviewed` 明显更多，且 `expected_edge_below_minimum` 占大头
  - 当前优先要审的是 `expected_edge_pct`
- 如果 `buy.reviewed` 主要卡在 `open_signal_return_24bars_too_weak`
  - 再去看 long 侧 signal 约束是不是过严

```bash
python3 - <<'PY'
import json

POST_FIX_MIN_RUN_ID = 1175

obj = json.load(open('/tmp/qount-signal-review-next.json'))
reviews = [
    r for r in obj["reviews"]
    if r.get("status") == "reviewed"
    and (r.get("run_id") or 0) >= POST_FIX_MIN_RUN_ID
    and r.get("decision_lifecycle") == "blocked_entry"
]

def avg(values):
    values = [v for v in values if v is not None]
    return None if not values else sum(values) / len(values)

summary = {}
for action in ("buy", "sell"):
    items = [r for r in reviews if r.get("decision_action") == action]
    by_reason = {}
    by_candidate_reason = {}
    for item in items:
        for reason in item.get("risk_reasons") or []:
            key = str(reason).split(":", 1)[0]
            by_reason[key] = by_reason.get(key, 0) + 1
        candidate_reason = item.get("candidate_filter_primary_reason") or "unknown"
        by_candidate_reason[candidate_reason] = by_candidate_reason.get(candidate_reason, 0) + 1
    summary[action] = {
        "reviewed": len(items),
        "missed_move": sum(r.get("outcome") == "missed_move" for r in items),
        "avg_opportunity_edge_pct": avg([r.get("opportunity_edge_pct") for r in items]),
        "by_reason": by_reason,
        "by_candidate_reason": by_candidate_reason,
    }

print(json.dumps(summary, ensure_ascii=False, indent=2))
PY
```

### 3.3 如果要专门看 `1286+` 这段新样本

上面的 `run_id >= 1175` 适合看整个 post-fix 阶段。  
如果你这次关心的是：

- `1279` 那笔第一条 `XRP long` 之后
- 系统又继续长出了哪些新 `fresh_entry`
- `XRP` 和 `SOL` 的分化有没有继续扩大

那就把口径再收窄到：

- `run_id >= 1286`

为什么是 `1286`：

- `1279~1285` 主要还是第一笔 `XRP long` 的持仓管理链
- 从 `1286` 开始，更适合单独看“第一笔新路径放出来之后，这版又继续产出了什么”

```bash
python3 - <<'PY'
import json

LATEST_PHASE_MIN_RUN_ID = 1286

obj = json.load(open('/tmp/qount-signal-review-next.json'))
reviews = [
    r for r in obj["reviews"]
    if r.get("status") == "reviewed" and (r.get("run_id") or 0) >= LATEST_PHASE_MIN_RUN_ID
]

def avg(values):
    values = [v for v in values if v is not None]
    return None if not values else sum(values) / len(values)

summary = {
    "cutoff": LATEST_PHASE_MIN_RUN_ID,
    "reviewed": len(reviews),
    "actionable_reviewed": sum(r.get("review_action") != "hold" for r in reviews),
    "fresh_entry_reviewed": sum(r.get("decision_lifecycle") == "fresh_entry" for r in reviews),
    "blocked_entry_reviewed": sum(r.get("decision_lifecycle") == "blocked_entry" for r in reviews),
    "management_hold_reviewed": sum(r.get("decision_lifecycle") == "management_hold" for r in reviews),
    "idle_hold_reviewed": sum(r.get("decision_lifecycle") == "idle_hold" for r in reviews),
    "missed_move_reviewed": sum(r.get("outcome") == "missed_move" for r in reviews),
    "fresh_entry_avg_net_edge_pct": avg([
        r.get("net_edge_pct")
        for r in reviews
        if r.get("decision_lifecycle") == "fresh_entry"
    ]),
    "actionable_avg_net_edge_pct": avg([
        r.get("net_edge_pct")
        for r in reviews
        if r.get("review_action") != "hold"
    ]),
    "by_symbol": {},
}

for symbol in sorted({r.get("symbol") for r in reviews if r.get("symbol")}):
    items = [r for r in reviews if r.get("symbol") == symbol]
    summary["by_symbol"][symbol] = {
        "reviewed": len(items),
        "fresh_entry": sum(r.get("decision_lifecycle") == "fresh_entry" for r in items),
        "blocked_entry": sum(r.get("decision_lifecycle") == "blocked_entry" for r in items),
        "management_hold": sum(r.get("decision_lifecycle") == "management_hold" for r in items),
        "idle_hold": sum(r.get("decision_lifecycle") == "idle_hold" for r in items),
        "missed_move": sum(r.get("outcome") == "missed_move" for r in items),
        "fresh_entry_avg_net_edge_pct": avg([
            r.get("net_edge_pct")
            for r in items
            if r.get("decision_lifecycle") == "fresh_entry"
        ]),
    }

print(json.dumps(summary, ensure_ascii=False, indent=2))
PY
```

这个切片当前最值得看的不是总 `reviewed`，而是：

- `XRP fresh_entry` 有没有继续增加
- `XRP fresh_entry_avg_net_edge_pct` 能不能继续保持正值
- `SOL fresh_entry_avg_net_edge_pct` 是不是还在负区间
- `missed_move` 主要堆在哪个 symbol / lifecycle 上

### 4. 如需逐条看 fresh entry / missed move，再拉细项

```bash
python3 - <<'PY'
import json
obj = json.load(open('/tmp/qount-signal-review-next.json'))
reviews = obj["reviews"]
payload = {
    "fresh_entry": [
        {
            "run_id": r.get("run_id"),
            "symbol": r.get("symbol"),
            "review_action": r.get("review_action"),
            "outcome": r.get("outcome"),
            "net_edge_pct": r.get("net_edge_pct"),
            "future_R": r.get("future_R"),
            "candidate_filter_primary_reason": r.get("candidate_filter_primary_reason"),
            "risk_reasons": r.get("risk_reasons"),
        }
        for r in reviews
        if r.get("status") == "reviewed" and r.get("decision_lifecycle") == "fresh_entry"
    ],
    "missed_move": [
        {
            "run_id": r.get("run_id"),
            "symbol": r.get("symbol"),
            "decision_context": r.get("decision_context"),
            "decision_lifecycle": r.get("decision_lifecycle"),
            "candidate_filter_primary_reason": r.get("candidate_filter_primary_reason"),
            "risk_reasons": r.get("risk_reasons"),
            "opportunity_edge_pct": r.get("opportunity_edge_pct"),
        }
        for r in reviews
        if r.get("status") == "reviewed" and r.get("outcome") == "missed_move"
    ],
}
print(json.dumps(payload, ensure_ascii=False, indent=2))
PY
```

如果你这次只想看 `1286+` 之后的逐条明细，把上面那段再收窄一层：

```bash
python3 - <<'PY'
import json

LATEST_PHASE_MIN_RUN_ID = 1286

obj = json.load(open('/tmp/qount-signal-review-next.json'))
reviews = [
    r for r in obj["reviews"]
    if r.get("status") == "reviewed" and (r.get("run_id") or 0) >= LATEST_PHASE_MIN_RUN_ID
]

payload = {
    "fresh_entry": [
        {
            "run_id": r.get("run_id"),
            "symbol": r.get("symbol"),
            "review_action": r.get("review_action"),
            "outcome": r.get("outcome"),
            "net_edge_pct": r.get("net_edge_pct"),
            "candidate_filter_primary_reason": r.get("candidate_filter_primary_reason"),
            "risk_reasons": r.get("risk_reasons"),
        }
        for r in reviews
        if r.get("decision_lifecycle") == "fresh_entry"
    ],
    "missed_move": [
        {
            "run_id": r.get("run_id"),
            "symbol": r.get("symbol"),
            "decision_lifecycle": r.get("decision_lifecycle"),
            "decision_action": r.get("decision_action"),
            "opportunity_edge_pct": r.get("opportunity_edge_pct"),
            "candidate_filter_primary_reason": r.get("candidate_filter_primary_reason"),
            "risk_reasons": r.get("risk_reasons"),
        }
        for r in reviews
        if r.get("outcome") == "missed_move"
    ],
}

print(json.dumps(payload, ensure_ascii=False, indent=2))
PY
```

## 2026-05-15 09:57 CST 续查更新

这段是按上面 `3.x` 那套口径继续往后查到最新远端 WSL live 样本后的更新。

如果你现在只想看最新判断，优先看这一节。

### 当前运行面

检查时间：

- `2026-05-15 09:57 CST`

当前确认结果：

- `qount-runner.timer`
  - 仍然是 `active (waiting)`
  - 下次触发为 `2026-05-15 10:00:00 CST`
- `runtime-status`
  - `mode=live`
  - `exchange_id=binance`
  - `market_type=future`
  - `halted=false`
  - `ai_failure_streak=0`
  - `day_start_equity=163.34624753`
- `live-guard-status`
  - `ok=true`
  - `armed=true`
  - `persistent=true`
  - `live_enable=true`
- 最新 live run
  - `run_id=1445`
  - `status=completed`
  - 最近几轮都是 `order_status=noop`
- 当前账户
  - `equity_quote=163.00971222`
  - `quote_free=163.00971222`
  - `open_positions=[]`

### 当前结论先说

到这一步，结论已经不能再写成“post-fix 还没有新的 fresh-entry 样本”了。

现在更准确的结论是：

- `SOL` 那条老的 flat-bias short 放行问题，到现在仍然没有重新回来
- `XRP long` 已经不止 `1279` 那一笔，后面继续长出了新的 `fresh_entry`
- 但系统不是“fresh-entry 已经全面修好”
  - `XRP fresh_entry` 明显转正
  - `SOL fresh_entry` 仍然偏差，而且问题已经从旧的 short 路径换成了 `SOL long`

所以当前更准确的说法应该是：

- 这版已经证明“先把 `SOL` 旧坏 short 路径收住，并把主动样本更多转向 `XRP long`”
- 还不能写成“所有 fresh-entry 质量都已经稳定改善”

### 昨晚为什么还能赚

这次复盘不能只看最新一条坏样本，还要看账户曲线和阶段性收益。

从账户权益看：

- `2026-05-14 16:35 CST` 当时文档里记录的 `quote_total=161.09543868`
- 到 `2026-05-15` 日切时，`day_start_equity=163.34624753`
- 夜间净抬升约 `+2.25080885 USDT`
- 截至 `2026-05-15 09:57 CST` 当前权益 `163.00971222`
- 即使把凌晨这段回撤算进去，仍然比 `16:35 CST` 高 `+1.91427354 USDT`

这说明：

- 昨晚 real PnL 层面确实是赚钱的
- 赚钱主体更像 `XRP long fresh_entry + 后续管理/止盈`
- 不是 `SOL` 帮你赚的

### `1286+` 当前摘要

这个口径下当前数字是：

- `reviewed=148`
- `actionable_reviewed=14`
- `fresh_entry_reviewed=8`
- `blocked_entry_reviewed=42`
- `management_hold_reviewed=64`
- `missed_move_reviewed=21`
- `fresh_entry_avg_net_edge_pct=0.16395814196052746`
- `actionable_avg_net_edge_pct=0.10194759752056057`

按 symbol 看：

- `XRP/USDT:USDT`
  - `reviewed=82`
  - `fresh_entry=5`
  - `blocked_entry=23`
  - `missed_move=15`
  - `fresh_entry_avg_net_edge_pct=0.3864116250553607`
- `SOL/USDT:USDT`
  - `reviewed=66`
  - `fresh_entry=3`
  - `blocked_entry=19`
  - `missed_move=6`
  - `fresh_entry_avg_net_edge_pct=-0.20679766319752793`

`1286+` 这段最关键的分化是：

- `XRP` 后面已经不只是 `1279` 那 1 笔，而是又继续长出了 `5` 笔 `fresh_entry`
- 这 `5` 笔里有 `2 good / 2 flat / 1 bad`
- `SOL` 这边虽然旧 short 没回来，但新的 `fresh_entry` 质量仍差
  - `3` 笔里有 `2 bad / 1 flat`

### 这轮做得好的地方

1. `SOL` 旧 flat-bias short 没有重新回来，这是这轮修复最先兑现的目标。
2. `XRP long` 不再只是单笔偶然样本，`1286+` 里已经有一批连续 `fresh_entry`，而且平均后验结果是正的。
3. 赚钱路径开始更清楚地集中在 `XRP`，不是继续靠 `SOL` 的坏 short 去赌。
4. runtime 没被改坏，timer / live guard / runtime-status 到最新都还是健康的。
5. 昨晚账户曲线确实向上，说明这版不是只在 review 统计里“看起来更好”，而是实盘层面也兑现过盈利。

### 这轮不足的地方

1. `SOL fresh_entry` 仍然偏差，只是问题从旧 short 换成了 `SOL long`。
2. `XRP` 的 `missed_move` 还是偏多，主体是 `blocked_entry buy`，说明机会并没有被吃干净。
3. `XRP blocked_entry buy` 现在主要卡在：
   - `open_signal_sma_fast_conflict`
   - `expected_edge_below_minimum`
   - `open_signal_return_24bars_too_weak`
4. `management_hold` 的 missed move 还不能算低，尤其 `XRP` 和 `SOL` 都还有管理阶段漏掉延续段的问题。
5. 最新 `run_id=1438` 的 `XRP fresh_entry` 又打出一笔 `bad`，说明新路径是变好了，但还远没有稳定到可以放松警惕。

## 2026-05-15 10:07 CST 再续查

这次是在上面 `09:57 CST` 那轮之后，继续按同一份文档再跑一轮远端 WSL 检查。

这轮的重点不是重新下结论，而是确认：

- runtime 有没有回归
- 最新几轮有没有新 actionable 样本
- `1286+` 这段口径有没有被新的样本改写

### 当前运行面

检查时间：

- `2026-05-15 10:07 CST`

当前确认结果：

- `qount-runner.timer`
  - 仍然是 `active (waiting)`
  - 下次触发为 `2026-05-15 10:10:00 CST`
- `runtime-status`
  - `halted=false`
  - `ai_failure_streak=0`
- `preflight-live`
  - 仍然全绿
- `live-guard-status`
  - `live_enable=true`
  - `persistent=true`
- 最新 live run
  - `run_id=1447`
  - `status=completed`
  - 最近几轮仍然是 `order_status=noop`
- 当前账户
  - `equity_quote=163.00971222`
  - `quote_free=163.00971222`
  - `open_positions=[]`

### 和 `09:57 CST` 相比，这轮新增了什么

先说最重要的：

- 没有新增 actionable / fresh-entry / blocked-entry 样本
- 这轮新增进入 3-bar review 的，主要只是新的 `hold` 样本

最新整窗摘要变成：

- `reviewed=225`
- `hold.reviewed=205`
- `actionable.reviewed=20`
- `by_lifecycle.fresh_entry.reviewed=12`
- `by_lifecycle.blocked_entry.reviewed=58`
- `by_lifecycle.management_hold.reviewed=100`

也就是说，相比 `09:57 CST`：

- `reviewed` 只多了 `1`
- 增量主要来自 `hold`
- 不是新的 entry / exit 行为

### 这轮最值得记下来的点

#### 1. 这轮没有推翻上一轮结论

当前两层核心口径变成：

- `run_id >= 1175`
  - `reviewed=211`
  - `actionable_reviewed=19`
  - `fresh_entry_reviewed=11`
  - `blocked_entry_reviewed=57`
  - `missed_move_reviewed=22`
  - `fresh_entry_avg_net_edge_pct=0.055604851519591096`
- `run_id >= 1286`
  - `reviewed=150`
  - `actionable_reviewed=14`
  - `fresh_entry_reviewed=8`
  - `blocked_entry_reviewed=42`
  - `missed_move_reviewed=21`
  - `fresh_entry_avg_net_edge_pct=0.16395814196052746`

这说明：

- 当前只是样本窗继续往后滚了一点
- 但 `XRP fresh_entry` 为正、`SOL fresh_entry` 为负 这个核心分化没有被新样本打掉

#### 2. 最新已完成 review 的新增样本，还是 `hold -> good_hold`

这轮进入 reviewed 的最新 run 主要是：

- `run_id=1444`
  - `SOL idle_hold -> good_hold`
- `run_id=1445`
  - `SOL idle_hold -> good_hold`

所以这轮不能写成：

- “又出现了新一笔好 entry”

更准确的写法是：

- “最近系统还在稳定运行，但新增 reviewed 样本主要只是合理 hold”

#### 3. `1446 / 1447` 还没进 3-bar review，但当前 live candidate 值得记

最新两轮 live run 是：

- `run_id=1446`
- `run_id=1447`

它们当前的 candidate 状态很有代表性：

- `XRP`
  - 仍然是 `candidate_ok`
- `SOL`
  - 已经回到 `higher_timeframe_flat_bias_soft_penalty`
  - 当前 `higher_timeframe_bias=flat`

这说明：

- `SOL` 旧 flat-bias 问题的压制逻辑仍然在工作
- `XRP` 还是更容易成为当前主动观察对象

#### 4. 新 reason 不是空了，但当前主要是 long 侧命中

这次按最近 `120` 个 live run 重查后，当前真实命中的新 reason 是：

- `run_id=1331`
  - `XRP/USDT:USDT`
  - `long_setup_pre_breakout_watch`
  - 当轮 `run_action=buy`
- `run_id=1332`
  - `SOL` 这轮实际在跑，但 `XRP` candidate 被打上 `long_setup_late_breakout_soft_penalty`
- `run_id=1356`
  - `XRP long_setup_late_breakout_soft_penalty`
- `run_id=1358`
  - `XRP long_setup_late_breakout_soft_penalty`
- `run_id=1366`
  - `XRP long_setup_late_breakout_soft_penalty`

当前这条线的含义是：

- long 侧的新 timing rule 已经确实进入过真实 live 样本
- 不是一直 `[]`
- 但 short 侧这轮还没有看到：
  - `short_setup_pre_breakdown_watch`
  - `short_setup_late_breakdown_soft_penalty`

#### 5. `1286+` 的 missed move 结构还没变

这轮 `1286+` 下：

- `SOL missed_move=6`
  - `management_hold=4`
  - `blocked_entry=2`
- `XRP missed_move=15`
  - `blocked_entry=8`
  - `idle_hold=4`
  - `management_hold=3`

`1286+ blocked_entry` 仍然主要是：

- `buy.reviewed=40`
  - `expected_edge_below_minimum=21`
  - `open_signal_return_24bars_too_weak=13`
  - `open_signal_sma_slow_conflict=8`
  - `open_signal_sma_fast_conflict=6`
- `sell.reviewed=2`
  - `2` 笔都是 `missed_move`
  - 原因都还是 `open_signal_return_24bars_too_weak`

这说明下一轮如果要继续动策略，优先级仍然没变：

- 先审 `XRP blocked_entry.buy`
- 再审 `SOL long fresh_entry`

## 2026-05-15 10:45 CST 二次窄优化已上线

上面 `1175+ / 1286+` 那些结论，仍然是第一轮 fresh-entry timing 修复的复盘结果。  
但在这之后，已经根据最新复查又上线了第二轮窄优化。

这轮不是重新大改策略方向，而是只针对两类已经明确的问题做窄修：

1. `SOL long fresh_entry`
   - 继续收紧 late / overextended long chase
2. `XRP blocked_entry.buy`
   - 给 `1h long` 下的 reclaim / oversold reversal / fast pullback 一条更窄的 risk 通道

这轮代码已经：

- 同步到远端 WSL
- 重新 `pip install -e .`
- 本地和远端 WSL 都重新跑通：
  - `PYTHONPATH=src python3 -m unittest tests.test_strategy_optimization`
  - `53` 条全部通过
- `runtime-status` 仍然：
  - `halted=false`
  - `ai_failure_streak=0`
- `preflight-live` 仍然全绿

### 新复查切点

为了不把第二轮代码和前一轮 `1175+ / 1286+` 样本混在一起，下次如果你问：

- “这轮新优化上线后，有没有开始改善”

请直接把下面这条当成新窗口起点：

- **`run_id >= 1455`**

这里的 `1455` 是：

- `2026-05-15 10:45 CST`
- 本轮二次窄优化部署完成后的第一条新 live run

### 当前刚上线后的第一条现场信号

`run_id=1455` 当前记录到的是：

- `symbol=XRP/USDT:USDT`
- `action=hold`
- `order_status=noop`
- candidate 仍然表现成：
  - `XRP = candidate_ok`
  - `SOL = higher_timeframe_flat_bias_soft_penalty`

这说明刚上线后的第一条新 run 里：

- runtime 没坏
- `SOL` 旧 flat-bias short 压制逻辑还在
- `XRP` 仍然是当前更容易进入主动观察的 symbol

但这还**不能**说明第二轮代码已经改善了 `fresh_entry` 质量，因为：

- 目前还没有 `run_id >= 1455` 的 reviewed 样本
- 现在只能先把它当成新的复查起点

## 下次重点看哪些变化

### 想看到的好变化

1. `XRP fresh_entry` 继续增加，而且 `avg_net_edge_pct` 不回到负值。
2. `SOL fresh_entry` 再出现时，不再稳定落在负区间，至少先回到接近 `0`。
3. `XRP blocked_entry.buy.missed_move` 明显下降，尤其不要长期被 `expected_edge_below_minimum` 和 `open_signal_sma_fast_conflict` 主导。
4. `management_hold.missed_move` 明显下降，说明系统不只是会开仓，也开始更会守住已经赚到的段落。
5. 夜间这类盈利不被后续几笔坏单快速回吐。
6. 新 reason 继续开始命中真实样本，但不是靠误杀大量干净 setup 来“变好”。
7. timer / preflight / live guard 继续稳定，不要把策略讨论又打回运行故障。

当前更理想的推进顺序是：

- 先继续验证 `XRP` 新路径是不是可持续
- 再判断 `SOL long` 到底是偶发坏样本，还是下一轮真正要修的新主问题

### 需要警惕的坏变化

1. `SOL fresh_entry.avg_net_edge_pct` 继续稳定为负，说明旧 short 问题虽然收住了，但 long 侧新问题已经足够实质。
2. `XRP` 最新连续几笔 `fresh_entry` 又重新集中打成 `bad`，把现在这点正基线吃回去。
3. `XRP blocked_entry.buy` 的 `missed_move` 继续堆高，说明当前还是漏掉了太多本该吃到的 long 机会。
4. `management_hold.missed_move` 继续上升，说明系统会开仓但不会守利润。
5. `SOL` 旧 short 路径重新出现，尤其是又回到 flat-bias 直接放空。
6. timer / preflight / live guard 出现回归。
   - 先按运行故障处理，不要直接谈策略。

## 这次复查的基线

下次比较时，先默认拿下面三层基线：

- 当前全窗基线：
  - `signal-review --limit 260 --horizon-bars 3 --threshold-pct 0.003`
  - `reviewed=225`
  - `hold.reviewed=205`
  - `actionable.reviewed=20`
  - `by_lifecycle.fresh_entry.reviewed=12`
  - `by_lifecycle.blocked_entry.reviewed=58`
  - `by_lifecycle.management_hold.reviewed=100`
  - `blocked_sell.reviewed=6`
  - `blocked_sell.missed_move=2`
- 当前 post-fix 基线（`run_id >= 1175`）：
  - `reviewed=211`
  - `actionable_reviewed=19`
  - `fresh_entry_reviewed=11`
  - `blocked_entry_reviewed=57`
  - `management_hold_reviewed=92`
  - `idle_hold_reviewed=43`
  - `missed_move_reviewed=22`
  - `fresh_entry_avg_net_edge_pct=0.055604851519591096`
  - `actionable_avg_net_edge_pct=0.018081945172659708`
- 当前 `1286+` 专门观察基线：
  - `reviewed=150`
  - `actionable_reviewed=14`
  - `fresh_entry_reviewed=8`
  - `blocked_entry_reviewed=42`
  - `management_hold_reviewed=64`
  - `idle_hold_reviewed=30`
  - `missed_move_reviewed=21`
  - `fresh_entry_avg_net_edge_pct=0.16395814196052746`
  - `actionable_avg_net_edge_pct=0.10194759752056057`
  - `XRP.fresh_entry_reviewed=5`
  - `XRP.fresh_entry_avg_net_edge_pct=0.3864116250553607`
  - `SOL.fresh_entry_reviewed=3`
  - `SOL.fresh_entry_avg_net_edge_pct=-0.20679766319752793`
- 第二轮窄优化的新起点：
  - `run_id >= 1455`
  - `2026-05-15 10:45 CST`
  - 当前刚上线，先不要拿它和 `1175+ / 1286+` 的旧窗直接合并下结论
- 专线恢复后的新起点：
  - `run_id >= 1495`
  - `2026-05-15 14:05 CST`
  - 这一窗必须和前面的“代理故障 / `-2015` / halted”样本彻底拆开
- 历史旧基线：
  - `actionable.avg_net_edge_pct=-0.0901%`
  - `by_lifecycle.fresh_entry.avg_net_edge_pct=-0.1443%`
  - `hold.reviewed=116`
  - `hold.good_hold=110`
  - `hold.missed_move=6`

## 2026-05-15 14:27 CST 专线恢复后的新基线（`run_id >= 1495`）

这段是 `2026-05-15 13:20-14:05 CST` 专线恢复之后的第一批真实 live 样本。

这次必须先把它和前面那一段彻底拆开：

- `1492-1494`
  - 还是 `-2015`
  - 属于专线 / 白名单没有恢复前的故障样本
- `1495+`
  - 属于 dedicated Binance 专线已经恢复后的新样本

当前恢复后的现场状态：

- `7907` 专线从 WSL 真实验证到的固定出口是：
  - `47.129.194.36`
- `preflight-live` 全绿
- `runtime-status`
  - `halted=false`
  - `ai_failure_streak=0`

### 当前这批 run 的结构

截至 `2026-05-15 14:27 CST`，`1495+` 已经跑出的 live run 是：

- `1495`
  - `XRP/USDT:USDT`
  - `action=sell`
  - `order_status=closed`
- `1496`
  - `XRP/USDT:USDT`
  - `action=hold`
  - `order_status=noop`
- `1497`
  - `XRP/USDT:USDT`
  - `action=hold`
  - `order_status=noop`
- `1498`
  - `XRP/USDT:USDT`
  - `action=hold`
  - `order_status=noop`
- `1499`
  - `XRP/USDT:USDT`
  - `action=hold`
  - `order_status=noop`

这组形态不是：

- “恢复后马上乱开很多单”
- 也不是“恢复后继续完全不动”

而是：

- `1495` 先开出一笔新的 `XRP short`
- 后面 `1496-1499` 连续进入 `position_management`

### 1495 这笔到底怎么样

`1495` 当轮细节：

- `SOL` / `XRP` 都是：
  - `candidate_ok`
  - `higher_timeframe_bias=short`
- AI 最终选的是：
  - `XRP sell`
  - `confidence=0.57`
  - `size_pct=0.10`
  - `take_profit_pct=0.022`
  - `stop_loss_pct=0.008`
- risk 结果：
  - `final_action=sell`
  - `reasons=["ok"]`

这说明恢复后的第一笔 actionable 样本，不是：

- 还卡在 `expected_edge_below_minimum`
- 也不是 `open_signal_return_24bars_too_weak`
- 更不是 `system_halted`

它是一个**干净放行**的 short entry。

### 1-bar 早读口径

如果只看 `1-bar` 的早读口径：

- `1495`
  - `net_edge_pct=-0.06533278666118959`
  - `outcome=flat`
- `1496`
  - `management_hold`
  - `outcome=good_hold`

这一步的含义是：

- 第一根 bar 的毛收益不够厚，还没盖过估算成本
- 但也不是明显坏单

### 3-bar 正式口径（截至 2026-05-15 14:27 CST）

按标准 `3-bar` 复核，当前已经有正式结果的是：

- `1495`
  - `decision_lifecycle=fresh_entry`
  - `net_edge_pct=0.0781686483531586`
  - `future_R=0.2832197404099949`
  - `outcome=flat`
- `1496`
  - `decision_lifecycle=management_hold`
  - `outcome=good_hold`
- `1497`
  - `decision_lifecycle=management_hold`
  - `outcome=good_hold`

当前还没走完 `3-bar` 的是：

- `1498`
- `1499`

这里有个很容易误读的点要记住：

- `1495` 的 `net_edge_pct` 已经是正的
- 但还没有高到跨过这套 review 的 `0.3%` 阈值
- 所以正式 `outcome` 仍记成 `flat`

更准确地说：

- 它不是坏单
- 也不是高质量大胜样本
- 当前应该记成：
  - **可接受、轻微正 edge、但边际不厚**

### 当前持仓面

截至 `2026-05-15 14:27 CST` 的现场持仓快照：

- 当前仍有一笔：
  - `XRP/USDT:USDT short`
  - `quantity=33.4`
  - `average_entry_price=1.464`
- 当前浮动：
  - `unrealized_pnl_quote=-0.03881547`

这说明：

- `1495` 不是开完马上反手或强平
- 这段恢复后的动作，目前仍然处在正常管理阶段

### 对这段恢复后样本的当前判断

这段 `1495+` 当前可以先下的判断是：

1. 运行恢复是实质性的，不是“看起来恢复”。
2. 恢复后第一笔 actionable 样本是一个 clean short，不是坏单。
3. 后面的 management hold 目前口径正常，没有乱 flip、乱补仓、乱平仓。
4. 但当前 actionable 样本仍然只有 `1` 笔，不能因为恢复后第一笔没坏，就直接写成“这轮 short 已经证明有效”。

所以这段最准确的阶段结论是：

- `1495+` 目前表现 **合格**
- 但证据上限仍然只是：
  - `行为已恢复`
  - `第一笔 short 可接受`
  - `management 目前正常`
- 还不能写成：
  - `恢复后策略已经明显变强`

### 下次继续看什么

`1495+` 这段后面继续复查时，优先看：

1. `1495` 这笔 `XRP short` 最后是：
   - 被 `TP`
   - 被 `SL`
   - 还是被 management 主动平掉
2. `1498 / 1499` 补完 `3-bar` 之后还是不是 `good_hold`
3. 恢复后第二笔新的 actionable 样本，是否还能保持：
   - 不被旧 risk gate 压回
   - 也不直接变成明显坏单
4. `1495+` 后续的 `fresh_entry` / `management_hold` 是否继续分工清晰，而不是重新回到：
   - `candidate_ok -> AI directional action -> risk hold`

## 下次如果直接让我查

下次可以直接用这种说法，不用再重新解释背景：

- `按 docs/fresh-entry-effect-check-2026-05-14.md 检查 fresh entry 改动效果`
- `按 run_id >= 1495 看专线恢复后的新基线`
- `先看运行是否正常，再按文档复查 actionable / fresh_entry / blocked_entry`
- `重点看新 reason 有没有开始命中，以及是不是还在 candidate -> AI -> risk -> hold`
- `重点看 blocked_entry.buy 现在主要被什么 reason 压回 hold`

## 2026-05-15 15:50 CST 再续查

这轮是在 `1495+` 那段专线恢复后样本继续长出来之后，再按同一口径做的现场复查。

先说当前结论：

- 运行面仍然正常
- `1495+` 没有出现明显回退
- 但当前仍然不能下“恢复后策略已经明显变强”的结论
- 现在最准确的说法仍然是：
  - `1495+` 行为恢复且样本合格
  - 当前主要在守一笔 `XRP short`
  - 证据仍然太少，不适合继续大动 management

### 当前运行面

检查时间：

- `2026-05-15 15:50 CST`

当前确认结果：

- `qount-runner.timer`
  - `active (waiting)`
- `runtime-status`
  - `halted=false`
  - `ai_failure_streak=0`
  - `day_start_equity=163.34624753`
- `preflight-live`
  - 仍然全绿
- `live-guard-status`
  - `live_enable=true`
  - `persistent=true`
- 当前持仓
  - `XRP/USDT:USDT short`
  - `quantity=33.4`
  - `average_entry_price=1.464`
  - `mark_price≈1.4684`
  - `unrealized_pnl_quote≈-0.1478`

### `1495+` 当前真实结构

截至这轮复查，`1495+` 的 `3-bar review` 已经变成：

- `reviewed=20`
- `fresh_entry=1`
- `management_hold=19`
- `good_hold=17`
- `missed_move=2`
- `flat=1`
- `actionable_avg_net_edge_pct=0.0781686483531586`

当前最新 live run 继续长到了：

- `1495`
  - `sell`
  - `fresh_entry`
- `1496-1514`
  - 基本都是 `XRP/USDT:USDT`
  - `action=hold`
  - `order_status=noop`
- `1515-1516`
  - 还没补完 `3-bar`

这段形态说明：

- 恢复后的逻辑不是“乱开单”
- 也不是“恢复后又彻底不动”
- 更像：
  - 先开出一笔 clean `XRP short`
  - 后面连续进入 `position_management`

### 这轮为什么先不继续硬改 management

`1495+` 当前真正需要警惕的是：

- `1498`
  - `management_hold`
  - `outcome=missed_move`
- `1502`
  - `management_hold`
  - `outcome=missed_move`

但这两笔还不够支持“立刻继续收紧 management”，原因是：

- 它们两边相邻的大量样本仍然是 `good_hold`
- 同一段 `1500-1514` 里，strategy 仍然多次正确选择了“继续 hold，而不是乱平仓”
- 现在如果继续拍脑袋收 management，更容易误伤当前这条已经恢复的 `XRP short -> management_hold` 路径

所以这轮更稳妥的做法不是继续热改逻辑，而是先把已经验证有效的 live 样本锁成回归测试，再继续观察新样本。

### 当前“历史数据回看 / 回测”能力边界

这次顺手把这个口径也记清楚，避免下次再把几种东西混成一个“backtest”。

当前仓库现成有三种历史回放 / 回测口径：

- `signal-review`
  - 基于**历史真实 run / snapshot / validated decision / risk verdict**
  - 再补抓后续 K 线
  - 评估 `good / bad / flat / missed_move / net_edge_pct`
  - 这更接近：
    - **历史决策复盘**
    - **决策级 post-cost review**
  - 不是“给一整段历史 K 线，从零重新跑完整策略”的 full backtest
- `paper-replay`
  - 只回放**已经存在的 paper 订单历史**
  - 输出 paper equity 曲线
  - 这更接近：
    - **订单执行结果回放**
  - 不是重新生成历史信号
- `backtest`
  - 基于**历史 OHLCV**
  - 从头重跑当前 `candidate -> AI -> validate -> risk -> execute`
  - 使用隔离 `paper` 账本，不污染主 `state/qount.db`
  - 输出：
    - `db`
    - `summary.json`
    - `review.json`
  - 这才是这里说的：
    - **真正历史回测**

也就是说：

- 现在仓库已经能做：
  - 历史真实决策复盘
  - 历史 paper 订单权益回放
  - 历史 OHLCV 全链路 paper 回测

这次已经现场跑通的命令是：

```bash
ssh home "wsl.exe bash -lc 'cd /home/alyaloale/Code/qount && set -a && source .env && set +a && PYTHONPATH=src ./.venv/bin/python -m qount.main backtest --start 2026-05-14T22:00:00+08:00 --end 2026-05-14T23:30:00+08:00 --max-bars 8 --review-horizon-bars 3 --review-threshold-pct 0.003'"
```

这次 smoke-run 的结果是：

- `runs_completed=8`
- `paper_filled=1`
- `paper_closed=0`
- `final_equity_quote=200.57048367093842`
- `total_return_pct=0.28524183546920767`
- `review.aggregate.actionable.avg_net_edge_pct=0.10047678103898071`

注意这轮只是：

- 小窗口
- `8` 根 bar
- 用来验证命令、数据链路、AI、review 输出都已经走通

不是用来直接下“策略已经稳定盈利”的大结论。

### 当前历史口径下，是否已经能看出“盈利”

先分成两层看，不要混：

#### 1. 决策复盘口径

这轮现场 `signal-review --limit 380 --horizon-bars 3 --threshold-pct 0.003` 摘要：

- `run_id >= 1175`
  - `actionable_count=20`
  - `actionable_net_edge_sum_pct=0.421725606633693`
  - `fresh_entry_avg_net_edge_pct=0.05748516792238839`
- `run_id >= 1286`
  - `actionable_count=15`
  - `actionable_net_edge_sum_pct=1.5054350136410064`
  - `fresh_entry_avg_net_edge_pct=0.15442597600415314`
- `run_id >= 1495`
  - `actionable_count=1`
  - `actionable_net_edge_sum_pct=0.0781686483531586`

这层口径说明：

- post-fix 尤其 `1286+` 这段，历史决策复盘已经是**正 edge**
- 但 `1495+` 样本仍然太少，不能只靠 1 笔就下强结论

#### 2. 真实 live 成交口径

这轮从交易所真实成交回放出来的当前账户概况是：

- `realized_pnl_quote=-0.39490188`
- `unrealized_pnl_quote≈-0.14777362`
- `equity_quote≈162.83620936`

这层口径说明：

- 当前真实 live 账户**还不能直接写成总账已经盈利**
- 但 recent review 窗口已经出现正向的决策质量改善
- 所以更准确的说法是：
  - **策略最近几窗的决策质量在变好**
  - **但账户总实盘累计还没有被这点新改善完全拉回正值**

### 如果下次要继续看“历史上到底赚不赚钱”

下次优先分三种问法：

1. `看历史真实决策质量`
   - 跑 `signal-review`
2. `看历史 paper 订单曲线`
   - 跑 `paper-replay`
3. `看真正历史回测`
   - 跑 `backtest`
   - 优先固定同一个时间窗做前后版本对比

## 2026-05-15 18:39 CST 策略已同步，实盘链路已恢复，开始观察表现

这一段是给下次继续看效果时的直接入口。

### 当前已确认状态

现场确认时间：

- `2026-05-15 18:39 CST`

当前确认结果：

- 新策略代码已经同步到 WSL
  - 包括：
    - `high_rsi_long_chase`
    - `higher_timeframe_short_reclaim`
    - `management_profitable_long_momentum_cooldown_close`
- WSL 已重新：
  - `pip install -e .`
- 远端单测：
  - `62` 条全部通过
- `qount-runner.timer`
  - `active (waiting)`
- `preflight-live`
  - 已重新全绿
- `run-once`
  - `run_id=1553`
  - `status=completed`
  - `symbol=SOL/USDT:USDT`
  - `action=hold`
  - `order_status=noop`

### 这次 `run-once` 为什么没开仓

这次不是链路问题，而是当前策略本身选择了 `filtered_hold`。

当轮候选原因是：

- `SOL`
  - `short_setup_latest_bar_rebound`
- `XRP`
  - `short_setup_countertrend_drift`
  - `short_setup_latest_bar_rebound`

也就是说：

- 现在环境已经恢复
- 但当前这根 bar 不满足新策略要的 clean short 形态

这正是我们这轮要观察的重点：

- 系统恢复后不是“见到一点下跌就强开”
- 而是在 real live 里继续验证：
  - 过滤掉的 setup 里，哪些后来真的是该挡
  - 哪些会重新堆成 `missed_move`

### 下次继续观察时，先看这几层

#### 1. 先看运行面

```bash
ssh home "wsl.exe bash -lc 'cd /home/alyaloale/Code/qount && date \"+%F %T %Z\"; systemctl --user status qount-runner.timer --no-pager --full | sed -n \"1,20p\"'"
ssh home "wsl.exe bash -lc 'cd /home/alyaloale/Code/qount && set -a && source .env && set +a && ./.venv/bin/python -m qount.main preflight-live | python3 -m json.tool'"
ssh home "wsl.exe bash -lc 'cd /home/alyaloale/Code/qount && set -a && source .env && set +a && ./.venv/bin/python -m qount.main runtime-status | python3 -m json.tool'"
```

只要这里还是：

- `preflight-live` 全绿
- `halted=false`
- timer 在正常触发

才继续看策略效果，不要把环境故障和策略效果混在一起。

#### 2. 再看最近 live runs

```bash
cat <<'PY' | ssh home 'wsl.exe bash -lc "cd /home/alyaloale/Code/qount && python3 -"'
import sqlite3, json
con = sqlite3.connect('state/qount.db')
con.row_factory = sqlite3.Row
rows = con.execute("""
select id, started_at, finished_at, status, summary_json
from runs
where mode='live'
order by id desc
limit 12
""").fetchall()
for r in rows:
    item = dict(r)
    item["summary_json"] = json.loads(item["summary_json"] or "{}")
    print(json.dumps(item, ensure_ascii=False))
PY
```

重点先看：

- 有没有新的 `completed` run
- 新的 actionable 是 `buy / sell / close` 还是继续大多 `hold`
- `candidate_filter` 里最近被挡的主因是不是开始变化

#### 3. 再按这轮策略的关注点复查

当前最值得继续盯的，不再是泛泛地问“能不能盈利”，而是：

1. `fresh_entry`
   - 有没有继续保持正边际
2. `management_hold`
   - `missed_move` 会不会继续下降
3. `SOL long`
   - management 的高位冷却 close 是否继续有用
4. `XRP`
   - 还能不能维持当前相对更好的正边际
5. `blocked_entry / blocked_sell`
   - 会不会重新开始堆高

对应命令继续用：

```bash
ssh home "wsl.exe bash -lc 'cd /home/alyaloale/Code/qount && set -a && source .env && set +a && ./.venv/bin/python -m qount.main signal-review --limit 260 --horizon-bars 3 --threshold-pct 0.003'"
```

### 当前对下次判断最有价值的基线

这轮策略同步完成后，可以先记这几个比较基线：

- `run_id=1553`
  - 第一条确认“新策略 + 实盘链路恢复后”的真实 run
  - 当前结果：
    - `SOL`
    - `filtered_hold`
    - `short_setup_latest_bar_rebound`
- `24 bar backtest`
  - `actionable.avg_net_edge_pct=+0.0698%`
  - `fresh_entry.avg_net_edge_pct=+0.2325%`
  - `management_hold.missed_move=3`
- `48 bar backtest`
  - `actionable.avg_net_edge_pct=+0.0698%`
  - `fresh_entry.avg_net_edge_pct=+0.2325%`
  - `management_hold.missed_move=3`

如果下次继续观察时：

- live 里开始出现新的 actionable
- 并且 review 没把这些基线打坏

才说明这轮策略优化不只是回测里更好，而是实盘里也开始兑现。

## 2026-05-15 19:30 CST 再续查：short precheck 已做窄放松

这一段对应的是：

- 先确认现在运行状态正常
- 再继续拆为什么最近几轮一直被 `countertrend/rebound` 挡掉
- 最后把修复同步到 WSL 并看真实 live run

### 这次确认出来的根因

最近这串 `hold/noop` 里，确实有一部分不是 AI 或 risk 在保守，而是 pre-AI 的 `candidate_filter` 先把 short 候选挡掉了。

现场确认到的旧逻辑是：

- `1h trend_bias=short`
- 但如果本地 `5m return_24bars > 0` 且 `sma_slow_ratio >= 0`
  - 直接记 `short_setup_countertrend_drift`
- 如果本地 `5m return_1bar > 0` 且 `sma_fast_ratio >= 0`
  - 直接记 `short_setup_latest_bar_rebound`
- 且旧阈值是：
  - `SHORT_REBOUND_1BAR_PCT = 0.0`
  - `SHORT_COUNTERTREND_24BAR_PCT = 0.0`

这意味着：

- 只要 `1h` 仍然偏空，但 `5m` 有一点点翻红回抽
- short 候选就可能在 AI 前直接被一票否决

### 本次已经落地的窄修

本次没有去重写 prompt / risk / management 主链路，只做了最小修复：

- `src/qount/candidate_filter.py`
  - `SHORT_REBOUND_1BAR_PCT = 0.0015`
  - `SHORT_COUNTERTREND_24BAR_PCT = 0.0025`

目标非常明确：

- 继续拦住**明显**反抽、明显逆势的 short
- 但不再把 `1h short` 结构里的**轻微** `5m pullback` 也零容忍地挡死

本地回归已经补上并通过：

- 保留“明显 countertrend short 仍被挡掉”的测试
- 新增“强 `1h short` 背景下，轻微 `5m pullback` 可以继续进入 AI/risk”的测试
- `PYTHONPATH=src python3 -m unittest tests.test_strategy_optimization`
  - `63` 条全部通过

### WSL 现场验证结果

生产 WSL 现场已经确认：

- 新阈值真实导入值为：
  - `SHORT_REBOUND_1BAR_PCT = 0.0015`
  - `SHORT_COUNTERTREND_24BAR_PCT = 0.0025`
- `qount-runner.timer`
  - 仍然 `active (waiting)`
- 修复后的新 live run 已经出现：
  - `run_id=1563`
  - `run_id=1564`
  - 都是 `completed`

这两轮最关键的区别是：

1. `run_id=1563`
   - `SOL`
     - `low_volatility_soft_penalty`
     - `low_volume`
     - `short_setup_countertrend_drift`
   - `XRP`
     - `low_volatility_soft_penalty`
     - `low_volume`
     - `short_setup_countertrend_drift`
   - 说明明显逆势 short 仍然会被挡

2. `run_id=1564`
   - `SOL`
     - 只剩：
       - `low_volatility_soft_penalty`
       - `low_volume`
     - **已经不再命中**
       - `short_setup_countertrend_drift`
       - `short_setup_latest_bar_rebound`
   - `XRP`
     - 仍有：
       - `short_setup_countertrend_drift`
   - 说明这次修复已经把“轻微回抽也一票否决”的路径拿掉了一部分，但没有把明显反抽全部放开

### 当前口径要怎么更新

从这次开始，关于 recent live `filtered_hold` 的判断要改成：

- 不能再默认说：
  - “最近 short 一直被 `countertrend/rebound` 挡掉，所以先继续怪 short precheck”
- 更准确的说法应该是：
  - short precheck 现在仍然保护明显反抽 short
  - 但 `1h short` 背景里的轻微 `5m pullback` 已经不再零容忍
  - 如果后面继续 `filtered_hold`，优先要看：
    - `low_volume`
    - `low_volatility`
    - AI 的 post-cost directional edge
    - risk 的 `expected_edge_below_minimum`

### 下次继续看时先盯什么

这次窄修之后，下一轮继续观察时，优先看这三件事：

1. 最近几轮 `candidate_filter` 里：
   - `short_setup_countertrend_drift`
   - `short_setup_latest_bar_rebound`
   是否继续下降
2. 有没有更多 symbol 能从 `filtered_hold` 进入：
   - `selected`
   - AI directional action
3. 如果已经进入 AI / risk，但最后仍然 `hold`
   - 那主问题就已经从 short precheck 转移到了：
     - `low_volume / low_volatility`
     - 或 `expected_edge_below_minimum`

## 2026-05-16 14:45 CST 阶段 0 上线验证补记

这一段专门记录这次：

- `flat-bias short flush` blocker
- `risk_debug`

同步到生产 WSL 之后的真实验证结果，避免下次只记得“代码改了”，忘了当场运行面发生了什么。

### 这次远端验证先发生了什么

这次部署后，远端先完成了：

- `./.venv/bin/python -m pip install -e .`
- `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_strategy_optimization`
  - `71` 条全部通过

也就是说：

- 代码本身已经在生产节点真实安装
- 基础策略测试没有回归

### 第一次 live 验证为什么没直接通过

第一次手动 `run-once` 打出的是真实失败样本：

- `run_id=1783`
- `status=market_data_failed`
- `error=binance GET https://fapi.binance.com/fapi/v1/exchangeInfo`

这一条要明确：

- 不是这轮策略代码把 live 路径跑坏了
- 而是当场 dedicated Binance 专线任务状态漂移

当时现场同时出现了这些现象：

- Windows `QountBinanceProxy` 旧候选名
  - `🇯🇵日本高速03|BGP|流媒体`
  - 已经不在当前 `clash-verge.yaml` 里
- 当前真实叶子已经变成：
  - `🇯🇵日本高速02|BGP|CUCM`
- 同一时刻会出现：
  - `status -Probe` 看起来不健康
  - 但 WSL `7907 -> Binance time` 又可能先恢复

从这次开始，这个口径要记清：

- 当 Windows 任务状态、`status -Probe`、WSL `curl --proxy` 三者打架时
- 生产真相仍然以：
  - `WSL 7907`
  - `preflight-live`
  - `真实 run 记录`
  为准

### 修复专线后，真实验证结果

专线按当前真实叶子重新拉起并复证后：

- `preflight-live`
  - 重新全绿
- 第二次手动 `run-once`
  - `run_id=1784`
  - `status=completed`
  - `symbol=SOL/USDT:USDT`
  - `action=hold`
  - `order_status=noop`
- `qount-runner.timer`
  - 已恢复
  - `ActiveState=active`
  - `SubState=waiting`

这次最重要的记录结论是：

1. `阶段 0` 改动已经真实上线到 WSL。
2. 远端测试和 live preflight 都已通过。
3. 第一次失败来自专线漂移，不是策略代码回归。
4. 修复专线后，真实 live `run-once` 已重新回到 `completed`。

### 当前计划进度口径也要同步更新

从这次验证之后，下次如果你只是想先知道“现在走到哪一步了”，可以直接按下面口径理解：

- `阶段 0`
  - 已上线、已远端验证通过
- `阶段 1`
  - 相关 entry/risk 规则已经在代码里，不是待开发
- `阶段 2`
  - 才是当前真实进行中的阶段
  - 重点变成继续看 live 样本增长和新 reason 命中
- `阶段 3`
  - 还没开始
  - 现在不要先动全局 `expected_edge` threshold

### 下次继续查这轮效果时，先别忘这三件事

1. 先确认当前 dedicated Binance 叶子名字，不要默认再用旧的：
   - `🇯🇵日本高速03|BGP|流媒体`
2. 先查 `WSL -> 192.168.128.1:7907` 和 `preflight-live`
   - 不要只看 Windows `status -Probe`
3. 再看这轮新逻辑有没有开始在真实样本里打出：
   - `fresh_entry_flat_bias_short_flush`
   - `risk_debug.expected_edge_components`

## 2026-05-16 20:38 CST 组合层风险与 cycle 口径升级补记

这一段对应的是：

- 组合层同向风险控制已经落地
- 弱 `alt short` fresh-entry 已经开始额外收紧
- `signal-review` 的复盘口径已经升级，不再只看单笔 trade review

### 这轮上线了什么

当前最新已经落地到代码里的主线是：

1. 组合层同向风险控制
   - `QOUNT_MAX_NET_DIRECTIONAL_EXPOSURE_PCT`
   - `QOUNT_MAX_CORRELATED_DIRECTIONAL_EXPOSURE_PCT`
   - `QOUNT_THIRD_SAME_DIRECTION_EDGE_BUFFER_PCT`
2. 弱 `alt short` fresh-entry 收紧
   - `QOUNT_ALT_SHORT_EDGE_PENALTY_PCT`
   - 当前只额外收紧 `SOL / XRP`
   - 只针对弱的：
     - `plain_open`
     - `flat_bias_short`
3. review 口径升级
   - `aggregate.by_hold_path`
   - `aggregate.cycle_summary`

这意味着从这轮开始，下次再看策略效果时，不能只问：

- “这笔 trade 好不好”

还要一起问：

- “这轮 cycle 一共处理了几个 symbol”
- “当时总净空 / 净多暴露是多少”
- “哪几个 symbol 真在贡献，哪几个只是把同方向仓位继续堆高”

### 这次远端 WSL 验证结果

现场时间：

- `2026-05-16 20:38 CST`

这次已经确认：

- 新代码已同步到生产 WSL
- 远端重新：
  - `./.venv/bin/python -m pip install -e .`
- 远端单测：
  - `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_strategy_optimization`
  - `77` 条全部通过
- `preflight-live`
  - 仍然全绿
- `qount-runner.timer`
  - `active (waiting)`

这轮没有额外强行手动 `run-once`。

原因要单独记住：

- 这已经是实盘环境
- 这次要验证的是：
  - 新口径有没有真实上线
  - 运行面有没有被打坏
- 不是为了文档更新，额外制造一笔新的 live 决策

### 新的 `signal-review` 切片已经在远端真实输出里

这次在远端 WSL 真实跑：

```bash
ssh home "wsl.exe bash -lc 'cd /home/alyaloale/Code/qount && set -a && source .env && set +a && ./.venv/bin/python -m qount.main signal-review --limit 80 --horizon-bars 3 --threshold-pct 0.003'"
```

当前输出已经包含：

- `aggregate.by_hold_path`
- `aggregate.cycle_summary`

这不是本地假数据或只在 unittest 里存在，而是已经能直接从生产 WSL 的真实 review 输出读到。

### 这轮现场摘要（`signal-review --limit 80 --horizon-bars 3 --threshold-pct 0.003`）

当前最新摘要是：

- `reviewed=73`
- `actionable.reviewed=3`
- `actionable.avg_net_edge_pct=-0.09411931297106671`
- `blocked_sell.by_reason`
  - `expected_edge_below_minimum=3`
  - `open_signal_return_24bars_too_weak=1`
  - `open_signal_sma_fast_conflict=1`

新的 `by_hold_path` 切片当前是：

- `candidate_ok_ai_hold`
  - `reviewed=3`
  - `good_hold=3`
- `candidate_ok_risk_hold`
  - `reviewed=2`
  - `good_hold=2`
- `candidate_penalty_ai_hold`
  - `reviewed=7`
  - `good_hold=7`
- `candidate_penalty_risk_hold`
  - `reviewed=2`
  - `good_hold=2`
- `management_ai_hold`
  - `reviewed=56`
  - `good_hold=56`

新的 `cycle_summary` 当前是：

- `cycles_reviewed=28`
- `avg_processed_symbols=2.607142857142857`
- `max_processed_symbols=4`
- `avg_start_short_notional_quote=208.1785642242857`
- `avg_end_short_notional_quote=197.6486596632143`

### 这组数字当前该怎么读

这轮最重要的不是某一笔单子，而是这三个结论：

1. 运行面现在是健康的
   - `preflight-live` 仍然全绿
   - timer 仍然正常触发
   - 所以当前主问题不是“系统没在跑”

2. `candidate_ok` 和 `candidate_penalty` 已经能拆开看
   - 当前确实存在：
     - `candidate_ok_ai_hold`
     - `candidate_ok_risk_hold`
   - 所以下次如果再说“为什么看起来 candidate 已经可以了但还是没出手”，现在已经能直接分清：
     - 是 AI 自己最后选 `hold`
     - 还是 risk 最后挡掉

3. 多币同轮已经不只是功能问题，而是组合暴露问题
   - `avg_processed_symbols > 2.6`
   - `max_processed_symbols = 4`
   - 当前平均 cycle 起点净空名义仓位已经在 `208` 附近
   - 这已经足够说明：
     - 现在最紧急的新风险不是“能不能多币”
     - 而是“会不会把一串高度相关的同向仓继续堆上去”

### 从这轮开始，下次优先看什么

下次继续查时，先看下面这几层，不要再只盯 `fresh_entry` 总数：

1. 先看 `blocked_sell.by_reason`
   - 如果还主要是：
     - `expected_edge_below_minimum`
   - 那就说明当前问题更偏：
     - 薄边际 short
     - 或第三笔同向仓额外 `edge` 要求

2. 再看 `aggregate.by_hold_path`
   - 如果主要增长的是：
     - `candidate_ok_ai_hold`
   - 说明问题在：
     - AI 最终选择
   - 如果主要增长的是：
     - `candidate_ok_risk_hold`
   - 说明问题在：
     - risk gate
     - 包括新的组合层 guard

3. 最后看 `aggregate.cycle_summary`
   - `avg_processed_symbols`
   - `max_processed_symbols`
   - `avg_start_short_notional_quote`
   - `avg_end_short_notional_quote`
   - 这四个字段现在已经是判断“多币同轮是不是在放大同向风险”的第一组入口

### 下次直接用的命令

先跑总 review：

```bash
ssh home "wsl.exe bash -lc 'cd /home/alyaloale/Code/qount && set -a && source .env && set +a && ./.venv/bin/python -m qount.main signal-review --limit 80 --horizon-bars 3 --threshold-pct 0.003'" > /tmp/qount-signal-review-next.json
```

如果你想直接抽这轮新增的两组切片，用：

```bash
python3 - <<'PY'
import json
obj = json.load(open('/tmp/qount-signal-review-next.json'))
agg = obj["aggregate"]
print(json.dumps({
    "blocked_sell_by_reason": agg["blocked_sell"].get("by_reason"),
    "by_hold_path": agg.get("by_hold_path"),
    "cycle_summary": agg.get("cycle_summary"),
}, ensure_ascii=False, indent=2))
PY
```

### 当前口径一句话总结

到 `2026-05-16 20:38 CST` 这一轮为止，最准确的说法是：

- 当前主问题仍然是新开仓质量
- 但多币同轮上线后，最紧急的新风险已经变成组合层同向堆仓
- 所以下一轮复查必须同时看：
  - `fresh_entry`
  - `by_hold_path`
  - `cycle_summary`
- 不能再只看单笔 trade review

## 2026-05-17 00:25 CST 新窗口续查

这段是 `2026-05-16 20:38 CST` 那轮组合层收紧上线之后的第一轮续查。

这次不再把“最近策略又亏了”的判断混回：

- `1833`
- `1495+` 早期恢复样本
- 或更早的 `1175+` 全窗口

当前要拆成两个窗口看：

1. `run_id >= 1974`
   - 用来看这轮逻辑上线后，最近一段真实 live 行为有没有继续出新的坏单
2. `run_id >= 1990`
   - 用来盯“下一笔 fresh-entry 什么时候出现”
   - 在新的 fresh-entry 出来之前，不要从一堆 `hold/noop` 里硬推“又亏了”或“已经彻底修好”

### 当前结论先说

截至 `2026-05-17 00:25 CST`：

- 最近窗口里已经**没有新的 actionable bad 样本**
- 当前新增样本主体是：
  - `blocked_entry -> good_hold`
  - `idle_hold -> good_hold`
  - `management_hold -> good_hold`
- 旧坏单 `run_id=1833` 用**当前代码重放**后，已经会被压成 `hold`
  - 原因是：
    - `portfolio_correlated_directional_exposure_limit:crypto_beta:short:0.310739>0.300000`
- 所以这轮更准确的说法应该是：
  - 这次窄修已经命中了最近最关键的亏损模式
  - 当前先继续观察下一笔新的 fresh-entry
  - 不要在 fresh-entry 新样本还没出来时，又把老坏单混回“最近持续亏”里

### `run_id >= 1974` 当前摘要

这段窗口当前数字是：

- `reviewed=16`
- `good_hold=14`
- `flat=1`
- `missed_move=1`
- `bad=0`

按 lifecycle 拆开：

- `blocked_entry=2`
- `idle_hold=5`
- `full_close=1`
- `management_hold=8`

这段的含义很直接：

- 最近这一小段里，系统主要是在合理地不出手或继续管理已有仓位
- 不是继续冒出新的坏 fresh-entry

这段里最需要记住的两条：

- `run_id=1990`
  - `ETH blocked_entry -> good_hold`
  - `risk_reasons=["expected_edge_below_minimum:0.001156<0.001500"]`
- `run_id=1986`
  - `ETH blocked_entry -> good_hold`
  - `risk_reasons=["expected_edge_below_minimum:0.001381<0.001500"]`

也就是说，最近这几条被 risk 压回去的 entry，不是主要问题，当前看起来反而是挡对了。

### `run_id >= 1990` 当前摘要

这个窗口是从现在开始默认的“下一笔 fresh-entry 观察窗”。

截至这次续查：

- `reviewed=2`
- `outcomes={"good_hold": 2}`
- `by_lifecycle={"blocked_entry": 2}`
- `fresh_entries=[]`

这代表：

- 从 `1990` 往后，到当前为止还**没有新的 fresh-entry reviewed 样本**
- 所以下次如果你只是想问“最新这轮有没有新的可复盘开仓”
  - 第一反应不是重跑整个历史结论
  - 而是先回答：
    - `1990+` 目前还没有 fresh-entry

### `1833` 旧坏单在当前代码下的重放结果

这次专门把当前大窗口里剩下的唯一 `bad` 样本重放了一次：

- 原始样本：
  - `run_id=1833`
  - `SOL/USDT:USDT sell`
  - `candidate_filter_primary_reason=candidate_ok`
  - 老 verdict：`approved`
  - review 结果：`bad`
- 用当前代码重放：
  - `final_action=hold`
  - `approved=false`
  - `reasons=["portfolio_correlated_directional_exposure_limit:crypto_beta:short:0.310739>0.300000"]`

这条证据很重要，因为它说明：

- 现在不能再把 `1833` 当成“当前逻辑还会继续放出来的坏单”
- 它已经被这轮组合层限制吃掉了
- 所以如果下一轮又出现新的坏单，优先要看是不是**另一种模式**
  - 而不是反复回到 `1833` 这类第三笔同向 short

### 下次默认复盘口径

下次来直接按下面顺序走，不要重新混窗口：

1. 先看 `run_id >= 1990`
   - 有没有新的 `fresh_entry`
   - 如果没有：
     - 直接记为“还在等下一笔 fresh-entry 样本”
2. 如果 `1990+` 里出现新的 `fresh_entry`
   - 再单独复盘这些新的 `run_id`
   - 不要把 `1833`、`1495+`、`1175+` 老结论一起搅进来
3. 如果只是 `blocked_entry` / `idle_hold` / `management_hold`
   - 先看 outcome 是不是仍然以 `good_hold` 为主
   - 只要还是这样，就不要把“没出手”直接写成“最近一直亏”

### 下次直接用的命令

如果你下次只想先回答一句“`1990+` 有没有新的 fresh-entry”，直接跑：

```bash
cat <<'PY' | ssh home 'wsl.exe bash -lc "cd /home/alyaloale/Code/qount && set -a && source .env && set +a && PYTHONPATH=src ./.venv/bin/python -"'
import json
from collections import Counter
from qount.orchestrator import Orchestrator
from qount.settings import Settings

orch = Orchestrator(Settings.from_env())
report = orch.signal_review(limit=200, horizon_bars=3, threshold_pct=0.003)
recent = [
    item for item in report["reviews"]
    if item.get("status") == "reviewed" and int(item["run_id"]) >= 1990
]

print(json.dumps({
    "reviewed": len(recent),
    "outcomes": dict(Counter(item["outcome"] for item in recent)),
    "by_lifecycle": dict(Counter(item["decision_lifecycle"] for item in recent)),
    "fresh_entries": [
        {
            "run_id": item["run_id"],
            "symbol": item["symbol"],
            "review_action": item["review_action"],
            "outcome": item["outcome"],
            "candidate_filter_primary_reason": item["candidate_filter_primary_reason"],
            "risk_reasons": item["risk_reasons"],
            "net_edge_pct": item["net_edge_pct"],
        }
        for item in recent
        if item["decision_lifecycle"] == "fresh_entry"
    ],
}, ensure_ascii=False, indent=2))
PY
```

如果你要看“这轮上线后最近一小段是不是还在继续出坏单”，再补一条：

```bash
cat <<'PY' | ssh home 'wsl.exe bash -lc "cd /home/alyaloale/Code/qount && set -a && source .env && set +a && PYTHONPATH=src ./.venv/bin/python -"'
import json
from collections import Counter
from qount.orchestrator import Orchestrator
from qount.settings import Settings

orch = Orchestrator(Settings.from_env())
report = orch.signal_review(limit=200, horizon_bars=3, threshold_pct=0.003)
recent = [
    item for item in report["reviews"]
    if item.get("status") == "reviewed" and int(item["run_id"]) >= 1974
]

print(json.dumps({
    "reviewed": len(recent),
    "outcomes": dict(Counter(item["outcome"] for item in recent)),
    "by_lifecycle": dict(Counter(item["decision_lifecycle"] for item in recent)),
}, ensure_ascii=False, indent=2))
PY
```
