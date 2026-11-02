"""Source/target checks and causal adaptations of range probability forecasts."""
from __future__ import annotations

import argparse
from collections import defaultdict
import datetime as dt
import hashlib
import json
from pathlib import Path
import time
from zoneinfo import ZoneInfo

import numpy as np

from qount.research.market_learning import range_geometry_from_distances
from qount.research.market_probability_refinement import (
    volatility_context,fit_geometry_offset,predict_geometry_offset,discounted_probability_mix,
)
from qount.research.market_state_validation import scores
from qount.research.market_stages import market_state_machine
from compare_market_feature_sets import records,fold_indices,date
from compare_market_state_profiles import paired_comparison
from study_binance_market_states import load_markets


def multiscale_runs(runs,relative):
    """Fixed complementary references; every adaptive layer uses mature losses.

    short_weight is the SHORT share *inside* the long/short pair. anchor_weight
    is the final geometric share; final short share=(1-anchor_weight)*short_weight.
    These are probability weights and do not represent capital allocation.
    """
    def with_context(rows):
        return [dict(r,context='low' if relative[r['index']]<np.log(.8) else
                     'high' if relative[r['index']]>np.log(1.2) else 'middle') for r in rows]
    long=with_context(runs['vol252_refit']);short=runs['vol63']
    lookup={r['index']:r for r in short}
    equal=[dict(r,probabilities=((np.asarray(r['probabilities'])+lookup[r['index']]['probabilities'])/2).tolist(),
        short_weight=.5,anchor_weight=0.) for r in long]
    global_mix=discounted_probability_mix(long,short)
    conditional_mix=discounted_probability_mix(long,short,conditional=True)
    for rows in (global_mix,conditional_mix):
        for r in rows:r['short_weight']=r['expert_weight'];r['anchor_weight']=0.
    guarded=discounted_probability_mix(with_context(runs['anchor']),conditional_mix)
    paired={r['index']:r for r in conditional_mix}
    for r in guarded:
        r['short_weight']=paired[r['index']]['short_weight']
        r['pair_training_maturity']=paired[r['index']]['weight_training_maturity'] or 0
        r['anchor_weight']=1-r['expert_weight']
    return dict(multiscale_equal=equal,multiscale_global=global_mix,
                multiscale_conditional=conditional_mix,multiscale_guarded=guarded)


def audit_sources(data,markets,states,sources,reference):
    expected={r['path']:r['sha256'] for r in json.loads(reference.read_text())['sources']}
    if any(s['path'] not in expected or s['sha256']!=expected[s['path']] for s in sources):
        raise ValueError('robustness_raw_source_drift')
    strict=np.full(len(data['X']),-1,int)
    checked=0;maximum_error=0.;overlap={'crypto':0,'etf_proxy':0}
    rel=list(data['feature_names']).index('relative_volatility')
    for k in range(len(data['X'])):
        group=str(data['group'][k]);asset=str(data['asset'][k]);i=int(data['bar_index'][k])
        bars=markets[group][asset];state=states[group][asset][bars[i].t]
        close=bars[i].t+int(group=='crypto')
        if close!=data['bar_close_time'][k] or close+60!=data['known_at'][k]:raise ValueError('raw_row_clock_mismatch')
        value=np.clip(np.log(state['volatility20']/state['volatility_reference']),-8,8)
        maximum_error=max(maximum_error,float(abs(value-data['X'][k,rel])))
        eligible=state['action_state'] in ('compression','range','wide_range') and i+5<len(bars)
        outcome=-1
        if eligible:
            lower=min(b.l for b in bars[i-20:i]);upper=max(b.h for b in bars[i-20:i])
            future=bars[i+1:i+6]
            outcome=int(all(lower<=b.c<=upper for b in future))
            strict[k]=int(all(lower<=b.l and b.h<=upper for b in future))
            if group=='crypto':first_open=bars[i+1].t+1-86400
            else:
                day=dt.datetime.fromtimestamp(bars[i+1].t,ZoneInfo('America/New_York')).date()
                first_open=int(dt.datetime.combine(day,dt.time(9,30),ZoneInfo('America/New_York')).timestamp())
            overlap[group]=max(overlap[group],max(0,int(data['known_at'][k])-first_open))
            maturity=bars[i+5].t+int(group=='crypto')+60
            if data['maturity'][k,2]!=maturity:raise ValueError('raw_target_maturity_mismatch')
        elif data['maturity'][k,2]!=0:raise ValueError('raw_censored_maturity_mismatch')
        if data['y'][k,2]!=outcome:raise ValueError('raw_close_target_mismatch')
        checked+=1
    if maximum_error>5e-7:raise ValueError('raw_relative_volatility_mismatch')
    return strict,dict(checked_rows=checked,source_files=len(sources),source_hashes_match=True,
        target_maturity_mismatches=0,close_target_mismatches=0,maximum_relative_volatility_error=maximum_error,
        intraday_predecision_overlap_seconds_max=overlap,strict_intraday_execution_aligned=False)


def selective_summary(rows,strict,threshold):
    chosen=[r for r in rows if r['probabilities'][1]>=threshold]
    if not chosen:return None
    quarters=defaultdict(list)
    for row in chosen:
        t=dt.datetime.fromtimestamp(row['known_at'],dt.timezone.utc)
        quarters[t.year,(t.month-1)//3].append(row['outcome'])
    interval=None
    if len(quarters)>=4:
        sums=np.array([sum(v) for v in quarters.values()]);counts=np.array([len(v) for v in quarters.values()])
        draw=np.random.default_rng(301026).integers(0,len(quarters),(3000,len(quarters)))
        interval=np.quantile(sums[draw].sum(axis=1)/counts[draw].sum(axis=1),[.025,.975]).tolist()
    return dict(threshold=threshold,count=len(chosen),unique_clocks=len({r['known_at'] for r in chosen}),
        quarter_clusters=len(quarters),coverage=len(chosen)/len(rows),close_keep_rate=float(np.mean([r['outcome'] for r in chosen])),
        close_keep_interval95=interval,mean_probability=float(np.mean([r['probabilities'][1] for r in chosen])),
        intraday_keep_rate=float(np.mean([strict[r['index']] for r in chosen])))


def report(result):
    lines=['# 区间预测稳健性、来源核对与因果适应','',
        '已消费历史上的固定机制研究，不是独立OOS；主目标保持未来5个收盘在固定先前20期边界内。','',
        '## 本轮假设','',
        '- 252期波动参考过慢：只改为严格先前63期sigma20中位数，保持单因素offset。',
        '- 低波状态持续时间缺失：相对波动率与低波持续占比交互；也比较正/负相对波动率的非对称斜率。',
        '- 关系失效需要遗忘：系数训练采用固定365天半衰期；预测权重采用固定180天半衰期/罚项1，另按已知低/中/高波上下文部分汇聚。',
        '- 迁移检验：逐季排除被预测资产的全部训练标签，分别测试252/63期参考，不训练资产ID。',
        '- 双尺度组合：252/63期等权，或只凭过去成熟误差自适应组合；另用同样规则控制组合相对几何锚的总权重。',
        '- 标签敏感性：另检查未来高低点是否也保持区间，只作诊断；没有将收盘概率冒充盘中不越界概率。','',
        '## 核对结果','',json.dumps(result['source_audit'],ensure_ascii=False),'',
        '币种决策在日线结束后60秒，下一根日K高低点包含这60秒；盘中标签仅为K线窗口诊断，不是决策/成交之后的严格止损目标。',
        'ETF按当前现金代理会话映射，无该60秒重叠；仍不是原生连续合约撮合。','',
        '|市场|观测数|收盘保持率|盘中高低点保持率|仅收盘保持数|','|---|---:|---:|---:|---:|']
    for r in result['label_sensitivity']:
        lines.append(f"|{r['group']}|{r['rows']}|{r['close_keep_fraction']:.2%}|{r['intraday_keep_fraction']:.2%}|{r['close_only_positive']}|")
    lines+=["",
        '## 总体预测','',
        '|市场|模型|样本|准确率|平衡准确率|Brier↓|','|---|---|---:|---:|---:|---:|']
    for r in result['evaluations']:
        if r['window']!='all':continue
        s=r['scores'];lines.append(f"|{r['group']}|{r['model']}|{s['count']}|{s['accuracy']:.2%}|{s['balanced_accuracy']:.2%}|{s['brier']:.5f}|")
    lines+=['','## 相同起点对照','',
        '差为左模型Brier减右模型Brier，负值较好；季度簇95%区间未校正多重比较。','',
        '|市场|对照|Brier差|95%区间|','|---|---|---:|---|']
    for r in result['comparisons']:
        ci=r['delta']['interval95'];lines.append(f"|{r['group']}|{r['left']} − {r['right']}|{r['delta']['mean']:+.5f}|{ci}|")
    lines+=['','## 高概率覆盖与目标边界','',
        '下表预测概率和命中率都针对收盘保持；盘中保持率仅为同批样本的另一目标诊断，不是概率校准评分。阈值固定，未据命中率调参。','',
        '|市场|模型|概率下限|样本/覆盖/时点|收盘保持率/季度簇95%区间|平均预测|盘中高低点保持率|',
        '|---|---|---:|---|---|---:|---:|']
    for r in result['selective']:
        if r['threshold']!=.8:continue
        interval=r.get('close_keep_interval95');label=f'[{interval[0]:.1%},{interval[1]:.1%}]' if interval else '不足'
        lines.append(f"|{r['group']}|{r['model']}|{r['threshold']:.1f}|{r['count']}/{r['coverage']:.1%}/{r.get('unique_clocks','—')}|{r['close_keep_rate']:.2%}/{label}|{r['mean_probability']:.2%}|{r['intraday_keep_rate']:.2%}|")
    lines+=['','## 来源与执行边界','',
        f"新拟合{len(result['fits'])}次，{result['elapsed_seconds']:.1f}秒；年度、标的/类别/状态诊断、迁移折和完整概率/权重另存results.json/predictions.npz。",'']
    lines+=['- '+s for s in result['limitations']]
    return '\n'.join(lines)+'\n'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dataset',type=Path,required=True)
    p.add_argument('--reference',type=Path,required=True)
    p.add_argument('--schema',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():p.error('retain prior results; choose a new output')
    started=time.monotonic()
    with np.load(args.dataset,allow_pickle=False) as z:data={k:z[k] for k in z.files}
    source=json.loads((args.reference/'results.json').read_text())
    if source['dataset_sha256']!=hashlib.sha256(args.dataset.read_bytes()).hexdigest():raise ValueError('robustness_dataset_mismatch')
    with np.load(args.reference/'predictions.npz') as z:archive={k:z[k] for k in z.files}
    markets,_,sources=load_markets()
    states={g:{a:market_state_machine(b) for a,b in book.items()} for g,book in markets.items()}
    strict,audit=audit_sources(data,markets,states,sources,args.schema)
    print('source/target audit passed',audit,flush=True)
    history={g:{a:volatility_context(b) for a,b in book.items()} for g,book in markets.items()}
    context=np.stack([history[str(g)][str(a)][i] for g,a,i in zip(data['group'],data['asset'],data['bar_index'])])
    rel=data['X'][:,list(data['feature_names']).index('relative_volatility')].astype(float)
    if np.nanmax(abs(context[:,3]+context[:,4]-rel))>5e-7:raise ValueError('volatility_context_source_mismatch')
    inputs=dict(vol252_refit=rel[:,None],vol63=context[:,[0]],asymmetric=np.c_[np.maximum(rel,0),np.minimum(rel,0)],
        duration=np.c_[rel,context[:,5]],vol_recent=rel[:,None],
        asymmetric_recent=np.c_[np.maximum(rel,0),np.minimum(rel,0)],duration_recent=np.c_[rel,context[:,5]])
    geometry=np.full(len(data['X']),np.nan)
    names=list(data['feature_names']);lo=names.index('lower_boundary_distance_sigma20');hi=names.index('upper_boundary_distance_sigma20')
    for i in np.flatnonzero(data['y'][:,2]>=0):geometry[i]=range_geometry_from_distances(float(data['X'][i,lo]),float(data['X'][i,hi]))
    fits=[];evaluations=[];comparisons=[];diagnostics=[];selective=[];forecasts=[];run_names=[];label_sensitivity=[];ref_checks=[]
    for group in ('crypto','etf_proxy'):
        runs={}
        for model in ('anchor','vol_only','vol_only_shrunk','legacy_tree'):
            rid=list(archive['run_names']).index(f'{group}/{model}')
            mask=archive['run_id']==rid;rows=archive['row_index'][mask]
            runs[model]=[dict(row,probabilities=prob.tolist()) for row,prob in zip(records(data,rows,2),archive['probabilities'][mask])]
            if model.endswith('_shrunk'):
                for row,weight,maturity in zip(runs[model],archive['expert_weight'][mask],archive['weight_training_maturity'][mask]):
                    row['expert_weight']=float(weight);row['weight_training_maturity']=int(maturity)
        lookup={r['index']:r for r in runs['anchor']}
        valid=(data['group']==group)&(data['bar_index']%5==0)&(data['y'][:,2]>=0)
        quarters=defaultdict(list)
        for r in runs['anchor']:
            t=dt.datetime.fromtimestamp(r['known_at'],dt.timezone.utc)
            quarters[t.year,(t.month-1)//3*3+1].append(r['index'])
        for model in inputs:runs[model]=[]
        for (year,month),test in sorted(quarters.items()):
            cutoff=int(dt.datetime(year,month,1,tzinfo=dt.timezone.utc).timestamp())
            train,test=fold_indices(data,valid,2,cutoff,test)
            for model,values in inputs.items():
                weight=None
                if model.endswith('_recent'):
                    age=(cutoff-data['maturity'][train,2])/86400
                    weight=np.exp(-np.log(2)*age/365.)
                fitted=fit_geometry_offset(values[train],data['y'][train,2],geometry[train],sample_weight=weight)
                pred=predict_geometry_offset(fitted,values[test],geometry[test])
                fits.append(dict(group=group,model=model,cutoff=cutoff,train_rows=len(train),test_rows=len(test),
                    last_training_maturity=int(data['maturity'][train,2].max()),coefficients=fitted['coefficients'].tolist(),
                    weighted_effective_rows=float((weight.sum()**2)/(weight@weight)) if weight is not None else len(train)))
                runs[model]+=[dict(lookup[int(i)],probabilities=prob.tolist()) for i,prob in zip(test,pred)]
            for model,key in (('loao252','vol252_refit'),('loao63','vol63')):
                runs.setdefault(model,[])
                for asset in sorted(set(data['asset'][test])):
                    held=test[data['asset'][test]==asset];training=train[data['asset'][train]!=asset]
                    if np.any(data['asset'][training]==asset):raise ValueError('held_asset_training_leak')
                    fitted=fit_geometry_offset(inputs[key][training],data['y'][training,2],geometry[training])
                    pred=predict_geometry_offset(fitted,inputs[key][held],geometry[held])
                    fits.append(dict(group=group,model=model,cutoff=cutoff,heldout_asset=str(asset),train_rows=len(training),test_rows=len(held),
                        training_assets=sorted(set(map(str,data['asset'][training]))),last_training_maturity=int(data['maturity'][training,2].max()),
                        coefficients=fitted['coefficients'].tolist()))
                    runs[model]+=[dict(lookup[int(i)],probabilities=prob.tolist()) for i,prob in zip(held,pred)]
            print(group,f'{year}-{month:02}',f'fits={len(fits)}',flush=True)
        original={r['index']:r['probabilities'] for r in runs['vol_only']}
        difference=max(np.max(abs(np.asarray(r['probabilities'])-original[r['index']])) for r in runs['vol252_refit'])
        if difference>1e-9:raise ValueError('volatility_offset_refit_drift')
        ref_checks.append(dict(group=group,maximum_reference_difference=float(difference)))
        for expert in ('vol252_refit','vol63'):
            baseline=[dict(r,context='low' if rel[r['index']]<np.log(.8) else 'high' if rel[r['index']]>np.log(1.2) else 'middle') for r in runs['anchor']]
            for conditional in (False,True):
                key=expert+('_discount_conditional' if conditional else '_discount_global')
                runs[key]=discounted_probability_mix(baseline,runs[expert],conditional=conditional)
        runs.update(multiscale_runs(runs,rel))
        for model,rows in runs.items():
            if {r['index'] for r in rows}!=set(lookup):raise ValueError('robustness_origin_mismatch')
            rid=len(run_names);run_names.append(f'{group}/{model}')
            for r in rows:
                forecasts.append((rid,r['index'],*r['probabilities'],r.get('expert_weight',np.nan),
                    r.get('weight_training_maturity') or 0,r.get('discounted_date_mass',0.),r.get('context_mass',0.),
                    r.get('short_weight',np.nan),r.get('anchor_weight',np.nan),r.get('pair_training_maturity',0)))
            for year in ['all']+sorted({date(r['known_at'])[:4] for r in rows}):
                chosen=rows if year=='all' else [r for r in rows if date(r['known_at']).startswith(year)
                    and date(r['mature_at'])<str(int(year)+1)+'-01-01']
                evaluations.append(dict(group=group,model=model,window=year,scores=scores(chosen)))
            for field in ('asset','category','key'):
                for value in sorted({r[field] for r in rows}):
                    chosen=[r for r in rows if r[field]==value]
                    diagnostics.append(dict(group=group,model=model,field=field,value=value,scores=scores(chosen)))
            for threshold in (.7,.8,.9):
                summary=selective_summary(rows,strict,threshold)
                if summary:selective.append(dict(group=group,model=model,**summary))
        close=np.array([r['outcome'] for r in runs['anchor']]);strict_y=np.array([strict[r['index']] for r in runs['anchor']])
        label_sensitivity.append(dict(group=group,rows=len(close),close_keep_fraction=float(close.mean()),
            intraday_keep_fraction=float(strict_y.mean()),close_only_positive=int(np.sum((close==1)&(strict_y==0)))))
        contrasts=[(name,'vol_only') for name in inputs if name!='vol252_refit']
        contrasts+=[('loao252','vol_only'),('loao63','vol63'),('vol63','anchor'),('vol63','legacy_tree')]
        for expert in ('vol252_refit','vol63'):
            for conditional in ('global','conditional'):
                name=expert+'_discount_'+conditional
                contrasts.extend([(name,expert),(name,'anchor'),(name,'vol_only_shrunk')])
        for model in ('multiscale_equal','multiscale_global','multiscale_conditional','multiscale_guarded'):
            contrasts.extend([(model,'vol_only'),(model,'anchor')])
        contrasts.extend([('multiscale_guarded','vol_only_shrunk'),('multiscale_conditional','multiscale_equal')])
        for left,right in contrasts:
            comparisons.append(dict(group=group,left=left,right=right,delta=paired_comparison(runs[left],runs[right])))
    result=dict(research_only=True,orders_authorized=False,independent_oos=False,dataset=str(args.dataset),dataset_sha256=source['dataset_sha256'],
        reference=str(args.reference),source_audit=audit,reference_checks=ref_checks,fits=fits,evaluations=evaluations,comparisons=comparisons,
        diagnostics=diagnostics,selective=selective,label_sensitivity=label_sensitivity,elapsed_seconds=time.monotonic()-started,
        parameters=dict(evaluation_start='2023-01-01',stride=5,refit='quarterly',offset_penalty=20,training_half_life_days=365,
            calibration_half_life_days=180,calibration_penalty=1,volatility_bands=[.8,1.2],parameter_search=False),
        limitations=[
            '所有历史已消费；本轮按明确机制比较，不宣称独立新样本，不校正多重比较。',
            '原始缓存核对只证明本地来源/公式/标签一致，不是历史发布可获时间或交易所全档案认证。',
            '未来5收盘保持与盘中高低点不越界是不同目标；后者只检查覆盖，未训练其概率。',
            '币种盘中日K窗口有60秒早于决策的部分；训练可执行风险目标前需分钟等细粒度数据重新对齐。',
            'LOAO每折排除该资产训练标签，但标的/时段已被研究消费；不是从未接触的新资产验证。',
            '适应权重只用严格成熟的历史预测，按日期归一；半衰期/罚项事前固定，不按年份事后切换。',
            '高概率阈值仅研究覆盖/校准，命中率不是交易胜率；收缩权重不是仓位，未实施任何操作。',
            '未来时段仍可能有关系变化；ETF只到2025、币种2026为部分年度，存续偏差/代理/PIT假设保留。',
        ])
    args.output.mkdir(parents=True)
    a=np.asarray(forecasts,float)
    np.savez_compressed(args.output/'predictions.npz',run_id=a[:,0].astype(int),row_index=a[:,1].astype(int),probabilities=a[:,2:4],
        expert_weight=a[:,4],weight_training_maturity=a[:,5].astype(np.int64),discounted_date_mass=a[:,6],context_mass=a[:,7],
        short_weight=a[:,8],anchor_weight=a[:,9],pair_training_maturity=a[:,10].astype(np.int64),
        bar_high_low_diagnostic=strict,intraday_diagnostic_execution_aligned=np.array(False),run_names=np.array(run_names))
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    (args.output/'report.md').write_text(report(result))
    print(json.dumps(dict(output=str(args.output),fits=len(fits),elapsed_seconds=result['elapsed_seconds'])))


if __name__=='__main__':main()
