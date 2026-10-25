"""One guarded state-exit ablation, with paired opportunity and path diagnostics."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import statistics
from pathlib import Path

from qount.research.binance_etf_leverage import replay
from qount.research.binance_macro_opportunities import cost_case
from qount.research.binance_macro_signals import exit_features
from qount.research.macro_depth_execution import DepthExitStress
from compare_macro_trend_continuation import RUNS, extended_inputs
from study_macro_admission_and_simplicity import headline, verify


def report(result):
    lines = ["# 宏观状态退出：要求价格确认", "",
        "单一候选：原状态标签导致趋势退出、但价格仍高于EMA20时继续持有；自身结构趋势和权益系统门、7天期限、成本门、资金费与初始风险全部保留。均值回归持有规则不改。",
        "2026-04-07至2026-10-22（右端不含），25%压力预算、现行档位历史套用、原分钟容量；本金15.2711为主，30/100及1x上限只作敏感性，不选资金规模。",
        "基础单边手续费5bp/滑点25bp与实际资金费；双成本10/50bp并加倍不利常规资金费；额外退出冲击独立于事前准入成本。现金基准0%。", "",
        "|本金|名义上限|情景|规则|收益|小时MDD|交易数|已闭合损益|截尾损益|", "|---:|---:|---|---|---:|---:|---:|---:|---:|"]
    for r in result["portfolios"]:
        s = r["headline"]
        lines.append(f"|{r['capital']:.4f}|{r['gross_cap']}|{r['scenario']}|{r['profile']}|{s['net_return']:.2%}|{s['max_drawdown']:.2%}|{s['trade_count']}|{s['closed_pnl']:+.5f}|{s['censored_pnl']:+.5f}|")
    lines += ["", "## 同机会、同初始数量的退出增量", "",
        "只比较每标的21天事前去重、最长持有期成熟、两种退出均闭合的机会；保留全部拒绝与截尾。不是独立样本或组合收益。", "",
        "|情景|配对数|平均单位名义增量|中位数增量|正增量数|去掉最好增量后|", "|---|---:|---:|---:|---:|---:|"]
    for r in result["paired_summary"]:
        fmt = lambda x: "—" if x is None else f"{x:.2%}"
        lines.append(f"|{r['scenario']}|{r['count']}|{fmt(r['mean_delta'])}|{fmt(r['median_delta'])}|{r['positive']}|{fmt(r['mean_without_best'])}|")
    lines += ["", "## 共同剔除机会后的完整账户重跑", "",
        "剔除根据历史结果选取，只是脆弱性诊断；两组删除相同episode，保留替代机会与重新定仓，不作为可交易规则。", "",
        "|剔除|情景|规则|收益|小时MDD|已闭合损益|", "|---|---|---|---:|---:|---:|"]
    for r in result["omissions"]:
        s = r["headline"]
        lines.append(f"|{r['omission']}|{r['scenario']}|{r['profile']}|{s['net_return']:.2%}|{s['max_drawdown']:.2%}|{s['closed_pnl']:+.5f}|")
    lines += ["", "## 固定入场的数量归一与机会变化", "",
        "共同入场用控制的原数量重估候选退出，区别退出变化与数量变化；不同入场只列为路径贡献，不当作新预测优势。", ""]
    lines += ["```json", json.dumps(result["base_attribution"], ensure_ascii=False, indent=2), "```", "",
        f"实际回放{result['replay_count']}次；延长控制三组精确复现，逐笔费用/资金费/现金/风险预算核对，候选不改变入场特征或初始数量。",
        "全部为已消费历史及事后延长回放，小时退出与容量仍为模型；独立OOS、真实成交和状态门稳定性未认证。生产规则及调度未改。", "",
        "复现：`PYTHONPATH=src ./.venv/bin/python scripts/research/compare_macro_state_exit.py --output <新目录>`", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new output; prior evidence is retained")
    _, (book, signals, gates, caps), sources, revisions = extended_inputs()
    control_path = RUNS/"macro_trend_continuation_20261022/comparison.json"
    saved = json.loads(control_path.read_text())
    controls = {r["scenario"]: r for r in saved["portfolios"] if r["window"] == "extended" and r["profile"] == "control"}
    venue_path = RUNS/"macro_leverage_cash_review_20261019/venue_snapshot.json"
    venue = json.loads(venue_path.read_text())
    for s, data in book.items():
        data["rule"] = dict(data["rule"], leverage_brackets=venue["symbols"][s]["brackets"])
    candidate = exit_features(signals, "state_exit_price_confirm")
    for symbol, rows in signals.items():
        for old, new in zip(rows, candidate[symbol]):
            assert {k: v for k, v in old.items() if k != "hold_tactical"} == {k: v for k, v in new.items() if k != "hold_tactical"}
    base_parameters = copy.deepcopy(controls["base"]["parameters"])
    capital = base_parameters["capital"]
    profiles = {"control": signals, "price_confirm": candidate}
    portfolios, events, omissions, checks = [], [], [], []
    replay_count = 0

    def run(profile, scenario, params, shock=0, confirmations=None, **extra):
        nonlocal replay_count
        data = cost_case(book, scenario)
        result = replay(data, profiles[profile], entry_confirmations=gates if confirmations is None else confirmations,
            entry_liquidity_caps=caps,
            exit_execution_model=DepthExitStress({}, use_depth=False, all_extra_slip=shock) if shock else None,
            **params, **extra)
        verify(result, data, params)
        replay_count += 1
        return result

    cases = (("base", .0005, .0025, 0), ("double_cost", .001, .005, 0),
             ("exit50bp", .0005, .0025, .005), ("exit200bp", .0005, .0025, .02))
    main_runs = {}
    for amount, gross in ((capital, 20), (capital, 1), (30., 20), (100., 20)):
        for scenario, fee, slip, shock in cases if amount == capital else cases[:2]:
            p = dict(base_parameters, capital=amount, gross_cap=gross, fee=fee, slip=slip)
            for profile in profiles:
                result = run(profile, scenario, p, shock)
                if amount == capital and gross == 20:
                    main_runs[profile, scenario] = result
                    if profile == "control" and scenario in controls:
                        old = controls[scenario]
                        assert result["trades"] == old["trades"] and result["curve"] == old["curve"]
                        checks.append(scenario+": exact extended control")
                row = dict(capital=amount, gross_cap=gross, profile=profile, scenario=scenario,
                    headline=headline(result), trades=result["trades"], curve=result["curve"])
                portfolios.append(row)
                print(amount, gross, profile, scenario, json.dumps(row["headline"]), flush=True)
    eligible = sorted((k for k, g in gates.items() if g["eligible"]), key=lambda k: (k[1], k[0]))
    nonoverlap, last_end = set(), {}
    for symbol, now in eligible:
        if now >= last_end.get(symbol, 0):
            nonoverlap.add((symbol, now))
            last_end[symbol] = now+21*86400
    for scenario, fee, slip, _ in cases[:2]:
        p = dict(base_parameters, fee=fee, slip=slip)
        for symbol, now in eligible:
            outcomes = {}
            for profile in profiles:
                result = run(profile, scenario, p, forced_entry=dict(symbol=symbol, time=now, engine="tactical"), entry_end_exclusive=now+1)
                assert len(result["trades"]) <= 1
                outcomes[profile] = dict(trade=result["trades"][0] if result["trades"] else None,
                                         rejections=result["summary"]["rejections"])
            a, b = outcomes["control"]["trade"], outcomes["price_confirm"]["trade"]
            assert bool(a) == bool(b)
            if a:
                for key in ("symbol", "entry_time", "entry_price", "quantity", "initial_stop", "leverage", "risk_budget_usdt"):
                    assert a[key] == b[key]
            horizon = p["tactical_setup_policies"][gates[symbol, now]["setup"]]["max_hold_hours"]
            events.append(dict(symbol=symbol, time=now, scenario=scenario, nonoverlap=(symbol, now) in nonoverlap,
                mature=now+horizon*3600 <= book[symbol]["trade"][-1].t+3600, outcomes=outcomes))
    paired = []
    for scenario, *_ in cases[:2]:
        values = []
        for e in events:
            if e["scenario"] != scenario or not e["nonoverlap"] or not e["mature"]:
                continue
            a, b = e["outcomes"]["control"]["trade"], e["outcomes"]["price_confirm"]["trade"]
            if a and b and a["exit_reason"] != "end_of_sample" and b["exit_reason"] != "end_of_sample":
                values.append((b["net_pnl"]-a["net_pnl"])/a["notional_usdt"])
        paired.append(dict(scenario=scenario, count=len(values), mean_delta=statistics.mean(values) if values else None,
            median_delta=statistics.median(values) if values else None, positive=sum(v > 0 for v in values),
            mean_without_best=(sum(values)-max(values))/(len(values)-1) if len(values)>1 else None))
    baseline = main_runs["control", "base"]["trades"]
    top = sorted((t for t in baseline if t["net_pnl"] > 0), key=lambda t: -t["net_pnl"])[:2]
    # Same episodes removed in both policies; selection is explicitly retrospective.
    patterns = {"missing_top_two": {(t["symbol"], gates[t["symbol"], t["entry_time"]]["anchor_time"]) for t in top},
                "missing_losing_trend_CL": {(t["symbol"], gates[t["symbol"], t["entry_time"]]["anchor_time"])
                    for t in baseline if t["symbol"] == "CLUSDT" and t["tactical_setup"] != "mean_reversion"}}
    for omission, omitted in patterns.items():
        altered = {key: dict(g, eligible=False, reason="common_hindsight_omission")
                   if (key[0], g["anchor_time"]) in omitted else g for key, g in gates.items()}
        for scenario, fee, slip, shock in (cases[0], cases[2]):
            p = dict(base_parameters, fee=fee, slip=slip)
            for profile in profiles:
                result = run(profile, scenario, p, shock, confirmations=altered)
                assert all((t["symbol"], gates[t["symbol"], t["entry_time"]]["anchor_time"]) not in omitted for t in result["trades"])
                omissions.append(dict(omission=omission, scenario=scenario, profile=profile,
                    headline=headline(result), trades=result["trades"]))
    a = {(t["symbol"], t["entry_time"]): t for t in baseline}
    b = {(t["symbol"], t["entry_time"]): t for t in main_runs["price_confirm", "base"]["trades"]}
    common, exit_delta, quantity_delta = [], 0., 0.
    for key in sorted(a.keys() & b.keys()):
        old, new = a[key], b[key]
        frozen_exit_delta = (new["net_pnl"]/new["quantity"]-old["net_pnl"]/old["quantity"])*old["quantity"]
        size_delta = new["net_pnl"]-old["net_pnl"]-frozen_exit_delta
        exit_delta += frozen_exit_delta
        quantity_delta += size_delta
        common.append(dict(symbol=key[0], time=key[1], exit_delta=frozen_exit_delta, quantity_delta=size_delta))
    attribution = dict(common_entries=common, same_quantity_exit_delta=exit_delta, common_quantity_delta=quantity_delta,
        control_only=[dict(symbol=k[0],time=k[1],net_pnl=a[k]["net_pnl"]) for k in sorted(a.keys()-b.keys())],
        candidate_only=[dict(symbol=k[0],time=k[1],net_pnl=b[k]["net_pnl"]) for k in sorted(b.keys()-a.keys())])
    delta = exit_delta+quantity_delta-sum(t["net_pnl"] for t in attribution["control_only"])+sum(t["net_pnl"] for t in attribution["candidate_only"])
    assert abs(delta-(sum(t["net_pnl"] for t in b.values())-sum(t["net_pnl"] for t in a.values()))) < 1e-8
    for path in (control_path, venue_path):
        sources.append(dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    unique = {s["path"]: s for s in sources}
    for source in unique.values():
        assert hashlib.sha256(Path(source["path"]).read_bytes()).hexdigest() == source["sha256"]
    output = dict(research_only=True,orders_authorized=False,independent_oos=False,
        hypothesis="A state-label exit may be premature while the same price trend remains intact; test guard and distinguish exit improvement from occupancy changes.",
        sample_start="2026-04-07",sample_end_exclusive="2026-10-22",parameters=base_parameters,
        replay_count=replay_count, control_checks=checks, sources=list(unique.values()),
        overlap_adjusted_price_revisions=revisions, portfolios=portfolios, events=events,
        paired_summary=paired, omissions=omissions, base_attribution=attribution,
        code=[dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in
            (Path(__file__),Path("src/qount/research/binance_macro_signals.py"),Path("src/qount/research/binance_etf_leverage.py"))])
    args.output.mkdir(parents=True)
    (args.output/"comparison.json").write_text(json.dumps(output,ensure_ascii=False,allow_nan=False)+"\n")
    (args.output/"report.md").write_text(report(output))
    print("saved",args.output,"replays",replay_count,flush=True)


if __name__ == "__main__":
    main()
