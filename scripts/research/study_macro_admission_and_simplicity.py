"""Offline cost-gate counterfactuals and fixed simple controls on retained inputs."""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import math
import statistics
from collections import Counter
from pathlib import Path

from qount.research.binance_etf_leverage import replay
from qount.research.binance_macro_attack import CONTRACT_SIGNALS
from qount.research.binance_macro_liquidity import load_capacity_contexts
from qount.research.binance_macro_opportunities import cost_case, fixed_fill_metrics, trade_pnl_components
from qount.research.lines.macro_1atr import inputs
from qount.research.lines.simple_trend import candidate_clocks, simple_features
from qount.strategies.macro_episodes import episode_confirmations


CACHE = Path("state/research_cache")
RUNS = Path("state/research_runs")
START, END = "2026-04-07", "2026-10-15"


def verify(result, data, parameters):
    """Reconcile fills and signed funding independently of replay summary fields."""
    fee, capital = parameters["fee"], parameters["capital"]
    for t in result["trades"]:
        assert t["feature_available"] < t["entry_time"]
        assert t["stress_risk_usdt"] <= t["risk_budget_usdt"] + 1e-8
        assert t["notional_usdt"] <= parameters["gross_cap"] * t["equity_before_entry"] + 1e-8
        paid = 0.0
        for row in data[t["symbol"]]["funding"]:
            stamp = int(row["fundingTime"])
            if not t["entry_time"] * 1000 <= stamp < t["exit_time"] * 1000:
                continue
            payment = -t["quantity"] * float(row["markPrice"]) * float(row["fundingRate"])
            if t["exit_reason"] in ("stop", "liquidation_proxy") and stamp >= (t["exit_time"]-3600)*1000 and payment > 0:
                continue
            paid += payment
        assert math.isclose(paid, t["funding"], abs_tol=1e-8)
        net = t["quantity"] * (t["exit_price"]-t["entry_price"]) + paid - fee*t["quantity"]*(t["entry_price"]+t["exit_price"])
        assert math.isclose(net, t["net_pnl"], abs_tol=1e-8)
        trade_pnl_components(t, fee=fee, slip=parameters["slip"])
    assert math.isclose(capital + sum(t["net_pnl"] for t in result["trades"]), result["summary"]["final_equity"], abs_tol=1e-8)


def economics(trade, parameters):
    if trade is None:
        return None
    parts = trade_pnl_components(trade, fee=parameters["fee"], slip=parameters["slip"])
    notional = trade["notional_usdt"]
    return dict(closed=trade["exit_reason"] != "end_of_sample", entry_notional=notional,
                net_return_on_notional=trade["net_pnl"]/notional,
                components_on_notional={k: v/notional for k, v in parts.items()},
                exit_reason=trade["exit_reason"])


def distribution(rows):
    executed = [r for r in rows if r["economic"] is not None]
    closed = [r for r in executed if r["economic"]["closed"]]
    values = [r["economic"]["net_return_on_notional"] for r in closed]
    return dict(opportunities=len(rows), executed=len(executed), closed=len(closed),
                censored=len(executed)-len(closed), unresolved=len(rows)-len(executed),
                mean_net=statistics.mean(values) if values else None,
                median_net=statistics.median(values) if values else None,
                wins=sum(v > 0 for v in values),
                mean_without_best=(sum(values)-max(values))/(len(values)-1) if len(values) > 1 else None,
                mean_components={k: statistics.mean(r["economic"]["components_on_notional"][k] for r in closed)
                                 if closed else None for k in ("raw_price_pnl", "slippage_cost", "fees", "net_funding")},
                exit_reasons=dict(Counter(r["economic"]["exit_reason"] for r in executed)))


def headline(result):
    trades = result["trades"]
    return dict(result["summary"],
                closed_pnl=sum(t["net_pnl"] for t in trades if t["exit_reason"] != "end_of_sample"),
                censored_pnl=sum(t["net_pnl"] for t in trades if t["exit_reason"] == "end_of_sample"),
                closed_count=sum(t["exit_reason"] != "end_of_sample" for t in trades),
                average_closed_notional_return=statistics.mean(t["net_pnl"]/t["notional_usdt"] for t in trades
                    if t["exit_reason"] != "end_of_sample") if any(t["exit_reason"] != "end_of_sample" for t in trades) else None)


def report(output):
    lines = ["# 当前宏观策略：成本门与简单规则对照", "",
             "2026-04-07 至 2026-10-15（右端不含），初始15.27112826 USDT；25%压力预算、当前档位历史套用。",
             "全部为已消费历史，不是独立OOS。现金基准0%；原生小时成交/止损近似、原分钟容量与资金费。",
             "基础单边手续费5bp、滑点25bp；双成本10/50bp并加倍不利常规资金费。", "",
             "## 成本门：同机会影子", "",
             "仅对原生确认已合格的机会，使用相同起始资本独立启动；正常拒绝后只取消入场成本比例门，其他约束、成本和退出不变。",
             "保留交易单位、最小名义额、清算距离和容量；取消成本门后仍不能成交的机会不填0收益。",
             "21天去重按入场时间预先选择，每标的保留最长21天窗口，跨标的仍可能相关；另排除期限未成熟的机会作配对。", "",
             "|样本|成本|正常准入|机会数|影子闭合/截尾/未成交|平均单位名义净收益|中位数|去掉最好一笔均值|", "|---|---|---|---:|---|---:|---:|---:|"]
    def pct(x):
        return "—" if x is None else f"{x:.2%}"
    for row in output["admission_summary"]:
        d = row["distribution"]
        lines.append(f"|{row['sample']}|{row['scenario']}|{row['admission']}|{d['opportunities']}|{d['closed']}/{d['censored']}/{d['unresolved']}|{pct(d['mean_net'])}|{pct(d['median_net'])}|{pct(d['mean_without_best'])}|")
    lines += ["", "## 相同约束下的固定简单规则", "",
              "原宏观、原SMA120+20日正动量、相同简单规则加禁止追涨；不搜索窗口或阈值。",
              "相同25%压力预算、原生ATR止损/小时移动止损、7天期限（宏观MR保留21天及7天续期）、容量及成本。",
              "20x与1x分别为统一名义上限；上限相同不代表实际风险或持仓路径相同。", "",
              "|规则|名义上限|成本|收益|小时MDD|成交数|已闭合损益USDT|末端估值USDT|实际最大名义敞口|", "|---|---:|---|---:|---:|---:|---:|---:|---:|"]
    for key, result in output["portfolios"].items():
        s = result["headline"]
        lines.append(f"|{key}|{result['parameters']['gross_cap']}|{result['scenario']}|{s['net_return']:.2%}|{s['max_drawdown']:.2%}|{s['trade_count']}|{s['closed_pnl']:+.4f}|{s['censored_pnl']:+.4f}|{s['maximum_observed_gross']:.2f}x|")
    lines += ["", "## 验证与解释边界", "",
              f"- 原宏观基础/双成本曲线与交易精确复现：{len(output['control_checks'])}组。",
              f"- {output['replay_count']}次回放逐笔核对费用、资金费、现金、预算和信息时点；正常准入影子取消成本门后逐笔不变。",
              "- 被拒/被接受组由事前成本几何分类，但非随机分组，不把均值差当作门槛的因果效应。",
              "- 单事件互相重叠，不能把单位收益均值相加为账户收益；末端截尾和期限未成熟单列。",
              "- 当前档位/交易单位回溯近似，历史原生止损可靠性、真实盘口成交及独立样本外仍未验证。",
              "- 简单加禁止追涨是固定机制消融，不按赢家选择新参数；不同策略持有期限不完全相同。",
              "- 实盘配置、源码、服务、调度与授权未变。", "",
              "复现：`PYTHONPATH=src ./.venv/bin/python scripts/research/study_macro_admission_and_simplicity.py --output <新目录>`", ""]
    lines += ["## 固定路径与重新选择的成本归因", "",
              "固定基础情景数量、原始成交参考价和退出时点，再增加费用/滑点及不利常规资金费；仅为会计诊断，不生成可执行净值或MDD。", "",
              "|规则|基础收益|固定原路径双成本|完整双成本|基础/双成本成交数|共同入场数|", "|---|---:|---:|---:|---:|---:|---:|"]
    for key, row in output["cost_path_attribution"].items():
        lines.append(f"|{key}|{row['base_return']:.2%}|{row['fixed_path_double_return']:.2%}|{row['full_double_return']:.2%}|{row['base_count']}/{row['double_count']}|{row['common_entries']}|")
    lines += ["", "双成本盈利更高若伴随机会集变化，不能归因费用更高有利；固定路径诊断保留截尾和未验证的退出可执行性。", ""]
    lines += ["## 简单候选的利润依赖（事后诊断）", "",
              "以下删除依据已知结果选择，不是可交易过滤器；每次从原始资金完整重跑，保留替代机会。只比较共同1x上限。", "",
              "|规则/成本|诊断|收益|小时MDD|成交数|已闭合损益|末端估值|", "|---|---|---:|---:|---:|---:|---:|"]
    for row in output["fragility"]:
        h = row["headline"]
        lines.append(f"|{row['policy']}/{row['scenario']}|{row['omission']}|{h['net_return']:.2%}|{h['max_drawdown']:.2%}|{h['trade_count']}|{h['closed_pnl']:+.4f}|{h['censored_pnl']:+.4f}|")
    if output.get("live_cost_observation"):
        live = output["live_cost_observation"]
        lines += ["", "## 真实执行成本的可观测证据", "",
                  f"只读核对时间：{live['observed_at']}；本策略归属成交{live['strategy']['accounting']['assigned_fill_count']}，当前空仓。",
                  "账户旧成交只能校核已发生的手续费，不能替代新策略入场滑点、原生止损成交或资金费续期证据。",
                  "现有订单/成交/资金费来源可用于下一笔核算；当前样本不支持认证25bp滑点或止损执行。",
                  "主动退出的精确决策参考报价及保护提交到确认的时间未完整持久化，不能事后用小时价格冒充精确执行基准。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live-observation", type=Path, help="Optional sanitized read-only API/SQLite observation; no exchange access.")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new output; retained results are never overwritten")
    control_path = RUNS/"macro_risk_candidate_20261020/with_policy_parity.json"
    controls = json.loads(control_path.read_text())["results"]
    venue_path = RUNS/"macro_leverage_cash_review_20261019/venue_snapshot.json"
    venue = json.loads(venue_path.read_text())
    book, signals, gates, caps, sources = inputs(CACHE/"binance_macro_attack_20261015",
        [CACHE/n for n in ("binance_macro_prefix_20260407_20260611", "binance_macro_earlier_20260611_20260730", "binance_macro_attack_20261015")],
        CACHE/"binance_macro_liquidity_20261015", START, END)
    for symbol, data in book.items():
        data["rule"] = dict(data["rule"], leverage_brackets=venue["symbols"][symbol]["brackets"])
    parameters = copy.deepcopy(controls["risk25_all_base"]["parameters"])
    parameters.pop("omission")
    parameters.pop("extra_exit_slip")
    simple, simple_sources = simple_features(CACHE/"binance_macro_attack_20261015", CONTRACT_SIGNALS, END)
    clocks = candidate_clocks(book, simple)
    roots = (CACHE/"binance_macro_liquidity_20261015", CACHE/"macro_simple_trend_minutes_20261017")
    simple_caps = {}
    for root in roots:
        keys = [key for key in clocks if (root/f"{key[0]}-trade-1m-{key[1]-960}-{key[1]+60}.json").exists()]
        extra, rows, _ = load_capacity_contexts(keys, root)
        for key, value in extra.items():
            if key in simple_caps:
                assert simple_caps[key] == value
            simple_caps[key] = value
        sources += rows
    assert all(key in simple_caps for key in clocks), "existing simple-rule minute cache is incomplete"
    for key in set(simple_caps) & set(caps):
        assert simple_caps[key] == caps[key]
    common_caps = {**caps, **simple_caps}
    for key, cap in common_caps.items():
        assert key[1]-120 <= cap["asof"] <= key[1]-60
    simple_gates = episode_confirmations(book, simple, "no_chase")
    prefix_checks = []
    for cutoff in ("2026-06-30", "2026-08-31", "2026-09-30"):
        stamp = int(dt.datetime.fromisoformat(cutoff).replace(tzinfo=dt.timezone.utc).timestamp())
        truncated = {s: dict(d, trade=[b for b in d["trade"] if b.t <= stamp]) for s, d in book.items()}
        past = {s: [r for r in rows if r["available"] <= stamp] for s, rows in simple.items()}
        prefix = episode_confirmations(truncated, past, "no_chase")
        assert prefix == {k: v for k, v in simple_gates.items() if k[1] <= stamp}
        prefix_checks.append(cutoff+": no future bars/features needed for episode confirmations")
    eligible = sorted((key for key, gate in gates.items() if gate["eligible"]), key=lambda k: (k[1], k[0]))
    nonoverlap, last_end = set(), {}
    for symbol, now in eligible:
        if now >= last_end.get(symbol, 0):
            nonoverlap.add((symbol, now))
            last_end[symbol] = now+21*86400
    events, portfolios, checks = [], {}, []
    replay_count = 0

    def run(data, features, confirmations, p, **extra):
        nonlocal replay_count
        result = replay(data, features, entry_confirmations=confirmations, entry_liquidity_caps=common_caps, **p, **extra)
        verify(result, data, p)
        replay_count += 1
        return result

    for scenario, fee, slip in (("base", .0005, .0025), ("double_cost", .001, .005)):
        data = cost_case(book, scenario)
        p = dict(parameters, fee=fee, slip=slip)
        baseline = run(data, signals, gates, p)
        old = controls[f"risk25_all_{scenario}"]
        assert baseline["trades"] == old["trades"] and baseline["curve"] == old["curve"]
        checks.append(scenario+": exact retained trades and curve")
        for symbol, now in eligible:
            forced = dict(symbol=symbol, time=now, engine="tactical")
            ordinary = run(data, signals, gates, p, forced_entry=forced, entry_end_exclusive=now+1)
            shadow = run(data, signals, gates, p, forced_entry=dict(forced, ignore_friction_gate=True), entry_end_exclusive=now+1)
            assert len(ordinary["trades"]) <= 1 and len(shadow["trades"]) <= 1
            if ordinary["trades"]:
                assert ordinary["trades"] == shadow["trades"], "cost bypass changed an admitted path"
                admission = "accepted"
            elif ordinary["summary"]["rejections"].get("friction_budget"):
                admission = "friction_rejected"
            else:
                admission = "other_rejected"
            trade = shadow["trades"][0] if shadow["trades"] else None
            horizon = p["tactical_setup_policies"][gates[symbol, now]["setup"]]["max_hold_hours"]
            events.append(dict(symbol=symbol, time=now, date=dt.datetime.fromtimestamp(now, dt.timezone.utc).isoformat(),
                scenario=scenario, admission=admission, setup=gates[symbol, now]["setup"],
                nonoverlap_21days=(symbol, now) in nonoverlap,
                horizon_mature=now+horizon*3600 <= data[symbol]["trade"][-1].t+3600,
                normal_rejections=ordinary["summary"]["rejections"], shadow_rejections=shadow["summary"]["rejections"],
                trade=trade, economic=economics(trade, p)))
        for gross in (20, 1):
            for name, fs, gs in (("macro", signals, gates), ("simple", simple, None), ("simple_no_chase", simple, simple_gates)):
                pp = dict(p, gross_cap=gross)
                result = baseline if name == "macro" and gross == 20 else run(data, fs, gs, pp)
                portfolios[f"{name}_gross{gross}_{scenario}"] = dict(scenario=scenario, parameters=pp,
                    headline=headline(result), trades=result["trades"], curve=result["curve"])
                print(name, gross, scenario, json.dumps(headline(result)), flush=True)
    summaries = []
    for sample in ("all", "per_symbol_21day", "mature_per_symbol_21day"):
        selected = [e for e in events if (sample == "all" or e["nonoverlap_21days"])
                    and (sample != "mature_per_symbol_21day" or e["horizon_mature"])]
        for scenario in ("base", "double_cost"):
            for admission in ("accepted", "friction_rejected", "other_rejected"):
                rows = [e for e in selected if e["scenario"] == scenario and e["admission"] == admission]
                summaries.append(dict(sample=sample, scenario=scenario, admission=admission, distribution=distribution(rows)))
    cost_paths = {}
    for name in ("macro", "simple", "simple_no_chase"):
        for gross in (20, 1):
            base = portfolios[f"{name}_gross{gross}_base"]
            double = portfolios[f"{name}_gross{gross}_double_cost"]
            fixed = [fixed_fill_metrics(t, t, book[t["symbol"]]["funding"], fee=.0005, slip=.0025)
                     for t in base["trades"]]
            base_keys = {(t["symbol"], t["entry_time"]) for t in base["trades"]}
            double_keys = {(t["symbol"], t["entry_time"]) for t in double["trades"]}
            fixed_pnl = sum(t["fixed_path_double_cost_pnl"] for t in fixed)
            cost_paths[f"{name}_gross{gross}"] = dict(base_return=base["headline"]["net_return"],
                fixed_path_double_return=fixed_pnl/parameters["capital"],
                full_double_return=double["headline"]["net_return"],
                fixed_closed_pnl=sum(t["fixed_path_double_cost_pnl"] for t in fixed if not t["right_censored"]),
                fixed_censored_pnl=sum(t["fixed_path_double_cost_pnl"] for t in fixed if t["right_censored"]),
                base_count=len(base["trades"]), double_count=len(double["trades"]),
                common_entries=len(base_keys & double_keys),
                fixed_path_not_executable=True)
    fragility = []
    for name, fs, gs in (("macro", signals, gates), ("simple_no_chase", simple, simple_gates)):
        for scenario, fee, slip in (("base", .0005, .0025), ("double_cost", .001, .005)):
            base = portfolios[f"{name}_gross1_{scenario}"]
            ranked = sorted((t for t in base["trades"] if t["net_pnl"] > 0), key=lambda t: -t["net_pnl"])[:2]
            omitted_episodes = {(t["symbol"], gs[t["symbol"], t["entry_time"]]["anchor_time"]) for t in ranked}
            for omission in ("omit_top_two_episodes", "omit_CL"):
                altered = {key: dict(g, eligible=False, reason="hindsight_fragility_diagnostic")
                           if ((key[0], g["anchor_time"]) in omitted_episodes if omission == "omit_top_two_episodes" else key[0] == "CLUSDT")
                           else g for key, g in gs.items()}
                p = dict(parameters, gross_cap=1, fee=fee, slip=slip)
                result = run(cost_case(book, scenario), fs, altered, p)
                assert all(((t["symbol"], gs[t["symbol"], t["entry_time"]]["anchor_time"]) not in omitted_episodes
                            if omission == "omit_top_two_episodes" else t["symbol"] != "CLUSDT") for t in result["trades"])
                fragility.append(dict(policy=name, scenario=scenario, omission=omission,
                    omitted_episodes=sorted(omitted_episodes) if omission == "omit_top_two_episodes" else None,
                    headline=headline(result), trades=result["trades"]))
    paired_groups = []
    by_key = {(e["symbol"], e["time"], e["scenario"]): e for e in events}
    for admission in ("accepted", "friction_rejected", "other_rejected"):
        base_group = [e for e in events if e["scenario"] == "base" and e["nonoverlap_21days"]
                      and e["horizon_mature"] and e["admission"] == admission]
        paired_groups.append(dict(base_admission=admission,
            base=distribution(base_group),
            double_cost=distribution([by_key[e["symbol"], e["time"], "double_cost"] for e in base_group])))
    unique = {row["path"]: row for row in sources+simple_sources}
    for path in (control_path, venue_path):
        unique[str(path)] = dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    for row in unique.values():
        assert hashlib.sha256(Path(row["path"]).read_bytes()).hexdigest() == row["sha256"]
    output = dict(research_only=True, orders_authorized=False, independent_oos=False,
        hypothesis="Does the cost gate exclude profitable unit-notional opportunities, and does macro complexity add beyond a fixed simple rule at common gross caps?",
        sample_start=START, sample_end_exclusive=END, initial_capital=parameters["capital"],
        parameters=parameters, symbols=list(book), benchmark="cash 0%", control_checks=checks,
        prefix_checks=prefix_checks, paired_base_admission_summary=paired_groups, cost_path_attribution=cost_paths,
        fragility=fragility,
        replay_count=replay_count, source_count=len(unique), sources=list(unique.values()),
        events=events, admission_summary=summaries, portfolios=portfolios)
    if args.live_observation:
        output["live_cost_observation"] = json.loads(args.live_observation.read_text())
    output["research_script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.output.mkdir(parents=True)
    (args.output/"comparison.json").write_text(json.dumps(output, ensure_ascii=False, allow_nan=False)+"\n")
    (args.output/"report.md").write_text(report(output))
    print("saved", args.output, "replays", replay_count, "sources", len(unique), flush=True)
    for row in summaries:
        if row["sample"] != "all":
            print(json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
