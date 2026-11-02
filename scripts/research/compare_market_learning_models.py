"""Fixed chronological ML/tree/neural pilots on the saved daily market panel."""
from __future__ import annotations

import argparse
from collections import defaultdict
import datetime as dt
import json
from pathlib import Path

import numpy as np

from qount.research.market_learning import behavior_features, fit_behavior, fit_candidate, model_matrix, range_geometry_from_distances
from qount.research.market_state_profiles import causal_shrink
from qount.research.market_state_validation import causal_probabilities, scores
from compare_market_state_profiles import paired_comparison
from validate_binance_market_states import summarize


def date(t):return dt.datetime.fromtimestamp(int(t),dt.timezone.utc).strftime("%Y-%m-%d")
def pct(v):return "—" if v is None else f"{v:.2%}"


def write_report(result):
    lines=["# 数据集上的机器学习与小型神经网络对照", "",
        "预测未来结果，经济类别与行为类别作为已知条件；不训练网络复述当前人工状态标签。",
        "所有历史已消费，以下是时间顺序计算的探索结果，不是独立OOS或收益回测。", "",
        "## 实验设定", "",
        "- 从2023起逐季预测；训练只用目标在季初前已经成熟的样本。每标的每5期取一个起点。",
        "- 特征填补、缩放只拟合训练部分；无随机验证切分、无测试集早停、无参数搜索。",
        "- 逻辑回归C=.1；直方图树80轮/最多7叶/最小叶60/L2=10；MLP为32→16隐层、固定40轮、L2=1。",
        "- MLP固定三个种子17/29/41，报告平均概率与全部种子表现，不挑最好种子。40轮是资源上限，不声称数值优化收敛。",
        "- 行为簇每季仅在此前可见的风格数据拟合；相同风格已在基础特征中，增量仅检验非线性表征。",
        "- 概率收缩仅看已成熟的既往预测误差，不将混合权重当作仓位。", "",
        "- range_geometry用同样已知的上下边界距离与sigma20，固定2048条零漂移高斯路径预测5次收盘保持区间；它是统计基线，不是市场真模型。", "",
        "|市场/目标|模型|样本|准确率|平衡准确率|Brier↓|", "|---|---|---:|---:|---:|---:|"]
    for r in result["evaluations"]:
        if r["window"]!="all":continue
        s=r["summary"]["model"]
        lines.append(f"|{r['group']}/{r['target']}|{r['model']}|{s['count']}|{pct(s['accuracy'])}|{pct(s['balanced_accuracy'])}|{s['brier']:.4f}|")
    lines += ["", "## 同机会增量", "",
        "差为左模型Brier减右模型Brier，负值较好。季度簇区间保留同时期相关资产，不校正多重比较。", "",
        "|市场/目标|对照|Brier差|95%区间|", "|---|---|---:|---|"]
    for r in result["comparisons"]:
        c=r["delta"]["interval95"]
        lines.append(f"|{r['group']}/{r['target']}|{r['left']}−{r['right']}|{r['delta']['mean']:+.5f}|{f'[{c[0]:+.5f},{c[1]:+.5f}]' if c else '—'}|")
    lines += ["", "## 神经网络种子敏感性", "",
        "|市场/目标|种子|准确率|平衡准确率|Brier|", "|---|---:|---:|---:|---:|"]
    for r in result["neural_seeds"]:
        s=r["scores"]
        lines.append(f"|{r['group']}/{r['target']}|{r['seed']}|{pct(s['accuracy'])}|{pct(s['balanced_accuracy'])}|{s['brier']:.4f}|")
    lines += ["", "## 方法裁决的边界", ""]+["- "+s for s in result["limitations"]]
    return "\n".join(lines)+"\n"


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():parser.error("preserve earlier experiment; choose new output")
    with np.load(args.dataset,allow_pickle=False) as loaded:data={k:loaded[k] for k in loaded.files}
    matrix=model_matrix(data)
    train_stride=data["bar_index"]%5==0
    evaluations,comparisons,forecasts,fits,seed_results=[],[],[],[],[]
    behavior_cache={}
    for group in ("crypto","etf_proxy"):
        for column,target,classes in ((0,"direction5",3),(2,"range5",2)):
            valid=(data["group"]==group)&train_stride&(data["y"][:,column]>=0)
            indices=np.flatnonzero(valid)
            samples=[dict(asset=str(data["asset"][i]),category=str(data["economic_category"][i]),
                known_at=int(data["known_at"][i]),mature_at=int(data["maturity"][i,column]),
                key=str(data["state"][i]),outcome=int(data["y"][i,column]),index=int(i),
                actionable=bool(data["route_class"][i]>=0),
                route_class=int(data["route_class"][i]) if column==0 and data["route_class"][i]>=0 else None,
                fixed_prediction=None) for i in indices]
            base=causal_probabilities(samples,classes)
            test_base=[r for r in base if date(r["known_at"])>="2023-01-01"]
            lookup={r["index"]:r for r in test_base}
            runs={"asset_prior":[dict(r,probabilities=r["baseline"]) for r in test_base],"pooled_state":test_base,
                  "linear":[],"tree":[],"tree_behavior":[],"mlp_ensemble":[]}
            neural={seed:[] for seed in (17,29,41)}
            quarters=defaultdict(list)
            for r in test_base:
                local=dt.datetime.fromtimestamp(r["known_at"],dt.timezone.utc)
                quarters[local.year,(local.month-1)//3*3+1].append(r["index"])
            for (year,month),test in sorted(quarters.items()):
                cutoff=int(dt.datetime(year,month,1,tzinfo=dt.timezone.utc).timestamp())
                train=np.flatnonzero(valid&(data["maturity"][:,column]<cutoff))
                if len(train)<200 or len(np.unique(data["y"][train,column]))!=classes:
                    raise ValueError("insufficient_learning_fold")
                if cutoff not in behavior_cache:
                    clustering=np.flatnonzero((data["known_at"]<cutoff)&(data["bar_index"]%20==5))
                    behavior_cache[cutoff]=fit_behavior(data,clustering)
                behavior=behavior_cache[cutoff]
                train_behavior,_=behavior_features(data,train,behavior)
                test_behavior,_=behavior_features(data,np.array(test),behavior)
                for name,kind,seed_list in (("linear","linear",(17,)),("tree","tree",(17,)),
                    ("tree_behavior","tree",(17,)),("mlp_ensemble","mlp",(17,29,41))):
                    a=np.c_[matrix[train],train_behavior] if name=="tree_behavior" else matrix[train]
                    b=np.c_[matrix[test],test_behavior] if name=="tree_behavior" else matrix[test]
                    probabilities=[]
                    for seed in seed_list:
                        model,diagnostics=fit_candidate(kind,a,data["y"][train,column],seed=seed)
                        p=model.predict_proba(b)
                        if list(model[-1].classes_)!=list(range(classes)):raise ValueError("learning_class_mismatch")
                        probabilities.append(p)
                        latest=int(data["maturity"][train,column].max())
                        cluster_latest=int(data["known_at"][behavior["training_indices"]].max())
                        assert latest<cutoff and cluster_latest<cutoff
                        fits.append(dict(group=group,target=target,model=name,cutoff=cutoff,
                            training_samples=len(train),last_training_maturity=latest,
                            last_cluster_feature=cluster_latest,**diagnostics))
                        if name=="mlp_ensemble":
                            neural[seed]+=[dict(lookup[i],probabilities=row.tolist(),model_fit_cutoff=cutoff)
                                           for i,row in zip(test,p)]
                    mean=np.mean(probabilities,axis=0)
                    runs[name]+=[dict(lookup[i],probabilities=p.tolist(),model_fit_cutoff=cutoff)
                                 for i,p in zip(test,mean)]
                print(group,target,year,month,'train',len(train),'test',len(test),flush=True)
            runs["tree_shrunk"]=causal_shrink(runs["pooled_state"],runs["tree"])
            runs["mlp_shrunk"]=causal_shrink(runs["pooled_state"],runs["mlp_ensemble"])
            if target=="range5":
                names=list(data["feature_names"])
                lower=names.index("lower_boundary_distance_sigma20")
                upper=names.index("upper_boundary_distance_sigma20")
                geometric=[]
                for row in test_base:
                    p=range_geometry_from_distances(float(data["X"][row["index"],lower]),float(data["X"][row["index"],upper]))
                    geometric.append(dict(row,probabilities=[1-p,p]))
                runs["range_geometry"]=geometric
            for name,records in runs.items():
                if len(records)!=len(test_base):raise ValueError("learning_origins_mismatch")
                years=sorted({date(r["known_at"])[:4] for r in records})
                for window in ["all"]+years:
                    selected=records if window=="all" else [r for r in records if date(r["known_at"]).startswith(window)
                        and date(r["mature_at"])<str(int(window)+1)+"-01-01"]
                    if selected:evaluations.append(dict(group=group,target=target,model=name,window=window,summary=summarize(selected)))
                forecasts.append(dict(group=group,target=target,model=name,records=records))
            for seed,records in neural.items():seed_results.append(dict(group=group,target=target,seed=seed,scores=scores(records)))
            contrasts=[("linear","pooled_state"),("tree","linear"),("tree_behavior","tree"),
                ("mlp_ensemble","linear"),("mlp_ensemble","tree"),("tree_shrunk","pooled_state"),("mlp_shrunk","pooled_state")]
            if target=="range5":contrasts += [("tree","range_geometry"),("mlp_ensemble","range_geometry")]
            for left,right in contrasts:
                comparisons.append(dict(group=group,target=target,left=left,right=right,delta=paired_comparison(runs[left],runs[right])))
    result=dict(research_only=True,orders_authorized=False,independent_oos=False,dataset=str(args.dataset),
        evaluations=evaluations,comparisons=comparisons,fits=fits,neural_seeds=seed_results,
        parameters=dict(MLP_hidden=[32,16],MLP_epochs=40,seeds=[17,29,41],tree_iterations=80,tree_leaves=7,
                        train_stride=5,refit="quarterly",evaluation_start="2023-01-01",parameter_search=False),
        limitations=[
            "NN属于监督机器学习的一类，本轮是小型MLP；不将结果外推为所有神经网络/序列模型的结论。",
            "行为聚类只定义相似历史行为，轮廓系数/Rand稳定性不等于自然类别真值或未来准确率。",
            "经济分类和行为分类未作为监督目标；未来方向/区间任务避免把复述规则当预测成功。",
            "缺失模式也可能编码数据年代与标的身份；OI覆盖有限，不能把其贡献与缺失机制混同。",
            "历史已消费、固定存续名单、代理行情和假定发布时点继续限制结论；未做独立新市场/新标的验证。",
            "模型只评价预测，未计成本、仓位、成交和账户风险；不称策略收益，不据概率调整仓位。",
            "RL优化状态—动作—奖励的序列决策，可研究空仓/部分持仓/加减仓；本数据尚缺完整执行/账户/成本环境，当前不训练RL。",
            "RL不要求先有高准确率分类器，但环境失真会使奖励与交易目标错位；不能用RL替代数据和撮合正确性。",
            "神经网络固定轮数不代表优化收敛，三个种子均保留；多模型/目标比较未校正，季度簇区间只作探索证据。" ])
    args.output.mkdir(parents=True)
    (args.output/"results.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n")
    (args.output/"predictions.json").write_text(json.dumps(forecasts,ensure_ascii=False,allow_nan=False)+"\n")
    (args.output/"report.md").write_text(write_report(result))
    print(json.dumps(dict(output=str(args.output),fold_fits=len(fits))))


if __name__=="__main__":main()
