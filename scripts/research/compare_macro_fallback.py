"""Test a small trend fallback in the same cash account, after macro admission."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

from qount.research.binance_etf_leverage import replay
from qount.research.binance_macro_attack import CONTRACT_SIGNALS
from qount.research.binance_macro_liquidity import load_capacity_contexts
from qount.research.binance_macro_opportunities import cost_case, fixed_fill_metrics, trade_pnl_components
from qount.research.lines.simple_trend import candidate_clocks, simple_features, trend_rows
from qount.research.macro_depth_execution import DepthExitStress
from qount.research_data.archives import timestamp
from qount.research_data.bars import NY
from qount.strategies.macro_episodes import episode_confirmations
from compare_macro_trend_continuation import CACHE, OLD, RUNS, TAIL, extended_inputs
from study_macro_admission_and_simplicity import headline, verify


SUFFIX = "::fallback"
CASES = (("base", .0005, .0025, 0), ("double_cost", .001, .005, 0),
         ("exit50bp", .0005, .0025, .005), ("exit200bp", .0005, .0025, .02))


def simple_inputs(book, sources, download):
    old, rows = simple_features(OLD, CONTRACT_SIGNALS, "2026-10-15", 1)
    sources += rows
    signals = {}
    for symbol, ticker in CONTRACT_SIGNALS.items():
        daily = []
        for root, end in ((OLD, "2026-10-15"), (TAIL, "2026-10-22")):
            path = root/f"yahoo-{ticker}-20250101-{end}.json"
            data = json.loads(path.read_text())["chart"]["result"][0]
            for stamp, close in zip(data["timestamp"], data["indicators"]["adjclose"][0]["adjclose"]):
                date = dt.datetime.fromtimestamp(stamp, NY).date()
                available = int(dt.datetime.combine(date, dt.time(16), NY).timestamp())
                if (root == OLD and available < timestamp("2026-10-15")) or (
                        root == TAIL and timestamp("2026-10-15") <= available < timestamp("2026-10-22")):
                    daily.append(dict(available=available, date=date.isoformat(), close=close))
        signals[symbol] = trend_rows(daily, 1)
        assert [f for f in signals[symbol] if f["available"] < timestamp("2026-10-15")] == old[symbol]
    keys = set(candidate_clocks(book, signals))
    caps = {}
    for root in (CACHE/"binance_macro_liquidity_20261015", CACHE/"macro_simple_trend_minutes_20261017", TAIL/"minutes", TAIL/"fallback_minutes"):
        cached = [key for key in keys if (root/f"{key[0]}-trade-1m-{key[1]-960}-{key[1]+60}.json").exists()]
        extra, rows, _ = load_capacity_contexts(cached, root)
        for key, value in extra.items():
            if key in caps:
                assert caps[key] == value
            caps[key] = value
        sources += rows
    missing = keys-caps.keys()
    print("simple capacity clocks", len(keys), "missing", len(missing), flush=True)
    extra, rows, _ = load_capacity_contexts(missing, TAIL/"fallback_minutes", download=download)
    caps.update(extra)
    sources += rows
    assert keys <= caps.keys()
    gates = episode_confirmations(book, signals, "no_chase")
    for cutoff in ("2026-06-30", "2026-08-31", "2026-09-30"):
        now = timestamp(cutoff)
        prefix_book = {s: dict(d, trade=[b for b in d["trade"] if b.t <= now]) for s, d in book.items()}
        prefix_features = {s: [f for f in rows if f["available"] <= now] for s, rows in signals.items()}
        assert episode_confirmations(prefix_book, prefix_features, "no_chase") == {k: g for k, g in gates.items() if k[1] <= now}
    return signals, gates, caps


def combine(book, macro, simple, gates, simple_gates, caps, simple_caps, *, gross, macro_on=True):
    """Virtual keys label rules on identical contracts; replay still has ONE position.

    Two disjoint monotone rank bands implement lexicographic macro priority using
    the existing proposal loop. Every rejected macro proposal is exhausted before
    a fallback is considered. They are not two accounts or tradable instruments.
    """
    data, features = dict(book), {}
    confirmations, capacity = dict(gates), dict(caps)
    for symbol in book:
        features[symbol] = [dict(f, rank_tactical=2+math.atan(f["rank_tactical"])/math.pi,
            entry_tactical=macro_on and f["entry_tactical"]) for f in macro[symbol]]
        virtual = symbol+SUFFIX
        data[virtual] = book[symbol]
        features[virtual] = [dict(f, rank_tactical=math.atan(f["rank_tactical"])/math.pi,
            entry_tactical=gross > 0 and f["entry_tactical"], gross_target=gross or 1) for f in simple[symbol]]
    confirmations.update({(s+SUFFIX, t): g for (s, t), g in simple_gates.items()})
    capacity.update({(s+SUFFIX, t): c for (s, t), c in simple_caps.items()})
    for key, cap in capacity.items():
        assert key[1]-120 <= cap["asof"] <= key[1]-60
    return data, features, confirmations, capacity


def attribution(control, candidate, fee, slip, shock=0):
    key = lambda t: (t["symbol"], t["entry_time"])
    old = {key(t): t for t in control["trades"]}
    new = {key(t): t for t in candidate["trades"] if not t["symbol"].endswith(SUFFIX)}
    fallback = [t for t in candidate["trades"] if t["symbol"].endswith(SUFFIX)]
    common = []
    for k in sorted(old.keys() & new.keys()):
        a, b = old[k], new[k]
        frozen = (b["net_pnl"]/b["quantity"]-a["net_pnl"]/a["quantity"])*a["quantity"]
        common.append(dict(symbol=k[0], time=k[1], frozen_exit_delta=frozen,
                           size_delta=b["net_pnl"]-a["net_pnl"]-frozen))
    decisions = {r["time"]: r for r in candidate.get("decisions", [])}
    missed = [dict(trade=old[k], decision=decisions.get(k[1]), occupied_by=[t["symbol"] for t in fallback
        if t["entry_time"] <= k[1] < t["exit_time"]]) for k in sorted(old.keys()-new.keys())]
    added = [new[k] for k in sorted(new.keys()-old.keys())]
    delta = sum(t["net_pnl"] for t in fallback)+sum(t["net_pnl"] for t in added)-sum(r["trade"]["net_pnl"] for r in missed)
    delta += sum(r["frozen_exit_delta"]+r["size_delta"] for r in common)
    assert abs(delta-(candidate["summary"]["final_equity"]-control["summary"]["final_equity"])) < 1e-8
    components = Counter()
    for trade in fallback:
        parts = trade_pnl_components(trade, fee=fee, slip=slip)
        # The shared decomposition knows ordinary slip only. Attribute the
        # separate uniform exit shock to execution rather than price alpha.
        extra = trade["quantity"]*trade["exit_price"]/(1-slip)*shock/(1-shock)
        parts["raw_price_pnl"] += extra
        parts["slippage_cost"] += extra
        components.update(parts)
    return dict(fallback_trades=len(fallback), fallback_pnl=sum(t["net_pnl"] for t in fallback),
        fallback_by_symbol={s.removesuffix(SUFFIX): sum(t["net_pnl"] for t in fallback if t["symbol"] == s)
                            for s in sorted({t["symbol"] for t in fallback})},
        fallback_components=dict(components), common=common, missed=missed, added=added, total_delta=delta)


def report(out):
    lines = ["# 宏观策略优先、低敞口趋势候补", "",
        "固定假设：当原宏观候选均不能入场时，SMA120＋20日正动量＋不追涨是否能补充净收益。",
        "候补上限0.5x/1x，原宏观20x、统一25%压力预算；共用单仓、现金与资金费，不把两条单跑曲线相加。",
        "先穷尽原宏观候选的成本/容量/风险准入，再考虑候补；在持候补不会强制让位，所有占仓损失计入。候补仍7天到期、原2ATR止损和2R移动止损。",
        "2026-04-07至2026-10-22（不含），8个原生合约及原ETF代理；本金15.27112826/30/100 USDT，现金基准0%。",
        "基础单边5bp手续费＋25bp滑点＋真实历史资金费；双成本10/50bp且不利常规资金费加倍；退出冲击额外50/200bp，不改变入场准入。现行档位历史套用。", "",
        "|本金|成本情景|规则|净收益|小时MDD|交易数|候补笔数|候补净损益|截尾损益|",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|"]
    for r in out["portfolios"]:
        h, a = r["headline"], r.get("attribution", {})
        lines.append(f"|{r['capital']:.4f}|{r['scenario']}|{r['profile']}|{h['net_return']:.2%}|{h['max_drawdown']:.2%}|{h['trade_count']}|{a.get('fallback_trades', 0)}|{a.get('fallback_pnl', 0):+.5f}|{h['censored_pnl']:+.5f}|")
    lines += ["", "## 主要账户路径归因", "",
        "共同入场用原数量区分退出与数量变化；遗漏、额外宏观机会和候补贡献单列，保留亏损与截尾。", ""]
    for r in out["portfolios"]:
        if r["capital"] == out["parameters"]["capital"] and r["scenario"] == "base" and r["profile"].startswith("fallback_"):
            a = r["attribution"]
            lines += [f"### {r['profile']}", "", f"候补逐标的净损益：{json.dumps(a['fallback_by_symbol'], ensure_ascii=False)}。",
                f"候补损益拆分：{json.dumps(a['fallback_components'], ensure_ascii=False)}。",
                f"原宏观缺失{len(a['missed'])}笔、额外{len(a['added'])}笔；候选总增量{a['total_delta']:+.6f} USDT。", ""]
            for missed in a["missed"]:
                t, decision = missed["trade"], missed["decision"]
                lines.append(f"- 原{t['symbol']} / {dt.datetime.fromtimestamp(t['entry_time'], dt.timezone.utc).date()} / 损益{t['net_pnl']:+.5f}：当时决策{json.dumps(decision, ensure_ascii=False)}。")
            lines.append("")
    lines += ["## 固定基础成交路径的双成本重估", "",
        "保持各规则基础场景的实际数量和进出时点，仅将手续费、滑点及不利常规资金费加倍。固定数量损益除以初始本金只作归因，不重新执行成本门、止损、风险预算或现金约束，不能当作可执行账户收益。", "",
        "|规则|固定路径双成本损益|损益/初始本金|", "|---|---:|---:|"]
    for r in out["portfolios"]:
        if r["capital"] == out["parameters"]["capital"] and r["scenario"] == "base":
            lines.append(f"|{r['profile']}|{r['frozen_path_double_cost_pnl']:+.5f}|{r['frozen_path_double_cost_pnl']/r['capital']:.2%}|")
    lines += ["## 共同剔除CL的脆弱性诊断", "", "所有规则都关闭CL新仓，重新定仓和选择机会；不作为可交易筛选规则。", "",
        "|成本|规则|收益|小时MDD|候补净损益|", "|---|---|---:|---:|---:|"]
    for r in out["omissions"]:
        lines.append(f"|{r['scenario']}|{r['profile']}|{r['headline']['net_return']:.2%}|{r['headline']['max_drawdown']:.2%}|{r['attribution']['fallback_pnl']:+.5f}|")
    lines += ["", "## 同一时点退出并换仓：理想化诊断", "",
        "观察到候补恰在宏观入场窗口退出后，使用已有exit_handover路由做事后机制诊断。允许即时退出并换到另一键，不强制打断仍在持有的候补。",
        "全部沿用小时开盘即时成交假设；不能表示真实先平仓确认、再提交IOC的延迟链路。退出延迟压力模型明确拒绝此路由，本实验保留该保护。", "",
        "|成本|剔除CL|规则|收益|小时MDD|交易数|", "|---|---|---|---:|---:|---:|"]
    for r in out["handover_diagnostics"]:
        h = r["headline"]
        lines.append(f"|{r['scenario']}|{r['omit_cl']}|{r['profile']}|{h['net_return']:.2%}|{h['max_drawdown']:.2%}|{h['trade_count']}|")
    lines += ["", "## 研究裁决", "",
        "本窗不支持将该候补并入生产：0.5x降低主要账户回撤但牺牲收益；1x仅小幅增收却放大回撤，统一退出冲击和共同剔除CL后都缺少稳定增量。",
        "双成本的正收益伴随候补只剩CL，以及末笔截尾，不证明同路径成本稳健；固定基础路径重估未产生相对原宏观的优势。",
        "即时换仓的0.5x结果较高，但来自事后理想化路由诊断，回撤更高、剔除CL后仍落后原策略；真实先平后开延迟和条件成交未获验证。保持现行25%预算和规则。"]
    lines += ["", "## 验证和解释边界", "",
        f"实际{out['replay_count']}次回放；原控制基础/双成本/退出冲击逐笔与净值精确复现，禁用候补的虚拟标的控制也精确复现。",
        f"{out['priority_audits']}个主要账户候补入场按其当时权益重新检查原宏观准入，均无可执行原宏观订单；未用未来原策略空仓区间筛选。",
        "旧日线/简单特征前缀不变；3个截断时点重建不追涨门一致；逐笔核对现金、费用、资金费、信息时点、风险和候补敞口上限。",
        "退出压力只施加所列统一冲击，unknown_extra_slip显式为0，避免给候补止损额外叠加默认2%未知盘口损失。初次结果保留于macro_fallback_20261022，其中冲击情景的候补止损含该默认2%，不能与本表相混；基础/双成本不受影响。",
        "全部已消费历史，非独立OOS；小时止损和成交量代理不能认证真实IOC、原生止损或历史盘口成交。生产信号、配置、权限与调度不变。", "",
        "复现：`PYTHONPATH=src ./.venv/bin/python scripts/research/compare_macro_fallback.py --output <新目录>`；首次缺公开分钟缓存可加`--download-minutes`。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--download-minutes", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new output; retain previous results")
    _, (book, macro, gates, caps), sources, revisions = extended_inputs()
    simple, simple_gates, simple_caps = simple_inputs(book, sources, args.download_minutes)
    control_path = RUNS/"macro_trend_continuation_20261022/comparison.json"
    controls = {r["scenario"]: r for r in json.loads(control_path.read_text())["portfolios"]
                if r["window"] == "extended" and r["profile"] == "control"}
    venue_path = RUNS/"macro_leverage_cash_review_20261019/venue_snapshot.json"
    venue = json.loads(venue_path.read_text())
    for symbol, d in book.items():
        d["rule"] = dict(d["rule"], leverage_brackets=venue["symbols"][symbol]["brackets"])
    parameters = controls["base"]["parameters"]
    bundles = {name: combine(book, macro, simple, gates, simple_gates, caps, simple_caps, gross=gross, macro_on=on)
               for name, gross, on in (("control", 0, True), ("fallback_half", .5, True),
                                      ("fallback_one", 1, True), ("trend_alone", 1, False))}
    portfolios, omissions, checks, handovers = [], [], [], []
    count = audits = 0

    def run(bundle, scenario, p, shock=0, confirmations=None):
        nonlocal count
        data, features, g, c = bundle
        data = cost_case(data, scenario)
        result = replay(data, features, entry_confirmations=g if confirmations is None else confirmations,
            entry_liquidity_caps=c, exit_execution_model=DepthExitStress({}, use_depth=False, unknown_extra_slip=0, all_extra_slip=shock) if shock else None, trace=True, **p)
        verify(result, data, p)
        for t in result["trades"]:
            if t["symbol"].endswith(SUFFIX):
                assert t["notional_usdt"] <= t["gross_target"]*t["equity_before_entry"]+1e-8
                assert t["gross_target"] in (.5, 1) and t["max_hold_hours"] == 168
        assert all(a["exit_time"] <= b["entry_time"] for a, b in zip(result["trades"], result["trades"][1:]))
        count += 1
        return result

    for capital in (parameters["capital"], 30., 100.):
        for scenario, fee, slip, shock in CASES if capital == parameters["capital"] else CASES[:2]:
            p = dict(parameters, capital=capital, fee=fee, slip=slip)
            original = replay(cost_case(book, scenario), macro, entry_confirmations=gates, entry_liquidity_caps=caps,
                exit_execution_model=DepthExitStress({}, use_depth=False, unknown_extra_slip=0, all_extra_slip=shock) if shock else None, **p)
            verify(original, cost_case(book, scenario), p)
            count += 1
            if capital == parameters["capital"] and scenario in controls:
                assert original["trades"] == controls[scenario]["trades"] and original["curve"] == controls[scenario]["curve"]
                checks.append(scenario+": retained control exact")
            for profile, bundle in bundles.items():
                result = run(bundle, scenario, p, shock)
                if profile == "control":
                    assert result["trades"] == original["trades"] and result["curve"] == original["curve"]
                a = attribution(original, result, fee, slip, shock)
                row = dict(capital=capital, scenario=scenario, profile=profile, headline=headline(result),
                    attribution=a, trades=result["trades"], curve=result["curve"])
                if scenario == "base":
                    row["frozen_path_double_cost_pnl"] = sum(fixed_fill_metrics(t, t,
                        book[t["symbol"].removesuffix(SUFFIX)]["funding"], fee=fee, slip=slip)["fixed_path_double_cost_pnl"]
                        for t in result["trades"])
                portfolios.append(row)
                print(capital, scenario, profile, json.dumps({k: row['headline'][k] for k in ('net_return','max_drawdown','trade_count')}), "fallback", a["fallback_pnl"], flush=True)
                if capital == parameters["capital"] and profile.startswith("fallback_"):
                    for t in result["trades"]:
                        if not t["symbol"].endswith(SUFFIX):
                            continue
                        only_now = {k: dict(g, eligible=g["eligible"] and k[1] == t["entry_time"]) for k, g in bundles["control"][2].items()}
                        check = run(bundles["control"], scenario, dict(p, capital=t["equity_before_entry"], entry_end_exclusive=t["entry_time"]+1), shock, only_now)
                        assert not check["trades"], "fallback selected while a macro order was executable"
                        audits += 1
    for scenario, fee, slip, shock in CASES[:2]:
        p = dict(parameters, fee=fee, slip=slip)
        results = {}
        for profile, bundle in bundles.items():
            if profile == "trend_alone":
                continue
            data, features, g, c = bundle
            no_cl = {k: dict(v, eligible=False) if k[0].removesuffix(SUFFIX) == "CLUSDT" else v for k, v in g.items()}
            results[profile] = run(bundle, scenario, p, shock, no_cl)
        for profile, result in results.items():
            omissions.append(dict(scenario=scenario, profile=profile, headline=headline(result), trades=result["trades"],
                attribution=attribution(results["control"], result, fee, slip)))
    for scenario, fee, slip, _ in CASES[:2]:
        p = dict(parameters, fee=fee, slip=slip, routing="exit_handover")
        for omit_cl in (False, True):
            for profile, bundle in bundles.items():
                if profile == "trend_alone":
                    continue
                g = {k: dict(v, eligible=False) if omit_cl and k[0].removesuffix(SUFFIX) == "CLUSDT" else v for k, v in bundle[2].items()}
                result = run(bundle, scenario, p, confirmations=g)
                handovers.append(dict(scenario=scenario, omit_cl=omit_cl, profile=profile,
                                      headline=headline(result), trades=result["trades"]))
    for path in (control_path, venue_path):
        sources.append(dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    unique = {s["path"]: s for s in sources}
    for source in unique.values():
        assert hashlib.sha256(Path(source["path"]).read_bytes()).hexdigest() == source["sha256"]
    out = dict(research_only=True, orders_authorized=False, independent_oos=False,
        hypothesis="Small fixed trend fallback after exhaustive macro admission can earn net returns without harmful occupancy.",
        sample_start="2026-04-07", sample_end_exclusive="2026-10-22", parameters=parameters,
        replay_count=count, priority_audits=audits, control_checks=checks, sources=list(unique.values()),
        search_scope="Two fixed fallback gross caps .5/1; existing instantaneous exit_handover routing diagnostic after viewing occupancy, six exploratory runs repeated here; no parameter-window or asset search.",
        uniform_exit_stress_unknown_extra_slip=0,
        overlap_adjusted_price_revisions=revisions, portfolios=portfolios, omissions=omissions, handover_diagnostics=handovers,
        code=[dict(path=str(p), sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in
              (Path(__file__), Path("src/qount/research/binance_etf_leverage.py"), Path("src/qount/research/lines/simple_trend.py"))])
    args.output.mkdir(parents=True)
    (args.output/"comparison.json").write_text(json.dumps(out, ensure_ascii=False, allow_nan=False)+"\n")
    (args.output/"report.md").write_text(report(out))
    print("saved", args.output, "replays", count, "priority audits", audits, flush=True)


if __name__ == "__main__":
    main()
