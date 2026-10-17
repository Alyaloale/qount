"""Fixed, continuous v0.2 breakout mechanism experiments with separate stock diagnostics."""
from __future__ import annotations

import argparse
import copy
import csv
import datetime as dt
import json
import math
from dataclasses import asdict
from pathlib import Path

from qount.research.small_account_breakout import generate_signals, simulate
from qount.research.small_account_breakout_data import acquire_continuous, sha, timestamp, write_json
from qount.research.small_account_breakout_study import (
    confirm_entries, enrich_bundle, fixed_cost_revaluation, group_events, load_continuous,
    path_diagnostic, signal_paths, stock_diagnostics, matched_exit_comparison,
)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config",type=Path,default=Path("config/small-account-breakout-v02.json"))
    p.add_argument("--cache",type=Path,default=Path("state/research_cache/small_account_breakout_v02_20261013"))
    p.add_argument("--reuse",type=Path,default=Path("state/research_cache/small_account_breakout_v01_20261013"))
    p.add_argument("--pilot",type=Path,default=Path("state/research_runs/small_account_breakout_v01_20261013_verified"))
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--download",action="store_true")
    args = p.parse_args()
    if args.output.exists(): raise FileExistsError("refuse_overwrite_research_bundle")
    study = json.loads(args.config.read_text())
    base = json.loads(Path(study["base_config"]).read_text())
    if study["research_only"] is not True or study["orders_authorized"] is not False:
        raise ValueError("research_only_contract_required")
    if args.download: acquire_continuous(base,study,args.cache,args.reuse)
    cfg = copy.deepcopy(base)
    cfg.update({"stock_symbols":[],"funding_interval_mode":study["funding_interval_mode"],
                "funding_interval_fallback_hours":study["funding_interval_fallback_hours"],"size_to_liquidity":True})
    args.output.mkdir(parents=True)
    write_json(args.output/"study-config.json",study)
    write_json(args.output/"base-config.json",base)
    write_json(args.output/"effective-config.json",cfg)
    data = load_continuous(args.cache,cfg,study)
    print(json.dumps({"data_quality":data.quality}),flush=True)
    start,end = timestamp(study["development_start"]),timestamp(study["development_end_exclusive"])
    raw,updates = generate_signals(data,cfg,start,end,simple=True)
    raw = group_events(raw,study["event_window_hours"])
    signal_sets = {"A_simple":raw,"B_direction":[s for s in raw if s.direction_pass],
                   "C_volume":[s for s in raw if s.volume_pass],
                   "D_original":[s for s in raw if s.direction_pass and s.volume_pass]}
    original = signal_sets["D_original"]
    results,settings = {},{}

    def run(name,signals,settings_cfg=None,risk=0.02,scenario="base"):
        current = copy.deepcopy(settings_cfg or cfg)
        bundle = simulate(data,current,study["development_start"],signals,updates,
                          variant="crypto",risk=risk,scenario=scenario,end_time=end)
        enrich_bundle(bundle,data,current,study)
        s = bundle["summary"]
        s["name"] = name
        # Independent arithmetic checks, including all newly added exit types.
        for t in bundle["trades"]:
            side = 1 if t["side"]=="long" else -1
            computed = side*t["quantity"]*(t["exit_price"]-t["entry_price"])-t["fees_usdt"]+t["funding_net_usdt"]
            if not math.isclose(computed,t["net_pnl_usdt"],abs_tol=1e-8): raise AssertionError("trade_ledger")
            if t["planned_risk_usdt"]>t["risk_budget_usdt"]+1e-8: raise AssertionError("risk_budget")
        peak,mdd = current["initial_equity_usdt"],0.0
        for row in bundle["curve"]:
            peak=max(peak,row["equity_usdt"])
            mdd=max(mdd,1-row["equity_usdt"]/peak)
        monthly={}
        previous=current["initial_equity_usdt"]
        for row in bundle["curve"]:
            # The value timestamp is the minute close; assign it to its actual bar month.
            month=dt.datetime.fromtimestamp(timestamp(row["time"])-60,dt.timezone.utc).strftime("%Y-%m")
            if month not in monthly: monthly[month]={"start_equity":previous}
            monthly[month]["end_equity"]=row["equity_usdt"]
            previous=row["equity_usdt"]
        s["monthly_returns"]={k:v["end_equity"]/v["start_equity"]-1 for k,v in monthly.items()}
        if not math.isclose(mdd,s["max_drawdown"],abs_tol=1e-10): raise AssertionError("nav_mdd")
        if len(bundle["curve"]) != (end-start)//60: raise AssertionError("continuous_curve_gap")
        with (args.output/f"{name}_equity.csv").open("w",newline="") as f:
            writer=csv.DictWriter(f,fieldnames=list(bundle["curve"][0]))
            writer.writeheader(); writer.writerows(bundle.pop("curve"))
        write_json(args.output/f"{name}.json",bundle)
        results[name],settings[name] = bundle,(signals,current)
        print(json.dumps({k:s[k] for k in ("name","final_equity_usdt","net_return","max_drawdown","trade_count","mean_net_r")}),flush=True)
        return bundle

    for name,signals in signal_sets.items(): run(name,signals)
    failure_cfg = {**cfg,"breakout_failure_exit":True}
    run("D_failure_exit",original,failure_cfg)
    confirmed = confirm_entries(original,updates,end)
    run("D_confirm_entry",confirmed)
    losing = [t for t in results["D_original"]["trades"] if t["net_pnl_usdt"]<0]
    trailing_eligible = bool(losing) and sum(t["diagnostic"]["mfe_r_confirmed"]>=1 for t in losing)*2>=len(losing)
    if trailing_eligible: run("D_trailing_1r",original,{**cfg,"trailing_activation_r":1.0})
    write_json(args.output/"matched-exit-comparison.json",
               matched_exit_comparison(results["D_original"]["trades"],data,cfg,updates,end))
    # No Cartesian grid: at most one combination, only after both single increments qualify.
    control = results["D_original"]["summary"]
    def improves(name):
        s=results[name]["summary"]
        return s["mean_net_r"] is not None and s["net_return"]>control["net_return"] and s["mean_net_r"]>control["mean_net_r"]
    mechanisms=[n for n in ("D_failure_exit","D_confirm_entry","D_trailing_1r") if n in results and improves(n)]
    filters=[n for n in ("A_simple","B_direction","C_volume") if improves(n)]
    combination = None
    if mechanisms and filters:
        chosen_filter=max(filters,key=lambda n:results[n]["summary"]["net_return"])
        mechanism=mechanisms[0]  # fixed priority: failure, confirmation, conditional trailing
        signals=signal_sets[chosen_filter]
        if mechanism=="D_confirm_entry": signals=confirm_entries(signals,updates,end)
        combination=f"combination_{chosen_filter}_{mechanism}"
        run(combination,signals,settings[mechanism][1])
    # Sensitivities always retain the primary matched mechanism comparison.
    for name in ("D_original","D_failure_exit"):
        signals,current=settings[name]
        for risk in study["risk_sensitivity"]:
            run(f"{name}_risk{int(risk*100)}",signals,current,risk=risk)
        for capital in study["capital_sensitivity_usdt"]:
            run(f"{name}_capital{int(capital)}",signals,{**current,"initial_equity_usdt":capital})
        for scenario in ("double_cost","stop_gap_1pct"):
            run(f"{name}_{scenario}",signals,current,scenario=scenario)
        write_json(args.output/f"{name}_fixed_double_cost.json",fixed_cost_revaluation(results[name]["trades"],2))
    for name in ("A_simple","B_direction","C_volume"):
        write_json(args.output/f"{name}_fixed_double_cost.json",fixed_cost_revaluation(results[name]["trades"],2))
    for scenario in ("double_cost","stop_gap_1pct"):
        run(f"A_simple_{scenario}",raw,scenario=scenario)
    write_json(args.output/"signal-paths.json",signal_paths(raw,data,cfg,study))
    # Reconstruct pilot paths using saved fills; never rewrite the original evidence.
    signal_map={(s.symbol,s.decision_time):s for s in raw}
    pilot=[]
    for week in base["draw_order"]:
        source=args.pilot/f"{week}_combined_r10_base.json"
        for t in json.loads(source.read_text())["trades"]:
            s=signal_map[(t["symbol"],timestamp(t["decision_time"]))]
            t["signal"]=asdict(s)
            t["exit_timing"]="intraminute_unknown" if t["exit_reason"] in {"initial_stop","trailing_stop","liquidation"} else "minute_open"
            t["diagnostic"]=path_diagnostic(t,data,base,study["post_exit_window_hours"])
            pilot.append(t)
    write_json(args.output/"pilot-trade-diagnostics.json",{"trades":pilot,"source_bundle":str(args.pilot)})
    write_json(args.output/"stock-diagnostics.json",stock_diagnostics(args.reuse,base))
    write_json(args.output/"summary.json",{"runs":[v["summary"] for v in results.values()],"quality":data.quality,
        "trailing_1r_condition_met":trailing_eligible,"combination":combination,"cash_return":0,
        "confirmation_counts":{"original":len(original),"confirmed":len(confirmed)},
        "research_only":True,"orders_authorized":False,"independent_oos":False,
        "verification":{"trade_arithmetic":"passed","risk_budget":"passed","continuous_nav_mdd":"passed"}})
    report=["# 小额突破 v0.2 连续开发实验","",f"{study['development_start']}—{study['development_end_exclusive']}（结束不含）。所有结果为开发样本，无独立 OOS。",
        "","|版本|本金|风险|净收益|最大回撤|交易数|均值净R|资金占用时间|","|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name,bundle in results.items():
        s=bundle["summary"]
        r=f"{s['mean_net_r']:.4f}" if s["mean_net_r"] is not None else "—"
        report.append(f"|{name}|{s['initial_equity_usdt']:.0f}|{s['risk_fraction']:.0%}|{s['net_return']:.2%}|{s['max_drawdown']:.2%}|{s['trade_count']}|{r}|{s['occupancy_fraction']:.2%}|")
    report += ["","1R 为成交价至实际初始止损价的距离×数量，净R扣费用和实际资金费。固定交易双倍成本与完整重跑分文件保存。",
        "资金费间隔历史快照缺失时，使用决策前最后两个常规结算的时间差延续假设，明确标识，不用当前间隔回填。",
        "分钟OHLC无法排序止损分钟高低点：MFE/MAE分别保存可确认值与该分钟边界值。退出后24小时路径不参与交易决策；右端不足24小时明确标注。",
        "股票仅分析原五周，未进入连续加密账户。现金0%为可执行对照；币价涨跌仅为行情参照。",
        "历史数量规则、盘口、保证金阶梯仍沿用v0.1近似。研究未连接生产或订单接口。",""]
    (args.output/"report.md").write_text("\n".join(report))
    sources=[args.config,Path(study["base_config"]),Path(__file__),
             *[Path("src/qount/research")/n for n in ("small_account_breakout.py","small_account_breakout_data.py","small_account_breakout_study.py")]]
    write_json(args.output/"input-manifest.json",json.loads((args.cache/"continuous-manifest.json").read_text()))
    write_json(args.output/"manifest.json",{"created_at":dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_hashes":{str(p):sha(p) for p in sources},
        "pilot_manifest_sha256":sha(args.pilot/"manifest.json"),"pilot_inputs_sha256":sha(args.reuse/"manifest.json"),
        "files":{p.name:sha(p) for p in sorted(args.output.iterdir()) if p.is_file()},
        "research_only":True,"orders_authorized":False})
    (args.output/"_COMPLETE").write_text(sha(args.output/"manifest.json")+"\n")
    return 0


if __name__=="__main__": raise SystemExit(main())
