"""Explain enriched-model regression and test bounded probability refinements."""
from __future__ import annotations

import argparse
from collections import defaultdict
import datetime as dt
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from qount.research.market_learning import fit_candidate,model_matrix,range_geometry_from_distances
from qount.research.market_probability_refinement import (
    COMPACT_FEATURES,OFFSET_FEATURES,fit_geometry_offset,predict_geometry_offset,permute_context_dates,
)
from qount.research.market_feature_enrichment import FIELDS
from qount.research.market_state_profiles import causal_shrink
from qount.research.market_state_validation import causal_probabilities,scores
from compare_market_feature_sets import TASKS,date,fold_indices,records
from compare_market_state_profiles import paired_comparison


TREES=('legacy_tree','enriched_tree','strong_tree','compact_tree','no_context_tree','recent_tree','permuted_context_tree')


def make_matrices(data):
    names=list(map(str,data['feature_names']));use=data['default_feature_mask']
    old=use.copy();old[45:]=False
    compact=np.array([n in COMPACT_FEATURES for n in names])
    families={name:group for name,group,*_ in FIELDS}
    context=np.array([families.get(n) in ('macro_context','global_context') for n in names])&use
    full=model_matrix(data)
    subset=np.flatnonzero(use);positions=np.flatnonzero(context[subset])
    columns=np.r_[positions,positions+len(subset)]
    matrices=dict(legacy_tree=model_matrix(data,feature_mask=old),enriched_tree=full,strong_tree=full,
        compact_tree=model_matrix(data,feature_mask=compact,include_asset=False,include_category=False,state_detail=None),
        no_context_tree=model_matrix(data,feature_mask=use&~context),permuted_context_tree=full)
    matrices['recent_tree']=matrices['legacy_tree']
    return matrices,columns


def probability(model,values,classes):
    result=np.zeros((len(values),classes))
    result[:,model[-1].classes_.astype(int)]=model.predict_proba(values)
    if not np.all(np.isfinite(result)) or not np.allclose(result.sum(axis=1),1):raise ValueError('invalid_refined_probability')
    return result


def report(r):
    lines=['# 模型退化原因与概率优化实验','',
        '离线、已消费历史；固定机制对照，无超参数网格，不作为独立OOS或盈利证据。','',
        '## 假设与实现','',
        '- 新增上下文可能提高训练拟合、降低跨时期泛化：记录训练/预测Brier，并作过去训练日期整体置换负对照。',
        '- 信息维度相对独立时点过多：比较8特征小树；强正则臂深度1/2叶/最小叶120/L2=50，其余树沿用80轮/7叶/最小叶60/L2=10。',
        '- 长历史关系可能失效：仅最近3日历年训练旧特征树，与扩展窗口比较。',
        '- 区间几何已有主要信息：比较仅截距和四风险特征的logistic offset，固定L2=20，不重新学习边界。',
        '- 不可靠专家概率需要收缩：方向锚为因果状态频率，区间锚为固定几何概率；权重只用严格已成熟的历史逐期预测，日期等权、固定罚项10，初始权重0。',
        '- MLP仅复用此前已保存三种子平均预测，检验收缩，不重新训练NN。置换臂仅诊断，不参与概率收缩或候选选择。','',
        '## 主要结果','',
        '|市场/目标|模型|样本|准确率|平衡准确率|Brier↓|校准误差|',
        '|---|---|---:|---:|---:|---:|---:|']
    for e in r['evaluations']:
        if e['window']!='all':continue
        s=e['scores'];lines.append(f"|{e['group']}/{e['target']}|{e['model']}|{s['count']}|{s['accuracy']:.2%}|{s['balanced_accuracy']:.2%}|{s['brier']:.5f}|{s['expected_calibration_error']:.4f}|")
    lines+=['','## 相同预测起点的差异','',
        '差为左模型Brier减右模型Brier，负值较好；季度簇95%区间未校正多重比较。','',
        '|市场/目标|对照|Brier差|95%区间|','|---|---|---:|---|']
    for c in r['comparisons']:
        ci=c['delta']['interval95']
        lines.append(f"|{c['group']}/{c['target']}|{c['left']} − {c['right']}|{c['delta']['mean']:+.5f}|{f'[{ci[0]:+.5f},{ci[1]:+.5f}]' if ci else '不足'}|")
    lines+=['','## 训练与后续误差诊断','',
        '下表的训练/预测误差均按每折测试行数加权，以配对比较同一批折；仅训练列是样本内。训练历史重复，不将训练行当独立样本。','',
        '|市场/目标|模型|训练Brier|后续Brier|差距|','|---|---|---:|---:|---:|']
    cells=defaultdict(list)
    for f in r['fits']:cells[f['group'],f['target'],f['model']].append(f)
    for (g,t,m),folds in cells.items():
        train=np.average([f['train_brier'] for f in folds],weights=[f['test_rows'] for f in folds])
        test=np.average([f['test_brier'] for f in folds],weights=[f['test_rows'] for f in folds])
        lines.append(f'|{g}/{t}|{m}|{train:.5f}|{test:.5f}|{test-train:+.5f}|')
    lines+=['','## 概率收缩权重','',
        '|市场/目标|专家|平均权重|最后权重|','|---|---|---:|---:|']
    for w in r['weights']:lines.append(f"|{w['group']}/{w['target']}|{w['model']}|{w['mean']:.3f}|{w['last']:.3f}|")
    lines+=['','## 资源、复核与限制','',
        f"实际新拟合{len(r['fits'])}次，耗时{r['elapsed_seconds']:.1f}秒。预测、年度/类别诊断、全部折时点和offset系数分别保存在predictions.npz/results.json。",'']
    lines+=['- '+s for s in r['limitations']]
    lines+=['','## 实际预测起点范围','']
    for b in r.get('evaluation_bounds',[]):
        lines.append(f"- {b['group']}/{b['target']}：{date(b['first_known_at'])}至{date(b['last_known_at'])}（UTC决策日期）。")
    lines+=['','预测分类未模拟资金账户，初始资金、交易成本、CAGR/MDD不适用。']
    lines+=['','参考：[概率校准与数据隔离](https://scikit-learn.org/stable/modules/calibration.html)、[树正则参数](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingClassifier.html)。']
    return '\n'.join(lines)+'\n'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dataset',type=Path,required=True)
    p.add_argument('--previous',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():p.error('retain prior experiments; choose a new output')
    started=time.monotonic()
    with np.load(args.dataset,allow_pickle=False) as z:data={k:z[k] for k in z.files}
    with np.load(args.previous/'predictions.npz',allow_pickle=False) as z:cached={k:z[k] for k in z.files}
    prior_result=json.loads((args.previous/'results.json').read_text())
    if prior_result['dataset_sha256']!=hashlib.sha256(args.dataset.read_bytes()).hexdigest():raise ValueError('prior_dataset_mismatch')
    cache={}
    for rid,name in enumerate(cached['run_names']):
        mask=cached['run_id']==rid
        cache[str(name)]=(cached['row_index'][mask],cached['probabilities'][mask])
    matrix,context_columns=make_matrices(data)
    offset_columns=[list(data['feature_names']).index(k) for k in OFFSET_FEATURES]
    geometry=np.full(len(data['X']),np.nan)
    lo=list(data['feature_names']).index('lower_boundary_distance_sigma20')
    hi=list(data['feature_names']).index('upper_boundary_distance_sigma20')
    for i in np.flatnonzero(data['y'][:,2]>=0):
        geometry[i]=range_geometry_from_distances(float(data['X'][i,lo]),float(data['X'][i,hi]))
    fits=[];evaluations=[];comparisons=[];weights=[];predictions=[];run_names=[];diagnostics=[];checks=[];bounds=[]
    for group in ('crypto','etf_proxy'):
        for column,target,classes in (TASKS[0],TASKS[2]):
            valid=(data['group']==group)&(data['bar_index']%5==0)&(data['y'][:,column]>=0)
            baseline=causal_probabilities(records(data,np.flatnonzero(valid),column),classes)
            test_base=[r for r in baseline if date(r['known_at'])>='2023-01-01']
            bounds.append(dict(group=group,target=target,first_known_at=min(r['known_at'] for r in test_base),
                               last_known_at=max(r['known_at'] for r in test_base)))
            lookup={r['index']:r for r in test_base}
            runs={name:[] for name in TREES}
            runs['asset_prior']=[dict(r,probabilities=r['baseline']) for r in test_base]
            runs['anchor']=[dict(r,probabilities=[1-geometry[r['index']],geometry[r['index']]]) if target=='range5' else dict(r) for r in test_base]
            runs['mlp_cached']=[]
            rows,probs=cache[f'full/{group}/{target}/enriched_mlp']
            if set(rows)!=set(lookup):raise ValueError('cached_forecast_origins_mismatch')
            runs['mlp_cached']=[dict(lookup[int(i)],probabilities=prob[:classes].tolist()) for i,prob in zip(rows,probs)]
            if target=='range5':runs['range_intercept']=[];runs['range_offset']=[]
            quarters=defaultdict(list)
            for row in test_base:
                t=dt.datetime.fromtimestamp(row['known_at'],dt.timezone.utc)
                quarters[t.year,(t.month-1)//3*3+1].append(row['index'])
            for (year,month),test in sorted(quarters.items()):
                cutoff=int(dt.datetime(year,month,1,tzinfo=dt.timezone.utc).timestamp())
                train,test=fold_indices(data,valid,column,cutoff,test)
                for name in list(TREES)+(['range_intercept','range_offset'] if target=='range5' else []):
                    training=train
                    if name=='recent_tree':
                        lower=int(dt.datetime(year-3,month,1,tzinfo=dt.timezone.utc).timestamp())
                        training=train[data['known_at'][train]>=lower]
                    a=matrix[name][training] if name in matrix else data['X'][training][:,offset_columns]
                    b=matrix[name][test] if name in matrix else data['X'][test][:,offset_columns]
                    extra={}
                    if name.startswith('range_'):
                        if name=='range_intercept':a,b=a[:,:0],b[:,:0]
                        model=fit_geometry_offset(a,data['y'][training,column],geometry[training])
                        pred=predict_geometry_offset(model,b,geometry[test])
                        train_pred=predict_geometry_offset(model,a,geometry[training])
                        extra=dict(coefficients=model['coefficients'].tolist(),iterations=model['iterations'])
                    else:
                        if name=='permuted_context_tree':a=permute_context_dates(a,data['known_at'][training],context_columns)
                        if name=='strong_tree':
                            model=make_pipeline(SimpleImputer(strategy='median',keep_empty_features=True),StandardScaler(),
                                HistGradientBoostingClassifier(max_iter=80,max_leaf_nodes=2,max_depth=1,min_samples_leaf=120,
                                    l2_regularization=50,learning_rate=.05,early_stopping=False,random_state=17))
                            model.fit(a,data['y'][training,column])
                        else:model,_=fit_candidate('tree',a,data['y'][training,column])
                        pred=probability(model,b,classes);train_pred=probability(model,a,classes)
                    truth=np.eye(classes)[data['y'][training,column]];test_truth=np.eye(classes)[data['y'][test,column]]
                    train_brier=float(np.mean(np.sum((train_pred-truth)**2,axis=1)))
                    test_brier=float(np.mean(np.sum((pred-test_truth)**2,axis=1)))
                    fits.append(dict(group=group,target=target,model=name,cutoff=cutoff,train_rows=len(training),test_rows=len(test),
                        unique_train_clocks=len(np.unique(data['known_at'][training])),columns=a.shape[1],
                        last_training_maturity=int(data['maturity'][training,column].max()),train_brier=train_brier,test_brier=test_brier,**extra))
                    runs[name]+=[dict(lookup[int(i)],probabilities=prob.tolist()) for i,prob in zip(test,pred)]
                print(group,target,f'{year}-{month:02}',f'fits={len(fits)}',flush=True)
            for name in ('legacy_tree','enriched_tree'):
                prior_rows,prior_prob=cache[f'full/{group}/{target}/{name}']
                prior_map={int(i):prob[:classes] for i,prob in zip(prior_rows,prior_prob)}
                delta=max(float(np.max(abs(np.array(row['probabilities'])-prior_map[row['index']]))) for row in runs[name])
                if delta>1e-12:raise ValueError('reference_refit_drift')
                checks.append(dict(group=group,target=target,model=name,maximum_probability_difference=delta))
            shrink_names=('legacy_tree','enriched_tree','strong_tree','compact_tree','mlp_cached')+ (('range_offset',) if target=='range5' else ())
            for name in shrink_names:
                shrunk=causal_shrink(runs['anchor'],runs[name],penalty=10.)
                runs[name+'_shrunk']=shrunk
                ordered=sorted(shrunk,key=lambda row:(row['known_at'],row['asset']))
                weights.append(dict(group=group,target=target,model=name,mean=float(np.mean([r['expert_weight'] for r in ordered])),
                    last=ordered[-1]['expert_weight'],last_weight_training_maturity=ordered[-1]['weight_training_maturity']))
            for name,rows in runs.items():
                if len(rows)!=len(test_base):raise ValueError('optimization_origin_mismatch')
                rid=len(run_names);run_names.append(f'{group}/{target}/{name}')
                for row in rows:
                    predictions.append((rid,row['index'],*(row['probabilities']+[np.nan]*(3-classes)),
                        row.get('expert_weight',np.nan),row.get('weight_training_maturity') or 0))
                years=sorted({date(r['known_at'])[:4] for r in rows})
                for window in ['all']+years:
                    selected=rows if window=='all' else [r for r in rows if date(r['known_at']).startswith(window)
                        and date(r['mature_at'])<str(int(window)+1)+'-01-01']
                    if selected:evaluations.append(dict(group=group,target=target,model=name,window=window,scores=scores(selected)))
                for category in sorted({r['category'] for r in rows}):
                    diagnostics.append(dict(group=group,target=target,model=name,category=category,
                        scores=scores([r for r in rows if r['category']==category])))
            contrasts=[(n,'legacy_tree') for n in ('enriched_tree','strong_tree','compact_tree','no_context_tree','recent_tree')]
            contrasts+=[('permuted_context_tree','enriched_tree'),('legacy_tree_shrunk','legacy_tree'),
                ('legacy_tree_shrunk','anchor'),('enriched_tree_shrunk','enriched_tree'),('mlp_cached_shrunk','mlp_cached'),
                ('compact_tree','anchor'),('compact_tree_shrunk','anchor'),
                ('strong_tree_shrunk','legacy_tree_shrunk'),('compact_tree_shrunk','legacy_tree_shrunk')]
            if target=='range5':contrasts+=[('range_intercept','anchor'),('range_offset','range_intercept'),
                ('range_offset','anchor'),
                ('range_offset','legacy_tree'),('range_offset_shrunk','legacy_tree_shrunk'),('range_offset_shrunk','anchor')]
            for left,right in contrasts:
                comparisons.append(dict(group=group,target=target,left=left,right=right,delta=paired_comparison(runs[left],runs[right])))
    result=dict(research_only=True,orders_authorized=False,independent_oos=False,dataset=str(args.dataset),
        dataset_sha256=prior_result['dataset_sha256'],previous=str(args.previous),fits=fits,evaluations=evaluations,
        comparisons=comparisons,weights=weights,diagnostics=diagnostics,reference_checks=checks,evaluation_bounds=bounds,
        elapsed_seconds=time.monotonic()-started,
        parameters=dict(evaluation_start='2023-01-01',refit='quarterly',stride=5,offset_penalty=20,shrink_penalty=10,
            recent_years=3,negative_control_seed=17,compact_features=COMPACT_FEATURES,offset_features=OFFSET_FEATURES),
        limitations=[
            '所有历史已消费，固定机制试验是原因定位，不是独立新样本；未校正多重比较。',
            '训练/后续误差差距和单种子日期置换只提供过拟合/不稳定关联证据，不能证明经济因果。',
            '行数不等于独立样本数；同日资产和重叠窗口相关，季度簇区间亦只是探索诊断。',
            '概率收缩使用过去时间外预测的成熟结果，不用分类器训练拟合值校准；初期完全使用锚概率。',
            '收缩可能只减少错误自信，不增加方向辨识能力；不能将概率改善称为交易胜率提升。',
            '低维offset依赖零漂移高斯几何近似；其改善也不证明市场服从高斯或可交易获利。',
            '七经济分组、四行为簇与十二/十四状态定义未变；不继续细分标签或扩大NN。',
            '未计算成交、成本、仓位或账户收益；未更改实盘/定时器/账户权限，未下载新数据。',
        ])
    args.output.mkdir(parents=True)
    a=np.asarray(predictions,float)
    np.savez_compressed(args.output/'predictions.npz',run_id=a[:,0].astype(int),row_index=a[:,1].astype(int),
        probabilities=a[:,2:5],expert_weight=a[:,5],weight_training_maturity=a[:,6].astype(np.int64),run_names=np.array(run_names))
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    (args.output/'report.md').write_text(report(result))
    print(json.dumps(dict(output=str(args.output),fits=len(fits),elapsed_seconds=result['elapsed_seconds'])))


if __name__=='__main__':main()
