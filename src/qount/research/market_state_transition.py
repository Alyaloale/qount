"""Typed early-state supervision; targets never form part of model inputs."""
from __future__ import annotations

import numpy as np
import torch
from torch import nn

from qount.research.market_state_neural import OHLCVGRU,fit_gru,forecast
from qount.research.market_state_calibration import apply_calibration
from qount.research.market_state_sequence import fold_scale
from qount.research.market_state_switch_models import change_features
from qount.research.market_state_dataset import validate_market_inputs

PHASE_NAMES=('continuation','early_upward','early_downward','early_sideways')
CONTINUOUS_NAMES=('direction_score','signed_slope_range_efficiency')


def phase_targets(asset,state,previous,*,early_days=3):
    """Ages use only predecessor labels; the unobserved initial age is masked.

    Short completed spells are not removed. No spell end or remaining duration
    is used, so maturity is still that of the current state's k+n label.
    """
    asset=np.asarray(asset);state=np.asarray(state);previous=np.asarray(previous)
    if (asset.ndim!=1 or state.shape!=asset.shape or previous.shape!=asset.shape
            or np.any(~np.isin(state,[0,1,2])) or np.any(~np.isin(previous,[0,1,2])) or early_days<1):
        raise ValueError('invalid_phase_supervision')
    phase=np.zeros(len(state),np.int64);age=np.full(len(state),-1,np.int64);valid=np.zeros(len(state),bool)
    for a in np.unique(asset):
        rows=np.flatnonzero(asset==a);known=False;running=0
        for j,row in enumerate(rows):
            if j and previous[row]!=state[rows[j-1]]:raise ValueError('phase_predecessor_mismatch')
            if state[row]!=previous[row]:known=True;running=1
            elif known:running+=1
            if known:
                valid[row]=True;age[row]=running
                if running<=early_days:phase[row]=1+state[row]
    return dict(phase=phase,phase_valid=valid,age=age)


def label_price_context(data,latest):
    """Recover target prices from this complete bundle, without parent caches.

    Overlapping retained input windows cover the historical prefix, and the
    separately retained latest windows cover the unlabelled future tail.
    Every repeated bar must agree; absent target prices are never filled.
    """
    validate_market_inputs(latest)
    size=int(max(data['label_context_source_rows'].max(),latest['two_n_source_rows'].max()))+1
    prices=np.full((size,4),np.nan)
    for source_rows,raw in ((data['two_n_source_rows'],data['two_n_raw_market']),
                           (latest['two_n_source_rows'],latest['two_n_raw_market'])):
        ids=np.asarray(source_rows).reshape(-1);bars=np.asarray(raw)[:,:,:4].reshape(-1,4)
        if np.any(ids<0) or np.any(ids>=size):raise ValueError('invalid_transition_source_rows')
        unique,first=np.unique(ids,return_index=True);present=np.isfinite(prices[unique]).all(1)
        if not np.array_equal(prices[unique[present]],bars[first[present]]):raise ValueError('conflicting_transition_prices')
        prices[unique]=bars[first]
        if not np.array_equal(prices[ids],bars):raise ValueError('conflicting_overlapping_transition_prices')
    context=prices[data['label_context_source_rows']]
    if not np.isfinite(context).all() or np.any(context<=0):raise ValueError('incomplete_transition_target_context')
    return context


def transition_targets(ds):
    d=ds.data;n=int(d['reference_sessions']);result=phase_targets(d['asset'],d['state'],d['previous_state_label'])
    # Future-containing prices are accessed exclusively by this target builder.
    with np.load(ds.root/'latest_inputs.npz',allow_pickle=False) as z:latest={k:z[k] for k in z.files}
    log=np.log(label_price_context(d,latest));close=log[:,:,3];t=np.arange(2*n)-(n-1)
    w=np.exp2(-abs(t)/(n/3));w/=w.sum();rw=(w[1:]+w[:-1])/2;rw/=rw.sum()
    slope=close@(w*(t-w@t)/(w@((t-w@t)**2)))
    returns=np.diff(close,axis=1);mean=returns@rw;vol=np.sqrt(((returns-mean[:,None])**2)@rw)
    ranges=np.maximum(log[:,1:,1]-log[:,1:,2],np.maximum(abs(log[:,1:,1]-close[:,:-1]),abs(log[:,1:,2]-close[:,:-1])))
    result['continuous']=np.column_stack((slope*np.sqrt(n)/np.maximum(vol,1e-10),slope/np.maximum(ranges@rw,1e-12))).astype(np.float32)
    if not np.isfinite(result['continuous']).all():raise ValueError('nonfinite_transition_targets')
    result.update(state=d['state'].copy(),available_at=d['label_available_at'].copy(),source_row=d['source_row'].copy())
    return result


class TypedTransitionGRU(OHLCVGRU):
    """Three-state output: continuation expert plus typed early-state mass.

    The four-way phase is an auxiliary output, not a fourth market state.
    Neither true age nor previous true state is needed for a forward pass.
    """
    def __init__(self,assets,hidden=32,channels=9):
        super().__init__(assets,hidden,channels)
        with torch.random.fork_rng():
            self.phase=nn.Linear(hidden+4,4)
            self.continuous=nn.Linear(hidden+4,2)

    def forward(self,sequence,asset):
        _,h=self.encoder(sequence);representation=torch.cat((h[-1],self.asset(asset)),1)
        continuation=self.head(representation).softmax(1)
        phase=self.phase(representation).softmax(1)
        probability=phase[:,:1]*continuation+phase[:,1:]
        return probability,phase,self.continuous(representation),continuation


def transition_predict(model,sequence,asset):
    model.eval();parts=[[],[],[]]
    with torch.no_grad():
        for start in range(0,len(sequence),1024):
            outputs=model(sequence[start:start+1024],asset[start:start+1024])
            for j in range(3):parts[j].append(outputs[j].numpy())
    return .99*np.concatenate(parts[0])+.01/3,np.concatenate(parts[1]),np.concatenate(parts[2])


def infer_typed_checkpoint(checkpoint,market,asset):
    """Infer from the reader's window-scaled daily inputs; no targets accepted."""
    if checkpoint.get('architecture')!='typed_transition_gru':raise ValueError('wrong_transition_architecture')
    market=np.asarray(market);asset=np.asarray(asset)
    if (market.ndim!=3 or market.shape[2]!=9 or len(market)!=len(asset)
            or not len(market) or not np.isfinite(market).all() or asset.ndim!=1 or asset.dtype.kind not in 'iu'
            or np.any(asset<0) or np.any(asset>=checkpoint['assets'])
            or market.shape[1]!=checkpoint.get('input_length',market.shape[1])):
        raise ValueError('invalid_transition_inference_inputs')
    def array(name):
        value=checkpoint[name]
        return value.detach().cpu().numpy() if isinstance(value,torch.Tensor) else np.asarray(value)
    mean=array('mean');scale=array('scale')
    if mean.shape!=(9,) or scale.shape!=(9,) or np.any(scale<=0):raise ValueError('invalid_saved_input_scaler')
    model=TypedTransitionGRU(checkpoint['assets'],checkpoint['hidden'],checkpoint['input_channels'])
    model.load_state_dict(checkpoint['model'])
    x=torch.from_numpy(np.ascontiguousarray((market-mean)/scale,dtype=np.float32));a=torch.from_numpy(asset.astype(np.int64))
    p,phase,continuous=transition_predict(model,x,a)
    return dict(state_probabilities=p,phase_probabilities=phase,
        continuous_predictions=continuous*array('target_scale')+array('target_mean'))


def infer_state_with_transition(checkpoint,market,asset):
    """Separate current-state estimate from current early-stage probability.

    A potentially useful phase signal must not overwrite the state estimator.
    Calibrators, when present, were fitted on earlier matured forecasts.
    """
    if checkpoint.get('architecture')!='state_with_transition_gru':raise ValueError('wrong_bundled_architecture')
    transition=dict(checkpoint,architecture='typed_transition_gru',model=checkpoint['transition_model'])
    result=infer_typed_checkpoint(transition,market,asset)
    def array(name):
        value=checkpoint[name]
        return value.detach().cpu().numpy() if isinstance(value,torch.Tensor) else np.asarray(value)
    model=OHLCVGRU(checkpoint['assets'],checkpoint['hidden'],checkpoint['input_channels'])
    model.load_state_dict(checkpoint['model'])
    x=torch.from_numpy(np.ascontiguousarray((np.asarray(market)-array('mean'))/array('scale'),dtype=np.float32))
    p=forecast(model,x,torch.from_numpy(np.asarray(asset,dtype=np.int64)))
    if 'state_calibration' in checkpoint:p=apply_calibration(p,checkpoint['state_calibration'])
    result['state_probabilities']=p
    if 'phase_calibration' in checkpoint:
        result['phase_probabilities']=apply_calibration(result['phase_probabilities'],checkpoint['phase_calibration'])
    result['early_trend_probability']=result['phase_probabilities'][:,1:3].sum(1)
    threshold=checkpoint.get('early_trend_threshold')
    result['early_trend_alert']=result['early_trend_probability']>=threshold if threshold is not None else None
    return result


def fit_typed_transition(sequence,asset,raw,targets,train,test,*,assets,seed,epochs=20):
    """Unweighted main likelihood, typed phase emphasis, continuous targets.

    Hard negatives are mature sideways continuations with a large observed
    three-day move or aggressive-flow change. Selection thresholds are fixed
    or fitted on training inputs only; test labels never set loss weights.
    """
    torch.manual_seed(seed);mean,scale=fold_scale(sequence[train])
    x=torch.from_numpy(np.ascontiguousarray((sequence-mean)/scale));a=torch.from_numpy(asset)
    y=torch.from_numpy(targets['state'].astype(np.int64));phase=torch.from_numpy(targets['phase'])
    phase_valid=torch.from_numpy(targets['phase_valid']);continuous=targets['continuous']
    target_mean=continuous[train].mean(0);target_scale=np.maximum(continuous[train].std(0),1e-6)
    z=torch.from_numpy(np.ascontiguousarray((continuous-target_mean)/target_scale))
    count=np.bincount(targets['phase'][train][targets['phase_valid'][train]],minlength=4)
    if np.any(count==0):raise ValueError('all_typed_phases_required_in_training')
    class_weight=np.minimum(np.sqrt(len(train)/count),4.);class_weight/=np.average(class_weight,weights=count)
    weight=torch.tensor(class_weight,dtype=torch.float32)
    diagnostic=change_features(raw);flow_threshold=float(np.quantile(abs(diagnostic[train,6]),.75))
    hard=(targets['state']==2)&(targets['phase']==0)&targets['phase_valid']
    hard&=(abs(diagnostic[:,1])>=1)|(abs(diagnostic[:,6])>=flow_threshold)
    example_weight=torch.from_numpy(np.where(hard,1.5,1).astype(np.float32))
    model=TypedTransitionGRU(assets);prior=(np.bincount(targets['state'][train],minlength=3)+1)/(len(train)+3)
    with torch.no_grad():
        model.head[-1].bias.copy_(torch.tensor(np.log(prior),dtype=torch.float32))
        model.phase.bias.copy_(torch.tensor(np.log((count+1)/(count.sum()+4)),dtype=torch.float32))
    optimizer=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.001)
    generator=torch.Generator().manual_seed(seed);history=[]
    for epoch in range(epochs):
        model.train();total=0.;size=0
        for positions in torch.randperm(len(train),generator=generator).split(256):
            ix=torch.from_numpy(train[positions.numpy()]);optimizer.zero_grad(set_to_none=True)
            probability,pred_phase,pred_cont,cont=model(x[ix],a[ix])
            main=nn.functional.nll_loss(probability.clamp_min(1e-8).log(),y[ix])
            known=phase_valid[ix];continuation=known&(phase[ix]==0)
            loss=main
            if known.any():
                phase_loss=nn.functional.nll_loss(pred_phase[known].clamp_min(1e-8).log(),phase[ix][known],weight=weight,reduction='none')
                phase_weight=example_weight[ix][known]
                loss=loss+.2*(phase_loss*phase_weight).mean()
            if continuation.any():loss=loss+.1*nn.functional.nll_loss(cont[continuation].clamp_min(1e-8).log(),y[ix][continuation])
            loss=loss+.1*nn.functional.huber_loss(pred_cont,z[ix])
            if not torch.isfinite(loss):raise RuntimeError('nonfinite_typed_transition_loss')
            loss.backward();nn.utils.clip_grad_norm_(model.parameters(),1.);optimizer.step()
            total+=float(loss.detach())*len(ix);size+=len(ix)
        history.append(total/size)
    probability,phase_probability,regression=transition_predict(model,x[test],a[test])
    detail=dict(loss=history,parameters=sum(p.numel() for p in model.parameters()),phase_counts=count.tolist(),
        phase_class_weights=class_weight.tolist(),hard_negative_rows=int(hard[train].sum()),hard_negative_flow_threshold=flow_threshold,
        main_loss_weight=1,phase_loss_weight=.2,continuation_loss_weight=.1,continuous_loss_weight=.1)
    checkpoint=dict(model=model.state_dict(),mean=mean,scale=scale,target_mean=target_mean,target_scale=target_scale,
        architecture='typed_transition_gru',assets=assets,hidden=32,input_channels=9,phase_names=list(PHASE_NAMES),
        continuous_names=list(CONTINUOUS_NAMES),epochs=epochs)
    return probability,phase_probability,regression*target_scale+target_mean,detail,checkpoint


def fit_state_with_transition(sequence,asset,raw,targets,train,test,*,assets,seed,epochs=20):
    """Fit independent state and phase estimators to avoid negative transfer."""
    state,base_detail,base=fit_gru(sequence,asset,targets['state'],train,test,assets=assets,epochs=epochs,seed=seed)
    _,phase,regression,typed_detail,typed=fit_typed_transition(sequence,asset,raw,targets,train,test,
        assets=assets,epochs=epochs,seed=seed)
    np.testing.assert_array_equal(base['mean'],typed['mean']);np.testing.assert_array_equal(base['scale'],typed['scale'])
    base_detail.pop('train_prediction')
    checkpoint=dict(base,architecture='state_with_transition_gru',transition_model=typed['model'],
        target_mean=typed['target_mean'],target_scale=typed['target_scale'],phase_names=list(PHASE_NAMES),continuous_names=list(CONTINUOUS_NAMES))
    return state,phase,regression,dict(state_training=base_detail,transition_training=typed_detail),checkpoint
