"""Fixed ablations of asset categories, state detail and forecast horizon."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import datetime as dt
import json
from pathlib import Path

import numpy as np

from qount.research.market_state_profiles import (
    CATEGORIES, FEATURE_NAMES, INTERACTION_FEATURES, category_probabilities, causal_shrink,
    profile_samples, quarterly_predictions,
)
from qount.research.market_state_validation import breakout_survival, causal_probabilities, range_containment
from qount.research.market_stages import market_state_machine
from study_binance_market_states import break_events, load_markets
from validate_binance_market_states import clustered_brier_difference, summarize


def date(stamp):
    return dt.datetime.fromtimestamp(stamp,dt.timezone.utc).strftime("%Y-%m-%d")


def describe_categories(markets, states):
    """Same calendar span, each market's actual clock; no return-selected groups."""
    counts=defaultdict(Counter)
    volatility=defaultdict(list)
    spells=defaultdict(list)
    events=defaultdict(list)
    asset_details={}
    for group,book in markets.items():
        for asset,bars in book.items():
            family=CATEGORIES[asset]
            selected=[b for b in bars if "2021-07-20"<=date(b.t)<"2026-01-01"]
            left,right=selected[0].t,selected[-1].t
            a=Counter()
            last,length,started=None,0,None
            for b in selected:
                r=states[group][asset][b.t]
                a[r["structure"]]+=1
                counts[family][r["structure"]]+=1
                counts[family]["observations"]+=1
                counts[family]["shock"]+=int(r["shock"])
                counts[family]["high_vol"]+=int(r["high_vol"])
                volatility[family].append(r["volatility20"]*np.sqrt(365.25 if group=="crypto" else 252))
                if r["structure"]==last:
                    length+=1
                else:
                    # Exclude left/right-censored runs from duration summaries.
                    if last in ("up_trend","down_trend") and started!=left:
                        spells[family].append(length)
                    last,length,started=r["structure"],1,b.t
            finished=break_events(bars,states[group][asset],"2021-07-20")
            for e in finished:
                if e["index"]+3<len(bars) and bars[e["index"]+3].t<=right and not e["censored"]:
                    events[family].append(e)
            asset_details[asset]=dict(category=family,structure_counts=dict(a))
    output=[]
    for family,c in counts.items():
        n=c["observations"]
        e=events[family]
        output.append(dict(category=family,assets=[s for s,v in CATEGORIES.items() if v==family],
            observations=n,up_trend_fraction=c["up_trend"]/n,down_trend_fraction=c["down_trend"]/n,
            range_fraction=sum(c[k] for k in ("compression","range","wide_range"))/n,
            median_annualized_volatility=float(np.median(volatility[family])),
            median_completed_trend_observations=float(np.median(spells[family])) if spells[family] else None,
            break_events=len(e),break_failure_rate=sum(v["failed"] for v in e)/len(e) if e else None))
    return dict(start="2021-07-20",end_exclusive="2026-01-01",by_category=output,by_asset=asset_details)


def paired_comparison(a,b):
    index={(r["asset"],r["known_at"]):r for r in b}
    assert len(index)==len(a)
    records=[]
    for r in a:
        other=index[r["asset"],r["known_at"]]
        assert r["outcome"]==other["outcome"] and r["mature_at"]==other["mature_at"]
        records.append(dict(r,baseline=other["probabilities"]))
    return clustered_brier_difference(records)


def percentage(value):
    return "—" if value is None else f"{value:.2%}"


def write_report(result):
    lines=["# 标的类别与阶段特征：固定模型对照", "",
        "检验类别信息、状态强度/持续时间和预测期限的增量。所有分组在看本次结果前按经济属性固定，不搜索参数。",
        "历史已消费，ETF为信号代理；不宣称独立OOS或策略净收益，不改变任何仓位。", "",
        "## 类别与历史结构差异", "",
        "2021-07-20至2025年末共同日历范围；币种按日历日，ETF按交易日，趋势持续单位为各自观测期。",
        "|类别|标的|观测|上升趋势|下降趋势|区间|中位年化波动|完整趋势段中位期数|突破失败率/事件数|",
        "|---|---|---:|---:|---:|---:|---:|---:|---|"]
    for r in result["descriptive"]["by_category"]:
        lines.append(f"|{r['category']}|{','.join(r['assets'])}|{r['observations']}|{percentage(r['up_trend_fraction'])}|{percentage(r['down_trend_fraction'])}|{percentage(r['range_fraction'])}|{percentage(r['median_annualized_volatility'])}|{r['median_completed_trend_observations']}|{percentage(r['break_failure_rate'])}/{r['break_events']}|")
    lines += ["", "结构相同不代表预测作用相同；单标的类别不提供跨标的泛化证据。以下使用独立未来结果验证。", "",
        "## 相同起点的模型对照", "",
        "5/20期使用同一批每5期起点，末端共同截去20期；因此与前轮样本略不同。20期标签重叠。",
        "每季拟合仅使用季初之前已成熟结果；缩放器只拟合训练样本。C=.1、收缩50固定，不调整类别权重。",
        "state_logit与details_shared分离模型形式/状态细节；details_category仅比details_shared多类别交互斜率，两者已有相同标的ID控制。",
        "adaptive_shared按已成熟预测的Brier选择共同细节模型权重；adaptive_category_weight仅将这个权重按类别收缩，adaptive_category进一步替换成类别交互专家。三者均从pooled_state出发，罚项10固定，同期资产总权重1。",
        "|市场/期限|模型|样本|准确率|平衡准确率|Brier|",
        "|---|---|---:|---:|---:|---:|"]
    for r in result["evaluations"]:
        if r["window"]!="all":continue
        s=r["summary"]["model"]
        lines.append(f"|{r['group']}/{r['horizon']}|{r['model']}|{s['count']}|{percentage(s['accuracy'])}|{percentage(s['balanced_accuracy'])}|{s['brier']:.4f}|")
    lines += ["", "## 同机会概率误差的增量", "",
        "差为左模型Brier−右模型Brier，负数较好；完整季度重采样保留同期相关资产，跨零不认定稳定改善。", "",
        "|市场/期限|对照|Brier差|季度簇95%区间|", "|---|---|---:|---|"]
    for r in result["comparisons"]:
        ci=r["delta"]["interval95"]
        lines.append(f"|{r['group']}/{r['horizon']}|{r['left']}−{r['right']}|{r['delta']['mean']:+.5f}|{('['+f'{ci[0]:+.5f},{ci[1]:+.5f}'+']') if ci else '—'}|")
    lines += ["", "## 各类别的5期结果", "",
        "|类别|模型|样本|准确率|平衡准确率|Brier|", "|---|---|---:|---:|---:|---:|"]
    for r in result["by_category"]:
        if r["horizon"]!=5:continue
        s=r["summary"]["model"]
        lines.append(f"|{r['category']}|{r['model']}|{s['count']}|{percentage(s['accuracy'])}|{percentage(s['balanced_accuracy'])}|{s['brier']:.4f}|")
    lines += ["", "## 类别对阶段维持判断的增量", "",
        "独立检验未来5期区间保持、未来3期突破维持；不以方向预测表现代替状态预测。",
        "|市场/任务|模型|样本|准确率|平衡准确率|Brier|", "|---|---|---:|---:|---:|---:|"]
    for r in result["phase_evaluations"]:
        if r["window"]!="all":continue
        s=r["summary"]["model"]
        lines.append(f"|{r['group']}/{r['task']}|{r['model']}|{s['count']}|{percentage(s['accuracy'])}|{percentage(s['balanced_accuracy'])}|{s['brier']:.4f}|")
    lines += ["", "|市场/任务|类别−共同Brier差|季度簇95%区间|", "|---|---:|---|"]
    for r in result["phase_comparisons"]:
        ci=r["delta"]["interval95"]
        lines.append(f"|{r['group']}/{r['task']}|{r['delta']['mean']:+.5f}|{('['+f'{ci[0]:+.5f},{ci[1]:+.5f}'+']') if ci else '—'}|")
    lines += ["", "## 限制", ""]+["- "+s for s in result["limitations"]]
    lines += ["", "逐年、逐标的、覆盖率、校准和各类增量保留在results.json。",
        "复现：`PYTHONPATH=src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 ./.venv/bin/python scripts/research/compare_market_state_profiles.py --output <新目录>`", ""]
    return "\n".join(lines)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():parser.error("retain prior evidence; choose new output")
    markets,_,sources=load_markets()
    states={g:{s:market_state_machine(bars) for s,bars in book.items()} for g,book in markets.items()}
    descriptive=describe_categories(markets,states)
    evaluations,by_category,by_asset,comparisons,forecasts,fits=[],[],[],[],[],[]
    phase_evaluations,phase_comparisons=[],[]
    for group,book in markets.items():
        start="2023-01-01" if group=="crypto" else "2019-01-01"
        for horizon in (5,20):
            samples=profile_samples(book,states[group],group,horizon)
            pooled=causal_probabilities(samples,3)
            pooled=[r for r in pooled if date(r["known_at"])>=start]
            conditioned=[r for r in category_probabilities(samples) if date(r["known_at"])>=start]
            runs={"asset_prior":[dict(r,probabilities=r["baseline"]) for r in pooled],
                  "pooled_state":pooled,"category_state":conditioned}
            for name,details,categorical in (("state_logit",False,False),("details_shared",True,False),("details_category",True,True)):
                runs[name],training=quarterly_predictions(samples,start,details=details,categorical=categorical)
                fits.append(dict(group=group,horizon=horizon,model=name,quarters=training))
            runs["adaptive_shared"]=causal_shrink(runs["pooled_state"],runs["details_shared"])
            runs["adaptive_category_weight"]=causal_shrink(runs["pooled_state"],runs["details_shared"],category_aware=True)
            runs["adaptive_category"]=causal_shrink(runs["pooled_state"],runs["details_category"],category_aware=True)
            print(group,horizon,'models fitted',len(pooled),'origins',flush=True)
            for name,records in runs.items():
                assert len(records)==len(pooled)
                for record in records:
                    assert record["last_training_maturity"] is None or record["last_training_maturity"]<record["known_at"]
                windows=[("all",start,"9999")]+[(str(y),f"{y}-01-01",f"{y+1}-01-01") for y in range(int(start[:4]),2027 if group=="crypto" else 2026)]
                for window,left,right in windows:
                    selected=[r for r in records if left<=date(r["known_at"])<right and date(r["mature_at"])<right]
                    if selected:evaluations.append(dict(group=group,horizon=horizon,model=name,window=window,summary=summarize(selected)))
                for category in sorted({r["category"] for r in records}):
                    selected=[r for r in records if r["category"]==category]
                    by_category.append(dict(group=group,horizon=horizon,model=name,category=category,summary=summarize(selected)))
                for asset in sorted(book):
                    selected=[r for r in records if r["asset"]==asset]
                    by_asset.append(dict(group=group,horizon=horizon,model=name,asset=asset,summary=summarize(selected)))
                forecasts.append(dict(group=group,horizon=horizon,model=name,
                    records=[{k:v for k,v in r.items() if k not in ("features",)} for r in records]))
            for left,right in (("category_state","pooled_state"),("details_shared","state_logit"),
                               ("details_category","details_shared"),("details_category","asset_prior"),
                               ("adaptive_shared","pooled_state"),("adaptive_category_weight","adaptive_shared"),
                               ("adaptive_category","adaptive_category_weight")):
                comparisons.append(dict(group=group,horizon=horizon,left=left,right=right,delta=paired_comparison(runs[left],runs[right])))
        for task,build in (("range5",range_containment),("break_survival3",breakout_survival)):
            samples=[dict(r,asset=asset,category=CATEGORIES[asset])
                     for asset,bars in book.items() for r in build(bars,states[group][asset])]
            pooled=[r for r in causal_probabilities(samples,2) if date(r["known_at"])>=start]
            conditioned=[r for r in category_probabilities(samples,classes=2) if date(r["known_at"])>=start]
            runs={"asset_prior":[dict(r,probabilities=r["baseline"]) for r in pooled],
                  "pooled_state":pooled,"category_state":conditioned}
            phase_comparisons.append(dict(group=group,task=task,delta=paired_comparison(conditioned,pooled)))
            for name,records in runs.items():
                windows=[("all",start,"9999")]+[(str(y),f"{y}-01-01",f"{y+1}-01-01") for y in range(int(start[:4]),2027 if group=="crypto" else 2026)]
                for window,left,right in windows:
                    selected=[r for r in records if left<=date(r["known_at"])<right and date(r["mature_at"])<right]
                    if selected:phase_evaluations.append(dict(group=group,task=task,model=name,window=window,summary=summarize(selected)))
                forecasts.append(dict(group=group,task=task,model=name,records=records))
            print(group,task,'category check',len(pooled),flush=True)
    result=dict(research_only=True,orders_authorized=False,independent_oos=False,
        categories=CATEGORIES,features=list(FEATURE_NAMES),category_interactions=[FEATURE_NAMES[i] for i in INTERACTION_FEATURES],
        assumptions=dict(C=.1,prior_strength=50,online_shrink_penalty=10,refit="quarterly, strict prior label maturity",
            horizons=[5,20],origin_stride=5,common_terminal_trim=20,parameter_search=False),
        descriptive=descriptive,evaluations=evaluations,by_category=by_category,by_asset=by_asset,
        comparisons=comparisons,phase_evaluations=phase_evaluations,phase_comparisons=phase_comparisons,
        fits=fits,sources=sources,
        limitations=[
            "类别按经济属性固定，是研究假设；BTC/ETH与其他缓存币不是按未来市值/收益分组；非完整市场分类。",
            "XLE属于能源企业权益，不与原油合并；SMH/XLE同属行业权益但经济驱动不同，类别内仍可能异质。",
            "黄金/铜/油每类仅一个原生映射代理，类别效应不能与该标的特效分离，不宣称类别可外推。",
            "所有已消费历史、当前存续名单、代理复权和原生合约数据不足等前轮限制保留。",
            "共同日历范围下币种仍按日历日、ETF按交易日；5期或20期不是相同自然日长度。",
            "20期目标使用每5期起点，标签存在重叠；季度簇区间未校正模型/类别/期限多重比较。",
            "固定简单正则模型也可能失配；加入类别未改善不证明经济驱动相同，改善也不证明因果。",
            "高准确率、中性多数类和概率校准须一起检查，阈值覆盖率不作为资金比例。",
            "本轮只做市场预测模型研究，不模拟收益/成本/仓位，不更新实盘、权限或服务。" ])
    args.output.mkdir(parents=True)
    (args.output/"results.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n")
    (args.output/"predictions.json").write_text(json.dumps(forecasts,ensure_ascii=False,allow_nan=False)+"\n")
    (args.output/"report.md").write_text(write_report(result))
    print(json.dumps(dict(output=str(args.output),comparisons=len(comparisons),models=9)))


if __name__=="__main__":main()
