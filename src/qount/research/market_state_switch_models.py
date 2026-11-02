"""Small isolated switch-learning ablations; not the default training model."""
from __future__ import annotations

import numpy as np
import torch
from torch import nn

from qount.research.market_state_neural import OHLCVGRU

CHANGE_FEATURES=('return1_sigma','return3_sigma','return7_sigma','drift_change_sigma',
    'recent_volatility_ratio','pressure1','pressure3_change','relative_quote',
    'relative_trades','prior_high_break_sigma','prior_low_break_sigma','signed_body_fraction')


def change_features(raw):
    """Fixed diagnostics derived only from the supplied completed daily bars."""
    raw=np.asarray(raw,float)
    if raw.ndim!=3 or raw.shape[1]<10 or raw.shape[2]!=9 or not np.isfinite(raw).all() or np.any(raw<=0):
        raise ValueError('complete_observed_nine_channel_window_required')
    c=np.log(raw[:,:,3]);returns=np.diff(c,axis=1);sigma=np.maximum(returns.std(1),1e-6)
    recent=(c[:,-1]-c[:,-4])/3;earlier=(c[:,-4]-c[:,0])/(c.shape[1]-4)
    pressure=2*raw[:,-1,8]/raw[:,-1,5]-1
    short=2*raw[:,-3:,8].sum(1)/raw[:,-3:,5].sum(1)-1
    old=2*raw[:,:-3,8].sum(1)/raw[:,:-3,5].sum(1)-1
    result=np.column_stack(((c[:,-1]-c[:,-2])/sigma,(c[:,-1]-c[:,-4])/(sigma*np.sqrt(3)),
        (c[:,-1]-c[:,-8])/(sigma*np.sqrt(7)),(recent-earlier)/sigma,
        np.log((returns[:,-3:].std(1)+1e-6)/(returns[:,:-3].std(1)+1e-6)),pressure,short-old,
        np.log(raw[:,-1,5]/np.median(raw[:,:-1,5],axis=1)),
        np.log(raw[:,-1,6]/np.median(raw[:,:-1,6],axis=1)),
        (c[:,-1]-np.log(raw[:,-8:-1,1].max(1)))/sigma,
        (c[:,-1]-np.log(raw[:,-8:-1,2].min(1)))/sigma,
        (raw[:,-1,3]-raw[:,-1,0])/np.maximum(raw[:,-1,1]-raw[:,-1,2],1e-10)))
    if not np.isfinite(result).all():raise ValueError('nonfinite_change_features')
    return result.astype(np.float32)


class SwitchGRU(OHLCVGRU):
    """Shared baseline encoder; alter one named component per ablation."""
    def __init__(self,assets,variant,hidden=32,channels=9):
        super().__init__(assets,hidden=hidden,channels=channels)
        self.variant=variant
        # Keep common initialization/dropout RNG identical to the baseline.
        with torch.random.fork_rng():
            if variant=='aux_switch':self.switch=nn.Linear(hidden+4,1)
            elif variant=='attention':
                self.query=nn.Linear(hidden,hidden,bias=False)
                self.merge=nn.Linear(2*hidden,hidden)
            elif variant=='change_features':
                self.head=nn.Sequential(nn.LayerNorm(hidden+4+len(CHANGE_FEATURES)),nn.Dropout(.1),
                    nn.Linear(hidden+4+len(CHANGE_FEATURES),3))

    def forward(self,sequence,asset,features=None):
        outputs,h=self.encoder(sequence);last=h[-1]
        if self.variant=='attention':
            weights=(outputs*self.query(last)[:,None]).sum(2)/(outputs.shape[-1]**.5)
            context=(outputs*weights.softmax(1)[:,:,None]).sum(1)
            last=torch.tanh(self.merge(torch.cat((last,context),1)))
        representation=torch.cat((last,self.asset(asset)),1)
        switch=self.switch(representation).squeeze(1) if self.variant=='aux_switch' else None
        if self.variant=='change_features':representation=torch.cat((representation,features),1)
        return self.head(representation),switch


def predict_switch_model(model,x,asset,features):
    model.eval();prob=[];switch=[]
    with torch.no_grad():
        for start in range(0,len(x),1024):
            logits,aux=model(x[start:start+1024],asset[start:start+1024],features[start:start+1024])
            prob.append(logits.softmax(1).numpy())
            switch.append(aux.sigmoid().numpy() if aux is not None else np.full(len(logits),np.nan))
    return .99*np.concatenate(prob)+.01/3,np.concatenate(switch)


def fit_switch_variant(sequence,asset,y,changed,features,train,test,*,assets,variant,seed,baseline):
    """Fixed hypotheses, no test-tuned weights or hyperparameters.

    Replay fine-tune has an equal-compute uniform replay control. For weighted
    replay only mature true switch labels determine sample loss weights.
    """
    torch.manual_seed(seed)
    mean=np.asarray(baseline['mean']);scale=np.asarray(baseline['scale'])
    x=torch.from_numpy(np.ascontiguousarray((sequence-mean)/scale))
    feature_mean=features[train].mean(0);feature_scale=np.maximum(features[train].std(0),1e-6)
    f=torch.from_numpy(np.ascontiguousarray((features-feature_mean)/feature_scale))
    a=torch.from_numpy(asset);target=torch.from_numpy(y.astype(np.int64));switch=torch.from_numpy(changed.astype(np.float32))
    model=SwitchGRU(assets,variant);replay=variant in ('uniform_replay','switch_replay')
    if replay:
        model.load_state_dict(baseline['model']);epochs=5;lr=.0003
        torch.manual_seed(seed+1000)
    else:
        epochs=20;lr=.001;prior=np.bincount(y[train],minlength=3)/len(train)
        with torch.no_grad():model.head[-1].bias.copy_(torch.tensor(np.log(prior),dtype=torch.float32))
    optimizer=torch.optim.AdamW(model.parameters(),lr=lr,weight_decay=.001)
    generator=torch.Generator().manual_seed(seed+1000 if replay else seed)
    weights=1+3*switch if variant in ('switch_replay','switch_weighted') else torch.ones_like(switch)
    positive=int(changed[train].sum());pos_weight=float(min(5.,np.sqrt((len(train)-positive)/max(positive,1))))
    history=[]
    for epoch in range(epochs):
        model.train();total=0.;count=0
        for positions in torch.randperm(len(train),generator=generator).split(256):
            ix=torch.from_numpy(train[positions.numpy()]);optimizer.zero_grad(set_to_none=True)
            logits,aux=model(x[ix],a[ix],f[ix]);losses=nn.functional.cross_entropy(logits,target[ix],reduction='none')
            loss=(losses*weights[ix]).sum()/weights[ix].sum()
            if aux is not None:
                loss=loss+.3*nn.functional.binary_cross_entropy_with_logits(aux,switch[ix],pos_weight=torch.tensor(pos_weight))
            if not torch.isfinite(loss):raise RuntimeError('nonfinite_switch_fit')
            loss.backward();nn.utils.clip_grad_norm_(model.parameters(),1.);optimizer.step()
            total+=float(loss.detach())*len(ix);count+=len(ix)
        history.append(total/count)
    p,aux=predict_switch_model(model,x[test],a[test],f[test])
    training,_=predict_switch_model(model,x[train],a[train],f[train])
    detail=dict(loss=history,epochs=epochs,learning_rate=lr,switch_weight=4 if variant in ('switch_replay','switch_weighted') else 1,
        auxiliary_loss_weight=.3 if variant=='aux_switch' else 0,auxiliary_positive_weight=pos_weight if variant=='aux_switch' else None,
        parameters=sum(p.numel() for p in model.parameters()))
    checkpoint=dict(model=model.state_dict(),mean=mean,scale=scale,feature_mean=feature_mean,feature_scale=feature_scale,
        variant=variant,hidden=32,assets=assets,input_channels=9)
    return p,aux,training,detail,checkpoint
