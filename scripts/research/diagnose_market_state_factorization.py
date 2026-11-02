"""Targeted offline diagnosis of the three-state prediction failure."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

import numpy as np
from sklearn.metrics import roc_auc_score
from threadpoolctl import threadpool_limits

from qount.research.market_learning import fit_candidate
from qount.research.market_state_factorization import purged_quarter


def metrics(y,p,ref):
    y=np.asarray(y,int);pred=p.argmax(1);one=np.eye(3)[y]
    err=np.sum((p-one)**2,1);base=np.sum((ref-one)**2,1)
    return dict(rows=len(y),accuracy=float(np.mean(pred==y)),
        balanced_accuracy=float(np.mean([np.mean(pred[y==c]==c) for c in range(3)])),
        recall=[float(np.mean(pred[y==c]==c)) for c in range(3)],
        auc=[float(roc_auc_score(y==c,p[:,c])) for c in range(3)],
        brier=float(err.mean()),frequency_brier=float(base.mean()),skill=float(1-err.mean()/base.mean()),
        predicted_counts=np.bincount(pred,minlength=3).tolist(),actual_share=one.mean(0).tolist(),
        average_probability=p.mean(0).tolist())


def probabilities(model,x,prior=None):
    p=np.zeros((len(x),3));p[:,model[-1].classes_.astype(int)]=model.predict_proba(x)
    if prior is not None:p*=prior;p/=p.sum(1,keepdims=True)
    return .99*p+.01/3


def boundary_diagnostics(d,p):
    labels=d['merged_three'];core=np.zeros(len(labels),bool);records=[]
    for asset in np.unique(d['asset']):
        rows=np.flatnonzero(d['asset']==asset)
        for k in range(2,len(rows)-2):
            row=rows[k]
            core[row]=labels[row]>=0 and np.all(labels[rows[k-2:k+3]]==labels[row])
    for group in ('crypto','etf_proxy'):
        rows=np.flatnonzero((d['group']==group)&np.isfinite(p['merged_three_probabilities']).all(1))
        for name,chosen in [('interior',core[d['target_row'][rows]]),('boundary',~core[d['target_row'][rows]])]:
            take=rows[chosen];y=d['target_merged_three'][take];probs=p['merged_three_probabilities'][take]
            pred=probs.argmax(1)
            records.append(dict(group=group,subset=name,rows=len(take),
                recall=[float(np.mean(pred[y==c]==c)) for c in range(3)],
                auc=[float(roc_auc_score(y==c,probs[:,c])) for c in range(3)]))
    return records


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=Path('state/research_runs/market_state_factorization_20261031_comparison'))
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    if args.output.exists():parser.error('preserve prior results: choose another output')
    with np.load(args.source/'dataset.npz',allow_pickle=False) as z:d={k:z[k] for k in z.files}
    with np.load(args.source/'predictions.npz',allow_pickle=False) as z:p={k:z[k] for k in z.files}
    old=json.loads((args.source/'results.json').read_text());N=len(d['asset']);labels=d['merged_three']
    y=d['target_merged_three'];mature=d['target_available_at'];known=d['known_at']
    common=np.isfinite(p['merged_three_probabilities']).all(1);ready=np.isfinite(d['X']).all(1)
    variants=('reproduced_tree','balanced_tree','balanced_prior_corrected','linear')
    predictions={v:np.full((N,3),np.nan) for v in variants}
    diagnostic={};training=[];folds=[];distance=[]
    for offset_name in ('center_now','half_cycle'):
        target=np.full(N,-1,int);clock=np.zeros(N,np.int64)
        for a in np.unique(d['asset']):
            ix=np.flatnonzero(d['asset']==a);n=int(d['horizon'][ix[0]])
            shift=0 if offset_name=='center_now' else n//2
            src=ix if shift==0 else ix[:-shift];dst=ix if shift==0 else ix[shift:]
            good=labels[dst]>=0;target[src[good]]=labels[dst[good]];clock[src[good]]=d['label_available_at'][dst[good]]
        diagnostic[offset_name]=dict(y=target,maturity=clock,p=np.full((N,3),np.nan),ref=np.full((N,3),np.nan))
    for fold in old['folds']:
        group=fold['group'];cutoff=fold['cutoff'];end=fold['end']
        members=np.flatnonzero((d['group']==group)&ready&d['target_mask'])
        train,test=purged_quarter(members,known,mature,cutoff,end)
        assert len(test)==fold['test_rows'] and np.all(common[test])
        names=np.unique(d['asset'][members]);identity=np.array([[a==n for n in names] for a in d['asset']],float)
        x=np.c_[d['X'],identity];prior=np.bincount(y[train],minlength=3)/len(train)
        assert np.all(prior>0) and np.max(mature[train])<cutoff
        tree,_=fit_candidate('tree',x[train],y[train],seed=17)
        reproduced=probabilities(tree,x[test]);assert np.allclose(reproduced,p['merged_three_probabilities'][test],atol=1e-12)
        predictions['reproduced_tree'][test]=reproduced
        train_ref=np.empty((len(train),3))
        for a in names:
            own=d['asset'][train]==a
            train_ref[own]=(np.bincount(y[train][own],minlength=3)+20*prior)/(own.sum()+20)
        training.append(dict(group=group,cutoff=cutoff,**metrics(y[train],probabilities(tree,x[train]),train_ref)))
        balanced=copy.deepcopy(tree)
        weights=1/(3*prior[y[train]])
        # Refit the learner with training-only inverse-frequency weights.
        transformed=balanced[:-1].transform(x[train])
        balanced[-1].fit(transformed,y[train],sample_weight=weights)
        predictions['balanced_tree'][test]=probabilities(balanced,x[test])
        predictions['balanced_prior_corrected'][test]=probabilities(balanced,x[test],prior=prior)
        linear,_=fit_candidate('linear',x[train],y[train],seed=17)
        predictions['linear'][test]=probabilities(linear,x[test])
        folds.append(dict(group=group,cutoff=cutoff,train_share=prior.tolist(),
            test_share=(np.bincount(y[test],minlength=3)/len(test)).tolist(),
            latest_training_target=int(mature[train].max()),test_rows=len(test)))
        for name,alt in diagnostic.items():
            rows=np.flatnonzero((d['group']==group)&ready&(alt['y']>=0))
            past=rows[alt['maturity'][rows]<cutoff]
            assert np.all(alt['y'][test]>=0) and alt['maturity'][past].max()<cutoff
            model,_=fit_candidate('tree',x[past],alt['y'][past],seed=17)
            alt['p'][test]=probabilities(model,x[test])
            for a in names:
                own=past[d['asset'][past]==a];dest=test[d['asset'][test]==a]
                freq=(np.bincount(alt['y'][own],minlength=3)+1)/(len(own)+3)
                alt['ref'][dest]=freq
        print(group,cutoff,'done',flush=True)
    results=[];existing=[];horizons=[];geometry=[]
    for group in ('crypto','etf_proxy'):
        ix=np.flatnonzero(common&(d['group']==group));ref=p['merged_three_frequency'][ix]
        existing.append(dict(group=group,model=metrics(y[ix],p['merged_three_probabilities'][ix],ref),
            frequency=metrics(y[ix],ref,ref)))
        for variant in variants:results.append(dict(group=group,variant=variant,**metrics(y[ix],predictions[variant][ix],ref)))
        for name,alt in diagnostic.items():horizons.append(dict(group=group,diagnostic=name,
            **metrics(alt['y'][ix],alt['p'][ix],alt['ref'][ix])))
        n=int(d['horizon'][ix[0]]);t=np.arange(2*n)-(n-1);w=np.exp2(-abs(t)/(n/3));w/=w.sum()
        geometry.append(dict(group=group,n=n,future_only_target=True,
            weighted_center_distance_sessions=float(w@np.arange(1,2*n+1)),
            weight_in_first_three_future_sessions=float(w[:3].sum()),
            weight_in_future_sessions_near_n=float(w[np.abs(t)<=n/3].sum())))
        # Observational transition diagnostics. center_now is unavailable at k.
        for name,current in [('latest_matured',labels[d['last_mature_row'][ix]]),
                ('retrospective_center_now',labels[ix])]:
            table=np.zeros((3,3),int);np.add.at(table,(current,y[ix]),1)
            distance.append(dict(group=group,source=name,counts=table.tolist(),
                target_given_source=(table/table.sum(1,keepdims=True)).tolist()))
    result=dict(research_only=True,orders_authorized=False,independent_oos=False,
        source=str(args.source),existing=existing,controlled_models=results,
        parameters=dict(classes=['upward','downward','sideways'],
            target='unchanged state[k+n], centered context through k+2n',
            diagnostic_target_offsets=dict(crypto=[0,7,14],etf_proxy=[0,5,10]),feature_count=12,
            feature_context='past 2n completed OHLC bars, numerical summaries plus asset identity',
            class_balance='training-only inverse-frequency weights, same fixed tree; prior corrected outputs reweight to original training prevalence',
            model_search=False,seed=17,evaluated_folds=len(folds)),
        training_fits=training,folds=folds,horizon_diagnostics=horizons,
        target_geometry=geometry,transition_diagnostics=distance,
        boundary_diagnostic=boundary_diagnostics(d,p),
        limitations=['Fixed diagnostic alternatives, no model/threshold search; historical test is consumed.',
            'Class balancing changes the objective and class prior; raw balanced probabilities are not calibrated for original prevalence.',
            'Training metrics reuse expanding historical rows and are in-sample, not new evidence of generalization.',
            'center_now/half_cycle are separate diagnostic targets with their own maturity purge; center_now partly shares observed prices and is mechanically easier.',
            'Retrospective center-now transition is an unavailable oracle diagnostic, never a prediction input.',
            'Interior/boundary subsets inspect future neighbor labels for diagnosis only; never a causal filter or input.',
            'Results cannot establish that prices or richer external features are intrinsically unpredictable.'])
    args.output.mkdir(parents=True)
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    np.savez_compressed(args.output/'predictions.npz',**predictions,
        center_now=diagnostic['center_now']['p'],half_cycle=diagnostic['half_cycle']['p'],
        research_only=True,orders_authorized=False)
    print('saved',args.output,flush=True)


if __name__=='__main__':
    with threadpool_limits(limits=1):main()
