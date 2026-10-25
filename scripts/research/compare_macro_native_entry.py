"""Fixed native trend entry filters, preserving mean-reversion as an ablation."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from qount.research.binance_etf_leverage import replay
from qount.research.binance_macro_opportunities import cost_case
from qount.research.binance_macro_signals import contract_confirmations
from qount.research.macro_depth_execution import DepthExitStress
from qount.research_data.archives import timestamp
from compare_macro_trend_continuation import RUNS, extended_inputs
from study_macro_admission_and_simplicity import distribution, economics, headline, verify


PROFILES = {"control": (None, None), "trend_above20": ("above20", "trend"),
            "trend_aligned20_50": ("aligned20_50", "trend"),
            "all_above20": ("above20", "all"), "all_aligned20_50": ("aligned20_50", "all"),
            "trend_half_risk": ("above20", "risk_half"),
            "trend_half_any": (None, "trend_half_any"), "risk12_5": (None, "global_half")}
CASES = (("base", .0005, .0025, 0), ("double_cost", .001, .005, 0),
         ("exit50bp", .0005, .0025, .005), ("exit200bp", .0005, .0025, .02))


def filtered_gates(gates, confirmations, mode, scope):
    if mode is None or scope == "risk_half":
        return gates
    result = {}
    for key, gate in gates.items():
        applies = scope == "all" or gate["setup"] != "mean_reversion"
        native = confirmations[mode].get(key)
        allowed = not applies or native is not None and native["eligible"]
        result[key] = dict(gate, eligible=gate["eligible"] and allowed,
                           reason=gate["reason"] if allowed or not gate["eligible"] else "native_"+mode)
        assert not result[key]["eligible"] or gate["eligible"]
    return result


def account_attribution(control, candidate):
    key = lambda t: (t["symbol"], t["entry_time"])
    a, b = ({key(t): t for t in r["trades"]} for r in (control, candidate))
    common = []
    for k in sorted(a.keys() & b.keys()):
        old, new = a[k], b[k]
        exit_delta = (new["net_pnl"]/new["quantity"]-old["net_pnl"]/old["quantity"])*old["quantity"]
        common.append(dict(symbol=k[0], time=k[1], frozen_exit_delta=exit_delta,
                           size_delta=new["net_pnl"]-old["net_pnl"]-exit_delta))
    removed = [a[k] for k in sorted(a.keys()-b.keys())]
    added = [b[k] for k in sorted(b.keys()-a.keys())]
    delta = sum(c["frozen_exit_delta"]+c["size_delta"] for c in common)-sum(t["net_pnl"] for t in removed)+sum(t["net_pnl"] for t in added)
    assert math.isclose(delta, candidate["summary"]["final_equity"]-control["summary"]["final_equity"], abs_tol=1e-8)
    return dict(common=common, removed=removed, added=added, total_delta=delta)


def report(out):
    lines = ["# 原生趋势确认：只过滤趋势入场是否更好", "",
        "假设：ETF突破/回撤与原生合约短期走势背离时，额外确认可减少亏损；均值回归不强制要求顺势。",
        "固定两个已有规则：above20=最近完成小时收盘>小时EMA20；aligned20_50还要求EMA20>EMA50。两种适用范围：仅突破/回撤、所有信号；共4个候选，无窗口或阈值搜索。",
        "观察硬过滤误伤盈利回撤后，追加单一机制对照trend_half_risk：趋势入场未站上EMA20时，压力预算25%→12.5%，保留原成本门和容量；强趋势及所有MR仍25%。未搜索折扣倍率。原生输入缺失时拒绝趋势入场。",
        "再补两个简单预算对照：trend_half_any对所有趋势入场一律12.5%、MR仍25%；risk12_5全策略及资金费复核统一12.5%。这两项在看到条件减仓改善后加入，用于检验原生均线的信息增量，不能作为预先未见实验。",
        "15日旧实验已发现全信号确认损害收益；当时为7月30日至10月15日、20%预算/7天统一期限等旧设置。本次只判断当前25%预算、不追涨、MR1ATR、7/21天与续期规则，不把共用历史当新证据。",
        "2026-04-07至2026-10-22（右端不含），8个原生合约及原ETF信号，本金15.27112826 USDT为主，30/100 USDT与1x总敞口为敏感性；现金基准0%。",
        "基础每边手续费5bp、滑点25bp及实际历史资金费；双成本10/50bp且不利常规资金费加倍；额外退出冲击统一50/200bp，unknown_extra_slip=0，不额外叠加2%止损冲击。",
        "保留原成本/容量门、排序、单仓、档位、止损、持有期限与资金费续期；折半预算是上限、不会强制将容量已约束的小仓砍半。原生确认只用入场前已完成小时，不改变原不追涨episode锚点。", "",
        "|本金|总敞口上限|成本|规则|收益|小时MDD|小时内悲观回撤界|已闭合/总笔数|截尾损益|",
        "|---:|---:|---|---|---:|---:|---:|---:|---:|"]
    for r in out["portfolios"]:
        h = r["headline"]
        lines.append(f"|{r['capital']:.4f}|{r['gross_cap']}|{r['scenario']}|{r['profile']}|{h['net_return']:.2%}|{h['max_drawdown']:.2%}|{h['intrahour_drawdown_bound']:.2%}|{h['closed_count']}/{h['trade_count']}|{h['censored_pnl']:+.5f}|")
    lines += ["", "## 同机会单位名义收益", "",
        "每标的按时间先选21天不重叠机会，要求原setup最长持有期成熟；用原控制独立开仓并保留所有拒绝，只把可闭合结果按确认放行/过滤分组。每组都是被选择的历史样本，跨标的可相关，不是配对因果或独立样本。", "",
        "|成本|规则|确认|机会数|闭合/截尾/未成交|单位名义均值|中位数|去掉最好后均值|",
        "|---|---|---|---:|---|---:|---:|---:|"]
    pct = lambda n: "—" if n is None else f"{n:.2%}"
    for r in out["opportunity_summary"]:
        d = r["distribution"]
        lines.append(f"|{r['scenario']}|{r['profile']}|{r['admission']}|{d['opportunities']}|{d['closed']}/{d['censored']}/{d['unresolved']}|{pct(d['mean_net'])}|{pct(d['median_net'])}|{pct(d['mean_without_best'])}|")
    lines += ["", "## 原机会共同剔除的账户重跑", "",
        "同时删除原策略两大盈利episode，或原亏损CL突破episode；历史结果选取仅诊断脆弱性，不作为可交易条件。两组都重选机会、重新定仓。", "",
        "|剔除|成本|规则|收益|小时MDD|截尾损益|", "|---|---|---|---:|---:|---:|"]
    for r in out["omissions"]:
        h = r["headline"]
        lines.append(f"|{r['omission']}|{r['scenario']}|{r['profile']}|{h['net_return']:.2%}|{h['max_drawdown']:.2%}|{h['censored_pnl']:+.5f}|")
    lines += ["", "## 基础账户的路径归因", ""]
    for r in out["portfolios"]:
        if r["capital"] != out["parameters"]["capital"] or r["gross_cap"] != 20 or r["scenario"] != "base" or r["profile"] == "control":
            continue
        a = r["attribution"]
        lines += [f"### {r['profile']}", "",
            f"总增量{a['total_delta']:+.6f} USDT；共同入场退出差{sum(c['frozen_exit_delta'] for c in a['common']):+.6f}，数量差{sum(c['size_delta'] for c in a['common']):+.6f}。",
            f"缺失原机会：{json.dumps([dict(symbol=t['symbol'], time=t['entry_time'], pnl=t['net_pnl']) for t in a['removed']], ensure_ascii=False)}。",
            f"新增机会：{json.dumps([dict(symbol=t['symbol'], time=t['entry_time'], pnl=t['net_pnl']) for t in a['added']], ensure_ascii=False)}。", ""]
    lines += ["## 研究裁决", "",
        "保留更简单的trend_half_any为离线研究候选：突破/回撤初始压力预算12.5%，MR仍25%，沿原期限/成本/容量/续期规则；不增加原生均线门。主账户基础收益33.16%/小时MDD7.72%，原策略32.56%/12.18%。",
        "条件减仓为33.17%/7.72%，仅比简单预算多0.001939 USDT，来自一笔XLE数量网格差异；30/100USDT两者相同，1x总敞口下两者与原策略相同。当前缺少均线信息增量证据。",
        "简单趋势预算的7个入场/退出均保留：CL突破0.47→0.23，少亏0.093733USDT；一笔XLE回撤0.42→0.41，少赚0.001939USDT；其他数量不变。风险预算减半不等于仓位机械减半，MR预算保持25%。",
        "共同删除该CL episode后，控制与两个减仓候选基础收益/MDD完全相同；共同删除原两大赢家后，简单预算收益9.49%低于控制10.97%，虽回撤较低。不能据此证明跨机会稳定增收。",
        "全策略统一12.5%使主账户基础收益仅13.48%，同时改变MR定仓及续期路径；不能把趋势预算候选解释成所有信号一律减仓。双成本下简单趋势预算仍与控制相同为-3.02%，成本敏感问题未解决。",
        "以上机制是在已观察历史上顺序研究所得，不认定独立OOS或生产资格。本轮不替换实盘规则。", "",
        "## 验证和限制", "",
        f"{out['replay_count']}次回放；4种成本控制的成交及净值与上一轮精确复现；逐笔现金、费用、资金费、预算、信息时点核对。3个截断时点重算原生确认一致，原episode锚点未重置。",
        "全部已消费历史，候选无独立OOS资格；小时止损、现行档位历史套用、分钟容量和成交假设不能认证真实执行。本轮不改生产信号、配置、权限或调度。", "",
        "复现：`PYTHONPATH=src ./.venv/bin/python scripts/research/compare_macro_native_entry.py --output <新目录>`。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new output; retain prior evidence")
    _, (book, signals, gates, caps), sources, revisions = extended_inputs()
    control_path = RUNS/"macro_fallback_final_20261022/comparison.json"
    saved = json.loads(control_path.read_text())
    parameters = saved["parameters"]
    controls = {r["scenario"]: r for r in saved["portfolios"] if r["capital"] == parameters["capital"] and r["profile"] == "control"}
    venue_path = RUNS/"macro_leverage_cash_review_20261019/venue_snapshot.json"
    venue = json.loads(venue_path.read_text())
    for s, d in book.items():
        d["rule"] = dict(d["rule"], leverage_brackets=venue["symbols"][s]["brackets"])
    native = {mode: contract_confirmations(book, list(gates), mode) for mode in ("above20", "aligned20_50")}
    prefix_checks = []
    for date in ("2026-06-30", "2026-08-31", "2026-09-30"):
        cutoff = timestamp(date)
        prefix = {s: dict(d, trade=[b for b in d["trade"] if b.t <= cutoff]) for s, d in book.items()}
        for mode in native:
            assert contract_confirmations(prefix, [k for k in gates if k[1] <= cutoff], mode) == {k: v for k, v in native[mode].items() if k[1] <= cutoff}
        prefix_checks.append(date)
    profile_gates = {name: filtered_gates(gates, native, mode, scope) for name, (mode, scope) in PROFILES.items()}
    risk_controls, trend_controls = {}, {}
    for key, gate in gates.items():
        if gate["setup"] == "mean_reversion":
            risk_controls[key] = dict(asof=key[1], multiplier=1)
        elif key in native["above20"]:
            context = native["above20"][key]
            risk_controls[key] = dict(asof=context["asof"], multiplier=1 if context["eligible"] else .5)
        trend_controls[key] = dict(asof=key[1], multiplier=1 if gate["setup"] == "mean_reversion" else .5)
    for name, rows in profile_gates.items():
        if name.startswith("trend_"):
            assert all(g == gates[k] for k, g in rows.items() if g["setup"] == "mean_reversion")
    portfolios, events, omissions, checks = [], [], [], []
    count = 0

    def run(profile, scenario, p, shock=0, confirmations=None, **extra):
        nonlocal count
        if profile == "risk12_5":
            p = dict(p, risk_fraction=.125)
        data = cost_case(book, scenario)
        result = replay(data, signals, entry_confirmations=profile_gates[profile] if confirmations is None else confirmations,
            entry_liquidity_caps=caps, exit_execution_model=DepthExitStress({}, use_depth=False, unknown_extra_slip=0, all_extra_slip=shock) if shock else None,
            entry_risk_controls=risk_controls if profile == "trend_half_risk" else trend_controls if profile == "trend_half_any" else None,
            **p, **extra)
        verify(result, data, p)
        for t in result["trades"]:
            if "entry_risk_control" in t:
                assert t["tactical_setup"] != "mean_reversion"
                assert t["risk_budget_usdt"] <= .125*t["equity_before_entry"]+1e-8
        count += 1
        return result

    primary = {}
    for capital, gross in ((parameters["capital"], 20), (parameters["capital"], 1), (30., 20), (100., 20)):
        for scenario, fee, slip, shock in CASES if capital == parameters["capital"] and gross == 20 else CASES[:2]:
            p = dict(parameters, capital=capital, gross_cap=gross, fee=fee, slip=slip)
            baseline = None
            for profile in PROFILES:
                result = run(profile, scenario, p, shock)
                if profile == "control":
                    baseline = result
                if capital == parameters["capital"] and gross == 20:
                    primary[profile, scenario] = result
                    if profile == "control":
                        assert result["trades"] == controls[scenario]["trades"] and result["curve"] == controls[scenario]["curve"]
                        checks.append(scenario+": exact retained control")
                h = headline(result)
                portfolios.append(dict(profile=profile, scenario=scenario, capital=capital, gross_cap=gross,
                    effective_risk_fraction=.125 if profile == "risk12_5" else parameters["risk_fraction"],
                    headline=h, trades=result["trades"], curve=result["curve"], attribution=account_attribution(baseline, result)))
                print(capital, gross, scenario, profile, h["net_return"], h["max_drawdown"], h["trade_count"], flush=True)
    eligible = sorted((k for k, g in gates.items() if g["eligible"]), key=lambda k: (k[1], k[0]))
    nonoverlap, last_end = set(), {}
    for s, now in eligible:
        if now >= last_end.get(s, 0):
            nonoverlap.add((s, now))
            last_end[s] = now+21*86400
    for scenario, fee, slip, _ in CASES[:2]:
        p = dict(parameters, fee=fee, slip=slip)
        for symbol, now in eligible:
            result = run("control", scenario, p, forced_entry=dict(symbol=symbol, time=now, engine="tactical"), entry_end_exclusive=now+1)
            assert len(result["trades"]) <= 1
            t = result["trades"][0] if result["trades"] else None
            horizon = p["tactical_setup_policies"][gates[symbol, now]["setup"]]["max_hold_hours"]
            events.append(dict(symbol=symbol, time=now, setup=gates[symbol, now]["setup"], scenario=scenario,
                nonoverlap=(symbol, now) in nonoverlap, mature=now+horizon*3600 <= book[symbol]["trade"][-1].t+3600,
                allowed={name: g[symbol, now]["eligible"] for name, g in profile_gates.items()},
                native={mode: c.get((symbol, now)) for mode, c in native.items()}, trade=t,
                economic=economics(t, p), rejections=result["summary"]["rejections"]))
    opportunity_summary = []
    for scenario, *_ in CASES[:2]:
        for profile in PROFILES:
            if profile in ("trend_half_risk", "trend_half_any", "risk12_5"):
                continue  # The shadow trades above isolate admission, not size.
            for allowed in (True, False):
                selected = [r for r in events if r["scenario"] == scenario and r["nonoverlap"] and r["mature"] and r["allowed"][profile] == allowed]
                opportunity_summary.append(dict(scenario=scenario, profile=profile, admission="pass" if allowed else "filtered", distribution=distribution(selected)))
    base = primary["control", "base"]["trades"]
    top = sorted((t for t in base if t["net_pnl"] > 0), key=lambda t: -t["net_pnl"])[:2]
    patterns = {"missing_top_two": {(t["symbol"], gates[t["symbol"], t["entry_time"]]["anchor_time"]) for t in top},
        "missing_losing_trend_CL": {(t["symbol"], gates[t["symbol"], t["entry_time"]]["anchor_time"])
            for t in base if t["symbol"] == "CLUSDT" and t["tactical_setup"] != "mean_reversion" and t["net_pnl"] < 0}}
    for omission, omitted in patterns.items():
        for scenario, fee, slip, shock in (CASES[0], CASES[2]):
            p = dict(parameters, fee=fee, slip=slip)
            for profile in PROFILES:
                altered = {k: dict(g, eligible=False) if (k[0], g["anchor_time"]) in omitted else g for k, g in profile_gates[profile].items()}
                result = run(profile, scenario, p, shock, confirmations=altered)
                assert all((t["symbol"], gates[t["symbol"], t["entry_time"]]["anchor_time"]) not in omitted for t in result["trades"])
                omissions.append(dict(omission=omission, profile=profile, scenario=scenario, headline=headline(result), trades=result["trades"]))
    for path in (control_path, venue_path, RUNS/"binance_macro_signal_optimization_20261015_final/summary.json"):
        sources.append(dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    unique = {s["path"]: s for s in sources}
    for s in unique.values():
        assert hashlib.sha256(Path(s["path"]).read_bytes()).hexdigest() == s["sha256"]
    out = dict(research_only=True, orders_authorized=False, independent_oos=False,
        sample_start="2026-04-07", sample_end_exclusive="2026-10-22", parameters=parameters, profiles=PROFILES,
        hypothesis="Native trend confirmation may improve trend entries without imposing a trend-following condition on mean-reversion.",
        replay_count=count, control_checks=checks, prefix_checks=prefix_checks, overlap_adjusted_price_revisions=revisions,
        native_confirmations=[dict(symbol=k[0], time=k[1], **r) for k, r in native["aligned20_50"].items()],
        risk_controls=[dict(symbol=k[0], time=k[1], **r) for k, r in risk_controls.items()],
        search_scope="Four fixed hard filters, followed by one adaptive .5 trend risk multiplier after hard-filter false positives, then two simple budget controls (all trends half / global .125) after observing conditional reduction; no window, asset or multiplier grid search. Consumed history throughout.",
        portfolios=portfolios, events=events, opportunity_summary=opportunity_summary, omissions=omissions, sources=list(unique.values()),
        code=[dict(path=str(p), sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in
            (Path(__file__), Path("src/qount/research/binance_macro_signals.py"), Path("src/qount/research/binance_etf_leverage.py"))])
    args.output.mkdir(parents=True)
    (args.output/"comparison.json").write_text(json.dumps(out, ensure_ascii=False, allow_nan=False)+"\n")
    (args.output/"report.md").write_text(report(out))
    print("saved", args.output, "replays", count, flush=True)


if __name__ == "__main__":
    main()
