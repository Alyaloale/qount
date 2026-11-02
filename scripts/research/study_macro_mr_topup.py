"""Minimum native experiment: can an unchanged MR budget fund a valid top-up?"""
import argparse
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path

from qount.research.binance_etf_leverage import replay
from qount.research.binance_macro_opportunities import cost_case
from qount.research.macro_topup import topup_quote
from qount.strategies.macro_1atr import RISK_FRACTION, entry_candidates, is_decision
from qount.strategies.macro_funding import feature_at, funding_reserve
from continue_macro_fixed_candidates import append_inputs
from study_macro_admission_and_simplicity import verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new output; keep old evidence")
    (book, features, gates, caps), sources, _ = append_inputs("2026-10-26", False)
    previous = json.loads(Path("state/research_runs/macro_mr_holding_20261026/comparison.json").read_text())
    assert previous["parameters"]["risk_fraction"] == RISK_FRACTION
    inputs = {s: {kind: {b.t: b for b in d[kind]} for kind in ("trade", "mark")} for s, d in book.items()}
    controls, observations, quotes = [], [], []
    for capital in (previous["parameters"]["capital"], 30., 100.):
        for scenario, fee, slip in (("base", .0005, .0025), ("double_cost", .001, .005)):
            data = cost_case(book, scenario)
            snapshots = {}
            def observe(position, feature, now, original):
                if is_decision(now):
                    snapshots[position["symbol"], position["entry_time"], now] = copy.deepcopy(position)
                return original
            p = dict(previous["parameters"], capital=capital, fee=fee, slip=slip)
            result = replay(data, features, entry_confirmations=gates, entry_liquidity_caps=caps,
                            mr_holding_rule=observe, **p)
            verify(result, data, p)
            old = next(r for r in previous["portfolios"] if r["capital"] == capital and
                       r["scenario"] == scenario and r["profile"] == "control")
            assert result["trades"] == old["trades"] and result["curve"] == old["curve"]
            controls.append(dict(capital=capital, scenario=scenario, headline=old["headline"],
                exact_trades_and_curve=True, mr_held_decisions=len(snapshots)))
            for (symbol, entry_time, now), position in sorted(snapshots.items()):
                f = feature_at(features[symbol], now)
                new_mr = (f["entry_tactical"] and f["tactical_setup"] == "mean_reversion"
                          and f["available"] > position["feature_available"])
                observations.append(dict(capital=capital, scenario=scenario, symbol=symbol,
                    entry_time=entry_time, time=now, new_mr=new_mr, feature_available=f["available"]))
                if not new_mr:
                    continue
                cash = position["equity_before_entry"]-position["entry_fee"]+position["funding"]
                mark = inputs[symbol]["mark"][now].o
                equity = cash+position["quantity"]*(mark-position["entry_price"])-position["quantity"]*mark*fee
                orders, rejections = entry_candidates(data, features, caps, now, equity, fee=fee, slip=slip)
                target = next((order for order in orders if order["symbol"] == symbol), None)
                row = dict(capital=capital, scenario=scenario, symbol=symbol, entry_time=entry_time,
                    time=now, iso=dt.datetime.fromtimestamp(now, dt.timezone.utc).isoformat(),
                    feature_date=f["date"], feature_available=f["available"], position=position,
                    cash=cash, marked_equity=equity, full_new_entry_gate=target is not None,
                    full_new_entry_order=target, rejections=rejections)
                if target:
                    deadline = min(position["funding_lease_deadline"],
                                   position["entry_time"]+position["max_hold_hours"]*3600)
                    hours = max(0., (deadline-now)/3600)
                    reserve = funding_reserve(data[symbol]["funding"], now, hours, p["funding_policy"])
                    gate_reserve = funding_reserve(data[symbol]["funding"], now, 168, p["funding_policy"])
                    reference = inputs[symbol]["trade"][now].o
                    liquidity = min(data[symbol]["trade"][next(i for i, b in enumerate(data[symbol]["trade"]) if b.t == now)-1].v*.01,
                                    caps[symbol, now]["quantity_cap"])
                    row["quote"] = topup_quote(position, data[symbol]["rule"], now=now, reserve_hours=hours,
                        reference=reference, equity=equity, cash=cash, reserve=reserve, gate_reserve=gate_reserve,
                        liquidity=liquidity, fee=fee, slip=slip, risk_fraction=p["risk_fraction"],
                        gap=p["sizing_gap_reserve"], gross_cap=min(p["gross_cap"], f["gross_target"]),
                        liquidation_multiple=p["liquidation_stop_multiple"], mark_price=mark)
                else:
                    row["quote"] = dict(allowed=False, reason="original_full_entry_gate_rejected")
                quotes.append(row)
                print(capital, scenario, row["iso"], symbol, row["quote"], flush=True)
    unique = {r["path"]: r for r in sources}
    for r in unique.values():
        assert hashlib.sha256(Path(r["path"]).read_bytes()).hexdigest() == r["sha256"]
    primary = previous["parameters"]["capital"]
    primary_quotes = [r for r in quotes if r["capital"] == primary]
    if not any(r["quote"]["allowed"] for r in primary_quotes):
        primary_verdict = "No executable top-up on the existing15U trajectory. With all eligible additions rejected, holdings and outcomes remain the original baseline; this is a feasibility elimination, not an add-on-fill portfolio simulation."
    else:
        primary_verdict = "A feasible15U order exists; a complete portfolio simulation is still required."
    out = dict(research_only=True, orders_authorized=False, independent_oos=False,
        sample_start="2026-04-07", sample_end_exclusive="2026-10-26", parameters=previous["parameters"],
        hypothesis="Retain existing MR position; new same-symbol MR must pass full original entry gates. Add only within original lifetime risk/funding budgets, unchanged leverage/stop/deadlines, current incremental capacity and order minimum.",
        controls=controls, observations=observations, quotes=quotes, sources=list(unique.values()),
        primary_verdict=primary_verdict,
        limitations=["Quotes only for larger accounts: not a simulation of fills, later financial exits, changed trailing or future portfolio opportunities.",
            "Only one repeated MR date in the observed baseline positions; already consumed history, not independent confirmation alpha. Current brackets/filters applied historically; ordinary slippage, liquidation proxy and executable IOC remain assumptions."])
    args.output.mkdir(parents=True)
    (args.output/"comparison.json").write_text(json.dumps(out, ensure_ascii=False, allow_nan=False)+"\n")
    lines = ["# 连续MR确认：不重置预算的增仓可行性", "",
        "原持仓继续；同标的出现更新的MR信号且通过原完整入场准入后，才计算额外订单。原止损不放宽、杠杆不调高、21日期限/7日复核不重置、终身风险及资金费额度不增加。旧仓的止损利润不抵扣新仓亏损，浮盈不作为可用现金。",
        "2026-04-07至10-26前，8原生合约、25%压力预算、原容量和现行档位；基础单边手续费5bp/滑点25bp、真实资金费、现金0%。双成本10/50bp及不利常规资金费加倍。", "",
        "## 机会与实际增量订单", "",
        "|本金|成本|新MR时点|旧数量|空仓重算目标|可增量|原因|", "|---:|---|---|---:|---:|---:|---|"]
    for r in quotes:
        q, target = r["quote"], r["full_new_entry_order"]
        lines.append(f"|{r['capital']:.4f}|{r['scenario']}|{r['iso']}|{r['position']['quantity']}|{target['quantity'] if target else '—'}|{q.get('quantity',0)}|{q['reason']}|")
    lines += ["", "## 15U为何不能下增量订单", ""]
    for r in primary_quotes:
        q = r["quote"]
        if "risk_headroom" in q:
            lines += [f"原终身预算{q['original_risk_budget']:.6f} USDT；按当前权益约束后{q['effective_risk_budget']:.6f}，旧仓压力风险{q['existing_stress_risk']:.6f}，余量{q['risk_headroom']:.6f}。",
                f"风险允许增量{q['risk_only_quantity']:.8f}，按数量步长取整{q['risk_only_grid_quantity']:.8f}；独立新增订单最少{q['minimum_increment']:.8f}，最低增量压力风险{q['minimum_increment_stress']:.6f}。"]
    lines += ["", primary_verdict, "",
        "放宽数量/最低名义额、提高原预算、改变旧止损或重置持有期限，会成为不同机制，本轮未这样做。较大账户存在可行报价不等于可执行盈利；尚未实现/运行有增仓成交的完整组合回放。", "",
        f"6组控制成交和净值逐值复现；{len(unique)}份共享公开输入hash一致；新增下载0。持仓观察回调只复制状态，结果与原回放完全相同。", ""]
    lines += ["- "+s for s in out["limitations"]]
    lines += ["", "仅离线研究，不变更生产源码、参数、权限、服务。", "",
        "复现：`PYTHONPATH=src ./.venv/bin/python scripts/research/study_macro_mr_topup.py --output <新目录>`", ""]
    (args.output/"report.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
