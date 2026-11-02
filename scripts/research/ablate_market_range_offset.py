"""Test whether relative-volatility correction explains the four-feature offset."""
from __future__ import annotations

import argparse
from collections import defaultdict
import datetime as dt
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from qount.research.market_probability_refinement import OFFSET_FEATURES,fit_geometry_offset,predict_geometry_offset
from qount.research.market_learning import range_geometry_from_distances
from qount.research.market_state_validation import scores
from qount.research.market_state_profiles import causal_shrink
from compare_market_feature_sets import date,fold_indices,records
from compare_market_state_profiles import paired_comparison


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dataset',type=Path,required=True)
    p.add_argument('--reference',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():p.error('retain prior experiments')
    started=time.monotonic()
    with np.load(a.dataset,allow_pickle=False) as z:d={k:z[k] for k in z.files}
    with np.load(a.reference/'predictions.npz',allow_pickle=False) as z:archive={k:z[k] for k in z.files}
    source=json.loads((a.reference/'results.json').read_text())
    if source['dataset_sha256']!=hashlib.sha256(a.dataset.read_bytes()).hexdigest():raise ValueError('ablation_source_mismatch')
    names=list(d['feature_names']);lo=names.index('lower_boundary_distance_sigma20');hi=names.index('upper_boundary_distance_sigma20')
    geometry=np.full(len(d['X']),np.nan)
    for i in np.flatnonzero(d['y'][:,2]>=0):geometry[i]=range_geometry_from_distances(float(d['X'][i,lo]),float(d['X'][i,hi]))
    evaluations=[];comparisons=[];fits=[];predictions=[];run_names=[]
    for group in ('crypto','etf_proxy'):
        runs={}
        for model in ('anchor','range_intercept','range_offset','legacy_tree'):
            rid=list(archive['run_names']).index(f'{group}/range5/{model}')
            mask=archive['run_id']==rid;rows=archive['row_index'][mask];prob=archive['probabilities'][mask,:2]
            runs[model]=[dict(row,probabilities=p.tolist()) for row,p in zip(records(d,rows,2),prob)]
        lookup={r['index']:r for r in runs['anchor']}
        valid=(d['group']==group)&(d['bar_index']%5==0)&(d['y'][:,2]>=0)
        quarters=defaultdict(list)
        for row in runs['anchor']:
            t=dt.datetime.fromtimestamp(row['known_at'],dt.timezone.utc)
            quarters[t.year,(t.month-1)//3*3+1].append(row['index'])
        for model,features in (('vol_only',('relative_volatility',)),('without_vol',tuple(k for k in OFFSET_FEATURES if k!='relative_volatility'))):
            columns=[names.index(k) for k in features];runs[model]=[]
            for (year,month),test in sorted(quarters.items()):
                cutoff=int(dt.datetime(year,month,1,tzinfo=dt.timezone.utc).timestamp())
                train,test=fold_indices(d,valid,2,cutoff,test)
                fitted=fit_geometry_offset(d['X'][train][:,columns],d['y'][train,2],geometry[train])
                prob=predict_geometry_offset(fitted,d['X'][test][:,columns],geometry[test])
                fits.append(dict(group=group,model=model,cutoff=cutoff,features=features,train_rows=len(train),
                    last_training_maturity=int(d['maturity'][train,2].max()),coefficients=fitted['coefficients'].tolist()))
                runs[model]+=[dict(lookup[int(i)],probabilities=p.tolist()) for i,p in zip(test,prob)]
        runs['vol_only_shrunk']=causal_shrink(runs['anchor'],runs['vol_only'],penalty=10.)
        for model,rows in runs.items():
            rid=len(run_names);run_names.append(f'{group}/{model}')
            predictions.extend((rid,r['index'],*r['probabilities'],r.get('expert_weight',np.nan),r.get('weight_training_maturity') or 0) for r in rows)
            for year in ['all']+sorted({date(r['known_at'])[:4] for r in rows}):
                selected=rows if year=='all' else [r for r in rows if date(r['known_at']).startswith(year)
                    and date(r['mature_at'])<str(int(year)+1)+'-01-01']
                evaluations.append(dict(group=group,model=model,window=year,scores=scores(selected)))
        for left,right in (('vol_only','range_intercept'),('without_vol','range_intercept'),
                           ('range_offset','vol_only'),('vol_only','legacy_tree'),('vol_only','anchor')):
            comparisons.append(dict(group=group,left=left,right=right,delta=paired_comparison(runs[left],runs[right])))
        for right in ('vol_only','anchor','legacy_tree'):
            comparisons.append(dict(group=group,left='vol_only_shrunk',right=right,
                delta=paired_comparison(runs['vol_only_shrunk'],runs[right])))
    result=dict(research_only=True,orders_authorized=False,dataset=str(a.dataset),dataset_sha256=source['dataset_sha256'],
        reference=str(a.reference),fits=fits,evaluations=evaluations,comparisons=comparisons,elapsed_seconds=time.monotonic()-started,
        parameters=dict(offset_penalty=20,shrink_penalty=10,refit='quarterly',stride=5,evaluation_start='2023-01-01'),
        limitation='Coefficient-motivated follow-up on already-consumed history; exploratory, no independent confirmation or trade returns')
    lines=['# 区间修正来源消融','',result['limitation'],'',
        '固定比较相对波动率单因素、去掉相对波动率的三因素，与前轮四因素/仅截距/几何/旧树同起点预测。',
        'vol_only_shrunk沿用前轮固定罚项10的成熟预测收缩，初期使用几何锚；不按2026事后表现切换模型。','',
        '|市场|模型|样本|准确率|平衡准确率|Brier|','|---|---|---:|---:|---:|---:|']
    for e in evaluations:
        if e['window']!='all':continue
        s=e['scores'];lines.append(f"|{e['group']}|{e['model']}|{s['count']}|{s['accuracy']:.2%}|{s['balanced_accuracy']:.2%}|{s['brier']:.5f}|")
    lines+=['','|市场|对照|Brier差|季度簇95%区间|','|---|---|---:|---|']
    for c in comparisons:lines.append(f"|{c['group']}|{c['left']} − {c['right']}|{c['delta']['mean']:+.5f}|{c['delta']['interval95']}|")
    lines+=['',f'新拟合{len(fits)}次，{result["elapsed_seconds"]:.1f}秒；各年度与全部参数/系数保存在results.json。',
        '相对波动率为当前sigma20除以最多252个严格先前sigma20的中位数，再取对数；所有缩放和系数仅用过去训练数据。',
        '保留2026等失败窗口；不把同一历史上的消融解释为独立验证。']
    a.output.mkdir(parents=True)
    array=np.asarray(predictions,float)
    np.savez_compressed(a.output/'predictions.npz',run_id=array[:,0].astype(int),row_index=array[:,1].astype(int),
        probabilities=array[:,2:4],expert_weight=array[:,4],weight_training_maturity=array[:,5].astype(np.int64),run_names=np.array(run_names))
    (a.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    (a.output/'report.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(dict(output=str(a.output),fits=len(fits),elapsed_seconds=result['elapsed_seconds'])))


if __name__=='__main__':main()
