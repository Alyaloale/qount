"""Causal, ordered OHLCV windows for models that learn their own features."""
from __future__ import annotations

import numpy as np

CHANNELS=('open','high','low','close','volume')


def same_day_targets(states,attributes,label_available_at):
    """Estimate S_n(k) at k; its hindsight answer only matures at k+n.

    The reference scale n does not shift the prediction target to k+n.
    Label maturity comes from the labeler and must still purge training rows.
    """
    states=np.asarray(states);attributes=np.asarray(attributes,float)
    clock=np.asarray(label_available_at,np.int64)
    if (states.ndim!=1 or clock.shape!=states.shape or attributes.ndim!=2
            or len(attributes)!=len(states) or np.any((states<-1)|(states>2))):
        raise ValueError('invalid_same_day_targets')
    valid=states>=0
    if np.any(clock[valid]<=0):raise ValueError('missing_label_maturity')
    return dict(target_main_state=states.astype(np.int16).copy(),
        target_attributes=np.where(valid[:,None],attributes,np.nan),
        target_row=np.where(valid,np.arange(len(states)),-1),target_mask=valid,
        target_available_at=np.where(valid,clock,0))


def raw_window(ohlcv,k,length):
    values=np.asarray(ohlcv,float)
    if values.ndim!=2 or values.shape[1]!=5 or length<1 or not 0<=k<len(values):
        raise ValueError('invalid_ohlcv_window')
    if k<length-1:return None
    window=values[k-length+1:k+1].copy()
    if np.any(~np.isfinite(window)) or np.any(window[:,:4]<=0) or np.any(window[:,4]<0):
        raise ValueError('invalid_ohlcv_values')
    return window


def model_window(raw):
    """Five columns, no technical indicators; retain the original raw tensor.

    Price levels are relative to the first completed close in this window.
    Volume uses log1p; zero volumes stay zero. Train-fold scaling is separate.
    """
    raw=np.asarray(raw,float)
    if raw.ndim!=2 or raw.shape[1]!=5 or not len(raw):raise ValueError('invalid_raw_sequence')
    if np.any(~np.isfinite(raw)) or np.any(raw[:,:4]<=0) or np.any(raw[:,4]<0):
        raise ValueError('invalid_raw_sequence_values')
    result=np.empty_like(raw)
    result[:,:4]=np.log(raw[:,:4]/raw[0,3])
    result[:,4]=np.log1p(raw[:,4])
    return result.astype(np.float32)


def fold_scale(training):
    """Fit scaling on training sequences only, across sample and time axes."""
    training=np.asarray(training)
    if (training.ndim!=3 or training.shape[2] not in (5,9) or not len(training)
            or np.any(~np.isfinite(training))):
        raise ValueError('invalid_training_sequences')
    mean=training.mean(axis=(0,1),dtype=np.float64)
    scale=np.maximum(training.std(axis=(0,1),dtype=np.float64),1e-6)
    return mean.astype(np.float32),scale.astype(np.float32)
