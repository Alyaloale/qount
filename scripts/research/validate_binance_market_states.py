"""Validate market-state reliability before any position or profit optimization."""
from __future__ import annotations

import argparse
from collections import defaultdict
import datetime as dt
import json
from pathlib import Path

import numpy as np

from qount.research.market_stages import market_state_machine
from qount.research.market_state_validation import (
    breakout_survival, causal_probabilities, future_direction, range_containment, scores,
)
from qount.research_data.bars import Bar
from study_binance_market_states import load_markets


def signature(row):
    event = row.get("event")
    return (row["action_state"], row["structure"], row["route_side"],
            None if event is None else (event["status"], event["started_at"], event["side"]))


def integrity_checks(book, states):
    prefix, scale = [], []
    calendar = [b.t for b in next(iter(book.values()))]
    for symbol, bars in book.items():
        for end in sorted({max(220, len(bars)//2), len(bars)*3//4, len(bars)-20}):
            short = market_state_machine(bars[:end])
            prefix.append(dict(symbol=symbol, cutoff=bars[end-1].t,
                matched=all(short[b.t]==states[symbol][b.t] for b in bars[:end])))
        for factor in (.001, 1000.):
            rescaled = [Bar(b.t, b.o*factor, b.h*factor, b.l*factor, b.c*factor, b.v) for b in bars]
            changed = market_state_machine(rescaled)
            mismatches = [b.t for b in bars if signature(changed[b.t]) != signature(states[symbol][b.t])]
            scale.append(dict(symbol=symbol, factor=factor, mismatches=len(mismatches), examples=mismatches[:5]))
    return dict(prefix_checks=prefix, scale_checks=scale,
        shared_calendar=all([b.t for b in bars]==calendar for bars in book.values()),
        invalid_volumes=sum(b.v < 0 for bars in book.values() for b in bars),
        zero_volume_observations=sum(b.v == 0 for bars in book.values() for b in bars))


def clustered_brier_difference(records):
    """Resample complete calendar quarters, retaining simultaneous assets."""
    groups = defaultdict(list)
    for r in records:
        date = dt.datetime.fromtimestamp(r["known_at"], dt.timezone.utc).date()
        actual = np.eye(len(r["probabilities"]))[r["outcome"]]
        delta = np.sum((np.array(r["probabilities"])-actual)**2)-np.sum((np.array(r["baseline"])-actual)**2)
        groups[f"{date.year}Q{(date.month-1)//3+1}"].append(delta)
    if not groups:
        return None
    sums = np.array([sum(v) for v in groups.values()])
    counts = np.array([len(v) for v in groups.values()])
    result = dict(mean=float(sums.sum()/counts.sum()), quarter_clusters=len(groups), interval95=None)
    if len(groups) >= 4:
        draws = np.random.default_rng(301026).integers(0,len(groups),(3000,len(groups)))
        delta = sums[draws].sum(axis=1)/counts[draws].sum(axis=1)
        result["interval95"] = np.quantile(delta,[.025,.975]).tolist()
    return result


def summarize(records):
    if not records:
        return None
    rule = [r for r in records if r["fixed_prediction"] is not None]
    simple = [r for r in records if r.get("simple_prediction") is not None]
    intended = []
    for key in sorted({r["key"] for r in records}):
        selected = [r for r in rule if r["key"]==key]
        if selected:
            intended.append(dict(key=key, count=len(selected),
                hit_rate=sum(r["fixed_prediction"]==r["outcome"] for r in selected)/len(selected)))
    selective = []
    actionable = [r for r in records if r["actionable"] and r["route_class"] is not None]
    for threshold in (.5,.6,.7):
        selected = [r for r in actionable if r["probabilities"][r["route_class"]] >= threshold]
        selective.append(dict(threshold=threshold, count=len(selected),
            coverage=len(selected)/len(records),
            actionable_coverage=len(selected)/len(actionable) if actionable else 0.,
            hit_rate=sum(r["outcome"]==r["route_class"] for r in selected)/len(selected) if selected else None,
            mean_probability=float(np.mean([r["probabilities"][r["route_class"]] for r in selected])) if selected else None))
    return dict(model=scores(records), baseline=scores(records,"baseline"),
        brier_difference=clustered_brier_difference(records),
        fixed_rule=dict(count=len(rule), coverage=len(rule)/len(records),
            accuracy=sum(r["fixed_prediction"]==r["outcome"] for r in rule)/len(rule) if rule else None,
            baseline_accuracy_same_origins=sum(int(np.argmax(r["baseline"]))==r["outcome"] for r in rule)/len(rule) if rule else None),
        simple_ema50_accuracy=sum(r["simple_prediction"]==r["outcome"] for r in simple)/len(simple) if simple else None,
        by_state=intended, selective_direction=selective)


def percent(value):
    return "—" if value is None else f"{value:.2%}"


def report(result):
    lines = ["# 市场状态模型可靠性验证", "",
        "先验证市场建模与判断，再研究空仓/部分持仓/加仓/减仓。没有交易策略或仓位参数优化。",
        "十种描述性状态没有天然真值；本次用另外定义的未来可观察事件评分，不把均线条件自洽称作预测正确。",
        "历史已被使用，本轮只保证计算按时间顺序，不宣称独立样本外认证。", "",
        "## 数据和因果实现", ""]
    for group, checks in result["integrity"].items():
        lines.append(f"- {group}：历史前缀{sum(c['matched'] for c in checks['prefix_checks'])}/{len(checks['prefix_checks'])}一致；价格尺度变化{sum(c['mismatches']==0 for c in checks['scale_checks'])}/{len(checks['scale_checks'])}一致；共同日期{checks['shared_calendar']}。")
    for check in result["source_spotchecks"]:
        lines.append(f"- 官方档案抽查{check['symbol']} {check['date']}：{check['status']}；仅验证该条日线，源URL及hash保留在results.json。")
    lines += ["",
        "## 未来结果预测", "",
        "方向任务为未来5期收盘位移超出±0.5×已知sigma20×sqrt(5)；中性仅指终点位移小，不等同震荡路径。",
        "区间任务要求未来5期所有收盘留在原20期边界内；突破任务从初次观察/首次确认分别预测其后3期守住边界。",
        "方向和区间任务按事前固定每5期取样；突破初次/确认存在重叠，季度簇区间保留同期相关资产。",
        "概率仅用严格早于决策时点成熟的标签；固定状态频率向资产历史频率收缩50个伪观测。未调整参数。", "",
        "|市场/任务/窗口|样本|模型准确率|历史频率基线|模型平衡准确率|基线平衡准确率|模型Brier|基线Brier|Brier差95%区间|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for case in result["evaluations"]:
        s=case["summary"]
        if s is None:
            continue
        ci=s["brier_difference"]["interval95"]
        label="—" if ci is None else f"[{ci[0]:+.4f},{ci[1]:+.4f}]"
        lines.append(f"|{case['group']}/{case['task']}/{case['window']}|{s['model']['count']}|{percent(s['model']['accuracy'])}|{percent(s['baseline']['accuracy'])}|{percent(s['model']['balanced_accuracy'])}|{percent(s['baseline']['balanced_accuracy'])}|{s['model']['brier']:.4f}|{s['baseline']['brier']:.4f}|{label}|")
    lines += ["", "平衡准确率为各真实类别召回率的平均，揭示总猜多数类造成的虚高准确率。Brier为各类别概率平方误差之和，越低越好；差=模型−基线，区间跨零不构成稳定改善证据。", "",
        "## 原状态规则的含义与方向覆盖率", ""]
    for case in result["evaluations"]:
        if case["task"]!="direction5" or case["window"]!="all":
            continue
        s=case["summary"]
        lines += [f"### {case['group']}", "", f"规则断言准确率{percent(s['fixed_rule']['accuracy'])}，在相同起点的历史频率基线为{percent(s['fixed_rule']['baseline_accuracy_same_origins'])}；规则断言覆盖{percent(s['fixed_rule']['coverage'])}。", "",
            "|状态|样本|对应未来结果命中率|", "|---|---:|---:|"]
        lines += [f"|{r['key']}|{r['count']}|{percent(r['hit_rate'])}|" for r in s['by_state']]
        lines += ["", "|方向概率阈值|样本|全部覆盖|可触发样本覆盖|命中率|平均预测概率|", "|---:|---:|---:|---:|---:|---:|"]
        lines += [f"|{r['threshold']:.0%}|{r['count']}|{percent(r['coverage'])}|{percent(r['actionable_coverage'])}|{percent(r['hit_rate'])}|{percent(r['mean_probability'])}|" for r in s['selective_direction']]
    lines += ["", "## 限制与动作边界", ""]+["- "+line for line in result["limitations"]]
    lines += ["", "复现：`PYTHONPATH=src ./.venv/bin/python scripts/research/validate_binance_market_states.py --output <新目录>`", ""]
    return "\n".join(lines)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--source-spotchecks",type=Path)
    args=parser.parse_args()
    if args.output.exists():
        parser.error("retain prior evidence; choose a new output")
    markets,_,sources=load_markets()
    integrity,predictions={},[]
    cases=[]
    for group,book in markets.items():
        states={s:market_state_machine(bars) for s,bars in book.items()}
        integrity[group]=integrity_checks(book,states)
        start="2023-01-01" if group=="crypto" else "2019-01-01"
        for task,build,classes in (("direction5",future_direction,3),
                                   ("range5",range_containment,2),
                                   ("break_survival3",breakout_survival,2)):
            samples=[]
            for asset,bars in book.items():
                for sample in build(bars,states[asset]):
                    row=states[asset][sample['known_at']]
                    simple=2 if row['close']>row['ema50'] else 0
                    samples.append(dict(sample,asset=asset,simple_prediction=simple if classes==3 else None))
            output=causal_probabilities(samples,classes)
            for row in output:
                assert row['last_training_maturity'] is None or row['last_training_maturity']<row['known_at']
                assert row['known_at']<row['mature_at']
            selected=[r for r in output if dt.datetime.fromtimestamp(r['known_at'],dt.timezone.utc).strftime('%Y-%m-%d')>=start]
            windows=[('all',start,'9999')]+[(str(year),f'{year}-01-01',f'{year+1}-01-01')
                       for year in range(int(start[:4]),2027 if group=='crypto' else 2026)]
            for window,left,right in windows:
                rows=[r for r in selected if left<=dt.datetime.fromtimestamp(r['known_at'],dt.timezone.utc).strftime('%Y-%m-%d')<right
                      and dt.datetime.fromtimestamp(r['mature_at'],dt.timezone.utc).strftime('%Y-%m-%d')<right]
                cases.append(dict(group=group,task=task,window=window,summary=summarize(rows)))
            predictions.append(dict(group=group,task=task,records=selected))
            print(group,task,len(selected),'chronological predictions',flush=True)
    checks=json.loads(args.source_spotchecks.read_text()) if args.source_spotchecks else []
    result=dict(research_only=True,orders_authorized=False,independent_oos=False,
        integrity=integrity,source_spotchecks=checks,sources=sources,evaluations=cases,
        assumptions=dict(prior_strength=50.,direction_horizon=5,range_horizon=5,break_horizon=3,
            neutral_threshold_known_sigma_multiplier=.5,classification_only=True,
            crypto_evaluation_start='2023-01-01',etf_proxy_evaluation_start='2019-01-01'),
        limitations=[
            "代码因果与尺度一致不等于经济模型真实或预测准确；十种状态没有外部十分类真值。",
            "价格档案抽查只有三条日线，不覆盖全部行情、资金费、复权历史和ETF跨源真实性。",
            "固定存续名单、复权代理、历史已消费及早期资金费标记价格近似等原限制继续保留。",
            "Brier/准确率评价未来结果；不包含净收益、止损、亏损幅度、成本、成交容量或仓位。",
            "每资产不重叠方向/区间标签仍有跨资产相关；突破初次/确认还存在同事件重叠。季度簇区间不校正多重比较。",
            "确认后未来3期与初次观察后未来3期从不同日期开始，不能将两组之差解释成同机会确认增益。",
            "高概率阈值可能只有少量或没有样本；同时保留覆盖率和概率校准，不保证高正确率。",
            "允许空仓、部分持仓、加仓、减仓和维持；模型/净优势未经验证，不将任何概率或risk_scale直接映射为资金比例。",
            "加仓必须复核新信息、总风险、相关暴露和执行成本；不得自动摊平亏损或重置原风险预算；本轮不实现交易或仓位改动。" ])
    args.output.mkdir(parents=True)
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    (args.output/'predictions.json').write_text(json.dumps(predictions,ensure_ascii=False,allow_nan=False)+'\n')
    (args.output/'report.md').write_text(report(result))
    print(json.dumps(dict(output=str(args.output),evaluation_rows=len(cases))))


if __name__=='__main__':
    main()
