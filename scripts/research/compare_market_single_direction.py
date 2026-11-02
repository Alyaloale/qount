"""Compare one future direction target using short and longer daily context."""
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
from sklearn.metrics import balanced_accuracy_score, roc_auc_score
from threadpoolctl import threadpool_limits

from qount.research.market_future_direction import price_targets, slope_targets, mature_split
from qount.research.market_state_dataset import CurrentStateDataset, DEFAULT_ROOT
from qount.research.market_state_profit import complete_history
from qount.research.market_state_sequence import fold_scale
from qount.research.market_state_flows import normalize_market_windows


class FutureGRU(nn.Module):
    def __init__(self,assets):
        super().__init__();self.encoder=nn.GRU(9,32,batch_first=True);self.asset=nn.Embedding(assets,4)
        self.head=nn.Sequential(nn.LayerNorm(36),nn.Dropout(.1),nn.Linear(36,1))

    def forward(self,x,asset):
        _,h=self.encoder(x);return self.head(torch.cat((h[-1],self.asset(asset)),1))


def predict(model,x,asset):
    model.eval()
    with torch.no_grad():return np.concatenate([model(x[s:s+1024],asset[s:s+1024]).sigmoid().numpy() for s in range(0,len(x),1024)])


def fit(sequence,asset,y,mask,train,test,*,assets,epochs,seed):
    torch.manual_seed(seed);mean,scale=fold_scale(sequence[train])
    x=torch.from_numpy(np.ascontiguousarray((sequence[train]-mean)/scale));a=torch.from_numpy(asset[train])
    target=torch.from_numpy(y[train].astype(np.float32));valid=torch.from_numpy(mask[train].astype(np.float32))
    model=FutureGRU(assets);prior=(y[train]*mask[train]).sum(0)/mask[train].sum(0)
    with torch.no_grad():model.head[-1].bias.copy_(torch.tensor(np.log(prior/(1-prior)),dtype=torch.float32))
    optimizer=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.001);generator=torch.Generator().manual_seed(seed)
    losses=[]
    for _ in range(epochs):
        model.train();total=0.;count=0
        for batch in torch.randperm(len(train),generator=generator).split(256):
            optimizer.zero_grad(set_to_none=True)
            raw=nn.functional.binary_cross_entropy_with_logits(model(x[batch],a[batch]),target[batch],reduction='none')
            loss=(raw*valid[batch]).sum()/valid[batch].sum();loss.backward();nn.utils.clip_grad_norm_(model.parameters(),1.);optimizer.step()
            total+=float(loss.detach())*len(batch);count+=len(batch)
        losses.append(total/count)
    testx=torch.from_numpy(np.ascontiguousarray((sequence[test]-mean)/scale));testa=torch.from_numpy(asset[test])
    probability=predict(model,testx,testa)
    checkpoint=dict(model=model.state_dict(),mean=torch.from_numpy(mean),scale=torch.from_numpy(scale),outputs=1,seed=seed,
        input_channels=9,input_length=sequence.shape[1],research_only=True,orders_authorized=False)
    return probability,checkpoint,dict(train_binary_cross_entropy=losses,parameters=sum(p.numel() for p in model.parameters()))


def metrics(y,p,baseline):
    brier=float(np.mean((p-y)**2));base=float(np.mean((baseline-y)**2))
    return dict(rows=len(y),positive_fraction=float(y.mean()),predicted_positive_fraction=float((p>=.5).mean()),
        accuracy=float(np.mean((p>=.5)==y)),balanced_accuracy=float(balanced_accuracy_score(y,p>=.5)),
        auc=float(roc_auc_score(y,p)),brier=brier,frequency_brier=base,brier_skill=1-brier/base)


def paired_quarter_interval(y,p,baseline,valid,fold_id):
    delta=((p-y)**2-(baseline-y)**2);ids=np.unique(fold_id[fold_id>=0]);sums=[];counts=[]
    for key in ids:
        chosen=valid&(fold_id[:,None]==key);sums.append(delta[chosen].sum());counts.append(chosen.sum())
    sums=np.array(sums);counts=np.array(counts);rng=np.random.default_rng(20261101)
    samples=rng.integers(len(ids),size=(4000,len(ids)));estimates=sums[samples].sum(1)/counts[samples].sum(1)
    return dict(mean=float(delta[valid].mean()),ci95=np.quantile(estimates,[.025,.975]).tolist(),blocks=len(ids),
        unit='whole quarter with all assets; descriptive on consumed history')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dataset',type=Path,default=DEFAULT_ROOT)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--target',choices=('endpoint','slope'),default='endpoint')
    ap.add_argument('--horizon',type=int,default=14)
    ap.add_argument('--lookback',type=int,choices=(14,90),default=90)
    ap.add_argument('--epochs',type=int,default=20)
    ap.add_argument('--seeds',type=int,nargs='+',default=[17,29,43])
    ap.add_argument('--max-seconds',type=int,default=900)
    args=ap.parse_args()
    if args.output.exists():ap.error('preserve previous experiments')
    if args.horizon<2 or not args.seeds:ap.error('invalid horizon or seeds')
    source_hash=hashlib.sha256((args.dataset/'dataset.npz').read_bytes()).hexdigest()
    ds=CurrentStateDataset(args.dataset);d=ds.data;history=complete_history(ds);count=len(d['asset'])
    y=np.zeros((count,1),bool);mask=np.zeros_like(y);observed=np.zeros_like(y)
    available=np.zeros((count,1),np.int64);value=np.full((count,1),np.nan)
    for asset in ds.asset_names:
        rows=np.flatnonzero(d['asset']==asset);h=history[asset]
        if args.target=='endpoint':
            t=price_targets(h['open_at'],h['market'][:,3],d['bar_open_at'][rows],
                n=max(14,args.horizon+1),horizons=(args.horizon,))
            values=t['returns'][:,0];labels=t['above'][:,0];valid=t['valid'][:,0];seen=t['observed'][:,0];ready=t['available_at'][:,0]
        else:
            t=slope_targets(h['open_at'],h['market'][:,3],d['bar_open_at'][rows],horizon=args.horizon)
            values=t['slopes'];labels=t['up'];valid=t['valid'];seen=t['observed'];ready=t['available_at']
        y[rows,0]=labels;mask[rows,0]=valid;observed[rows,0]=seen;available[rows,0]=ready;value[rows,0]=values
    asset_index=ds.asset_index
    if args.lookback==14:
        sequence=d['n_scaled_market'].copy()
        input_complete=np.ones(count,bool)
    else:
        sequence=np.full((count,args.lookback,9),np.nan,np.float32)
        input_complete=np.zeros(count,bool)
        for asset in ds.asset_names:
            rows=np.flatnonzero(d['asset']==asset);h=history[asset]
            indices=np.searchsorted(h['open_at'],d['bar_open_at'][rows])
            aligned=(indices<len(h['open_at']))
            aligned[aligned]&=h['open_at'][indices[aligned]]==d['bar_open_at'][rows[aligned]]
            enough=aligned&(indices>=args.lookback-1)
            for row,index in zip(rows[enough],indices[enough]):
                raw=h['market'][index-args.lookback+1:index+1]
                sequence[row]=normalize_market_windows(raw[None])[0]
                input_complete[row]=True
    if sequence.shape[1:]!=(args.lookback,9):raise ValueError('invalid_native_market_input_shape')
    args.output.mkdir(parents=True);torch.set_num_threads(2);torch.use_deterministic_algorithms(True)
    np.savez_compressed(args.output/'dataset.npz',schema='single_future_direction_v1',target=args.target,
        horizon=args.horizon,lookback=args.lookback,model_input=sequence,asset=d['asset'],asset_index=asset_index,
        source_row=d['source_row'],decision_at=d['decision_at'],target_value=value,above=y,valid=mask,
        observed=observed,target_available_at=available,research_only=True,orders_authorized=False)
    frequency=np.full((count,1),np.nan);linear=np.full((count,1),np.nan);predictions=[]
    fold_id=np.full(count,-1,np.int64);fits=[];start=time.monotonic()
    stamps=[dt.datetime.fromtimestamp(int(s)/1000,dt.timezone.utc) for s in d['decision_at']]
    quarters=sorted({(s.year,(s.month-1)//3*3+1) for s in stamps if s.year>=2023})
    for year,month in quarters:
        if time.monotonic()-start>args.max_seconds:raise RuntimeError('bounded_training_budget_exceeded')
        cutoff=int(dt.datetime(year,month,1,tzinfo=dt.timezone.utc).timestamp()*1000)
        end=int(dt.datetime(year+int(month==10),1 if month==10 else month+3,1,tzinfo=dt.timezone.utc).timestamp()*1000)
        train,test=mature_split(d['decision_at'],available,observed&input_complete[:,None],cutoff,end)
        if len(train)<200 or not len(test):continue
        for ai in range(len(ds.asset_names)):
            tr=train[asset_index[train]==ai]
            frequency[test[asset_index[test]==ai],0]=((y[tr,0]*mask[tr,0]).sum()+1)/(mask[tr,0].sum()+2)
        mean,scale=fold_scale(sequence[train]);flat=((sequence-mean)/scale).reshape(count,-1)
        flat=np.c_[flat,np.eye(len(ds.asset_names),dtype=np.float32)[asset_index]]
        tr=train[mask[train,0]];model=LogisticRegression(C=.1,max_iter=400);model.fit(flat[tr],y[tr,0]);linear[test,0]=model.predict_proba(flat[test])[:,1]
        details=[]
        for seed in args.seeds:
            p,checkpoint,detail=fit(sequence,asset_index,y,mask,train,test,assets=len(ds.asset_names),epochs=args.epochs,seed=seed)
            predictions.append((seed,test.copy(),p[:,0].copy()));details.append(dict(seed=seed,**detail))
            checkpoint.update(asset_names=ds.asset_names,cutoff=cutoff,epochs=args.epochs,source_dataset_sha256=source_hash,
                horizon=args.horizon,target=args.target,independent_oos=False)
            torch.save(checkpoint,args.output/f'latest_{seed}.pt')
        fold_id[test]=cutoff;fits.append(dict(cutoff=cutoff,end=end,train_rows=len(train),test_rows=len(test),details=details))
    valid=mask[:,0]&np.isfinite(frequency[:,0]);complete=np.isfinite(frequency[:,0])
    if not complete.any():raise RuntimeError('no_predictions')
    by_seed={}
    for seed in args.seeds:
        p=np.full(count,np.nan)
        for s,rows,vals in predictions:
            if s==seed:p[rows]=vals
        by_seed[str(seed)]=p
    stacked=np.stack([by_seed[str(s)] for s in args.seeds]);seen=np.isfinite(stacked)
    ensemble=np.divide(np.nansum(stacked,axis=0),seen.sum(0),out=np.full(count,np.nan),where=seen.sum(0)>0)
    candidates={'constant_half':np.full(count,.5),'frequency':frequency[:,0],'linear_raw_sequence':linear[:,0],'gru_ensemble':ensemble}
    candidates.update({f'gru_seed_{s}':p for s,p in by_seed.items()})
    result=dict(research_only=True,orders_authorized=False,independent_oos=False,target=args.target,horizon=args.horizon,
        lookback=args.lookback,input_channels=9,input_scaling='window-relative log OHLC and log1p activity; fold scaler fitted on training rows only',
        target_definition=(f'C[k+{args.horizon}]/C[k]-1 > 0' if args.target=='endpoint' else f'OLS slope of C[k+1]...C[k+{args.horizon}] on day number > 0'),
        input_rows=count,fully_observed_rows=int(observed[:,0].sum()),missing_future_rows=int((~observed[:,0]).sum()),
        predictions=int(complete.sum()),folds=fits,models={})
    for name,p in candidates.items():
        chosen=valid&np.isfinite(p);result['models'][name]=dict(metrics=metrics(y[chosen,0],p[chosen],frequency[chosen,0]),
            brier_delta_vs_frequency=paired_quarter_interval(y,p[:,None],frequency,mask&np.isfinite(frequency),fold_id))
    # Summarise optimization progress across folds/seeds without mixing test losses.
    loss_curves=np.array([detail['train_binary_cross_entropy'] for fold in fits for detail in fold['details']],float)
    result['training_loss']=dict(name='masked binary cross entropy',epochs=args.epochs,curves=int(len(loss_curves)),
        median_by_epoch=np.median(loss_curves,axis=0).tolist(),
        q25_by_epoch=np.quantile(loss_curves,.25,axis=0).tolist(),q75_by_epoch=np.quantile(loss_curves,.75,axis=0).tolist(),
        note='training folds only; no validation/test labels used for weight updates')
    result['elapsed_seconds']=time.monotonic()-start
    np.savez_compressed(args.output/'predictions.npz',frequency=frequency,linear=linear,ensemble=ensemble,fold_id=fold_id,
        source_row=d['source_row'],training_loss=loss_curves,research_only=True,orders_authorized=False)
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print('saved',args.output,'seconds',round(result['elapsed_seconds'],1),flush=True)


if __name__=='__main__':
    with threadpool_limits(limits=1):main()
