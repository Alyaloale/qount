"""Quarterly forward comparison of 18 direct future-price/profit binary targets."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import torch
from torch import nn
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score,roc_auc_score
from threadpoolctl import threadpool_limits

from qount.research.market_future_direction import (HORIZONS,PATTERN_NAMES,TASK_NAMES,
    direction_patterns,long_profit_targets,mature_split,price_targets)
from qount.research.market_state_dataset import CurrentStateDataset,DEFAULT_ROOT
from qount.research.market_state_profit import complete_history
from qount.research.market_state_sequence import fold_scale


class FutureGRU(nn.Module):
    def __init__(self,assets,outputs):
        super().__init__()
        self.encoder=nn.GRU(9,32,batch_first=True);self.asset=nn.Embedding(assets,4)
        self.head=nn.Sequential(nn.LayerNorm(36),nn.Dropout(.1),nn.Linear(36,outputs))

    def forward(self,x,asset):
        _,h=self.encoder(x)
        return self.head(torch.cat((h[-1],self.asset(asset)),1))


def predict(model,x,asset):
    model.eval()
    with torch.no_grad():
        return np.concatenate([model(x[s:s+1024],asset[s:s+1024]).sigmoid().numpy()
                               for s in range(0,len(x),1024)])


def fit(sequence,asset,y,mask,train,test,*,assets,epochs,seed):
    torch.manual_seed(seed);mean,scale=fold_scale(sequence[train])
    x=torch.from_numpy(np.ascontiguousarray((sequence[train]-mean)/scale))
    a=torch.from_numpy(asset[train]);target=torch.from_numpy(y[train].astype(np.float32))
    valid=torch.from_numpy(mask[train].astype(np.float32));model=FutureGRU(assets,y.shape[1])
    prior=(y[train]*mask[train]).sum(0)/mask[train].sum(0)
    with torch.no_grad():model.head[-1].bias.copy_(torch.tensor(np.log(prior/(1-prior)),dtype=torch.float32))
    optimizer=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.001)
    generator=torch.Generator().manual_seed(seed);losses=[]
    for _ in range(epochs):
        model.train();total=0.;count=0
        for batch in torch.randperm(len(train),generator=generator).split(256):
            optimizer.zero_grad(set_to_none=True)
            raw=nn.functional.binary_cross_entropy_with_logits(model(x[batch],a[batch]),target[batch],reduction='none')
            loss=(raw*valid[batch]).sum()/valid[batch].sum()
            if not torch.isfinite(loss):raise RuntimeError('nonfinite_future_loss')
            loss.backward();nn.utils.clip_grad_norm_(model.parameters(),1.);optimizer.step()
            total+=float(loss.detach())*len(batch);count+=len(batch)
        losses.append(total/count)
    p=predict(model,torch.from_numpy(np.ascontiguousarray((sequence[test]-mean)/scale)),torch.from_numpy(asset[test]))
    checkpoint=dict(model=model.state_dict(),mean=torch.from_numpy(mean),scale=torch.from_numpy(scale),
        asset_names=None,horizons=HORIZONS,task_names=TASK_NAMES,input_channels=9,input_length=sequence.shape[1],
        outputs=y.shape[1],seed=seed,research_only=True,orders_authorized=False)
    return p,checkpoint,dict(train_binary_cross_entropy=losses,parameters=sum(p.numel() for p in model.parameters()))


def metrics(y,p,baseline):
    pred=p>=.5;brier=float(np.mean((p-y)**2));base=float(np.mean((baseline-y)**2))
    return dict(rows=len(y),positive_fraction=float(y.mean()),predicted_positive_fraction=float(pred.mean()),
        accuracy=float(np.mean(pred==y)),balanced_accuracy=float(balanced_accuracy_score(y,pred)),
        auc=float(roc_auc_score(y,p)),brier=brier,frequency_brier=base,brier_skill=1-brier/base)


def paired_quarter_interval(y,p,baseline,valid,fold_id):
    """Resample whole quarters; never treat overlapping horizons/assets as independent."""
    delta=((p-y)**2-(baseline-y)**2)
    ids=np.unique(fold_id[fold_id>=0]);sums=[];counts=[]
    for key in ids:
        chosen=valid&(fold_id[:,None]==key);sums.append(delta[chosen].sum());counts.append(chosen.sum())
    sums=np.array(sums);counts=np.array(counts);rng=np.random.default_rng(20261101)
    samples=rng.integers(len(ids),size=(4000,len(ids)))
    estimates=sums[samples].sum(1)/counts[samples].sum(1)
    return dict(mean=float(delta[valid].mean()),ci95=np.quantile(estimates,[.025,.975]).tolist(),
        blocks=len(ids),unit='whole quarter with all assets and horizons; descriptive on consumed history')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,default=DEFAULT_ROOT);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--epochs',type=int,default=20);parser.add_argument('--seeds',type=int,nargs='+',default=[17,29,43])
    parser.add_argument('--max-seconds',type=int,default=900);args=parser.parse_args()
    if args.output.exists():parser.error('preserve previous experiments')
    if args.epochs<1 or not args.seeds:parser.error('positive epochs and seeds required')
    source_hash=hashlib.sha256((args.dataset/'dataset.npz').read_bytes()).hexdigest()
    ds=CurrentStateDataset(args.dataset);d=ds.data;history=complete_history(ds);count=len(d['asset']);horizon_count=len(HORIZONS);heads=len(TASK_NAMES)*horizon_count
    y=np.zeros((count,heads),bool);mask=np.zeros_like(y);observed=np.zeros_like(y)
    returns=np.full((count,heads),np.nan);available=np.zeros((count,heads),np.int64)
    entries=np.zeros(count,np.int64);exits=np.zeros((count,horizon_count),np.int64);funding=np.full((count,horizon_count),np.nan)
    with np.load(args.dataset/'funding_events.npz',allow_pickle=False) as z:events={k:z[k] for k in z.files}
    for asset in ds.asset_names:
        rows=np.flatnonzero(d['asset']==asset);h=history[asset];ev=events['asset']==asset
        t=price_targets(h['open_at'],h['market'][:,3],d['bar_open_at'][rows])
        profit=long_profit_targets(h['open_at'],h['market'],d['decision_at'][rows],events['observed_at'][ev],events['rate'][ev])
        for block,values,labels,valid,seen,clock in [
            (0,t['returns'],t['above'],t['valid'],t['observed'],t['available_at']),
            (1,t['mean_returns'],t['mean_above'],t['mean_valid'],t['observed'],t['available_at']),
            (2,profit['net_returns'],profit['profitable'],profit['valid'],profit['observed'],profit['available_at'])]:
            cols=slice(block*horizon_count,(block+1)*horizon_count);y[rows,cols]=labels;mask[rows,cols]=valid
            returns[rows,cols]=values;observed[rows,cols]=seen;available[rows,cols]=clock
        entries[rows]=profit['entry_at'];exits[rows]=profit['exit_at'];funding[rows]=profit['funding_proxy_returns']
    # The old state, its boundaries, previous-state and transition labels never enter X or Y.
    sequence=d['n_scaled_market'].copy();asset_index=ds.asset_index
    if sequence.shape[1:]!=(14,9):raise ValueError('this_comparison_requires_fourteen_native_bars')
    args.output.mkdir(parents=True);torch.set_num_threads(2);torch.use_deterministic_algorithms(True)
    np.savez_compressed(args.output/'dataset.npz',schema='direct_future_direction_v1',
        raw_market=d['n_raw_market'],asset=d['asset'],asset_index=asset_index,source_row=d['source_row'],
        input_source_rows=d['n_source_rows'],market_names=d['market_names'],bar_open_at=d['bar_open_at'],
        decision_at=d['decision_at'],horizons=HORIZONS,task_names=TASK_NAMES,above=y,valid=mask,
        observed=observed,returns=returns,target_available_at=available,entry_at=entries,exit_at=exits,
        funding_proxy_returns=funding,research_only=True,orders_authorized=False)
    probabilities=np.full((len(args.seeds),count,heads),np.nan);linear=np.full((count,heads),np.nan)
    frequency=np.full_like(linear,np.nan);fold_id=np.full(count,-1,np.int64);fits=[];start=time.monotonic()
    stamps=[dt.datetime.fromtimestamp(int(s)/1000,dt.timezone.utc) for s in d['decision_at']]
    quarters=sorted({(s.year,(s.month-1)//3*3+1) for s in stamps if s.year>=2023})
    for year,month in quarters:
        if time.monotonic()-start>args.max_seconds:raise RuntimeError('bounded_training_budget_exceeded')
        cutoff=int(dt.datetime(year,month,1,tzinfo=dt.timezone.utc).timestamp()*1000)
        end=int(dt.datetime(year+int(month==10),1 if month==10 else month+3,1,tzinfo=dt.timezone.utc).timestamp()*1000)
        train,test=mature_split(d['decision_at'],available,observed,cutoff,end)
        if len(train)<200 or not len(test):continue
        for ai in range(len(ds.asset_names)):
            tr=train[asset_index[train]==ai];te=test[asset_index[test]==ai]
            frequency[te]=((y[tr]*mask[tr]).sum(0)+1)/(mask[tr].sum(0)+2)
        mean,scale=fold_scale(sequence[train])
        flat=((sequence-mean)/scale).reshape(count,-1)
        flat=np.c_[flat,np.eye(len(ds.asset_names),dtype=np.float32)[asset_index]]
        for head in range(heads):
            tr=train[mask[train,head]];model=LogisticRegression(C=.1,max_iter=400)
            model.fit(flat[tr],y[tr,head]);linear[test,head]=model.predict_proba(flat[test])[:,1]
        details=[]
        for si,seed in enumerate(args.seeds):
            p,cp,detail=fit(sequence,asset_index,y,mask,train,test,assets=len(ds.asset_names),epochs=args.epochs,seed=seed)
            probabilities[si,test]=p;details.append(dict(seed=seed,**detail))
            cp.update(asset_names=ds.asset_names,cutoff=cutoff,epochs=args.epochs,source_dataset_sha256=source_hash,
                fee_per_side=.0005,slippage_per_side=.0002,funding_marks='daily open proxy',
                independent_oos=False,source_dataset=str(args.dataset))
            torch.save(cp,args.output/f'latest_{seed}.pt')
        fold_id[test]=cutoff
        fits.append(dict(cutoff=cutoff,end=end,train_rows=len(train),test_rows=len(test),
            latest_training_target=int(available[train].max()),details=details))
        print('fit',year,month,'train',len(train),'test',len(test),f'{heads} heads','seconds',round(time.monotonic()-start,1),flush=True)
    valid=mask&np.isfinite(frequency);complete=np.isfinite(frequency).all(1)
    if not complete.any():raise RuntimeError('no_predictions')
    result=dict(research_only=True,orders_authorized=False,independent_oos=False,
        historical_data_already_used_in_research=True,source_dataset=str(args.dataset),source_dataset_sha256=source_hash,
        torch_version=str(torch.__version__),seeds=args.seeds,epochs=args.epochs,horizons=HORIZONS,task_names=TASK_NAMES,
        raw_channels=d['market_names'].tolist(),input_length=14,input_scaling='within-window relative log prices, log1p activity, train-fold channel standardisation',
        target_definitions=['C[k+h] / C[k] - 1 > 0', 'mean(C[k+1], ..., C[k+h]) / C[k] - 1 > 0',
            'long at first daily open strictly after signal, exit h days after entry; net PnL > 0'],
        cost_assumptions=dict(fee_per_side=.0005,adverse_slippage_per_side=.0002,
            funding='actual historical rate/time, daily open mark proxy; opening settlement before orders',
            lot_tick_spread_impact_liquidation_modelled=False),
        input_rows=count,fully_observed_rows=int(observed.all(1).sum()),missing_future_rows=int((~observed.all(1)).sum()),
        exact_ties_per_task_and_horizon=(observed&~mask).sum(0).reshape(len(TASK_NAMES),horizon_count).tolist(),
        predictions=int(complete.sum()),test_first_decision=int(d['decision_at'][complete].min()),
        test_last_decision=int(d['decision_at'][complete].max()),folds=fits,models={})
    candidates={'constant_half':np.full_like(frequency,.5),'frequency':frequency,'linear_raw_sequence':linear}
    candidates.update({f'gru_seed_{seed}':probabilities[si] for si,seed in enumerate(args.seeds)})
    candidates['gru_ensemble']=probabilities.mean(0)
    for name,p in candidates.items():
        by_head=[];by_task={}
        for head in range(heads):
            chosen=valid[:,head]
            by_head.append(dict(task=TASK_NAMES[head//horizon_count],horizon=HORIZONS[head%horizon_count],
                **metrics(y[chosen,head],p[chosen,head],frequency[chosen,head])))
        for ti,task in enumerate(TASK_NAMES):
            cols=slice(ti*horizon_count,(ti+1)*horizon_count);chosen=valid[:,cols]
            by_task[task]=metrics(y[:,cols][chosen],p[:,cols][chosen],frequency[:,cols][chosen])
        overall=metrics(y[valid],p[valid],frequency[valid])
        by_year={};by_asset={}
        for name_group,groups,out in [('year',sorted({s.year for s in stamps if s.year>=2023}),by_year),
                                     ('asset',ds.asset_names,by_asset)]:
            for key in groups:
                group=np.array([s.year==key for s in stamps]) if name_group=='year' else d['asset']==key
                chosen=valid&group[:,None]
                if chosen.any():out[str(key)]=metrics(y[chosen],p[chosen],frequency[chosen])
        pattern_valid=complete&mask[:,:horizon_count].all(1)
        actual=direction_patterns(y[pattern_valid,:horizon_count]);predicted=direction_patterns(p[pattern_valid,:horizon_count]>=.5)
        result['models'][name]=dict(overall=overall,by_head=by_head,by_task=by_task,by_year=by_year,by_asset=by_asset,
            brier_delta_vs_frequency=paired_quarter_interval(y,p,frequency,valid,fold_id),
            close_crossing_pattern=dict(rows=int(pattern_valid.sum()),accuracy=float(np.mean(actual==predicted)),
                actual_counts=np.bincount(actual,minlength=6).tolist(),predicted_counts=np.bincount(predicted,minlength=6).tolist(),
                names=PATTERN_NAMES,interpretation='thresholded marginal probabilities, NOT joint reversal probabilities'))
    actual_pattern=direction_patterns(y[:,:horizon_count]);pattern_valid=complete&mask[:,:horizon_count].all(1)
    mode=np.full(count,-1,np.int64)
    for fold in fits:
        tr,te=mature_split(d['decision_at'],available,observed,fold['cutoff'],fold['end'])
        tr=tr[mask[tr,:horizon_count].all(1)];mode[te]=np.bincount(actual_pattern[tr],minlength=6).argmax()
    result['mature_pattern_mode_baseline']=dict(rows=int(pattern_valid.sum()),
        accuracy=float(np.mean(mode[pattern_valid]==actual_pattern[pattern_valid])))
    pred_pattern=direction_patterns(candidates['gru_ensemble'][:,:horizon_count]>=.5)
    confusion=np.zeros((6,6),np.int64)
    np.add.at(confusion,(actual_pattern[pattern_valid],pred_pattern[pattern_valid]),1)
    result['models']['gru_ensemble']['close_crossing_pattern']['confusion']=confusion.tolist()
    # Cached latest input inference, using last quarterly model, not live market data.
    with np.load(args.dataset/'latest_inputs.npz',allow_pickle=False) as z:latest={k:z[k] for k in z.files}
    latest_probs=[]
    for seed in args.seeds:
        cp=torch.load(args.output/f'latest_{seed}.pt',weights_only=True);model=FutureGRU(len(ds.asset_names),heads)
        model.load_state_dict(cp['model']);a=np.array([ds.asset_names.index(x) for x in latest['asset']],np.int64)
        x=(latest['n_scaled_market']-cp['mean'].numpy())/cp['scale'].numpy()
        latest_probs.append(predict(model,torch.from_numpy(np.ascontiguousarray(x)),torch.from_numpy(a)))
    result['cached_latest']=dict(live=False,asset=latest['asset'].tolist(),decision_at=latest['decision_at'].tolist(),
        ensemble_probabilities=np.mean(latest_probs,axis=0).reshape(-1,len(TASK_NAMES),horizon_count).tolist())
    result['elapsed_seconds']=time.monotonic()-start
    if hashlib.sha256((args.dataset/'dataset.npz').read_bytes()).hexdigest()!=source_hash:raise RuntimeError('source_dataset_changed')
    np.savez_compressed(args.output/'predictions.npz',probabilities=probabilities,linear=linear,frequency=frequency,
        source_row=d['source_row'],quarter_id=fold_id,seeds=args.seeds,research_only=True,orders_authorized=False)
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print('saved',args.output,'seconds',round(result['elapsed_seconds'],1),flush=True)


if __name__=='__main__':
    with threadpool_limits(limits=1):main()
