"""Fixed one-R profit-protection ablations on the extended native sample."""
from __future__ import annotations

import argparse
import copy
import functools
import hashlib
import json
import statistics
from pathlib import Path
from unittest.mock import patch

import qount.research.binance_etf_leverage as model
from qount.research.binance_macro_opportunities import cost_case
from qount.research.macro_depth_execution import DepthExitStress
from qount.research.macro_profit_protection import protect_profit
from qount.strategies import macro_1atr as live_policy
from compare_macro_trend_continuation import RUNS, extended_inputs
from study_macro_admission_and_simplicity import headline, verify


PROFILES = {"control": (False, False), "cost_floor_1r": (False, True),
            "trail_1r": (True, False), "trail_1r_cost_floor": (True, True)}


def report(output):
    lines = ["# 当前宏观策略：1R利润保护消融", "",
        "固定两项机制：1R后覆盖已知费用的止损底线；原2ATR移动止损从2R提前到1R激活。二者各自及组合，共四格，不搜索阈值。",
        "2026-04-07至10-22（右端不含），初始15.27112826USDT、25%压力预算、原20x名义上限；保留原信号、成本门、不追涨、容量及资金费续期。",
        "基础单边手续费5bp、滑点25bp及实际资金费；双成本10/50bp及不利常规资金费加倍。额外退出冲击保持事前准入成本不变。",
        "底线仅用已完成小时收盘、已付费用和已知净资金费支出；更新对后续交易生效，不用小时最高价提前保本。底线不是跳空或未来资金费下的零亏损保证。", "",
        "|机制|成本情景|收益|小时MDD|已闭合/截尾|已闭合净损益|截尾估值|", "|---|---|---:|---:|---:|---:|---:|"]
    for row in output["portfolios"]:
        s = row["headline"]
        lines.append(f"|{row['profile']}|{row['scenario']}|{s['net_return']:.2%}|{s['max_drawdown']:.2%}|{s['closed_count']}/{s['trade_count']-s['closed_count']}|{s['closed_pnl']:+.5f}|{s['censored_pnl']:+.5f}|")
    lines += ["", "## 同一批独立启动机会的配对", "",
        "按每标的21天窗口事前去重，并只比较最长持有期限已成熟、控制可成交且两条路径均闭合的机会。未成交/截尾/未成熟都单列。跨资产仍相关，不能相加成组合收益。", "",
        "|候选|成本|配对数|平均单位名义增量|中位数增量|正增量数|不计最大增量后的均值|", "|---|---|---:|---:|---:|---:|---:|"]
    for row in output["paired_summary"]:
        fmt = lambda v: "—" if v is None else f"{v:.2%}"
        lines.append(f"|{row['profile']}|{row['scenario']}|{row['count']}|{fmt(row['mean_delta'])}|{fmt(row['median_delta'])}|{row['positive']}|{fmt(row['mean_without_best'])}|")
    lines += ["", "## 验证与限制", "",
        f"- {output['replay_count']}次实际回放；延长样本原基础/双成本/50bp冲击三组交易与净值精确复现。",
        "- 每笔现金、手续费和资金费独立重算；同机会入场数量/价格/初始止损/杠杆一致，只改变后续保护。",
        "- 原始历史特征不改写，新段不是当时前向；全部为已消费历史，不认证独立OOS。",
        "- 小时价格路径和退出容量近似仍保留；更紧止损可能改变实际成交滑点与触发频率，不能从模型收益推定真实可成交。",
        "- 未修改生产源码、配置、权限、调度或真实订单。", "",
        "复现：`PYTHONPATH=src ./.venv/bin/python scripts/research/compare_macro_profit_protection.py --output <新目录>`", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new output; retained evidence is not overwritten")
    _, bundle, sources, revisions = extended_inputs()
    book, signals, gates, caps = bundle
    retained_path = RUNS/"macro_trend_continuation_20261022/comparison.json"
    retained = json.loads(retained_path.read_text())
    venue_path = RUNS/"macro_leverage_cash_review_20261019/venue_snapshot.json"
    venue = json.loads(venue_path.read_text())
    for symbol, data in book.items():
        data["rule"] = dict(data["rule"], leverage_brackets=venue["symbols"][symbol]["brackets"])
    controls = {r["scenario"]: r for r in retained["portfolios"] if r["window"] == "extended" and r["profile"] == "control"}
    p = copy.deepcopy(controls["base"]["parameters"])
    original = live_policy.trailing_update
    portfolios, events, checks = [], [], []
    count = 0

    def run(profile, data, parameters, shock=0, **extra):
        nonlocal count
        early, floor = PROFILES[profile]
        updater = (original if profile == "control" else functools.partial(protect_profit,
            fee=parameters["fee"], slip=parameters["slip"], early_trail=early, cost_floor=floor))
        with patch.object(live_policy, "trailing_update", updater):
            result = model.replay(data, signals, entry_confirmations=gates, entry_liquidity_caps=caps,
                exit_execution_model=DepthExitStress({}, use_depth=False, all_extra_slip=shock) if shock else None,
                **parameters, **extra)
        verify(result, data, parameters)
        count += 1
        return result

    for scenario, fee, slip, shock in (("base", .0005, .0025, 0), ("double_cost", .001, .005, 0),
                                     ("exit50bp", .0005, .0025, .005), ("exit200bp", .0005, .0025, .02)):
        parameters = dict(p, fee=fee, slip=slip)
        data = cost_case(book, scenario)
        for profile in PROFILES:
            result = run(profile, data, parameters, shock)
            if profile == "control" and scenario in controls:
                assert result["trades"] == controls[scenario]["trades"] and result["curve"] == controls[scenario]["curve"]
                checks.append(scenario+": exact extended control")
            row = dict(profile=profile, scenario=scenario, headline=headline(result),
                       trades=result["trades"], curve=result["curve"])
            portfolios.append(row)
            print(profile, scenario, json.dumps(row["headline"]), flush=True)
    eligible = sorted((k for k, g in gates.items() if g["eligible"]), key=lambda k: (k[1], k[0]))
    nonoverlap, last_end = set(), {}
    for symbol, now in eligible:
        if now >= last_end.get(symbol, 0):
            nonoverlap.add((symbol, now))
            last_end[symbol] = now+21*86400
    for scenario, fee, slip in (("base", .0005, .0025), ("double_cost", .001, .005)):
        data, parameters = cost_case(book, scenario), dict(p, fee=fee, slip=slip)
        for symbol, now in eligible:
            outcomes = {}
            for profile in PROFILES:
                result = run(profile, data, parameters,
                    forced_entry=dict(symbol=symbol, time=now, engine="tactical"), entry_end_exclusive=now+1)
                assert len(result["trades"]) <= 1
                trade = result["trades"][0] if result["trades"] else None
                outcomes[profile] = dict(trade=trade, rejections=result["summary"]["rejections"])
                control = outcomes["control"]["trade"]
                assert bool(trade) == bool(control)
                if trade:
                    for key in ("symbol", "entry_time", "entry_price", "quantity", "initial_stop", "leverage", "risk_budget_usdt"):
                        assert trade[key] == control[key], (profile, key)
            horizon = parameters["tactical_setup_policies"][gates[symbol, now]["setup"]]["max_hold_hours"]
            events.append(dict(symbol=symbol, time=now, scenario=scenario,
                nonoverlap=(symbol, now) in nonoverlap,
                mature=now+horizon*3600 <= book[symbol]["trade"][-1].t+3600, outcomes=outcomes))
    paired = []
    for profile in list(PROFILES)[1:]:
        for scenario in ("base", "double_cost"):
            selected = [e for e in events if e["scenario"] == scenario and e["nonoverlap"] and e["mature"]]
            deltas = []
            for e in selected:
                a, b = e["outcomes"]["control"]["trade"], e["outcomes"][profile]["trade"]
                if a and b and a["exit_reason"] != "end_of_sample" and b["exit_reason"] != "end_of_sample":
                    deltas.append((b["net_pnl"]-a["net_pnl"])/a["notional_usdt"])
            paired.append(dict(profile=profile, scenario=scenario, count=len(deltas),
                mean_delta=statistics.mean(deltas) if deltas else None,
                median_delta=statistics.median(deltas) if deltas else None,
                positive=sum(v > 0 for v in deltas),
                mean_without_best=(sum(deltas)-max(deltas))/(len(deltas)-1) if len(deltas)>1 else None))
    assert live_policy.trailing_update is original
    for path in (retained_path, venue_path):
        sources.append(dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    unique = {s["path"]: s for s in sources}
    for source in unique.values():
        assert hashlib.sha256(Path(source["path"]).read_bytes()).hexdigest() == source["sha256"]
    output = dict(research_only=True, orders_authorized=False, independent_oos=False,
        hypothesis="Can one-R cost-cover protection or earlier two-ATR trailing improve realized outcomes without loosening admission or raising entry risk?",
        sample_start="2026-04-07", sample_end_exclusive="2026-10-22", parameters=p,
        profiles=PROFILES, replay_count=count, control_checks=checks, sources=list(unique.values()),
        overlap_adjusted_price_revisions=revisions, portfolios=portfolios, events=events, paired_summary=paired,
        code=[dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()) for path in
            (Path(__file__), Path("src/qount/research/macro_profit_protection.py"), Path("src/qount/research/binance_etf_leverage.py"))])
    args.output.mkdir(parents=True)
    (args.output/"comparison.json").write_text(json.dumps(output, ensure_ascii=False, allow_nan=False)+"\n")
    (args.output/"report.md").write_text(report(output))
    print("saved", args.output, "replays", count, flush=True)


if __name__ == "__main__":
    main()
