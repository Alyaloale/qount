"""Compare fixed ETF risk-budget mechanisms; cache-only, no fitting or orders."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from qount.research.etf_risk_budget import Costs, simulate, summarize  # noqa: E402
from qount.research.personal_trading_assistant import (  # noqa: E402
    CORE_ETF_UNIVERSE, PersonalTradingAssistantKernel, load_dataset_from_clean_indices,
)


SYMBOLS = ("513100.SH", "159915.SZ")
POLICIES = ("buy_hold", "ma120", "static75", "vol15", "exposure_matched_diagnostic")
CASES = {
    "base": (Costs(), 1),
    "double_cost": (Costs(commission_bps=12, slippage_bps=10, minimum_commission=10), 1),
    "delay2": (Costs(), 2),
    "delay2_slip25": (Costs(slippage_bps=25), 2),
}


def period(result, start, end, initial=100_000):
    rows = result["nav"]
    indices = [i for i, r in enumerate(rows) if start <= r["date"] <= end]
    if not indices:
        return None
    i = indices[0]
    capital = rows[i - 1]["equity"] if i else initial
    return summarize(rows[i:indices[-1] + 1], capital)


def paired_log_interval(a, b, *, draws=1000):
    """Paired moving-block diagnostic, not a multiple-testing/OOS certificate."""
    x = np.diff(np.log([100_000] + [r["equity"] for r in a["nav"]]))
    y = np.diff(np.log([100_000] + [r["equity"] for r in b["nav"]]))
    diff = x - y
    intervals = {}
    for block in (40, 120):
        rng = np.random.default_rng(20261025 + block)
        samples = []
        for _ in range(draws):
            starts = rng.integers(0, len(diff) - block + 1, (len(diff) + block - 1) // block)
            values = np.concatenate([diff[i:i + block] for i in starts])[:len(diff)]
            samples.append(float(np.mean(values) * 252 * 100))
        intervals[str(block)] = [float(v) for v in np.quantile(samples, [.025, .975])]
    return dict(annual_log_return_difference_pct=float(np.mean(diff) * 252 * 100),
                paired_block_95pct=intervals, draws=draws, independent_oos=False)


def preliminary(dataset):
    # These were executed first. Preserve failed mechanisms as well as the new candidate.
    result = {}
    kernel = PersonalTradingAssistantKernel(cash_apr=0)
    for symbol in SYMBOLS + ("000300.SH",):
        bars, meta = dataset[symbol], CORE_ETF_UNIVERSE[symbol]
        bh, _ = kernel.simulate_buy_and_hold(bars, meta)
        cash, _ = kernel.simulate_pure_cash(bars, meta)
        curves = [kernel.simulate_trend_timing(bars, meta, ma_period=p)[0] for p in (20, 60, 120)]
        tests = dict(buy_hold=bh, ma120=curves[-1],
                     half_core_half_timing=[(a + b) / 2 for a, b in zip(bh, curves[-1])],
                     static75_unrebalanced=[.75 * a + .25 * b for a, b in zip(bh, cash)],
                     three_speed_unrebalanced=[sum(v) / 3 for v in zip(*curves)])
        result[symbol] = {}
        for name, nav in tests.items():
            metrics = summarize([dict(date=b.trade_date, equity=v, weight=0)
                                 for b, v in zip(bars, nav)], 1_000_000)
            # These composed NAVs do not carry a share-level exposure ledger.
            metrics.pop("average_weight")
            result[symbol][name] = metrics
    return result


def markdown(result):
    lines = ["# ETF风险预算研究", "",
        "结论：保留513100.SH的固定波动率预算作为研究候选；未建立独立样本外收益优势，不替换生产。创业板结果不支持跨资产推广。", "",
        "本轮线上状态检查、既有策略运行判断与研究优先级见仓库docs/current.md；只读时点快照位于state/research_runs/etf_risk_budget_20261025/live-status.json。本报告仅呈现离线研究，模拟YTD与本报告长期回放不是同一收益口径。", "",
        "## 假设与规则", "",
        "先检验长期持仓/择时各半及MA20/60/120等资本组合；两者未取得跨标的稳定优势，失败结果保留在results.json的preliminary中。随后改问：减少波动较高时的敞口，是否比全进全出的方向择时更有风险收益价值？未搜索波动目标、窗口或比例。", "",
        "候选vol15：只做多、不借款；用最近20个完成日线的简单收益样本标准差×√252估计波动率，目标权重=min(100%,15%/估计波动率)。每个ISO周首个已完成交易日收盘决定，下一交易日开盘成交；不是事前知道本周末日，也不是当日收盘成交。其余留现金。15%是定仓目标，不能保证实际波动或损失上限。", "",
        "同引擎对照：买入持有、原MA120/1.5%带宽/两日确认、固定75%周度再平衡。另以主情景候选全窗平均实际持仓比例构造固定仓位对照；该比例是事后诊断，只用于区分择时与风险暴露，不是可事前选择的交易候选。其余成本/本金情景沿用该比例，不逐格重新选择。", "",
        "## 样本与成本", "",
        "实际场内ETF 513100.SH、159915.SZ；2014-01-02至2026-10-09，起点前至少120个交易日仅用于暖启动。本金主情景10万元人民币，另测1万/100万元；100份整手、最低佣金5元、每边佣金6bp和滑点5bp，现金收益0。双成本为12bp/10bp、最低佣金10元；另测信号晚一交易日、以及晚一日且每边滑点25bp。全部场景重新定仓和回放，不是固定路径简单扣费。", "",
        "513100于2022-01-13的1:5拆分沿用既有元数据，原价份额会计与信号调整保持连续。[基金公司拆分结果公告](https://pdf.dfcfw.com/pdf/H2_AN202201141540309205_1.pdf)。交易所价格已包含基金管理费影响，不重复扣。其他分红/到账资格未完整认证；成交量/开盘盘口、QDII溢价、市场冲击及券商具体收费未认证。单价日保守延后交易，其他开盘成交仍是假设，不证明真实成交。尾端按市价估值，未假装卖出。", "",
        "数据复用本地clean_indices缓存，无新行情请求、无Tiingo预算消耗。历史已被研究消费，时间分段、跨标的和bootstrap均不能恢复独立OOS身份；本轮观察结果后改换研究假设的顺序明确保留。", "",
        "## 主情景（10万元、基础成本）", "",
        "|标的|规则|自然日历净CAGR|日收盘MDD|标准Calmar|平均权益仓位|双边年换手|成交指令数|",
        "|---|---|---:|---:|---:|---:|---:|---:|"]
    for symbol in SYMBOLS:
        for policy in POLICIES:
            row = next(r for r in result["comparisons"] if r["symbol"] == symbol and
                       r["policy"] == policy and r["capital"] == 100_000 and r["case"] == "base")
            m = row["metrics"]
            lines.append(f'|{symbol}|{policy}|{m["cagr_calendar_pct"]:.2f}%|{m["max_drawdown_pct"]:.2f}%|{m["calmar"]:.3f}|{m["average_weight"]:.1%}|{m["annual_turnover_two_sided"]:.2f}x|{m["trade_count"]}|')
    lines += ["", "## 候选与对照的成本/延迟压力（513100、10万元）", "",
              "|情景|规则|净CAGR|MDD|Calmar|", "|---|---|---:|---:|---:|"]
    for row in result["comparisons"]:
        if row["symbol"] == "513100.SH" and row["capital"] == 100_000:
            m = row["metrics"]
            lines.append(f'|{row["case"]}|{row["policy"]}|{m["cagr_calendar_pct"]:.2f}%|{m["max_drawdown_pct"]:.2f}%|{m["calmar"]:.3f}|')
    lines += ["", "## 本金敏感性（513100、vol15）", "", "|本金|情景|净CAGR|MDD|年换手|", "|---:|---|---:|---:|---:|"]
    for row in result["comparisons"]:
        if row["symbol"] == "513100.SH" and row["policy"] == "vol15":
            m = row["metrics"]
            lines.append(f'|{row["capital"]:,}|{row["case"]}|{m["cagr_calendar_pct"]:.2f}%|{m["max_drawdown_pct"]:.2f}%|{m["annual_turnover_two_sided"]:.2f}x|')
    lines += ["", "## 各年收益（基础成本、连续账户，不在年初重设持仓）", "",
              "|年份|买持|MA120|固定75%|波动预算|事后匹配静态|", "|---|---:|---:|---:|---:|---:|"]
    for year, values in result["annual"]["513100.SH"].items():
        lines.append("|" + str(year) + "|" + "|".join(f'{values[p]["total_return_pct"]:.2f}%' for p in POLICIES) + "|")
    lines += ["", "## 分段结果（513100、基础成本，诊断而非独立OOS）", "",
              "|窗口|规则|净CAGR|MDD|Calmar|", "|---|---|---:|---:|---:|"]
    for window, values in result["periods"]["513100.SH"].items():
        for policy, m in values.items():
            lines.append(f'|{window}|{policy}|{m["cagr_calendar_pct"]:.2f}%|{m["max_drawdown_pct"]:.2f}%|{m["calmar"]:.3f}|')
    lines += ["", "## 不确定性与裁决", ""]
    for symbol, comparison in result["bootstrap"].items():
        for name, data in comparison.items():
            ci = data["paired_block_95pct"]
            lines.append(f'- {symbol}，vol15相对{name}：年化对数收益差{data["annual_log_return_difference_pct"]:.2f}个百分点；40/120日配对块95%诊断区间分别[{ci["40"][0]:.2f}, {ci["40"][1]:.2f}] / [{ci["120"][0]:.2f}, {ci["120"][1]:.2f}]。')
    lines += ["", "候选在513100三个大分段的Calmar均高于原择时，但2014–2017回撤仍略高于事后匹配静态；2025与2026截至10月9日收益落后该静态对照。创业板候选亦弱于匹配静态，不支持把同一风险规则推广到所有ETF。", "",
              "判断依据应同时看收益、回撤和相近敞口对照，不按单个Calmar排第一就宣称优秀。候选只保留为513100风险配置研究；创业板负面结果、各年亏损和压力表现均保留。当前实盘宏观25%预算、信号、执行权限和全部线上服务均未修改。该人民币场内ETF候选不能直接用于当前15USDT的币安账户。", "",
              "本轮没有生成独立OOS收益证据。下一项优先问题是：候选的回撤改善能否在相同事前风险预算及真实ETF成交/溢价约束下复现。若结果只来自风险暴露变化而无稳定增量，就保留简单静态配置，不继续扫参。", "",
              "复现：`PYTHONPATH=src .venv/bin/python scripts/research/compare_etf_risk_budget.py --output 新的空目录`。配置、输入/源码hash、所有结果和主情景逐日账本在results.json，无训练或订单路径。"]
    return "\n".join(lines) + "\n"


def run(data_path, output):
    if output.exists():
        raise FileExistsError("use_new_output_directory")
    dataset = load_dataset_from_clean_indices(data_path)
    result = dict(created_at=datetime.now(timezone.utc).isoformat(), research_only=True,
                  orders_authorized=False, promotion_evidence=False,
                  config=dict(start="20140102", volatility_window=20, target_volatility=.15,
                              sample_role="consumed_history_discovery", capitals=[10_000, 100_000, 1_000_000],
                              cases={name: dict(costs=asdict(costs), delay=delay) for name, (costs, delay) in CASES.items()}),
                  input_hashes={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in (data_path, Path(__file__), ROOT / "src/qount/research/etf_risk_budget.py",
                                          ROOT / "src/qount/research/personal_trading_assistant.py")},
                  preliminary=preliminary(dataset), comparisons=[], primary={}, annual={}, periods={}, bootstrap={})
    for symbol in SYMBOLS:
        bars, meta = dataset[symbol], CORE_ETF_UNIVERSE[symbol]
        primary = {}
        # Candidate exposure is observed first solely to construct the diagnostic control.
        diagnostic_weight = simulate(bars, meta, "vol15")["metrics"]["average_weight"]
        result.setdefault("diagnostic_static_weights", {})[symbol] = diagnostic_weight
        for capital in result["config"]["capitals"]:
            for case, (costs, delay) in CASES.items():
                for label in POLICIES:
                    policy = "constant" if label in ("static75", "exposure_matched_diagnostic") else label
                    weight = diagnostic_weight if label == "exposure_matched_diagnostic" else .75
                    replay = simulate(bars, meta, policy, initial_capital=capital, costs=costs,
                                      delay=delay, constant_weight=weight)
                    result["comparisons"].append(dict(symbol=symbol, policy=label, capital=capital,
                                                       case=case, metrics=replay["metrics"]))
                    if capital == 100_000 and case == "base":
                        primary[label] = replay
        result["primary"][symbol] = primary
        result["annual"][symbol] = {str(y): {p: period(r, f"{y}0101", f"{y}1231") for p, r in primary.items()}
                                    for y in range(2014, 2027)}
        result["periods"][symbol] = {f"{a}-{b}": {p: period(r, f"{a}0101", f"{b}1231") for p, r in primary.items()}
                                     for a, b in ((2014, 2017), (2018, 2021), (2022, 2026))}
        result["bootstrap"][symbol] = {p: paired_log_interval(primary["vol15"], primary[p])
                                       for p in ("buy_hold", "static75", "exposure_matched_diagnostic")}
    output.mkdir(parents=True)
    (output / "results.json").write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    (output / "report.md").write_text(markdown(result), encoding="utf-8")
    print(json.dumps(dict(output=str(output), replays=len(result["comparisons"]),
                          primary={s: {p:r["metrics"] for p,r in v.items()} for s,v in result["primary"].items()}), ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data/processed/clean_indices_daily_2013_2026.json")
    parser.add_argument("--output", type=Path, default=ROOT / "state/research_runs/etf_risk_budget_20261025")
    args = parser.parse_args()
    run(args.data.resolve(), args.output.resolve())
