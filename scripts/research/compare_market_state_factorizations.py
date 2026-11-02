"""Compare five classes, merged three, and direction plus independent attributes."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from qount.research.market_daily_states import LOCAL_STATES
from qount.research.market_learning import fit_candidate
from qount.research.market_state_boundaries import window_refinement
from qount.research.market_state_factorization import (
    ATTRIBUTE_NAMES, INPUT_NAMES, MAIN_STATES, causal_inputs, factored_window,
    merge_five, project_five_probabilities, purged_quarter,
)
from qount.research_data.bars import Bar

SOURCE=Path('state/research_runs/market_state_boundaries_20261031_two_week_v2/dataset.npz')
SCHEMES=('five','merged_three','factored_three')
PERTURBATIONS=(('score_low',dict(slope_threshold=.4)),('score_high',dict(slope_threshold=.6)),
    ('half_life_short',dict(half_life_factor=.8/3)),('half_life_long',dict(half_life_factor=1.2/3)),
    ('efficiency_low',dict(efficiency_threshold=.08)),('efficiency_high',dict(efficiency_threshold=.12)),
    ('compression_low',dict(compression_threshold=.60)),('compression_high',dict(compression_threshold=.70)))


def classification_metrics(actual,p,reference):
    actual=np.asarray(actual,int);p=np.asarray(p,float)
    pred=p.argmax(1);onehot=np.eye(p.shape[1])[actual]
    error=np.sum((p-onehot)**2,axis=1);base=np.sum((reference-onehot)**2,axis=1)
    high=p.max(1)>=.70
    return dict(rows=len(actual),accuracy=float(np.mean(pred==actual)),
        balanced_accuracy=float(np.mean([np.mean(pred[actual==c]==c) for c in np.unique(actual)])),
        brier=float(error.mean()),frequency_brier=float(base.mean()),
        brier_skill=float(1-error.mean()/base.mean()) if base.mean()>0 else None,
        log_loss=float(-np.log(p[np.arange(len(actual)),actual]).mean()),
        high70_rows=int(sum(high)),high70_coverage=float(high.mean()),
        high70_accuracy=float(np.mean(pred[high]==actual[high])) if high.any() else None,
        high70_frequency_accuracy=float(np.mean(reference[high].argmax(1)==actual[high])) if high.any() else None,
        high70_predicted_counts=np.bincount(pred[high],minlength=p.shape[1]).tolist(),
        high70_average_probability=float(p[high].max(1).mean()) if high.any() else None,
        actual_counts=np.bincount(actual,minlength=p.shape[1]).tolist(),
        class_recall=[float(np.mean(pred[actual==c]==c)) if np.any(actual==c) else None for c in range(p.shape[1])])


def asset_frequency(y,assets,train,test,classes):
    global_=(np.bincount(y[train],minlength=classes)+1)/(len(train)+classes)
    result=np.empty((len(test),classes))
    for a in np.unique(assets[test]):
        own=train[assets[train]==a]
        result[assets[test]==a]=(np.bincount(y[own],minlength=classes)+20*global_)/(len(own)+20)
    return result


def asset_mean(y,assets,train,test):
    output=np.empty(len(test))
    for a in np.unique(assets[test]):
        own=train[assets[train]==a]
        output[assets[test]==a]=float(y[own].mean()) if len(own) else float(y[train].mean())
    return output


def classifier(matrix,y,train,test,classes):
    model,_=fit_candidate('tree',matrix[train],y[train],seed=17)
    p=np.full((len(test),classes),.01/classes)
    p[:,model[-1].classes_.astype(int)]+=.99*model.predict_proba(matrix[test])
    return p,model[-1].classes_.astype(int).tolist()


def regression(matrix,y,train,test):
    model=make_pipeline(SimpleImputer(strategy='median'),StandardScaler(),
        HistGradientBoostingRegressor(max_iter=80,max_leaf_nodes=7,max_depth=3,
            min_samples_leaf=60,l2_regularization=10,learning_rate=.05,
            early_stopping=False,random_state=17))
    model.fit(matrix[train],y[train]);return model.predict(matrix[test])


def paired_interval(values,quarters):
    groups=np.unique(quarters)
    sums=np.array([values[quarters==q].sum() for q in groups])
    counts=np.array([sum(quarters==q) for q in groups])
    draws=np.random.default_rng(17).integers(0,len(groups),(2000,len(groups)))
    estimates=sums[draws].sum(1)/counts[draws].sum(1)
    return dict(mean=float(values.mean()),interval95=np.quantile(estimates,[.025,.975]).tolist(),
                quarter_clusters=len(groups))


def stability_summary(records):
    result=[]
    for group in ('crypto','etf_proxy'):
        for name,_ in PERTURBATIONS:
            own=[r for r in records if r['group']==group and r['perturbation']==name]
            for scheme in SCHEMES:
                changed=np.array([r[scheme]!=r[scheme+'_base'] for r in own])
                edge=np.array([r['boundary'] for r in own])
                main_changed=np.array([(r[scheme] if scheme!='five' else int(merge_five([r[scheme]])[0])) !=
                                       (r[scheme+'_base'] if scheme!='five' else int(merge_five([r[scheme+'_base']])[0])) for r in own])
                result.append(dict(group=group,perturbation=name,scheme=scheme,rows=len(own),
                    changed=float(changed.mean()),main_direction_changed=float(main_changed.mean()),
                    boundary_changed=float(changed[edge].mean()) if edge.any() else None,
                    interior_changed=float(changed[~edge].mean()) if (~edge).any() else None))
    return result


def export_merged_view(output,d):
    """Concrete three-state/attribute view; five-class contrasts are retained."""
    np.savez_compressed(output/'three_main_states_and_attributes.npz',
        schema=np.array('three_main_states_with_independent_attributes_v1'),
        research_only=np.array(True),orders_authorized=np.array(False),label_uses_future=np.array(True),
        asset=d['asset'],group=d['group'],known_at=d['known_at'],ohlcv=d['ohlcv'],horizon=d['horizon'],
        X=d['X'],feature_names=d['feature_names'],feature_available_at=d['feature_available_at'],
        main_state=d['merged_three'],main_state_names=d['main_state_names'],attributes=d['attributes'],
        attribute_names=d['attribute_names'],label_available_at=d['label_available_at'],
        target_main_state=d['target_merged_three'],target_attributes=d['target_attributes'],
        target_row=d['target_row'],target_available_at=d['target_available_at'],target_mask=d['target_mask'])
    with (output/'three_main_states_and_attributes.csv').open('w',newline='') as stream:
        writer=csv.writer(stream)
        writer.writerow(['group','asset','close_date_utc','known_at_ms','open','high','low','close','volume',
            'reference_sessions','main_state',*ATTRIBUTE_NAMES,'label_available_at_ms',
            'next_period_main_state','next_period_available_at_ms'])
        for k in range(len(d['asset'])):
            group=str(d['group'][k]);stamp=int(d['known_at'][k]//1000)-(61 if group=='crypto' else 60)
            state=int(d['merged_three'][k]);target=int(d['target_merged_three'][k])
            writer.writerow([group,str(d['asset'][k]),dt.datetime.fromtimestamp(stamp,dt.timezone.utc).date().isoformat(),
                int(d['known_at'][k]),*d['ohlcv'][k],int(d['horizon'][k]),MAIN_STATES[state] if state>=0 else 'unlabeled',
                *[float(x) if np.isfinite(x) else '' for x in d['attributes'][k]],int(d['label_available_at'][k]),
                MAIN_STATES[target] if target>=0 else 'unlabeled',int(d['target_available_at'][k])])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,default=SOURCE)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():p.error('preserve previous results; choose another output')
    with np.load(args.source,allow_pickle=False) as z:d={k:z[k] for k in z.files}
    count=len(d['asset']);state5=d['daily_state'][:,2].copy();merged=merge_five(state5)
    factored=np.full(count,-1,np.int16);attributes=np.full((count,4),np.nan)
    numeric=np.full((count,len(INPUT_NAMES)),np.nan);last_mature_row=np.full(count,-1,np.int64)
    position=np.zeros(count,np.int64);stability=[]
    for a in sorted(set(d['asset'])):
        ix=np.flatnonzero(d['asset']==a);g=str(d['group'][ix[0]]);n=int(d['horizon'][ix[0],2])
        bars=[Bar(int(d['known_at'][k]//1000)-(61 if g=='crypto' else 60),*d['ohlcv'][k]) for k in ix]
        raw_states=state5[ix]
        for k,row in enumerate(ix):
            position[row]=k
            inputs=causal_inputs(bars,k,n)
            if inputs is not None:
                numeric[row]=inputs;last_mature_row[row]=ix[k-n]
            if raw_states[k]<0:continue
            window=bars[k-n+1:k+n+1];label=factored_window(window,n)
            factored[row]=label['state'];attributes[row]=label['attributes']
            if k%5:continue
            base=window_refinement(window,n)
            policy='pair_combined' if g=='crypto' else 'noise_only'
            assert base[policy]==raw_states[k],(a,k)
            near=raw_states[max(0,k-2):min(len(ix),k+3)]
            for name,parameters in PERTURBATIONS:
                altered=window_refinement(window,n,evidence_parameters=parameters)[policy]
                alt3=factored_window(window,n,**parameters)['state']
                stability.append(dict(asset=str(a),group=g,row=int(row),perturbation=name,
                    boundary=bool(np.any(near!=raw_states[k])),five_base=int(raw_states[k]),
                    merged_three_base=int(merged[row]),factored_three_base=int(factored[row]),
                    five=int(altered),merged_three=int(merge_five([altered])[0]),factored_three=int(alt3)))
        print('labels',a,'valid',int(sum(raw_states>=0)),flush=True)
    assert np.array_equal(state5>=0,factored>=0)
    destination=d['next_period_row'][:,2];mask=d['next_period_mask'][:,2]
    maturity=d['next_period_available_at'][:,2];known=d['known_at']
    labels={'five':state5,'merged_three':merged,'factored_three':factored}
    targets={name:np.full(count,-1,np.int16) for name in SCHEMES}
    target_attributes=np.full((count,4),np.nan)
    for name in SCHEMES:targets[name][mask]=labels[name][destination[mask]]
    target_attributes[mask]=attributes[destination[mask]]
    feature_ready=np.isfinite(numeric).all(1)
    eligible=mask&feature_ready&np.isfinite(target_attributes).all(1)
    assert np.all(d['feature_available_at'][feature_ready]<=known[feature_ready])
    good=last_mature_row[feature_ready]
    assert np.all(d['state_available_at'][good,2]<=known[feature_ready])
    predictions={name:np.full((count,5 if name=='five' else 3),np.nan) for name in SCHEMES}
    references={name:np.full_like(predictions[name],np.nan) for name in SCHEMES}
    persistence={name:np.full_like(predictions[name],np.nan) for name in SCHEMES}
    attr_predictions=np.full((count,3),np.nan);attr_reference=np.full((count,3),np.nan)
    folds=[];quarter_id=np.full(count,-1,np.int64)
    for g in ('crypto','etf_proxy'):
        group_rows=np.flatnonzero((d['group']==g)&eligible)
        names=sorted(set(d['asset'][group_rows]))
        identity=np.array([[a==name for name in names] for a in d['asset']],float)
        matrix=np.c_[numeric,identity]
        quarters=sorted({(stamp.year,(stamp.month-1)//3*3+1) for stamp in
            [dt.datetime.fromtimestamp(int(known[k])/1000,dt.timezone.utc) for k in group_rows] if stamp.year>=2023})
        for year,month in quarters:
            cutoff=int(dt.datetime(year,month,1,tzinfo=dt.timezone.utc).timestamp())*1000
            end=int(dt.datetime(year+int(month==10),1 if month==10 else month+3,1,tzinfo=dt.timezone.utc).timestamp())*1000
            train,test=purged_quarter(group_rows,known,maturity,cutoff,end)
            if len(train)<200 or not len(test):continue
            quarter_id[test]=cutoff;support={}
            for name in SCHEMES:
                classes=5 if name=='five' else 3
                predictions[name][test],support[name]=classifier(matrix,targets[name],train,test,classes)
                references[name][test]=asset_frequency(targets[name],d['asset'],train,test,classes)
                persistence[name][test]=.99*np.eye(classes)[labels[name][last_mature_row[test]]]+.01/classes
            binary=target_attributes[:,1].astype(float)
            binary_y=np.where(np.isfinite(binary),binary,-1).astype(np.int16)
            pcomp,_=classifier(matrix,binary_y,train,test,2)
            attr_predictions[test,0]=pcomp[:,1]
            attr_reference[test,0]=asset_mean(binary,d['asset'],train,test)
            logvol=np.log(np.maximum(target_attributes[:,2],1e-10))
            attr_predictions[test,1]=regression(matrix,logvol,train,test)
            attr_reference[test,1]=asset_mean(logvol,d['asset'],train,test)
            attr_predictions[test,2]=np.clip(regression(matrix,target_attributes[:,3],train,test),0,1)
            attr_reference[test,2]=asset_mean(target_attributes[:,3],d['asset'],train,test)
            folds.append(dict(group=g,cutoff=cutoff,end=end,training_rows=len(train),test_rows=len(test),
                latest_training_target=int(maturity[train].max()),supported_classes=support))
            print('fit',g,f'{year}Q{(month-1)//3+1}','train',len(train),'test',len(test),flush=True)
    metrics=[];paired=[];attribute_metrics=[];yearly=[]
    for g in ('crypto','etf_proxy'):
        ix=np.flatnonzero((d['group']==g)&np.isfinite(predictions['five']).all(1))
        for name in SCHEMES:
            n=int(d['horizon'][ix[0],2]);nonoverlap=ix[position[ix]%(2*n)==0]
            stats=classification_metrics(targets[name][ix],predictions[name][ix],references[name][ix])
            stats['persistence_brier']=classification_metrics(targets[name][ix],persistence[name][ix],references[name][ix])['brier']
            stats['nonoverlap']=classification_metrics(targets[name][nonoverlap],predictions[name][nonoverlap],references[name][nonoverlap])
            metrics.append(dict(group=g,scheme=name,**stats))
            years=known[ix].astype('datetime64[ms]').astype('datetime64[Y]').astype(str)
            for year in sorted(set(years)):
                rows=ix[years==year]
                yearly.append(dict(group=g,scheme=name,year=year,**classification_metrics(targets[name][rows],predictions[name][rows],references[name][rows])))
        y=targets['merged_three'][ix];projected=project_five_probabilities(predictions['five'][ix])
        ref=references['merged_three'][ix]
        onehot=np.eye(3)[y]
        delta=np.sum((predictions['merged_three'][ix]-onehot)**2,axis=1)-np.sum((projected-onehot)**2,axis=1)
        paired.append(dict(group=g,common_task='same merged-three target',
            projected_five=classification_metrics(y,projected,ref),direct_three=classification_metrics(y,predictions['merged_three'][ix],ref),
            direct_minus_projected_brier=paired_interval(delta,quarter_id[ix])))
        true=[target_attributes[ix,1],np.log(np.maximum(target_attributes[ix,2],1e-10)),target_attributes[ix,3]]
        for j,name in enumerate(('is_compression','log_volatility_daily','path_efficiency')):
            actual=true[j];p=attr_predictions[ix,j];ref=attr_reference[ix,j]
            error=(p-actual)**2 if j==0 else abs(p-actual)
            base=(ref-actual)**2 if j==0 else abs(ref-actual)
            record=dict(group=g,attribute=name,rows=len(ix),metric='binary_brier' if j==0 else 'mae',
                model_error=float(error.mean()),asset_history_error=float(base.mean()),
                skill=float(1-error.mean()/base.mean()),
                paired_error_delta=paired_interval(error-base,quarter_id[ix]))
            lag=((numeric[ix,2]<=.65).astype(float) if j==0 else
                 np.log(np.maximum(numeric[ix,4],1e-10)) if j==1 else numeric[ix,6])
            half=.5*lag+.5*ref
            lag_error=(lag-actual)**2 if j==0 else abs(lag-actual)
            half_error=(half-actual)**2 if j==0 else abs(half-actual)
            record.update(persistence_error=float(lag_error.mean()),
                fixed_half_shrinkage_error=float(half_error.mean()),
                model_vs_half_shrinkage=paired_interval(error-half_error,quarter_id[ix]))
            if j==0:record.update(prevalence=float(actual.mean()),accuracy=float(np.mean((p>=.5)==actual)))
            attribute_metrics.append(record)
    counts=[]
    for g in ('crypto','etf_proxy'):
        valid=(d['group']==g)&(state5>=0)
        for name in SCHEMES:
            counts.append(dict(group=g,scheme=name,counts=np.bincount(labels[name][valid],minlength=5 if name=='five' else 3).tolist(),
                valid_rows=int(valid.sum())))
    result=dict(schema='market_state_factorization_comparison_v1',research_only=True,orders_authorized=False,
        independent_oos=False,source=str(args.source),label_counts=counts,stability=stability_summary(stability),
        metrics=metrics,paired_common_task=paired,attribute_metrics=attribute_metrics,yearly=yearly,folds=folds,
        parameters=dict(reference='two-week',groups_horizon=dict(crypto=14,etf_proxy=10),
            target='state[k+n], centered [k+1,k+2n], target available at k+2n close + buffer',
            model='fixed shallow HGB 80 iterations, 7 leaves, depth3, minleaf60, l2=10, seed17',
            stability_stride=5,perturbations=[dict(name=name,parameters=pr) for name,pr in PERTURBATIONS],
            attribute_names=list(ATTRIBUTE_NAMES),input_names=list(INPUT_NAMES)),
        limitations=[
            '三组使用相同日线、过去2n根数值特征及资产身份、相同季度/成熟时间切分；不将中心事后标签或属性放进输入。',
            'five为当前五类候选；merged_three只合并非方向类，控制类别减少；factored_three只用标准化斜率方向阈值，不再用路径效率或收缩决定方向。',
            'A/B保留已有局部边界与弱收缩修正；C为未经该后处理的纯斜率定义。C是整套定义对照，不能把差异仅归因为去掉一个方向强度门槛。',
            '三个方案各自目标不完全相同，原始准确率、平衡准确率和Brier不能直接跨标签比较；共同目标配对比较仅用于five投影和merged_three，两者未来三类目标完全相同。',
            '独立属性为中心/外侧真振幅比及收缩标记、加权日收益波动率、整段净位移/总收盘路径长度；独立指单独输出，不意味着统计独立。',
            '属性另与当前值延续、当前值和训练期资产均值各50%的固定收缩基线比较；波动在对数尺度收缩。不搜索混合权重，优于长期均值不等于模型有增量。',
            '稳定性按每标的每5根固定取样，完整重算五类后处理及三类映射；共同斜率/半衰期扰动用于主要比较，效率/收缩扰动对纯方向主标签不作用是定义结果，不能宣传为额外预测能力。',
            '模型季度测试互不重复，只用截止前成熟目标训练；另报间隔2n根的非重叠目标样本。季度簇区间仅诊断，相关性与已消费历史、同样本规则选择限制保留。',
            '所有历史已消费，不是独立未见样本；三类较易预测不自动代表更真实或更有交易价值；本轮没有账户/交易回测或生产变更。',
            '保留既定下一周期中心标签目标，其原始窗口覆盖接下来2n根，而非仅未来n根持仓路径；没有为结果擅自改目标时钟。'])
    args.output.mkdir(parents=True)
    np.savez_compressed(args.output/'dataset.npz',asset=d['asset'],group=d['group'],known_at=known,ohlcv=d['ohlcv'],
        research_only=np.array(True),orders_authorized=np.array(False),label_uses_future=np.array(True),
        horizon=d['horizon'][:,2],X=numeric,feature_names=np.array(INPUT_NAMES),feature_available_at=known,
        state5=state5,merged_three=merged,factored_three=factored,attributes=attributes,
        attribute_names=np.array(ATTRIBUTE_NAMES),label_available_at=d['state_available_at'][:,2],
        target_five=targets['five'],target_merged_three=targets['merged_three'],target_factored_three=targets['factored_three'],
        target_attributes=target_attributes,target_available_at=maturity,target_row=destination,target_mask=mask,
        main_state_names=np.array(MAIN_STATES),five_state_names=np.array(LOCAL_STATES),last_mature_row=last_mature_row)
    arrays={f'{name}_probabilities':p for name,p in predictions.items()}
    arrays.update({f'{name}_frequency':p for name,p in references.items()})
    np.savez_compressed(args.output/'predictions.npz',**arrays,attribute_predictions=attr_predictions,
        attribute_reference=attr_reference,quarter_id=quarter_id,
        attribute_prediction_names=np.array(['is_compression','log_volatility_daily','path_efficiency']),
        five_state_names=np.array(LOCAL_STATES),main_state_names=np.array(MAIN_STATES))
    with np.load(args.output/'dataset.npz',allow_pickle=False) as z:
        export_merged_view(args.output,{key:z[key] for key in z.files})
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    (args.output/'report.md').write_text(report(result,args.output))
    print('saved',args.output,'folds',len(folds),'fits',6*len(folds),flush=True)


def report(r,output):
    lines=['# 五分类与三类主状态＋独立属性对照','',
        '同一批日线、同一两周参考尺度、同样过去2n根输入；季度成熟时钟切分。五类、直接合并三类、方向解耦三类并列，不挑最好年份。','']
    if r.get('research_choice'):
        lines += ['## 本轮判断','',
            '后续研究接口暂用B：上行／下行／震荡三类＋独立属性。保留原方向成立条件，仅合并非方向类；五类保留为对照。此选择改善类别语义与表示，不代表方向更稳定或预测更强。C纯斜率方向方案本轮不采用。','',
            '三套固定浅树在两组市场的全期Brier均未胜资产历史频率；相同三类目标上的直接训练与五类概率投影差异区间均跨零。波动率相对历史均值有可预测性，但固定半收缩误差更低，尚无树模型增量；收缩及路径效率也未显示稳定增量。','',
            'B仍依赖原斜率／真振幅强度门槛，不是已证实稳健的最终定义；独立路径效率属性采用整窗净位移／总收盘路径长度，与方向规则中的斜率／真振幅指标不同。震荡是未达到本尺度方向条件的剩余类，不保证固定箱体或均值回归。','']
    lines += [
        '|市场|方案|预测行|平衡准确率|Brier|历史频率Brier|相对频率Brier技能|非重叠技能|',
        '|---|---|---:|---:|---:|---:|---:|---:|']
    for m in r['metrics']:lines.append(f"|{m['group']}|{m['scheme']}|{m['rows']}|{m['balanced_accuracy']:.2%}|{m['brier']:.5f}|{m['frequency_brier']:.5f}|{m['brier_skill']:+.2%}|{m['nonoverlap']['brier_skill']:+.2%}|")
    lines+=['','不同标签的原始准确率不可直接判断方案优劣；以下是相同三类目标上的直接训练对比五类概率投影。','',
        '|市场|直接三类－五类投影的Brier差|季度簇95%区间|','|---|---:|---|']
    for p in r['paired_common_task']:
        x=p['direct_minus_projected_brier'];lines.append(f"|{p['group']}|{x['mean']:+.5f}|{x['interval95']}|")
    lines+=['','## 70%概率输出检查','',
        '|市场|方案|高分行|高分命中率|同批历史频率命中率|高分预测类别计数|',
        '|---|---|---:|---:|---:|---|']
    for m in r['metrics']:
        if m['high70_rows']:
            lines.append(f"|{m['group']}|{m['scheme']}|{m['high70_rows']}|{m['high70_accuracy']:.2%}|{m['high70_frequency_accuracy']:.2%}|{m['high70_predicted_counts']}|")
    lines+=['','## 独立属性预测','', '|市场|属性|误差|模型|资产历史均值|当前值延续|固定半收缩|','|---|---|---|---:|---:|---:|---:|']
    for a in r['attribute_metrics']:lines.append(f"|{a['group']}|{a['attribute']}|{a['metric']}|{a['model_error']:.6f}|{a['asset_history_error']:.6f}|{a['persistence_error']:.6f}|{a['fixed_half_shrinkage_error']:.6f}|")
    lines+=['','## 稳定性与类别支持','',
        '下表为重新标注后发生变化的比例；效率和收缩参数不作用于C是定义本身的结果。B对收缩定义明显更少敏感，但保留原方向强度门槛，币种对该门槛仍敏感。C移除了这个门槛，却更依赖斜率阈值，不能裁定整体更稳定。','',
        '|市场|扰动|A五类|B合并三类|C纯斜率三类|','|---|---|---:|---:|---:|']
    for group in ('crypto','etf_proxy'):
        for name,_ in PERTURBATIONS:
            values={s['scheme']:s['changed'] for s in r['stability'] if s['group']==group and s['perturbation']==name}
            lines.append(f"|{group}|{name}|{values['five']:.2%}|{values['merged_three']:.2%}|{values['factored_three']:.2%}|")
    lines+=['','完整类别分布、边界/内部变化、逐年结果、训练类支持及全部折时钟见results.json；稳定性样本每标的每5根取一次，非预测测试抽样。','',
        '## 逐日数据与图','',
        '- `three_main_states_and_attributes.csv` / `.npz`：B三类与独立属性的逐日视图，含原OHLCV、n、标签和目标成熟时间；缺少上下文为未标注，不是第四类。',
        '- `dataset.npz`：三方案及共同输入、属性、目标；`predictions.npz`：相同测试行的概率和属性预测，含轴名称。',
        '- [BTC同窗对照](plots/btcusdt_factorization.png)、[ETH同窗对照](plots/ethusdt_factorization.png)：红上行、绿下行、蓝震荡；附收缩、波动率和路径效率曲线，均为历史事后标注。','',
        '## 条件与限制','',*['- '+v for v in r['limitations']],'',
        '```bash',f'OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONPATH=src ./.venv/bin/python scripts/research/compare_market_state_factorizations.py --output {output}','```','']
    return '\n'.join(lines)


if __name__=='__main__':
    with threadpool_limits(limits=1):main()
