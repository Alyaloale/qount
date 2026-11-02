"""Separate label-boundary, training-objective and representation bottlenecks."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from sklearn.metrics import average_precision_score,roc_auc_score
import torch
from threadpoolctl import threadpool_limits

from qount.research.market_state_dataset import CurrentStateDataset,DEFAULT_ROOT
from qount.research.market_state_neural import fit_gru
from qount.research.market_state_switch_models import CHANGE_FEATURES,change_features,fit_switch_variant
from compare_market_state_normalization import evaluate,paired_blocks

BASELINE=Path('state/research_runs/market_state_normalization_compare_20261101')
VARIANTS=('baseline','uniform_replay','switch_replay','switch_weighted','aux_switch','attention','change_features')


def merged_label_components(raw,n,threshold=.5,efficiency_threshold=.1):
    """Vectorized current crypto pair_combined five-class rule, then merge.

    The five-class noise step only maps among nondirectional classes and
    therefore does not change the merged label. Price-edge relocation does.
    """
    log=np.log(raw[:,:,:4]);close=log[:,:,3];returns=np.diff(close,axis=1);center=n-1
    ranges=np.maximum(log[:,1:,1]-log[:,1:,2],np.maximum(abs(log[:,1:,1]-close[:,:-1]),abs(log[:,1:,2]-close[:,:-1])))
    atr=np.maximum(np.median(ranges,axis=1),1e-10);scores=[];efficiencies=[];labels=[]
    for offset in range(-3,4):
        t=np.arange(2*n)-(center+offset);w=np.exp2(-abs(t)/(n/3));w/=w.sum()
        slope=close@(w*(t-w@t)/(w@((t-w@t)**2)))
        rw=(w[1:]+w[:-1])/2;rw/=rw.sum();mean=returns@rw
        vol=np.sqrt(((returns-mean[:,None])**2)@rw);score=slope*np.sqrt(n)/np.maximum(vol,1e-10)
        efficiency=abs(slope)/np.maximum(ranges@rw,1e-12)
        near=abs((t[:-1]+t[1:])/2)<=max(1,n/3)
        ratio=ranges[:,near].mean(1)/np.maximum(ranges[:,~near].mean(1),1e-12)
        signs=np.sign(close-(close@w)[:,None]);crossings=(signs[:,1:]!=signs[:,:-1]).sum(1)
        five=np.where((score>=threshold)&(efficiency>=efficiency_threshold),0,np.where((score<=-threshold)&(efficiency>=efficiency_threshold),1,
            np.where(ratio<=.65,3,np.where(crossings>=2,2,4))))
        scores.append(score);efficiencies.append(efficiency);labels.append(five)
    labels=np.asarray(labels).T;score=scores[3];efficiency=efficiencies[3];base=labels[:,3]
    changes=labels[:,1:]!=labels[:,:-1];cut=changes.argmax(1)+1;a=labels[:,0];b=labels[:,-1]
    peak=(a==0)|(b==1);trough=(a==1)|(b==0)
    eligible=(changes.sum(1)==1)&(cut>=3)&(7-cut>=3)&((a<2)|(b<2))&(peak!=trough)
    local=close[:,center-2:center+3]
    pivot=center-2+np.where(peak,local.argmax(1),local.argmin(1));pair=base.copy()
    for p in range(center-1,center+2):
        before=close[:,center-3:p+1];after=close[:,p:center+4]
        enter=np.where(peak,close[:,p]-before.min(1),before.max(1)-close[:,p])
        leave=np.where(peak,close[:,p]-after.min(1),after.max(1)-close[:,p])
        take=eligible&(pivot==p)&(enter>=atr)&(leave>=atr)
        pair[take]=np.where(center<=p,a,b)[take]
    merged=np.where(pair<2,pair,2)
    return merged,score,efficiency,np.where(base<2,base,2)


def label_diagnostics(ds):
    d=ds.data;n=int(d['reference_sessions'])
    with np.load(str(d['source_dataset']),allow_pickle=False) as parent:
        raw=parent['market'][d['label_context_source_rows']]
    current,original,efficiency,unrefined=merged_label_components(raw,n)
    np.testing.assert_array_equal(current,d['state'])
    pure=np.where(original>=.5,0,np.where(original<=-.5,1,2))
    flat=raw.copy();flat[:,n:,:4]=raw[:,n-1,3,None,None]
    flat_state=merged_label_components(flat,n)[0]
    high=merged_label_components(raw,n,.55)[0];low=merged_label_components(raw,n,.45)[0]
    gate_high=merged_label_components(raw,n,efficiency_threshold=.11)[0]
    gate_low=merged_label_components(raw,n,efficiency_threshold=.09)[0]
    past=np.log(d['n_raw_market'][:,:,3]);past_return=past[:,-1]-past[:,0]
    result=[]
    for title,mask in [('all',np.ones(len(raw),bool)),('trend_onset',d['switch_label']&(d['state']<2)),
        ('trend_continuation',~d['switch_label']&(d['state']<2)),('sideways_onset',d['switch_label']&(d['state']==2))]:
        sign=np.where(d['state'][mask]==0,1,-1)
        result.append(dict(subset=title,rows=int(mask.sum()),flat_future_label_disagreement=float(np.mean(flat_state[mask]!=d['state'][mask])),
            threshold_plus10pct_label_disagreement=float(np.mean(high[mask]!=d['state'][mask])),
            threshold_minus10pct_label_disagreement=float(np.mean(low[mask]!=d['state'][mask])),
            efficiency_gate_plus10pct_label_disagreement=float(np.mean(gate_high[mask]!=d['state'][mask])),
            efficiency_gate_minus10pct_label_disagreement=float(np.mean(gate_low[mask]!=d['state'][mask])),
            median_abs_score=float(np.median(abs(original[mask]))),
            median_slope_range_efficiency=float(np.median(efficiency[mask])),
            observed_past_window_same_direction=float(np.mean(past_return[mask]*sign>0)) if title.startswith('trend') else None))
    return dict(source_labels_reproduced=True,definition='merge_five(window_refinement(pair_combined)); slope/range efficiency gate retained',
        pure_direction_disagreement_rows=int((pure!=current).sum()),pure_direction_disagreement_share=float(np.mean(pure!=current)),
        pair_boundary_changed_rows=int((unrefined!=current).sum()),groups=result,
        interpretation='Flat-future and threshold changes are label sensitivity diagnostics only, not alternative truth, model inputs or proof of a prediction upper bound.')


def phase_metrics(d,rows,p,reference):
    r=evaluate(d,rows,p,reference);side=d['state'][rows]==2
    r['sideways_misclassified_as_trend']=float(np.mean(p[side].argmax(1)!=2))
    return r


def capacity_sanity(ds):
    """Can the same GRU memorize a tiny balanced, training-only case set?"""
    d=ds.data;cutoff=1672531200000;train=np.flatnonzero(d['label_available_at']<cutoff)
    rng=np.random.default_rng(17);parts=[]
    for state,count in ((0,32),(1,32),(2,64)):
        eligible=train[(d['state'][train]==state)&(d['switch_label'][train] if state<2 else ~d['switch_label'][train])]
        parts.append(rng.choice(eligible,count,replace=False))
    selected=np.concatenate(parts);start=time.monotonic()
    p,detail,_=fit_gru(ds.inputs(np.arange(len(d['state'])))['market'],ds.asset_index,d['state'],selected,selected,
        assets=len(ds.asset_names),epochs=1000,seed=17)
    y=d['state'][selected];onset=y<2
    return dict(research_only=True,orders_authorized=False,
        scope='capacity sanity only; train evaluated on itself; no generalization or trading inference',
        cutoff=cutoff,training_rows=len(selected),source_rows=d['source_row'][selected].tolist(),
        class_counts=np.bincount(y,minlength=3).tolist(),epochs=1000,seed=17,
        accuracy=float(np.mean(p.argmax(1)==y)),trend_onset_accuracy=float(np.mean(p.argmax(1)[onset]==y[onset])),
        seconds=time.monotonic()-start,last_training_cross_entropy=detail['training_cross_entropy'][-1])


def early_phase_diagnostics(d,rows,probability):
    age=np.full(len(d['state']),-1,int)
    for a in np.unique(d['asset']):
        known=False;running=0
        for row in np.flatnonzero(d['asset']==a):
            if d['switch_label'][row]:known=True;running=1
            elif known:running+=1
            if known:age[row]=running
    pred=probability.argmax(1);y=d['state'][rows]
    early=(age[rows]>=1)&(age[rows]<=3)&(y<2)
    # Hindsight conditioning is diagnostic only, never an inference filter.
    origin=d['previous_state_label'][rows]==2;event=y[origin]<2;score=probability[origin,:2].sum(1)
    return dict(first_three_trend_days=int(early.sum()),first_three_trend_accuracy=float(np.mean(pred[early]==y[early])),
        from_true_sideways_rows=int(origin.sum()),from_true_sideways_trend_onset_prevalence=float(event.mean()),
        from_true_sideways_trend_onset_roc_auc=float(roc_auc_score(event,score)),
        from_true_sideways_trend_onset_average_precision=float(average_precision_score(event,score)),
        conditioning_is_hindsight_not_model_input=True)


def summarize(ds,p,aux,reference,fold,seeds,training):
    d=ds.data;valid=np.isfinite(p).all((0,1,3));rows=np.flatnonzero(valid);records=[];means={}
    for j,name in enumerate(VARIANTS):
        group=[]
        for i,seed in enumerate(seeds):
            own=dict(variant=name,seed=seed,**phase_metrics(d,rows,p[i,j,rows],reference[rows]))
            own['early_phase']=early_phase_diagnostics(d,rows,p[i,j,rows])
            own['per_asset']={}
            for a in ds.asset_names:
                ix=rows[d['asset'][rows]==a];own['per_asset'][a]=phase_metrics(d,ix,p[i,j,ix],reference[ix])
            records.append(own);group.append(own)
        mean={k:float(np.mean([r[k] for r in group])) for k in ('accuracy','balanced_accuracy','macro_f1','brier',
            'trend_switch_accuracy','sideways_switch_accuracy','sideways_misclassified_as_trend')}
        mean['switch_accuracy']=float(np.mean([r['switch']['accuracy'] for r in group]))
        mean['class_recall']=np.mean([r['class_recall'] for r in group],axis=0).tolist()
        for k in ('first_three_trend_accuracy','from_true_sideways_trend_onset_roc_auc','from_true_sideways_trend_onset_average_precision'):
            mean[k]=float(np.mean([r['early_phase'][k] for r in group]))
        mean['in_sample_trend_switch_accuracy_by_fold_mean']=float(np.mean([f['training_metrics']['trend_switch_accuracy'] for f in training if f['variant']==name]))
        means[name]=mean
    aux_stats=[]
    for i,seed in enumerate(seeds):
        score=aux[i,VARIANTS.index('aux_switch'),rows];actual=d['switch_label'][rows];chosen=score>=.5
        aux_stats.append(dict(seed=seed,rows=len(rows),switch_prevalence=float(actual.mean()),
            roc_auc=float(roc_auc_score(actual,score)),average_precision=float(average_precision_score(actual,score)),
            threshold=.5,recall=float(chosen[actual].mean()),false_positive_rate=float(chosen[~actual].mean()),
            precision=float(actual[chosen].mean()) if chosen.any() else None,predicted_rows=int(chosen.sum()),
            note='Weighted auxiliary loss; raw probabilities not calibrated. No threshold selected on test.'))
    intervals={}
    for j,name in enumerate(VARIANTS[1:],1):
        pair=p[:,[0,j]]
        trend=dict(d);trend['switch_label']=d['switch_label']&(d['state']<2)
        intervals[name]=dict(overall=paired_blocks(d,rows,pair,28),trend_onset=paired_blocks(trend,rows,pair,28))
    return dict(rows=len(rows),dates=len(np.unique(d['decision_at'][rows])),switch_rows=int(d['switch_label'][rows].sum()),
        trend_switch_rows=int((d['switch_label'][rows]&(d['state'][rows]<2)).sum()),
        first_decision=str(d['decision_at'][rows].min().astype('datetime64[ms]')),
        last_decision=str(d['decision_at'][rows].max().astype('datetime64[ms]')),
        seed_mean=means,records=records,auxiliary_switch_detection=aux_stats,paired_intervals=intervals)


def write_report(r,out):
    s=r['summary'];lines=['# 切换学习瓶颈诊断','',
        f"同一完整7币种数据、14×9输入，16个季度前推，种子{r['seeds']}，共同测试{s['rows']}条、{s['dates']}天；切换{s['switch_rows']}条，其中新趋势{s['trend_switch_rows']}条。决策日期{s['first_decision']}—{s['last_decision']} UTC。",
        '只用成熟训练标签，原标签、归一化及默认模型不变。三种子均值不是集成结果。历史已被消费，属于研究对照，不是独立未来验证。','',
        '## 单因素对照','',
        '- baseline：原GRU32，普通交叉熵20轮；本轮重拟合并与原保存概率逐值核对。',
        '- uniform_replay：相同20轮权重起点，降低学习率后普通损失继续5轮。',
        '- switch_replay：相同20轮起点，继续5轮，切换首日样本损失×4；与uniform_replay控制额外训练量。',
        '- switch_weighted：结构不变，20轮全程切换首日损失×4。',
        '- aux_switch：20轮，共享编码器，增加二分类切换监督头；辅助损失0.3，正权重由训练折确定。真实前日状态不作为输入。',
        '- attention：20轮，在相同GRU输出上增加以最后时刻为query的时间注意力池化和融合。',
        '- change_features：20轮，保留原始序列，向分类头补充12个仅用历史窗口的变化摘要，训练折拟合尺度。',
        '注意力与特征分支含少量新增参数，实验只能评价具体实现，不能宣称整个架构家族有效或无效。','',
        '| 方案 | 准确率 | 宏F1 | Brier低优 | 新趋势首日正确率 | 进入震荡首日正确率 | 震荡误判趋势率 |','|---|---:|---:|---:|---:|---:|---:|']
    for name,v in s['seed_mean'].items():
        lines.append(f"| {name} | {v['accuracy']:.2%} | {v['macro_f1']:.4f} | {v['brier']:.4f} | {v['trend_switch_accuracy']:.2%} | {v['sideways_switch_accuracy']:.2%} | {v['sideways_misclassified_as_trend']:.2%} |")
    lines += ['', '新趋势首日正确率是当日三分类是否识别新方向，不是独立二分类切换检测的召回。震荡误判趋势率以事后震荡样本为分母。两者应联合看，避免靠频繁报告趋势获得表面召回。','',
        '## 标签边界诊断','',
        '当前主标签实际为旧五类pair_combined合并，保留斜率/日振幅效率门槛和边界修正；不是纯方向三类。已从原生28根上下文完整复现。把未来14根OHLC改为当天收盘价，仅检验标签对未来路径的敏感性；不是替代标签或可预测率上限。',
        f"纯方向备选定义与当前标签有{r['label_diagnostics']['pure_direction_disagreement_rows']}条（{r['label_diagnostics']['pure_direction_disagreement_share']:.2%}）不同；当前边界修正相对原五类基础规则改变{r['label_diagnostics']['pair_boundary_changed_rows']}条。",'',
        '| 子集 | 样本 | 未来走平后标签改变 | 方向阈值+10%后改变 | 效率门槛+10%后改变 | 原方向分数绝对值中位数 | 过去窗口净变化同向比例 |','|---|---:|---:|---:|---:|---:|---:|']
    for v in r['label_diagnostics']['groups']:
        past=f"{v['observed_past_window_same_direction']:.2%}" if v['observed_past_window_same_direction'] is not None else '—'
        lines.append(f"| {v['subset']} | {v['rows']} | {v['flat_future_label_disagreement']:.2%} | {v['threshold_plus10pct_label_disagreement']:.2%} | {v['efficiency_gate_plus10pct_label_disagreement']:.2%} | {v['median_abs_score']:.3f} | {past} |")
    lines += ['', '所有子集按事后标签诊断，不进入模型输入。首日边界敏感与未来依赖说明任务困难，不等于标签错误或已证明不可预测。','',
        '## 训练内是否已经学到首日','',
        '| 方案 | 训练折内新趋势首日正确率均值 | 时间前推测试新趋势首日正确率 |','|---|---:|---:|']
    for name,v in s['seed_mean'].items():lines.append(f"| {name} | {v['in_sample_trend_switch_accuracy_by_fold_mean']:.2%} | {v['trend_switch_accuracy']:.2%} |")
    lines += ['', '训练列为各折各种子比例的均值，扩展训练集彼此重叠；不作为独立样本计数，且与测试列的时间组成不同。']
    if 'capacity_sanity' in r:
        cap=r['capacity_sanity']
        lines += ['',f"容量检查：仅用2023年前已成熟的128条均衡训练样本（上/下行首日各32、震荡延续64），相同GRU训练1,000轮，训练自身正确率{cap['accuracy']:.2%}，其中新趋势首日{cap['trend_onset_accuracy']:.2%}。这证明能记忆这个小子集，不证明全数据容量充足、泛化有效或有可交易信号。"]
    lines += ['',
        '## 早期阶段与起点排序能力','',
        '| 方案 | 新趋势前3日正确率 | 真实前日震荡子集的起点ROC-AUC | 同子集起点PR平均精度 |','|---|---:|---:|---:|']
    for name,v in s['seed_mean'].items():
        lines.append(f"| {name} | {v['first_three_trend_accuracy']:.2%} | {v['from_true_sideways_trend_onset_roc_auc']:.3f} | {v['from_true_sideways_trend_onset_average_precision']:.3f} |")
    group=s['records'][0]['early_phase']
    lines += ['',f"前日真实震荡子集共{group['from_true_sideways_rows']}条，进入趋势基率{group['from_true_sideways_trend_onset_prevalence']:.2%}。分数为模型上/下行概率之和；此处使用事后前日标签分组，仅用于诊断，实时不能据此筛选。",
        '起点正确率上升与起点排序改善应区分；模型更频繁报告趋势也可能提高前者。','',
        '## 辅助头的切换检测','',
        '| 种子 | 切换基率 | ROC-AUC | PR平均精度 | 阈值0.5召回 | 精确率 | 非切换日误报率 |','|---|---:|---:|---:|---:|---:|---:|']
    for v in s['auxiliary_switch_detection']:
        precision=f"{v['precision']:.2%}" if v['precision'] is not None else '—'
        lines.append(f"| {v['seed']} | {v['switch_prevalence']:.2%} | {v['roc_auc']:.3f} | {v['average_precision']:.3f} | {v['recall']:.2%} | {precision} | {v['false_positive_rate']:.2%} |")
    lines += ['', '辅助头采用正样本加权，原始概率未校准；0.5为固定诊断阈值，没有使用测试集调阈值。PR随机参考为切换基率。','',
        '## 研究判断','',
        '本轮优先问题是监督任务与边界可辨识性，随后是切换类型和训练目标；尚无证据把更大注意力架构作为首选解决方案。边界依赖未来不能证明不可预测，所有架构结论只适用于本轮小模型与固定训练设置。',
        '无差别切换加权主要改善进入震荡，对新趋势首日仍弱且整体概率误差增加。单二分类辅助切换头的排序接近随机，注意力/变化特征有类别均衡收益，但趋势误报增加、起点条件排序未明显改善。',
        '下一项有效实验应保留原始数据与三类主输出，先区分进入上行、进入下行、进入震荡，并用成熟标签给新趋势前3日及相似但未切换的难负例提供监督；与普通重放做配对。另可单独检验方向分数、斜率/日振幅效率两个连续目标，减少只围绕离散边界学习的困难。上述改进尚未运行，不宣称有效。',
        '完整逐种子、逐币种、训练损失和28日按日期配对分块区间见results.json；逐条主状态及切换概率见predictions.npz。',
        '没有补造/复制新事件，没有使用未来数据或真实前日状态作输入，没有交易回测或实盘变更。']
    (out/'report.md').write_text('\n'.join(lines)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--dataset',type=Path,default=DEFAULT_ROOT)
    parser.add_argument('--baseline',type=Path,default=BASELINE);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--seeds',type=int,nargs='+',default=[17,29,43]);parser.add_argument('--max-seconds',type=int,default=1800)
    args=parser.parse_args()
    if args.output.exists():parser.error('preserve previous experiments')
    ds=CurrentStateDataset(args.dataset);d=ds.data;rows=np.arange(len(d['state']));sequence=ds.inputs(rows)['market'];asset=ds.asset_index
    features=change_features(ds.inputs(rows,scaled=False)['market']);labels=label_diagnostics(ds)
    source_hash=hashlib.sha256((args.dataset/'dataset.npz').read_bytes()).hexdigest()
    old=json.loads((args.baseline/'results.json').read_text());assert old['dataset_sha256']==source_hash
    with np.load(args.baseline/'predictions.npz',allow_pickle=False) as f:previous={k:f[k] for k in f.files}
    np.testing.assert_array_equal(previous['source_row'],d['source_row'])
    p=np.full((len(args.seeds),len(VARIANTS),len(rows),3),np.nan);aux=np.full(p.shape[:-1],np.nan)
    reference=previous['reference'];fold=previous['fold_id'];fits=[];args.output.mkdir(parents=True)
    (args.output/'label_diagnostics.json').write_text(json.dumps(labels,ensure_ascii=False,indent=2)+'\n')
    torch.set_num_threads(2);torch.use_deterministic_algorithms(True);start=time.monotonic()
    for cutoff in np.unique(fold[fold>=0]):
        test=np.flatnonzero(fold==cutoff);train=np.flatnonzero(d['label_available_at']<cutoff)
        assert len(train)>0 and d['label_available_at'][train].max()<cutoff
        for i,seed in enumerate(args.seeds):
            if time.monotonic()-start>args.max_seconds:raise RuntimeError('bounded_switch_diagnosis_budget_exceeded')
            fit_start=time.monotonic();prob,detail,baseline=fit_gru(sequence,asset,d['state'],train,test,assets=len(ds.asset_names),epochs=20,seed=seed)
            seed_position=previous['seeds'].tolist().index(seed)
            np.testing.assert_allclose(prob,previous['probabilities'][seed_position,0,test],rtol=0,atol=2e-7)
            p[i,0,test]=prob;training=detail.pop('train_prediction')
            fits.append(dict(cutoff=int(cutoff),seed=seed,variant='baseline',seconds=time.monotonic()-fit_start,
                training_rows=len(train),test_rows=len(test),latest_training_label=int(d['label_available_at'][train].max()),
                training_metrics=phase_metrics(d,train,training,np.full_like(training,1/3)),**detail))
            for j,name in enumerate(VARIANTS[1:],1):
                if time.monotonic()-start>args.max_seconds:raise RuntimeError('bounded_switch_diagnosis_budget_exceeded')
                fit_start=time.monotonic()
                prob,auxiliary,training,detail,checkpoint=fit_switch_variant(sequence,asset,d['state'],d['switch_label'],features,train,test,
                    assets=len(ds.asset_names),variant=name,seed=seed,baseline=baseline)
                p[i,j,test]=prob;aux[i,j,test]=auxiliary
                for key in ('mean','scale','feature_mean','feature_scale'):checkpoint[key]=torch.as_tensor(checkpoint[key])
                checkpoint.update(cutoff=int(cutoff),seed=seed,asset_names=ds.asset_names,research_only=True,orders_authorized=False)
                torch.save(checkpoint,args.output/f'latest_{name}_{seed}.pt')
                fits.append(dict(cutoff=int(cutoff),seed=seed,variant=name,seconds=time.monotonic()-fit_start,
                    training_rows=len(train),test_rows=len(test),latest_training_label=int(d['label_available_at'][train].max()),
                    training_metrics=phase_metrics(d,train,training,np.full_like(training,1/3)),**detail))
            print(f"quarter={dt.datetime.fromtimestamp(int(cutoff)/1000,dt.timezone.utc).date()} seed={seed} completed7 elapsed={time.monotonic()-start:.1f}s",flush=True)
            np.savez_compressed(args.output/'predictions.npz',probabilities=p,switch_probabilities=aux,reference=reference,fold_id=fold,
                source_row=d['source_row'],seeds=np.array(args.seeds),variants=np.array(VARIANTS),research_only=True,orders_authorized=False)
    assert source_hash==hashlib.sha256((args.dataset/'dataset.npz').read_bytes()).hexdigest()
    capacity=capacity_sanity(ds)
    (args.output/'capacity_sanity.json').write_text(json.dumps(capacity,ensure_ascii=False,indent=2)+'\n')
    result=dict(research_only=True,orders_authorized=False,independent_oos=False,dataset=str(args.dataset),dataset_sha256=source_hash,
        source_unchanged=True,seeds=args.seeds,variants=list(VARIANTS),feature_names=list(CHANGE_FEATURES),fits=fits,
        elapsed_seconds=time.monotonic()-start,versions=dict(torch=str(torch.__version__),numpy=np.__version__),
        label_diagnostics=labels,capacity_sanity=capacity,summary=summarize(ds,p,aux,reference,fold,args.seeds,fits))
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n');write_report(result,args.output)
    print(json.dumps(result['summary']['seed_mean'],ensure_ascii=False),flush=True)


if __name__=='__main__':
    with threadpool_limits(limits=1):main()
