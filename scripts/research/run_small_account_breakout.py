"""Reproduce the preregistered five-week, public-only breakout discovery pilot."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import statistics
from pathlib import Path

from qount.research.small_account_breakout import generate_signals, load_data, simulate
from qount.research.small_account_breakout_data import acquire, sha, timestamp, write_json


def csv_write(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("")
        return
    with path.open("w",newline="") as stream:
        writer = csv.DictWriter(stream,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config",type=Path,default=Path("config/small-account-breakout-v01.json"))
    parser.add_argument("--cache",type=Path,default=Path("state/research_cache/small_account_breakout_v01_20261013"))
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--download",action="store_true",help="download missing public inputs")
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if config["research_only"] is not True or config["orders_authorized"] is not False:
        raise ValueError("research_only_contract_required")
    if args.output.exists():
        raise FileExistsError("refuse_overwrite_research_bundle")
    if args.download:
        acquire(config,args.cache)
    manifest = json.loads((args.cache / "manifest.json").read_text())
    for record in manifest["files"]:
        if sha(args.cache / record["file"]) != record["sha256"]:
            raise ValueError(f"input_hash_mismatch:{record['file']}")
    args.output.mkdir(parents=True)
    (args.output / "config.json").write_bytes(args.config.read_bytes())
    write_json(args.output / "input-manifest.json",manifest)
    summaries, quality = [],{}
    for week in sorted(config["draw_order"]):
        data = load_data(args.cache,config,week)
        quality[week] = data.quality
        start,end = timestamp(week),timestamp(week)+7*86400
        signals,updates = generate_signals(data,config,start,end)
        simple_signals,_ = generate_signals(data,config,start,end,simple=True)
        # Fixed comparisons; report every variant, never choose a winner for deployment.
        jobs = [(variant,risk,"base") for variant in ("simple","crypto","combined")
                for risk in config["risk_fractions"]]
        jobs += [("combined",config["primary_risk_fraction"],scenario)
                 for scenario in config["scenarios"] if scenario != "base"]
        for variant,risk,scenario in jobs:
            bundle = simulate(data,config,week,simple_signals if variant=="simple" else signals,
                              updates,variant=variant,risk=risk,scenario=scenario)
            summary = bundle["summary"]
            summaries.append(summary)
            name = f"{week}_{variant}_r{int(risk*100):02d}_{scenario}"
            write_json(args.output / f"{name}.json",{key:value for key,value in bundle.items() if key!="curve"})
            csv_write(args.output / f"{name}_equity.csv",bundle["curve"])
            print(json.dumps({key:summary[key] for key in ("week_start","variant","risk_fraction",
                 "scenario","final_equity_usdt","trade_count","stock_trades","max_drawdown")}),flush=True)
    primary = [s for s in summaries if s["variant"]=="combined" and s["risk_fraction"]==config["primary_risk_fraction"] and s["scenario"]=="base"]
    aggregate = {"independent_initial_equity_each_week":True,
        "mean_week_return":statistics.mean(row["net_return"] for row in primary),
        "median_week_return":statistics.median(row["net_return"] for row in primary),
        "positive_weeks":sum(row["net_return"]>0 for row in primary),
        "total_weeks":len(primary),"total_trades":sum(row["trade_count"] for row in primary),
        "equal_10_usdt_per_week_total_initial":sum(row["initial_equity_usdt"] for row in primary),
        "equal_10_usdt_per_week_total_final":sum(row["final_equity_usdt"] for row in primary),
        "mean_log_growth":statistics.mean(row["log_growth"] for row in primary),
        "worst_observed_week_drawdown":max(row["max_drawdown"] for row in primary),
        "continuous_account_performance":False,"independent_oos":False}
    write_json(args.output / "summary.json",{"primary_aggregate":aggregate,"runs":summaries,
        "quality":quality,"research_only":True,"orders_authorized":False})
    report = ["# 小额合约进攻策略 v0.1：五个随机周探索回测", "",
        "每周独立从 10 USDT 空仓开始，周末按成本平仓。固定规则、无调参；不是连续账户或独立样本外验证。",
        "", "| UTC 周起始 | 终值 USDT | 净收益 | 最大回撤 | 交易数（股票） | 手续费 | 资金费净额 |", "|---|---:|---:|---:|---:|---:|---:|"]
    for s in primary:
        report.append(f"| {s['week_start']} | {s['final_equity_usdt']:.4f} | {s['net_return']:.2%} | {s['max_drawdown']:.2%} | {s['trade_count']}（{s['stock_trades']}） | {s['fees_usdt']:.4f} | {s['funding_net_usdt']:.4f} |")
    report += ["", "## 固定对照与压力情景", "", "| 版本 | 单笔风险 | 情景 | 平均周收益 | 最差周收益 | 最差周内回撤 | 交易总数 |", "|---|---:|---|---:|---:|---:|---:|"]
    keys = sorted({(s["variant"],s["risk_fraction"],s["scenario"]) for s in summaries})
    for variant,risk,scenario in keys:
        rows = [s for s in summaries if (s["variant"],s["risk_fraction"],s["scenario"])==(variant,risk,scenario)]
        report.append(f"| {variant} | {risk:.0%} | {scenario} | {statistics.mean(s['net_return'] for s in rows):.2%} | {min(s['net_return'] for s in rows):.2%} | {max(s['max_drawdown'] for s in rows):.2%} | {sum(s['trade_count'] for s in rows)} |")
    report += ["", "## 证据边界", "",
        "- 所有收益已计双边手续费、买卖价差/滑点假设与按实际结算时点的资金费；保证金仅冻结，不计作成本。",
        "- 默认加密每边手续费 5bp、滑点 5bp；股票永续每边手续费 5bp、滑点 10bp。成本是研究假设，不是账户费率认证。",
        "- double_cost和funding_2x重新应用成本门与仓位计算，会改变交易集合；交易减少带来的回撤下降不等于信号更稳健。stop_gap_1pct只对实际止损退出额外施加1%不利成交。",
        "- 真实一分钟永续成交 OHLC 与标记 OHLC；一分钟内先后顺序未知，止损与强平同分钟触及时保守记强平。没有历史盘口，不证明可按该价成交。",
        "- 设置杠杆与账户名义敞口分开；保证金占用≤60%；仓位向下取整，低于最小数量/名义金额不补单。",
        "- 历史交易规则使用当前公开快照近似，BTC 最低名义按官方 4 月 14 日变更分段；其余历史步长和费率未逐日认证。",
        "- 强平使用标记价格与保守维持保证金假设（加密1%、股票5%）加清算费缓冲，不是账户专属真实阶梯。",
        "- 资金费预估只用决策前72小时已结算记录，按最大绝对费率及最长持有期留预算；真实未来费率仅进入事后账本。",
        "- 首个35日小时窗口只用于指标预热，不计收益；股票15分钟ATR使用连续合约行情预热48小时，VWAP和开盘区间只用常规时段。",
        "- 执行按下一分钟开盘加不利滑点近似；两个模块均检查0.3ATR偏离上限。周末样本结束平仓按最后一分钟收盘加不利滑点近似，未用该价格生成信号。",
        "- 简单基线为不加方向/放量过滤的20小时双向突破，其他成本和风险边界一致。现金收益0；未杠杆化币价涨跌只作行情参照，不是假设10 USDT可下单的合约基准。",
        "- 每周数据独立重置；相邻的9月28日和10月5日并非独立市场机制。35日不足以年化CAGR、Calmar或估算100倍概率。",
        "- research_only=true / orders_authorized=false；不接入旧StrategyIntent，不改生产服务，不调用私有账户接口。", ""]
    (args.output / "report.md").write_text("\n".join(report))
    sources = [args.config,Path("src/qount/research/small_account_breakout.py"),
               Path("src/qount/research/small_account_breakout_data.py"),Path(__file__)]
    write_json(args.output / "manifest.json",{"created_at":dt.datetime.now(dt.timezone.utc).isoformat(),
        "research_only":True,"orders_authorized":False,
        "source_hashes":{str(path):sha(path) for path in sources},
        "files":{path.name:sha(path) for path in sorted(args.output.iterdir()) if path.is_file()}})
    (args.output / "_COMPLETE").write_text(sha(args.output / "manifest.json")+"\n")
    print(json.dumps({"output":str(args.output),"primary_aggregate":aggregate}),flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
