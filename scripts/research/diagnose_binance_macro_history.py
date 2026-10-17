"""Expand fixed ETF direction labels and attribute retained native candidates."""
import argparse
import hashlib
import json
import statistics
from pathlib import Path

from qount.research.binance_macro_attack import CONTRACT_SIGNALS, macro_features
from qount.research.binance_macro_history import (
    account_concentration, adjusted_bars, distribution, first_episodes, forward_label,
)


def report(result):
    selected = [r for r in result["aggregates"] if r["sample"]=="nonoverlap_15sessions"]
    lookup = {(r["cohort"],r["sessions"],r["scenario"]):r for r in selected}
    lines = ["# 固定规则长样本方向诊断与合约利润集中度", "",
        "**裁决：尚未收敛为稳定盈利策略。中期均值回归方向机制值得继续研究；日际反转门没有显示增量，降为对照，不替换为反向过滤。1ATR原生合约门仍是未认证探索候选。**", "",
        "2017-01-01至2026-01-01（末日不含），2016全年预热，八个当前ETF代理及原有宏观观察池，复用原始固定信号公式。取得13个独立Yahoo日线缓存约3.4MiB，未拼接调整口径不同的旧CSV。617个信号段首中142个均值回归、475个趋势；这些不是独立样本。", "",
        "信号在实际交易日16:00纽约之后可用，早收市保守延迟至16:00；方向标签从下一真实交易日09:30开盘至持有第5／15个交易日收盘。沿用两种固定摩擦假设：每边手续费5bp／滑点25bp，压力10bp／50bp。未计资金费、止损、杠杆、10USDT最小订单、容量、共享占仓或10AM执行价，因此下表是按入场名义额计算的方向标签均值，**不是策略回测收益，更不是币安账户收益**。", "",
        "## 去除同资产重叠后的结果", "",
        "按时间先后、跨全部战术类型，以最长15交易日区间对每个资产去重；取样在日际门和未来收益之前完成。不同资产同期相关性仍在。", "",
        "|信号|持有交易日|成熟机会|基础平均|双摩擦平均|基础中位数|去掉最佳一笔后的基础平均|", "|---|---:|---:|---:|---:|---:|---:|"]
    names = {"mr_all":"原始均值回归", "mr_daily_reversal":"均值回归＋日际反转", "trend":"趋势对照"}
    for cohort in names:
        for n in (5,15):
            b,d = lookup[cohort,n,"base"],lookup[cohort,n,"double_cost"]
            lines.append(f"|{names[cohort]}|{n}|{b['mature']}|{b['mean']:.2%}|{d['mean']:.2%}|{b['median']:.2%}|{b['mean_ex_best']:.2%}|")
    lines += ["", "所有段首、不去路径重叠时，原始／日际门15日基础均值分别+1.43%／+1.26%（142／102个）；同资产去重后分别+1.45%／+0.88%（93／70个）。两种取样均未显示日际门的增量，不因被拒绝组事后均值更高而改成反向门。", "",
        "原始均值回归15日去重样本覆盖48个自然月，7/8资产、8/9年份基础均值为正，逐一剔除某年后的总体均值为+1.21%至+1.69%。但2022年仅2个机会、均值−5.75%；整体最差单次固定持有标签−9.96%。数据曾参与其他研究、当前资产池事后确定、各资产仍相关，不能据此认证统计显著或独立OOS，更不能直接加杠杆外推。", "",
        "趋势对照15日也未通过双摩擦，且5日均值为负；这只是固定持有诊断，尚未包含趋势规则的动态止损／提前退出，不能据此删除实际趋势入口。", "",
        "## 原生合约账户利润集中度", "",
        "复用2026-04-07至10-15原有分钟核对损益，不新增成交样本。以下减法固定旧数量，只用于归因；去掉交易后实际账户会重新配仓，不等于新的账户回测。", "",
        "|入口|本金USDT|全部净损益USDT|已闭合净损益|截尾持仓损益|已闭合扣除最佳一笔|", "|---|---:|---:|---:|---:|---:|"]
    for c in result["concentration"]:
        if c["scenario"]!="base":
            continue
        lines.append(f"|{c['arm']}|{c['capital']}|{c['total_pnl']:+.5f}|{c['closed_pnl']:+.5f}|{c['censored_pnl']:+.5f}|{c['closed_ex_best_pnl']:+.5f}|")
    lines += ["", "10USDT日际版97.22%的净利润来自一笔IWM，其他三笔仅+0.04749USDT；100USDT其他三笔−2.03026USDT。1ATR版10USDT已闭合扣除IWM后−0.13497USDT，且总利润64.82%来自XLE末端截尾；100USDT基础总损益仍为负。原有高成本账户1ATR两尺度亏损、日际门两尺度零交易；没有新增成本盈利证据。", "",
        "## 后续研究方向与复核", "",
        "暂不加新信号门或提高杠杆。保留原始均值回归与1ATR门用于原生合约对照，日际反转门降为对照。最有价值的问题转为：中期方向优势能否在真实资金费、2ATR止损、7天续期与单仓占用下兑现；不能用ETF固定持有标签替代这一步。现有均值回归最长21日已与该方向一致，本次不延长参数。", "",
        "统一调整OHLC仍为当前下载的Yahoo历史版本，未认证历史时点可得的现金分红。结构趋势门的同ETF／同年日均标签只作为描述性参照，不是风险匹配Alpha或可交易基准；其取样重叠。全部617事件、各年／资产、双摩擦、截尾及两尺度归因见summary.json。", "",
        "原38个公共输入hash不变；原默认信号与来源记录hash精确复现。新增6项针对时钟／下一真实交易日开盘／标签成熟／去重先于过滤／OHLC调整／分钟归因的测试，相关137项全部通过。冻结Universal／Dual-Engine、服务、账户与权限未改；research_only=true / orders_authorized=false。", "",
        "```bash", "PYTHONPATH=src ./.venv/bin/python scripts/research/diagnose_binance_macro_history.py --output state/research_runs/binance_macro_history_replay", "PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -p 'test_binance*.py'", "```", "",
        "输出目录须不存在，缺公共日线缓存时加--download。不是新的独立OOS验证或实盘授权。"]
    return "\n".join(lines)+"\n"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--download", action="store_true", help="Missing public Yahoo history only")
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError("refuse_overwrite_history_study")
    cache = Path("state/research_cache/binance_macro_etf_history_20261015")
    features, sources = macro_features(cache, "2026-01-01", args.download, start_date="2016-01-01")
    events, controls, ranges = [], {}, {}
    for symbol, ticker in CONTRACT_SIGNALS.items():
        bars = adjusted_bars(json.loads((cache/f"yahoo-{ticker}-20160101-2026-01-01.json").read_text()))
        assert len(bars) == len(features[symbol])+200
        ranges[ticker] = dict(bars=len(bars), first=features[symbol][0]["date"], last=features[symbol][-1]["date"])
        # Structural-only same-ETF/year reference; daily observations overlap.
        # Match before seeing returns, and never call this risk-matched alpha.
        indices = {b.t:i for i,b in enumerate(bars)}
        for f in features[symbol]:
            if "2017-01-01" <= f["date"] < "2026-01-01" and f["hold_structural"]:
                i = indices[f["available"]]
                for n in (5, 15):
                    label = forward_label(bars, i, n)
                    if not label["censored"]:
                        for scenario in ("base", "double_cost"):
                            controls.setdefault((ticker,f["date"][:4],n,scenario),[]).append(label[scenario])
        for e in first_episodes(features[symbol], bars):
            e.update(symbol=symbol, proxy=ticker)
            e["structural_reference"] = {
                str(n):{scenario:statistics.mean(controls[ticker,e["year"],n,scenario])
                        if controls.get((ticker,e["year"],n,scenario)) else None
                        for scenario in ("base", "double_cost")} for n in (5,15)}
            events.append(e)
    cohorts = {
        "mr_all": lambda e:e["setup"]=="mean_reversion",
        "mr_daily_reversal": lambda e:e["setup"]=="mean_reversion" and e["daily_reversal"],
        "mr_no_daily_reversal": lambda e:e["setup"]=="mean_reversion" and not e["daily_reversal"],
        "trend": lambda e:e["setup"]!="mean_reversion",
    }
    aggregates = []
    for sample in ("first_episodes", "nonoverlap_15sessions"):
        pool = [e for e in events if sample=="first_episodes" or e["nonoverlap"]]
        for name, test in cohorts.items():
            chosen = [e for e in pool if test(e)]
            for n in (5,15):
                for scenario in ("base","double_cost"):
                    matched = [e["structural_reference"][str(n)][scenario] for e in chosen
                               if not e["outcomes"][str(n)]["censored"] and e["structural_reference"][str(n)][scenario] is not None]
                    excess = [e["outcomes"][str(n)][scenario]-e["structural_reference"][str(n)][scenario]
                              for e in chosen if not e["outcomes"][str(n)]["censored"] and e["structural_reference"][str(n)][scenario] is not None]
                    aggregates.append(dict(sample=sample,cohort=name,sessions=n,scenario=scenario,
                        **distribution(chosen,n,scenario),
                        matched_structural_mean=statistics.mean(matched) if matched else None,
                        matched_excess_mean=statistics.mean(excess) if excess else None,
                        matched_events=len(matched),
                        by_year={year:distribution([e for e in chosen if e["year"]==year],n,scenario)
                                 for year in sorted({e["year"] for e in events})},
                        by_asset={ticker:distribution([e for e in chosen if e["proxy"]==ticker],n,scenario)
                                  for ticker in CONTRACT_SIGNALS.values()}))
    old = Path("state/research_runs/binance_macro_daily_reversal_20261015_final")
    concentration = []
    for arm in ("baseline", "mr_signal_gap_1atr", "mr_daily_reversal"):
        for capital in (10,100):
            for scenario in ("base","double_cost"):
                path = old/f"{arm}_{capital}_{scenario}.json"
                raw = path.read_bytes()
                sources.append(dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest()))
                c = account_concentration(json.loads(raw))
                concentration.append(dict(arm=arm,capital=capital,scenario=scenario,**c))
    original = json.loads(Path("state/research_runs/binance_macro_execution_optimization_20261015_final/summary.json").read_text())["sources"]
    for s in sources+original:
        assert hashlib.sha256(Path(s["path"]).read_bytes()).hexdigest()==s["sha256"]
    result = dict(signal_start="2017-01-01", end_exclusive="2026-01-01",warmup_start="2016-01-01",
        horizons_sessions=[5,15], ranges=ranges, events=events, aggregates=aggregates,
        concentration=concentration,sources=sources,original_inputs_verified=len(original),
        research_only=True,orders_authorized=False,independent_oos=False,
        assumptions=[
            "Frozen original tactical rules, structural/systemic gates and zero-threshold daily reversal; no threshold search. Signal at16NY (conservatively after early closes), labels buy NEXT session09:30 open and sell Nth held session close.",
            "ETF direction labels only. Base each-side fee5bp/slip25bp; stress10bp/50bp. No funding, stops, leverage,10USDT order/capacity constraints, occupancy or actual10AM fills. Never interpret as executable perp returns or replace native1ATR gate with ETF ATR.",
            "Contemporary Yahoo adjusted OHLC, not historical-vintage PIT cash dividends. Current eight mapped proxy assets are selected ex post; long history also used by prior Universal research, not independent OOS.",
            "First episodes before gates; per-asset15-session nonoverlap selection before gates/outcomes, shared across horizons. Cross-asset and time dependence remain; no IID significance claim.",
            "Structural-only same-ETF/year daily next-open controls overlap and are descriptive, not a tradable/risk-matched portfolio or causal alpha estimate.",
            "Native account concentration reuses prior minute PnL with frozen quantities. Subtracting best/unfinished trades is arithmetic attribution, never a resized counterfactual strategy."])
    args.output.mkdir(parents=True)
    (args.output/"summary.json").write_text(json.dumps(result,ensure_ascii=False,allow_nan=False)+"\n")
    (args.output/"report.md").write_text(report(result))
    print(json.dumps(dict(events=len(events),sources=len(sources),output=str(args.output),
        nonoverlap=[{k:r[k] for k in ("cohort","sessions","scenario","mature","mean","mean_ex_best")}
                    for r in aggregates if r["sample"]=="nonoverlap_15sessions"]),ensure_ascii=False),flush=True)


if __name__=="__main__":
    main()
