"""Analyze current-state forecasts, including causal trend-rule baselines."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from compare_market_state_factorizations import classification_metrics,paired_interval
from qount.research.market_state_factorization import purged_quarter

NAMES=('upward','downward','sideways')


def class_summary(y,p):
    pred=p.argmax(1);table=np.zeros((3,3),np.int64);np.add.at(table,(y,pred),1)
    records=[]
    for c in range(3):
        actual=int((y==c).sum());chosen=pred==c;correct=int(((y==c)&chosen).sum())
        high=chosen&(p.max(1)>=.7)
        records.append(dict(state=NAMES[c],actual_rows=actual,predicted_rows=int(chosen.sum()),
            correct_rows=correct,precision=correct/int(chosen.sum()) if chosen.any() else None,
            recall=correct/actual if actual else None,high70_rows=int(high.sum()),
            high70_precision=float(np.mean(y[high]==c)) if high.any() else None,
            high70_mean_probability=float(np.mean(p[high,c])) if high.any() else None))
    return dict(confusion_true_rows_predicted_columns=table.tolist(),classes=records)


def causal_rule(raw,n):
    """Fixed original slope/range gate, computed on completed historical bars."""
    log=np.log(raw[:,:,:4]);price=log[:,:,3];length=raw.shape[1]
    t=np.arange(length)-(length-1);w=np.exp2(-np.abs(t)/(n/3));w/=w.sum()
    tc=float(w@t);center=price@w
    slope=((price-center[:,None])*(w*(t-tc))).sum(1)/float(w@((t-tc)**2))
    returns=np.diff(price,axis=1);rw=(w[:-1]+w[1:])/2;rw/=rw.sum()
    drift=returns@rw;vol=np.sqrt(((returns-drift[:,None])**2)@rw)
    tr=np.maximum(log[:,1:,1]-log[:,1:,2],np.maximum(np.abs(log[:,1:,1]-price[:,:-1]),np.abs(log[:,1:,2]-price[:,:-1])))
    score=slope*np.sqrt(n)/np.maximum(vol,1e-10);strength=np.abs(slope)/np.maximum(tr@rw,1e-12)
    return np.where((score>=.5)&(strength>=.1),0,np.where((score<=-.5)&(strength>=.1),1,2)).astype(np.int16)


def rule_probabilities(rule,y,assets,train,test):
    """Train-only conditional frequencies; no thresholds selected on test."""
    result=np.empty((len(test),3))
    global_prior=(np.bincount(y[train],minlength=3)+1)/(len(train)+3)
    for c in range(3):
        own=train[rule[train]==c]
        prior=(np.bincount(y[own],minlength=3)+3*global_prior)/(len(own)+3)
        for asset in np.unique(assets[test]):
            selected=(rule[test]==c)&(assets[test]==asset)
            past=own[assets[own]==asset]
            result[selected]=(np.bincount(y[past],minlength=3)+20*prior)/(len(past)+20)
    return result


def temporal_diagnostics(d,p):
    y=d['target_main_state'];valid=np.isfinite(p['raw_n_gru']).all(1)
    pred=np.where(valid,np.nan_to_num(p['raw_n_gru'],nan=-1).argmax(1),-1)
    records=[];runs=[]
    for group in ('crypto','etf_proxy'):
        samples=[];previous=[];current=[];high_runs=0;high_rows=0
        for asset in np.unique(d['asset'][d['group']==group]):
            rows=np.flatnonzero(d['asset']==asset);last=-1;age=0;old=-1;prior_high=False;prior_pred=-1
            for row in rows:
                state=int(y[row])
                if state<0:last=-1;age=0;old=-1
                elif state!=last:old=last;last=state;age=1
                else:age+=1
                if valid[row] and 1<=age<=2 and old>=0:
                    samples.append(row);previous.append(old);current.append(state)
                high=bool(valid[row] and p['raw_n_gru'][row].max()>=.7)
                if high:
                    high_rows+=1
                    if not prior_high or pred[row]!=prior_pred:high_runs+=1
                prior_high=high;prior_pred=pred[row]
        samples=np.array(samples);previous=np.array(previous);current=np.array(current)
        records.append(dict(group=group,rows=len(samples),correct_current=float(np.mean(pred[samples]==current)),
            predict_previous_state=float(np.mean(pred[samples]==previous)),
            other_state=float(np.mean((pred[samples]!=current)&(pred[samples]!=previous)))))
        runs.append(dict(group=group,high70_rows=high_rows,contiguous_high70_predicted_state_runs=high_runs))
    return records,runs


def complete_spell_diagnostics(d,p):
    y=d['target_main_state'];valid=np.isfinite(p['raw_n_gru']).all(1)
    pred=np.nan_to_num(p['raw_n_gru'],nan=-1).argmax(1);spells=[];records=[]
    for asset in np.unique(d['asset']):
        rows=np.flatnonzero(d['asset']==asset);start=0
        for stop in range(1,len(rows)+1):
            if stop<len(rows) and y[rows[stop]]==y[rows[start]]:continue
            part=rows[start:stop];state=int(y[part[0]])
            if (state>=0 and start>0 and stop<len(rows) and y[rows[start-1]]>=0
                    and y[rows[stop]]>=0 and valid[part].all()):
                hits=np.flatnonzero(pred[part]==state);first=part[:2];high=p['raw_n_gru'][first].max(1)>=.7
                spells.append(dict(group=str(d['group'][part[0]]),n=int(d['horizon'][part[0]]),length=len(part),
                    first_two_rows=len(first),first_two_correct=int(np.sum(pred[first]==state)),
                    high_rows=int(high.sum()),high_correct=int(np.sum(pred[first][high]==state)),
                    first_hit_delay=int(hits[0]) if len(hits) else None))
            start=stop
    for group in ('crypto','etf_proxy'):
        for name,condition in [('all_complete',lambda s:True),('length_ge5',lambda s:s['length']>=5),
                               ('length_ge_n',lambda s:s['length']>=s['n'])]:
            own=[s for s in spells if s['group']==group and condition(s)]
            rows=sum(s['first_two_rows'] for s in own);high=sum(s['high_rows'] for s in own)
            detected=[s['first_hit_delay'] for s in own if s['first_hit_delay'] is not None]
            records.append(dict(group=group,subset=name,spells=len(own),first_two_rows=rows,
                first_two_accuracy=sum(s['first_two_correct'] for s in own)/rows,
                first_two_high70_rows=high,first_two_high70_accuracy=sum(s['high_correct'] for s in own)/high if high else None,
                detected_spells=len(detected),median_first_hit_delay_among_detected=float(np.median(detected))))
    return records


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=Path('state/research_runs/market_state_current_raw_sequences_20261101'))
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    if args.output.exists():parser.error('preserve existing analyses')
    with np.load(args.source/'dataset.npz',allow_pickle=False) as z:d={k:z[k] for k in z.files}
    with np.load(args.source/'predictions.npz',allow_pickle=False) as z:p={k:z[k] for k in z.files}
    previous=json.loads((args.source/'results.json').read_text())
    assert str(d['target_mode'])=='current' and np.array_equal(d['target_main_state'],d['main_state'])
    y=d['target_main_state'];N=len(y);valid=np.isfinite(p['raw_n_gru']).all(1)
    rules={name:np.full(N,-1,np.int16) for name in ('past_n_rule','past_2n_rule')}
    calibrated={name:np.full((N,3),np.nan) for name in rules}
    for group in ('crypto','etf_proxy'):
        for name,key,multiple in [('past_n_rule','n_raw_ohlcv',1),('past_2n_rule','two_n_raw_ohlcv',2)]:
            rows=np.flatnonzero((d['group']==group)&d['n_valid' if multiple==1 else 'two_n_valid'])
            n=int(d['horizon'][rows[0]]);rules[name][rows]=causal_rule(d[key][rows,-n*multiple:],n)
    ready=d['n_valid']&d['two_n_valid']&d['target_mask']
    for fold in previous['folds']:
        rows=np.flatnonzero((d['group']==fold['group'])&ready)
        train,test=purged_quarter(rows,d['known_at'],d['target_available_at'],fold['cutoff'],fold['end'])
        assert len(train)==fold['training_rows'] and len(test)==fold['test_rows']
        assert d['target_available_at'][train].max()<fold['cutoff']
        for name in rules:calibrated[name][test]=rule_probabilities(rules[name],y,d['asset'],train,test)
    core=np.zeros(N,bool);neighborhood_valid=np.zeros(N,bool);age=np.full(N,-1,int)
    for asset in np.unique(d['asset']):
        rows=np.flatnonzero(d['asset']==asset);last=-1;running=0
        for k,row in enumerate(rows):
            if y[row]<0:last=-1;running=0;continue
            running=running+1 if y[row]==last else 1;age[row]=running;last=y[row]
            if 2<=k<len(rows)-2:
                neighbors=y[rows[k-2:k+3]]
                if (neighbors>=0).all():neighborhood_valid[row]=True;core[row]=np.all(neighbors==y[row])
    groups=[];assets=[];years=[];quarters=[];boundary=[];calibration=[];baseline=[];phase_comparison=[]
    for group in ('crypto','etf_proxy'):
        rows=np.flatnonzero(valid&(d['group']==group));actual=y[rows];model=p['raw_n_gru'][rows];ref=p['frequency'][rows]
        groups.append(dict(group=group,**class_summary(actual,model)))
        for asset in np.unique(d['asset'][rows]):
            ix=rows[d['asset'][rows]==asset]
            assets.append(dict(group=group,asset=str(asset),**classification_metrics(y[ix],p['raw_n_gru'][ix],p['frequency'][ix])))
        calendar=d['known_at'][rows].astype('datetime64[ms]').astype('datetime64[Y]').astype(str)
        for year in np.unique(calendar):
            ix=rows[calendar==year]
            years.append(dict(group=group,year=str(year),**classification_metrics(y[ix],p['raw_n_gru'][ix],p['frequency'][ix])))
        for quarter in np.unique(p['quarter_id'][rows]):
            ix=rows[p['quarter_id'][rows]==quarter]
            quarters.append(dict(group=group,cutoff=int(quarter),**classification_metrics(y[ix],p['raw_n_gru'][ix],p['frequency'][ix])))
        for name,mask in [('interior',core),('boundary',neighborhood_valid&~core),('first_two_spell_days',(age>=1)&(age<=2)),('spell_day_three_on',age>=3)]:
            ix=rows[mask[rows]]
            boundary.append(dict(group=group,subset=name,**classification_metrics(y[ix],p['raw_n_gru'][ix],p['frequency'][ix]),**class_summary(y[ix],p['raw_n_gru'][ix])))
        confidence=model.max(1);pred=model.argmax(1)
        for low,high in [(0,.5),(.5,.6),(.6,.7),(.7,.8),(.8,.9),(.9,1.00001)]:
            chosen=(confidence>=low)&(confidence<high)
            calibration.append(dict(group=group,minimum=low,maximum=high,rows=int(chosen.sum()),
                mean_probability=float(confidence[chosen].mean()) if chosen.any() else None,
                accuracy=float(np.mean(pred[chosen]==actual[chosen])) if chosen.any() else None))
        one=np.eye(3)[actual];model_error=np.sum((model-one)**2,1)
        for name in rules:
            probability=calibrated[name][rows];error=np.sum((probability-one)**2,1)
            baseline.append(dict(group=group,name=name,direct_rule_accuracy=float(np.mean(rules[name][rows]==actual)),
                **classification_metrics(actual,probability,ref),
                model_minus_rule_brier=paired_interval(model_error-error,p['quarter_id'][rows]),
                rule_direction_counts=np.bincount(rules[name][rows],minlength=3).tolist()))
        for phase,mask in [('first_two',(age>=1)&(age<=2)),('day_three_on',age>=3)]:
            take=rows[mask[rows]]
            phase_comparison.append(dict(group=group,phase=phase,rows=len(take),
                gru=float(np.mean(p['raw_n_gru'][take].argmax(1)==y[take])),
                past_n_rule_calibrated=float(np.mean(calibrated['past_n_rule'][take].argmax(1)==y[take]))))
    lag,runs=temporal_diagnostics(d,p)
    result=dict(research_only=True,orders_authorized=False,independent_oos=False,source=str(args.source),
        groups=groups,assets=assets,years=years,quarters=quarters,boundary=boundary,calibration=calibration,causal_rule_baselines=baseline,
        transition_lag_diagnostic=lag,high_confidence_runs=runs,
        complete_spell_length_diagnostics=complete_spell_diagnostics(d,p),phase_rule_comparison=phase_comparison,
        assumptions=['Analysis uses saved predictions; no new neural fits or model selection.',
            'Rule uses fixed score>=0.5 and abs(slope)/range>=0.1 on past n or 2n bars only; no future bars.',
            'Probabilistic rule baseline is training-matured class frequency conditional on asset and rule state; group conditional smoothing20, no test calibration.',
            'Boundary/interior and true spell age use hindsight labels for diagnostics, never inference features or trading filters.',
            'Same-day labels partly share observed history; state estimation skill is not evidence of future trading returns.',
            'Only one seed/architecture, consumed historical folds, overlapping daily observations and correlated assets remain limitations.'])
    args.output.mkdir(parents=True)
    (args.output/'analysis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    np.savez_compressed(args.output/'causal_rule_predictions.npz',**calibrated,**{name+'_class':x for name,x in rules.items()},research_only=True,orders_authorized=False)
    print('saved',args.output)
    for record in baseline:print(record['group'],record['name'],'direct accuracy',record['direct_rule_accuracy'],'calibrated accuracy',record['accuracy'],'skill',record['brier_skill'],'model minus rule',record['model_minus_rule_brier'])


if __name__=='__main__':main()
