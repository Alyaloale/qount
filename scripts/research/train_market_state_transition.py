"""Validate typed early-state learning against saved identical baseline folds."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from sklearn.metrics import average_precision_score,roc_auc_score
import torch
from threadpoolctl import threadpool_limits

from qount.research.market_state_dataset import CurrentStateDataset,DEFAULT_ROOT
from qount.research.market_state_calibration import apply_calibration,fit_calibration,mature_calibration_rows
from qount.research.market_state_transition import CONTINUOUS_NAMES,PHASE_NAMES,fit_typed_transition,transition_targets
from diagnose_market_state_switch_learning import phase_metrics,early_phase_diagnostics
from compare_market_state_normalization import paired_blocks
from compare_market_state_factorizations import asset_frequency


def summarize(ds,targets,p,phase,reference,fold,seeds):
    d=ds.data;valid=np.isfinite(p).all((0,1,3));rows=np.flatnonzero(valid);records=[];means={}
    for j,name in enumerate(('baseline','typed_transition')):
        group=[]
        for i,seed in enumerate(seeds):
            r=dict(model=name,seed=seed,**phase_metrics(d,rows,p[i,j,rows],reference[rows]))
            r['early_phase']=early_phase_diagnostics(d,rows,p[i,j,rows]);r['per_asset']={};r['per_quarter']={}
            for asset in ds.asset_names:
                own=rows[d['asset'][rows]==asset];r['per_asset'][asset]=phase_metrics(d,own,p[i,j,own],reference[own])
            for cutoff in np.unique(fold[rows]):
                own=rows[fold[rows]==cutoff];r['per_quarter'][str(int(cutoff))]=phase_metrics(d,own,p[i,j,own],reference[own])
            group.append(r);records.append(r)
        means[name]={k:float(np.mean([r[k] for r in group])) for k in ('accuracy','balanced_accuracy','macro_f1','brier',
            'trend_switch_accuracy','sideways_switch_accuracy','sideways_misclassified_as_trend')}
        means[name]['first_three_trend_accuracy']=float(np.mean([r['early_phase']['first_three_trend_accuracy'] for r in group]))
        means[name]['class_recall']=np.mean([r['class_recall'] for r in group],axis=0).tolist()
    auxiliary=[];known=targets['phase_valid'][rows];actual=targets['phase'][rows][known]
    for i,seed in enumerate(seeds):
        probability=phase[i,rows][known];onset=np.isin(actual,[1,2]);score=probability[:,1:3].sum(1)
        auxiliary.append(dict(seed=seed,early_trend_prevalence=float(onset.mean()),early_trend_roc_auc=float(roc_auc_score(onset,score)),
            early_trend_average_precision=float(average_precision_score(onset,score)),
            phase_accuracy=float(np.mean(probability.argmax(1)==actual))))
    trend=dict(d);trend['switch_label']=d['switch_label']&(d['state']<2)
    return dict(rows=len(rows),first_decision=str(d['decision_at'][rows].min().astype('datetime64[ms]')),
        last_decision=str(d['decision_at'][rows].max().astype('datetime64[ms]')),seed_mean=means,records=records,
        auxiliary=auxiliary,paired_intervals=dict(overall=paired_blocks(d,rows,p,28),trend_onset=paired_blocks(trend,rows,p,28)))


def historical_calibration(ds,targets,p,phase,fold,seeds):
    """Calibrate each fold using only earlier, already-mature OOS forecasts."""
    d=ds.data;calibrated=np.full_like(p,np.nan);phase_cal=np.full_like(phase,np.nan)
    alarm=np.zeros(phase.shape[:2],bool);enabled=np.zeros_like(alarm);records=[]
    for cutoff in np.unique(fold[fold>=0]):
        test=np.flatnonzero(fold==cutoff)
        for i,seed in enumerate(seeds):
            for j,model in enumerate(('baseline','typed_transition')):
                history=mature_calibration_rows(d['decision_at'],targets['available_at'],p[i,j],cutoff)
                calibration=fit_calibration(p[i,j,history],targets['state'][history])
                calibrated[i,j,test]=apply_calibration(p[i,j,test],calibration)
                records.append(dict(cutoff=int(cutoff),seed=seed,model=model,calibration=calibration,
                    latest_calibration_label=int(targets['available_at'][history].max()) if len(history) else None))
            history=mature_calibration_rows(d['decision_at'],targets['available_at'],phase[i],cutoff)
            history=history[targets['phase_valid'][history]]
            calibration=fit_calibration(phase[i,history],targets['phase'][history])
            phase_cal[i,test]=apply_calibration(phase[i,test],calibration)
            threshold=None
            if calibration['rows']>=200:
                past=apply_calibration(phase[i,history],calibration)[:,1:3].sum(1)
                negative=~np.isin(targets['phase'][history],[1,2])
                threshold=float(np.quantile(past[negative],.95))
                enabled[i,test]=True;alarm[i,test]=phase_cal[i,test,1:3].sum(1)>=threshold
            records.append(dict(cutoff=int(cutoff),seed=seed,model='phase',calibration=calibration,early_trend_threshold=threshold,
                historical_false_positive_target=.05,
                latest_calibration_label=int(targets['available_at'][history].max()) if len(history) else None))
    warning=[];valid=np.isfinite(p).all((0,1,3));rows=np.flatnonzero(valid&targets['phase_valid'])
    for i,seed in enumerate(seeds):
        ix=rows[enabled[i,rows]];actual=np.isin(targets['phase'][ix],[1,2]);chosen=alarm[i,ix]
        onset=d['switch_label'][ix]&(d['state'][ix]<2)
        score=phase_cal[i,rows,1:3].sum(1);truth=np.isin(targets['phase'][rows],[1,2])
        warning.append(dict(seed=seed,rows=len(ix),early_trend_prevalence=float(actual.mean()),
            precision=float(actual[chosen].mean()) if chosen.any() else None,recall=float(chosen[actual].mean()),
            false_positive_rate=float(chosen[~actual].mean()),first_day_recall=float(chosen[onset].mean()),
            alarm_rows=int(chosen.sum()),auc=float(roc_auc_score(truth,score)),average_precision=float(average_precision_score(truth,score)),
            note='Target is current day within first three trend days, not a forecast of next-day switch. Historical FPR budget does not guarantee test FPR.'))
    return calibrated,phase_cal,alarm,enabled,dict(records=records,warning=warning)


def bundle_metrics(ds,targets,raw_phase,calibrated_phase,fold):
    d=ds.data;known=(fold>=0)&targets['phase_valid'];rows=np.flatnonzero(known)
    frequency=np.full((len(known),4),np.nan)
    for cutoff in np.unique(fold[known]):
        train=np.flatnonzero((targets['available_at']<cutoff)&targets['phase_valid']);test=np.flatnonzero(fold==cutoff)
        frequency[test]=asset_frequency(targets['phase'],d['asset'],train,test,4)
    actual=np.isin(targets['phase'][rows],[1,2]);hot=np.eye(4)[targets['phase'][rows]];metrics={}
    count=len(raw_phase)
    for name,p in [('frequency',np.repeat(frequency[None],count,axis=0)),('raw',raw_phase),('calibrated',calibrated_phase)]:
        risk=p[:,rows,1:3].sum(2)
        metrics[name]=dict(early_brier=float(((risk-actual)**2).mean()),phase_brier=float(((p[:,rows]-hot)**2).sum(2).mean()),
            mean_probability=float(risk.mean()),actual_prevalence=float(actual.mean()),
            roc_auc=float(np.mean([roc_auc_score(actual,a) for a in risk])),
            average_precision=float(np.mean([average_precision_score(actual,a) for a in risk])))
    pair=np.full((count,2,len(known),3),np.nan)
    for i in range(count):
        for j,risk in enumerate((frequency[rows,1:3].sum(1),calibrated_phase[i,rows,1:3].sum(1))):
            pair[i,j,rows]=np.c_[1-risk,risk,np.zeros(len(rows))]
    shadow=dict(d);shadow['state']=np.isin(targets['phase'],[1,2]).astype(int)
    interval=paired_blocks(shadow,rows,pair,28)['changes']['brier']
    interval['relative_minus_existing']/=2;interval['interval95']=(np.array(interval['interval95'])/2).tolist()
    return dict(rows=len(rows),probability_target='current day within first three trend days',metrics=metrics,
        calibrated_minus_frequency_binary_brier=interval,state_output='retained baseline without main calibration or joint phase mixing',
        automatic_alerts_enabled=False)


def write_report(r,out):
    s=r['summary'];lines=['# 分类型切换学习修复验证','']
    if 'bundle_metrics' in r:
        m=r['bundle_metrics']['metrics'];ci=r['bundle_metrics']['calibrated_minus_frequency_binary_brier']
        lines += ['采用独立的主状态估计与早期阶段估计。主状态保留原GRU概率，新增阶段模型经历史成熟预测校准，输出当天处于新趋势前3日的概率；不自动触发告警、改判或交易。',
            '未采用混合主状态及主状态校准：两者均未改善主分类。默认入口已切到`state_with_transition`，旧模型仍可显式`--model gru`运行。','',
            '可用组合权重：`latest_state_with_transition_17.pt`（另有29/43）；默认训练入口另实跑的权重与说明见[端到端报告](../market_state_transition_default_20261101/report.md)。`latest_17.pt`等是未采用的混合主状态研究模型。','',
            '| 新趋势早期概率 | Brier低优 | 平均概率 | 实际占比 | ROC-AUC | PR平均精度 |','|---|---:|---:|---:|---:|---:|']
        for name in ('frequency','raw','calibrated'):
            v=m[name];lines.append(f"| {name} | {v['early_brier']:.4f} | {v['mean_probability']:.2%} | {v['actual_prevalence']:.2%} | {v['roc_auc']:.3f} | {v['average_precision']:.3f} |")
        lines += ['',f"校准概率相对成熟资产频率基线的Brier差{ci['relative_minus_existing']:+.6f}，28日分块95%区间{ci['interval95']}，跨零，尚无稳定优势证据。原主状态预测保持逐条一致，3种子平均准确率仍{s['seed_mean']['baseline']['accuracy']:.2%}。",
            '阶段概率属于当天事后阶段的估计，不是下一日切换预报。分类型监督有弱排序信号，首日高准确率尚未解决。','',
            '## 未采用的混合主状态对照','']
    lines += [
        f"同一完整7币种数据、14×9输入、16季度前推、种子{r['seeds']}，共同测试{s['rows']}条；决策时间{s['first_decision']}—{s['last_decision']} UTC。",
        '保留原主标签和输入缩放。该对照版本的三状态输出由“延续状态专家＋进入上/下/震荡前3日的概率”组成，阶段不是第四个市场状态。',
        '主状态使用不加权的全样本负对数似然。辅助阶段损失分类型平衡，并增加已成熟震荡难负例权重；另外预测连续方向分数、带符号的斜率/日振幅效率。未知初始段龄被掩码，没有使用未来段长。',
        '所有辅助目标只供监督，成熟时点仍为k+n。模型推断只接收日线序列和标的身份。未校准或用测试集选阈值；该历史已消费，不是独立未来验证。','',
        '| 模型 | 准确率 | 平衡准确率 | 宏F1 | Brier低优 | 新趋势首日 | 新趋势前3日 | 震荡误报趋势 |','|---|---:|---:|---:|---:|---:|---:|---:|']
    for name,v in s['seed_mean'].items():
        lines.append(f"| {name} | {v['accuracy']:.2%} | {v['balanced_accuracy']:.2%} | {v['macro_f1']:.4f} | {v['brier']:.4f} | {v['trend_switch_accuracy']:.2%} | {v['first_three_trend_accuracy']:.2%} | {v['sideways_misclassified_as_trend']:.2%} |")
    lines += ['', '## 随机种子复核','', '| 种子 | 模型 | 准确率 | Brier | 新趋势首日 | 震荡误报趋势 |','|---|---|---:|---:|---:|---:|']
    for v in s['records']:
        lines.append(f"| {v['seed']} | {v['model']} | {v['accuracy']:.2%} | {v['brier']:.4f} | {v['trend_switch_accuracy']:.2%} | {v['sideways_misclassified_as_trend']:.2%} |")
    lines += ['', '## 辅助阶段头','', '| 种子 | 早期趋势基率 | 早期趋势AUC | PR平均精度 |','|---|---:|---:|---:|']
    for v in s['auxiliary']:lines.append(f"| {v['seed']} | {v['early_trend_prevalence']:.2%} | {v['early_trend_roc_auc']:.3f} | {v['early_trend_average_precision']:.3f} |")
    lines += ['', '## 配对差异','', '按28日日期分块，保留同日全部币种及种子；2,000次重采样，只近似处理时间依赖。','',
        '| 指标 | 候选−基线 | 95%区间 |','|---|---:|---|']
    for key in ('accuracy','brier','switch_accuracy'):
        block=s['paired_intervals']['trend_onset' if key=='switch_accuracy' else 'overall']['changes'][key]
        factor=1 if key=='brier' else 100;lo,hi=np.array(block['interval95'])*factor
        lines.append(f"| {key}{'（新趋势首日）' if key=='switch_accuracy' else ''} | {block['relative_minus_existing']*factor:+.4f} | [{lo:+.4f}, {hi:+.4f}] |")
    lines += ['', '混合主状态版本未被采用；研究默认保留原主状态，新增独立阶段概率。当前排序信号较弱，首日硬分类尚未解决，测试通过不代表预测能力或交易收益已修复。',
        '完整逐币种/季度/种子结果见results.json；targets.npz为辅助监督，predictions.npz为配对预测；latest_*仅最后一折研究权重。']
    (out/'report.md').write_text('\n'.join(lines)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--dataset',type=Path,default=DEFAULT_ROOT)
    parser.add_argument('--baseline',type=Path,default=Path('state/research_runs/market_state_normalization_compare_20261101'))
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--seeds',type=int,nargs='+',default=[17,29,43])
    parser.add_argument('--max-seconds',type=int,default=900);args=parser.parse_args()
    if args.output.exists():parser.error('preserve existing results')
    ds=CurrentStateDataset(args.dataset);d=ds.data;rows=np.arange(len(d['state']));targets=transition_targets(ds)
    sequence=ds.inputs(rows)['market'];raw=ds.inputs(rows,scaled=False)['market'];asset=ds.asset_index
    source_hash=hashlib.sha256((args.dataset/'dataset.npz').read_bytes()).hexdigest()
    old=json.loads((args.baseline/'results.json').read_text());assert old['dataset_sha256']==source_hash
    with np.load(args.baseline/'predictions.npz',allow_pickle=False) as z:base={k:z[k] for k in z.files}
    np.testing.assert_array_equal(base['source_row'],d['source_row'])
    p=np.full((len(args.seeds),2,len(rows),3),np.nan);phase=np.full((len(args.seeds),len(rows),4),np.nan)
    regression=np.full((len(args.seeds),len(rows),2),np.nan);fold=base['fold_id'];reference=base['reference'];fits=[]
    for i,seed in enumerate(args.seeds):p[i,0]=base['probabilities'][base['seeds'].tolist().index(seed),0]
    args.output.mkdir(parents=True);np.savez_compressed(args.output/'targets.npz',**targets,research_only=True,orders_authorized=False)
    torch.set_num_threads(2);torch.use_deterministic_algorithms(True);start=time.monotonic()
    for cutoff in np.unique(fold[fold>=0]):
        train=np.flatnonzero(targets['available_at']<cutoff);test=np.flatnonzero(fold==cutoff)
        for i,seed in enumerate(args.seeds):
            if time.monotonic()-start>args.max_seconds:raise RuntimeError('bounded_transition_training_exceeded')
            before=time.monotonic()
            prob,phase_prob,reg,detail,cp=fit_typed_transition(sequence,asset,raw,targets,train,test,assets=len(ds.asset_names),seed=seed)
            p[i,1,test]=prob;phase[i,test]=phase_prob;regression[i,test]=reg
            for key in ('mean','scale','target_mean','target_scale'):cp[key]=torch.as_tensor(cp[key])
            cp.update(dataset_schema=str(d['schema']),dataset=str(args.dataset),asset_names=ds.asset_names,cutoff=int(cutoff),seed=seed,
                reference_sessions=14,input_length=14,target_mode='current',target_maturity='k+n',research_only=True,orders_authorized=False)
            torch.save(cp,args.output/f'latest_{seed}.pt')
            fits.append(dict(cutoff=int(cutoff),seed=seed,training_rows=len(train),test_rows=len(test),
                latest_training_target=int(targets['available_at'][train].max()),seconds=time.monotonic()-before,**detail))
            print('fit',cutoff,seed,'seconds',round(time.monotonic()-before,1),'elapsed',round(time.monotonic()-start,1),flush=True)
            np.savez_compressed(args.output/'predictions.npz',probabilities=p,phase_probabilities=phase,continuous_predictions=regression,
                reference=reference,fold_id=fold,seeds=np.array(args.seeds),source_row=d['source_row'],research_only=True,orders_authorized=False)
    assert source_hash==hashlib.sha256((args.dataset/'dataset.npz').read_bytes()).hexdigest()
    result=dict(research_only=True,orders_authorized=False,independent_oos=False,dataset=str(args.dataset),dataset_sha256=source_hash,
        source_unchanged=True,seeds=args.seeds,fits=fits,phase_names=list(PHASE_NAMES),elapsed_seconds=time.monotonic()-start,
        summary=summarize(ds,targets,p,phase,reference,fold,args.seeds))
    calibrated,phase_cal,alarm,enabled,calibration=historical_calibration(ds,targets,p,phase,fold,args.seeds)
    calibration['summary']=summarize(ds,targets,calibrated,phase_cal,reference,fold,args.seeds)
    result.update(selected_architecture='state_with_transition_gru',selected_state_output='retained baseline; joint mixture and main calibration rejected',
        selected_phase_output='typed phase head with matured-forecast calibration',calibration=calibration,
        bundle_metrics=bundle_metrics(ds,targets,phase,phase_cal,fold))
    (args.output/'calibration.json').write_text(json.dumps(calibration,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    (args.output/'bundle_metrics.json').write_text(json.dumps(result['bundle_metrics'],ensure_ascii=False,indent=2)+'\n')
    np.savez_compressed(args.output/'calibrated_predictions.npz',probabilities=calibrated,phase_probabilities=phase_cal,alarm=alarm,alarm_enabled=enabled,
        source_row=d['source_row'],seeds=np.array(args.seeds),fold_id=fold,research_only=True,orders_authorized=False)
    for seed in args.seeds:
        base=torch.load(args.baseline/f'latest_existing_{seed}.pt',map_location='cpu',weights_only=True)
        typed=torch.load(args.output/f'latest_{seed}.pt',map_location='cpu',weights_only=True)
        assert base['cutoff']==typed['cutoff']
        fitted=next(x['calibration'] for x in calibration['records'] if x['seed']==seed and x['cutoff']==base['cutoff'] and x['model']=='phase')
        cp=dict(base,architecture='state_with_transition_gru',model_type='state_with_transition',transition_model=typed['model'],
            target_mean=typed['target_mean'],target_scale=typed['target_scale'],phase_names=list(PHASE_NAMES),
            continuous_names=list(CONTINUOUS_NAMES),phase_calibration=fitted)
        torch.save(cp,args.output/f'latest_state_with_transition_{seed}.pt')
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n');write_report(result,args.output)
    print(json.dumps(result['summary']['seed_mean']),flush=True)


if __name__=='__main__':
    with threadpool_limits(limits=1):main()
