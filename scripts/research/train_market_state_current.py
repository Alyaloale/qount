"""Current training entry: complete native-nine-channel same-day state data."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import time
from pathlib import Path

import numpy as np
import torch
from threadpoolctl import threadpool_limits

from qount.research.market_state_dataset import CurrentStateDataset,DEFAULT_ROOT
from compare_market_state_factorizations import asset_frequency,classification_metrics
from qount.research.market_state_neural import fit_gru
from qount.research.market_state_transition import CONTINUOUS_NAMES,PHASE_NAMES,fit_state_with_transition,fit_typed_transition,phase_targets,transition_targets
from qount.research.market_state_calibration import apply_calibration,fit_calibration,mature_calibration_rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,default=DEFAULT_ROOT)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--lookback',choices=('n','two_n'),default='n')
    parser.add_argument('--epochs',type=int,default=20)
    parser.add_argument('--model',choices=('state_with_transition','gru','typed_transition'),default='state_with_transition',
        help='default keeps the state estimator and independently learns calibrated early-stage probabilities')
    parser.add_argument('--seed',type=int,default=17)
    parser.add_argument('--smoke',action='store_true',help='one epoch on first training fold; no performance conclusion')
    parser.add_argument('--max-seconds',type=int,default=900)
    args=parser.parse_args()
    if args.output.exists():parser.error('preserve previous experiments')
    if args.epochs<1:parser.error('positive epochs required')
    ds=CurrentStateDataset(args.dataset);d=ds.data;rows=np.arange(ds.summary['rows'])
    bundle=ds.inputs(rows,lookback=args.lookback);sequence=bundle['market'];asset=bundle['asset_index'];y=ds.targets(rows)['state']
    if sequence.shape[-1]!=9 or not np.isfinite(sequence).all():raise ValueError('complete_nine_channel_input_required')
    targets=transition_targets(ds) if args.model!='gru' else None
    raw=ds.inputs(rows,lookback=args.lookback,scaled=False)['market'] if targets is not None else None
    phase_probabilities=np.full((len(rows),4),np.nan);continuous_predictions=np.full((len(rows),2),np.nan)
    raw_phase_probabilities=np.full_like(phase_probabilities,np.nan)
    stamps=[dt.datetime.fromtimestamp(int(t)/1000,dt.timezone.utc) for t in d['decision_at']]
    quarters=sorted({(s.year,(s.month-1)//3*3+1) for s in stamps if s.year>=2023})
    probabilities=np.full((len(rows),3),np.nan);frequency=np.full_like(probabilities,np.nan)
    fold_id=np.full(len(rows),-1,np.int64);fits=[];start=time.monotonic()
    torch.set_num_threads(2);torch.use_deterministic_algorithms(True);args.output.mkdir(parents=True)
    for year,month in quarters:
        if time.monotonic()-start>args.max_seconds:raise RuntimeError('bounded_training_budget_exceeded')
        cutoff=int(dt.datetime(year,month,1,tzinfo=dt.timezone.utc).timestamp())*1000
        end=int(dt.datetime(year+int(month==10),1 if month==10 else month+3,1,tzinfo=dt.timezone.utc).timestamp())*1000
        train,test=ds.split(cutoff,end)
        if len(train)<200 or not len(test):continue
        if args.smoke:test=test[:32]
        if args.model!='gru':
            fit=fit_state_with_transition if args.model=='state_with_transition' else fit_typed_transition
            p,phase,continuous,detail,checkpoint=fit(sequence,asset,raw,targets,train,test,
                assets=len(ds.asset_names),epochs=1 if args.smoke else args.epochs,seed=args.seed)
            raw_phase_probabilities[test]=phase
            if args.model=='state_with_transition':
                history=mature_calibration_rows(d['decision_at'],targets['available_at'],raw_phase_probabilities,cutoff)
                history=history[targets['phase_valid'][history]]
                calibration=fit_calibration(raw_phase_probabilities[history],targets['phase'][history])
                phase=apply_calibration(phase,calibration);checkpoint['phase_calibration']=calibration
                detail['phase_calibration']=dict(rows=len(history),fitted_rows=calibration['rows'],
                    latest_label=int(targets['available_at'][history].max()) if len(history) else None)
            phase_probabilities[test]=phase;continuous_predictions[test]=continuous
            for key in ('target_mean','target_scale'):checkpoint[key]=torch.as_tensor(checkpoint[key])
        else:
            p,detail,checkpoint=fit_gru(sequence,asset,y,train,test,assets=len(ds.asset_names),epochs=1 if args.smoke else args.epochs,seed=args.seed)
        detail.pop('train_prediction',None);probabilities[test]=p;frequency[test]=asset_frequency(y,d['asset'],train,test,3);fold_id[test]=cutoff
        checkpoint['mean']=torch.as_tensor(checkpoint['mean']);checkpoint['scale']=torch.as_tensor(checkpoint['scale'])
        checkpoint.update(dataset_schema=str(d['schema']),dataset=str(args.dataset),market_names=d['market_names'].tolist(),
            asset_names=ds.asset_names,reference_sessions=int(d['reference_sessions']),target_mode='current',
            lookback=args.lookback,input_length=sequence.shape[1],cutoff=cutoff,smoke_only=args.smoke,
            model_type=args.model,seed=args.seed,
            funding_enabled=False,research_only=True,orders_authorized=False)
        torch.save(checkpoint,args.output/'latest.pt')
        fits.append(dict(cutoff=cutoff,end=end,training_rows=len(train),test_rows=len(test),
            latest_training_label=int(d['label_available_at'][train].max()),**detail))
        print('fit',year,month,'train',len(train),'test',len(test),'channels',sequence.shape[-1],flush=True)
        if args.smoke:break
    valid=np.isfinite(probabilities).all(1)
    if not valid.any():raise RuntimeError('no_test_predictions')
    result=dict(research_only=True,orders_authorized=False,dataset=str(args.dataset),schema=str(d['schema']),
        smoke_only=args.smoke,independent_oos=False,lookback=args.lookback,input_channels=9,
        input_blocks=['native_market_sequence'],incomplete_blocks_used=False,funding_enabled=False,
        target='S_n(k)',target_maturity='k+n',model=args.model,seed=args.seed,epochs=1 if args.smoke else args.epochs,folds=fits,
        phase_names=list(PHASE_NAMES),continuous_names=list(CONTINUOUS_NAMES),
        phase_probability_target='current day within first three days of its state',
        phase_calibration='earlier out-of-fold forecasts with labels matured before current fold; last365days' if args.model=='state_with_transition' else None,
        automatic_transition_alerts=False,state_and_transition_independent=args.model=='state_with_transition',
        predictions=int(valid.sum()),elapsed_seconds=time.monotonic()-start)
    if not args.smoke:
        result['metrics']=classification_metrics(y[valid],probabilities[valid],frequency[valid])
        # Evaluation always separates trend entry, sideways entry and early days.
        # These are retrospective supervision masks, never inputs.
        phase=phase_targets(d['asset'],y,d['previous_state_label'])
        for name,mask in [('new_trend_first_day',d['switch_label']&(y<2)),
            ('new_sideways_first_day',d['switch_label']&(y==2)),
            ('new_trend_first_three_days',np.isin(phase['phase'],[1,2])&phase['phase_valid'])]:
            chosen=valid&mask
            result[name]=dict(rows=int(chosen.sum()),accuracy=float(np.mean(probabilities[chosen].argmax(1)==y[chosen])) if chosen.any() else None)
        sideways=valid&(y==2)
        result['sideways_misclassified_as_trend']=float(np.mean(probabilities[sideways].argmax(1)!=2)) if sideways.any() else None
        if targets is not None:
            from sklearn.metrics import average_precision_score,roc_auc_score
            chosen=valid&targets['phase_valid'];early=np.isin(targets['phase'][chosen],[1,2]);risk=phase_probabilities[chosen,1:3].sum(1)
            result['early_trend_probability']=dict(target='current day within first three trend days',rows=int(chosen.sum()),
                prevalence=float(early.mean()),mean_probability=float(risk.mean()),brier=float(np.mean((risk-early)**2)),
                roc_auc=float(roc_auc_score(early,risk)),average_precision=float(average_precision_score(early,risk)))
    np.savez_compressed(args.output/'predictions.npz',source_row=d['source_row'],probabilities=probabilities,
        phase_probabilities=phase_probabilities,continuous_predictions=continuous_predictions,
        raw_phase_probabilities=raw_phase_probabilities,
        frequency=frequency,quarter_id=fold_id,smoke_only=args.smoke,research_only=True,orders_authorized=False)
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print('saved',args.output,'smoke_only',args.smoke,flush=True)


if __name__=='__main__':
    with threadpool_limits(limits=1):main()
