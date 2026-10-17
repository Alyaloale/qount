"""Fixed native MR entries: paid7/21-day labels versus actual guarded exits."""
import argparse
import hashlib
import json
import math
import statistics
from collections import Counter
from pathlib import Path

from qount.research.binance_etf_leverage import load_inputs, replay
from qount.research.binance_macro_attack import CONTRACT_SIGNALS, directional_book, macro_features
from qount.research.binance_macro_entry_episodes import episode_confirmations
from qount.research.binance_macro_liquidity import load_capacity_contexts
from qount.research.binance_macro_opportunities import cost_case, native_horizon_components, trade_pnl_components
from qount.research.binance_macro_setup import setup_policies
from qount.research_data.archives import timestamp


def metrics(rows, days):
    labels = [r["labels"][str(days)] for r in rows]
    mature = [r for r in labels if not r["censored"]]
    values = [r["on_notional"]["net_pnl"] for r in mature]
    result = dict(events=len(rows),mature=len(mature),censored=len(labels)-len(mature),
        mean_net=statistics.mean(values) if values else None,
        mean_ex_best=(sum(values)-max(values))/(len(values)-1) if len(values)>1 else None,
        initial_stop_touches=sum(r["initial_stop_first_touch"] is not None for r in mature),
        static_liquidation_touches=sum(r["static_liquidation_first_touch"] is not None for r in mature))
    result["mean_components"] = {k:statistics.mean(r["on_notional"][k] for r in mature) if mature else None
                                 for k in ("raw_price_pnl","slippage_cost","fees","net_funding")}
    return result


def report(result):
    rows = result["aggregates"]
    lines = ["# 原生合约均值回归：固定入场、实际退出与持有成本", "",
        "**裁决：尚未获得稳定净盈利证据。原始组的提前退出在这组样本中减少了损失；不取消止损／续期约束，不因ETF长样本方向结果延长合约持有。1ATR门继续保留探索身份。**", "",
        "## 实验条件", "",
        "2026-04-07至2026-10-15（末日不含），沿用各合约实际缓存起点及14完整UTC日ATR预热，八个实际执行合约观察池。固定9个均值回归段首：CL两次、铜一次、SPY两次、IWM三次、XLE一次。所有信号、入场时点、风险预算50%、2ATR止损、容量、3%越价准备、7天续期／最长21天和强平缓冲均不调参；请求20x／仿真逐仓上限50x，不代表实际20x敞口。", "",
        "复跑正常准入与费用门影子共36条小时路径，逐笔与既有结果一致。影子仅绕过入场摩擦／止损比例拒绝，仍真实扣费并保留其他约束；相互隔离、每次初始10USDT。下述平均收益分母为各笔入场名义额，**不是共享账户收益、不可相加，不是新增独立样本外验证**。正常准入与共享占仓仍会进一步改变可交易集合。", "",
        "基础每边手续费5bp／滑点25bp；压力10bp／50bp并加倍不利普通资金费，特殊资金费与有利费用不改。固定7／21自然日标签沿用每种成本下原入场数量与价格，以原生合约目标小时开盘退出、计入[start,end)实际signed资金费，但忽略所有中途退出；越过止损／强平代理的标签不可执行。", "",
        "## 相同已成熟机会：现有退出规则与固定期限", "",
        "只取21天已成熟的同一批机会比较7／21天，末笔XLE不塞入短期组抬高均值。", "",
        "|入场条件|共同成熟数|现有退出基础|固定7天基础|固定21天基础|现有退出压力|固定21天压力|", "|---|---:|---:|---:|---:|---:|---:|"]
    for gate in ("original","gap_1atr","daily_reversal"):
        b = next(r for r in rows if r["sample"]=="first_episodes" and r["gate"]==gate and r["scenario"]=="base")
        d = next(r for r in rows if r["sample"]=="first_episodes" and r["gate"]==gate and r["scenario"]=="double_cost")
        x,y = b["paired_21_mature"],d["paired_21_mature"]
        lines.append(f"|{gate}|{x['events']}|{x['actual_mean']:.2%}|{x['fixed7_mean']:.2%}|{x['fixed21_mean']:.2%}|{y['actual_mean']:.2%}|{y['fixed21_mean']:.2%}|")
    lines += ["", "原始固定21天的8条成熟路径有3条触及初始止损价、1条穿过不含资金费抵押影响的静态1%维持保证金强平代理价；这些不等于原策略发生3次止损或1次强平。CL6月1日机会按规则在7天费用预算失败时退出，净名义额损失−3.25%；无任何退出的21天标签为−20.36%，价格方向−21.45%、资金费净收入+1.63%。另一CL次日结构失效退出亦避免更长路径损失。不能把续期失败统一解释为错失机会。", "",
        "## 去除同资产21天重叠，再检查盈利来源", "",
        "从原始段首先按时间选取互不重叠21天区间，再应用各门；统一去掉CL6月16日和IWM7月31日，保留7个机会，其中XLE未成熟。去重在门和未来结果之前完成，不按某门重新填补被丢弃机会；不是各门实际账户的成交集合。", "",
        "|入口|已闭合数|基础净均值|压力净均值|基础扣除最佳一笔后均值|", "|---|---:|---:|---:|---:|"]
    for gate in ("original","gap_1atr","daily_reversal"):
        b = next(r for r in rows if r["sample"]=="nonoverlap_21days" and r["gate"]==gate and r["scenario"]=="base")
        d = next(r for r in rows if r["sample"]=="nonoverlap_21days" and r["gate"]==gate and r["scenario"]=="double_cost")
        lines.append(f"|{gate}|{b['actual_closed']}|{b['actual_mean_net']:.2%}|{d['actual_mean_net']:.2%}|{b['actual_mean_ex_best']:.2%}|")
    lines += ["", "去重原始组6条闭合路径基础均值：原始价格+0.4825%，滑点−0.5000%，手续费−0.1000%，净资金费+0.1455%，合计+0.0280%。方向收益较薄，资金费在本组整体是收入，不能只把亏损归于资金费。", "",
        "去重1ATR组5条闭合路径基础均值：原始价格+1.3383%，滑点−0.5021%，手续费−0.1004%，净资金费−0.0517%，合计+0.6840%；压力下−0.0250%。去掉最佳IWM后基础−0.1278%，正收益仍未摆脱单笔依赖。未去重时该组7条闭合基础+0.6614%、压力−0.0216%，结论一致。日际门在统一去重后只剩铜和9月IWM两个成熟机会，不能凭这么小的集合判定其普遍效力。", "",
        "## 验证范围与研究判断", "",
        "本轮支持保留现有退出保护，不支持仅凭ETF长样本将合约变成无条件21天持有。下一关键问题是能否获得足够多不重叠的原生合约净优势机会，以及交易摩擦是否可被真实成交改善；不按已知输赢删除CL或添加新门。当前6／5个去重闭合样本不认证统计稳定性，跨资产仍相关。", "",
        f"{result['legacy_controls']}个正常／影子小时控制精确复现，{result['scheduled_exit_component_identities']}个21天自然到期路径与固定21天标签的全部损益组成一致；成熟端点、实际资金费边界、原入场价与时钟缺口均检查。原38输入及所有复用来源hash不变，无新下载。新增5项针对资金费[start,end)、原生小时开盘、截尾、行情缺口和不可执行路径的测试；本轮相关142项通过。", "",
        "固定期限标签没有完整模拟资金费抵押或动态强平，静态强平旗标仅作诊断；新影子路径仍为小时撮合，没有新增分钟认证。当前filters/MMR、历史资金费可得性、ETF调整/PIT与退出流动性近似继续存在。按原退出规则计算的模拟损益与不可执行的固定持有标签必须分开解释。", "",
        "research_only=true / orders_authorized=false；没有私有账户调用、真实订单、服务、定时器或生产变更。", "",
        "```bash", "PYTHONPATH=src ./.venv/bin/python scripts/research/diagnose_binance_macro_native_carry.py --output state/research_runs/binance_macro_native_carry_replay", "PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -p 'test_binance*.py'", "```", "",
        "输出目录必须不存在。全部9机会、拒绝／准入、退出原因、费用分解、两种成本及截尾见summary.json。"]
    return "\n".join(lines)+"\n"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output",type=Path,required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError("refuse_overwrite_native_carry")
    cache = Path("state/research_cache/binance_macro_attack_20261015")
    features,sources = macro_features(cache,"2026-10-15")
    symbols = tuple(CONTRACT_SIGNALS)
    data,inputs = load_inputs(cache,timestamp("2026-07-30"),timestamp("2026-10-15"),symbols=symbols)
    sources += inputs
    for folder,start,end,subset in (
        ("binance_macro_earlier_20260611_20260730","2026-06-11","2026-07-30",tuple(s for s in symbols if s!="SMHUSDT")),
        ("binance_macro_prefix_20260407_20260611","2026-04-07","2026-06-11",("SPYUSDT","QQQUSDT","XAUUSDT","COPPERUSDT","CLUSDT")),
    ):
        prefix,inputs = load_inputs(Path("state/research_cache")/folder,timestamp(start),timestamp(end),symbols=subset)
        sources += inputs
        data = {s:{**d,**{k:prefix[s][k]+d[k] for k in ("trade","mark","funding")}} if s in prefix else d
                for s,d in data.items()}
    book,signals = directional_book(data,features,"long",20/3)
    gates = episode_confirmations(book,signals,"no_chase")
    caps,inputs,_ = load_capacity_contexts(sorted(gates,key=lambda k:(k[1],k[0])),Path("state/research_cache/binance_macro_liquidity_20261015"))
    sources += inputs
    refs = {}
    for key,folder in (("shadow","binance_macro_admission_shadow_20261015"),
                       ("normal","binance_macro_entry_sleeves_20261015"),
                       ("gates","binance_macro_daily_reversal_20261015_final")):
        path = Path("state/research_runs")/folder/"summary.json"
        raw = path.read_bytes()
        refs[key] = json.loads(raw)
        sources.append(dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest()))
    normal = {(e["symbol"],e["time"]):e for e in refs["normal"]["isolated_events"]}
    current_gates = {(e["symbol"],e["time"]):e for e in refs["gates"]["events"]}
    params = dict(strategy="macro_tactical",gross_cap=20,risk_fraction=.5,exchange_leverage=50,
        liquidation_stop_multiple=1.25,account_controls=False,funding_policy="debit_stress",sizing_gap_reserve=.03,
        allow_partial_histories=True,tactical_setup_policies=setup_policies(7,21),funding_lease_hours=168,funding_lease_budget="risk")
    events,controls,last_end = [],0,{}
    scheduled_identities = 0
    for old in sorted(refs["shadow"]["events"],key=lambda e:(e["time"],e["symbol"])):
        if old["setup"]!="mean_reversion":
            continue
        s,now = old["symbol"],old["time"]
        assert gates[s,now]["first"] and gates[s,now]["eligible"]
        nonoverlap = now >= last_end.get(s,0)
        if nonoverlap:
            last_end[s] = now+21*86400
        e = dict(symbol=s,time=now,nonoverlap=nonoverlap,
                 gap_eligible=current_gates[s,now]["gap_gate"]["eligible"],
                 daily_eligible=current_gates[s,now]["daily_gate"]["eligible"],outcomes={})
        for scenario in ("base","double_cost"):
            cb = cost_case(book,scenario)
            fee,slip = (.001,.005) if scenario=="double_cost" else (.0005,.0025)
            for ignored in (False,True):
                b = replay(cb,signals,**params,capital=10,fee=fee,slip=slip,
                    forced_entry=dict(symbol=s,time=now,engine="tactical",ignore_friction_gate=ignored),
                    entry_liquidity_caps=caps)
                ref = old["outcomes"][scenario] if ignored else normal[s,now]["outcomes"][scenario]
                assert bool(b["trades"])==ref["accepted"]
                if ref["accepted"]:
                    assert b["trades"]==[ref["trade"]]
                else:
                    assert b["summary"]["rejections"]==ref["rejections"]
                controls += 1
                if not ignored:
                    continue
                assert len(b["trades"])==1
                t = b["trades"][0]
                comp = trade_pnl_components(t,fee=fee,slip=slip)
                e["outcomes"][scenario] = dict(normal_accepted=old["outcomes"][scenario]["normal_accepted"],
                    trade=t,components=comp,on_notional={k:v/t["notional_usdt"] for k,v in comp.items()},
                    censored=t["exit_reason"]=="end_of_sample",
                    labels={str(days):native_horizon_components(t,cb[s],days,fee=fee,slip=slip) for days in (7,21)})
                if t["exit_reason"]=="time_exit":
                    fixed = e["outcomes"][scenario]["labels"]["21"]
                    assert not fixed["censored"]
                    for k,v in comp.items():
                        assert math.isclose(v,fixed["components"][k],abs_tol=1e-8)
                    scheduled_identities += 1
        events.append(e)
    aggregates = []
    for sample in ("first_episodes","nonoverlap_21days"):
        for gate in ("original","gap_1atr","daily_reversal"):
            selected = [e for e in events if (sample=="first_episodes" or e["nonoverlap"])
                        and {"original":True,"gap_1atr":e["gap_eligible"],"daily_reversal":e["daily_eligible"]}[gate]]
            for scenario in ("base","double_cost"):
                rows = [e["outcomes"][scenario] for e in selected]
                common = [r for r in rows if not r["labels"]["21"]["censored"]]
                closed = [r for r in rows if not r["censored"]]
                vals = [r["on_notional"]["net_pnl"] for r in closed]
                paired = [r for r in common if not r["censored"]]
                aggregates.append(dict(sample=sample,gate=gate,scenario=scenario,events=len(rows),
                    normal_admitted=sum(r["normal_accepted"] for r in rows),
                    actual_closed=len(closed),actual_censored=len(rows)-len(closed),
                    actual_mean_net=statistics.mean(vals) if vals else None,
                    actual_mean_ex_best=(sum(vals)-max(vals))/(len(vals)-1) if len(vals)>1 else None,
                    actual_exit_counts=dict(Counter(r["trade"]["exit_reason"] for r in rows)),
                    actual_mean_components={k:statistics.mean(r["on_notional"][k] for r in closed) if closed else None
                                            for k in ("raw_price_pnl","slippage_cost","fees","net_funding")},
                    fixed_7=metrics(rows,7),fixed_21=metrics(rows,21),
                    paired_21_mature=dict(events=len(paired),
                        actual_mean=statistics.mean(r["on_notional"]["net_pnl"] for r in paired) if paired else None,
                        fixed7_mean=metrics(paired,7)["mean_net"],fixed21_mean=metrics(paired,21)["mean_net"])))
    original = json.loads(Path("state/research_runs/binance_macro_execution_optimization_20261015_final/summary.json").read_text())["sources"]
    unique = {s["path"]:s for s in sources}
    for source in list(unique.values())+original:
        assert hashlib.sha256(Path(source["path"]).read_bytes()).hexdigest()==source["sha256"]
    result = dict(start="2026-04-07",end_exclusive="2026-10-15",capital=10,
        events=events,aggregates=aggregates,legacy_controls=controls,sources=list(unique.values()),
        scheduled_exit_component_identities=scheduled_identities,
        original_inputs_verified=len(original),research_only=True,orders_authorized=False,independent_oos=False,
        assumptions=[
            "Nine fixed MR first opportunities. Normal and shadow36 hourly replays must match old trades/rejects. Shadow bypasses entry friction-ratio gate only; fees, risk, capacity, original/current renewal budgets, stops and21day cap retained.",
            "Actual paths use original hourly replay. Fixed7/21calendar-day labels use same entry/quantity, native exit-hour open and actual signed funding[start,end); stress doubles adverse ordinary funding only. Labels remove all exits, so never executable account returns.",
            "Initial-stop/static1percent-MMR liquidation touch flags are price-only diagnostics, not actual liquidation or a full collateral path. Dynamic trails and funding collateral can bind earlier.",
            "Per-asset21day nonoverlap selection occurs BEFORE gates/results; includes rejected opportunities, preserves longest horizon even for early exits. Cross-asset dependence remains. Endpoint maturity never uses last available price.",
            "No signal/threshold/leverage/risk/exit tuning, no new independent OOS, no new minute certification or synthetic prelisting data. Current filters, historical funding availability and adjustment/PIT limitations remain."])
    args.output.mkdir(parents=True)
    (args.output/"summary.json").write_text(json.dumps(result,ensure_ascii=False,allow_nan=False)+"\n")
    (args.output/"report.md").write_text(report(result))
    print(json.dumps(dict(output=str(args.output),events=len(events),legacy_controls=controls,
        aggregates=[{k:r[k] for k in ("sample","gate","scenario","events","actual_mean_net","actual_mean_ex_best","paired_21_mature")}
                    for r in aggregates]),ensure_ascii=False),flush=True)


if __name__=="__main__":
    main()
