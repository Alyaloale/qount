"""Native daily trading activity and explicit causal event joins.

Aggressive turnover is not net cash deposited at an exchange. Missing
derivative observations remain missing rather than becoming zero flows.
"""
from __future__ import annotations

import numpy as np

MARKET_CHANNELS=('open','high','low','close','base_volume','quote_volume',
                 'trade_count','taker_buy_base_volume','taker_buy_quote_volume')
FLOW_NAMES=('taker_buy_base_volume','taker_sell_base_volume','taker_buy_quote_volume',
            'taker_sell_quote_volume','signed_taker_quote_delta')
POSITION_NAMES=('sum_open_interest','sum_open_interest_value','count_toptrader_long_short_ratio',
                'sum_toptrader_long_short_ratio','count_long_short_ratio','sum_taker_long_short_vol_ratio')


def trading_flows(market):
    a=np.asarray(market,float)
    if a.ndim!=2 or a.shape[1]!=9:raise ValueError('expected_nine_native_market_fields')
    for total,buy in ((4,7),(5,8)):
        good=np.isfinite(a[:,total])&np.isfinite(a[:,buy])
        if np.any(a[good,buy]<0) or np.any(a[good,buy]>a[good,total]+1e-8):
            raise ValueError('taker_buy_exceeds_total')
    buy_base=a[:,7];sell_base=a[:,4]-buy_base;buy_quote=a[:,8];sell_quote=a[:,5]-buy_quote
    return np.c_[buy_base,sell_base,buy_quote,sell_quote,buy_quote-sell_quote]


def asof_indices(observed,available,decision,*,max_age_ms=None):
    """Last published event at each decision, without stale forward filling."""
    observed=np.asarray(observed,np.int64);available=np.asarray(available,np.int64)
    decision=np.asarray(decision,np.int64)
    if (observed.ndim!=1 or available.shape!=observed.shape or decision.ndim!=1
            or np.any(np.diff(observed)<=0) or np.any(np.diff(available)<0)):
        raise ValueError('events_must_be_unique_and_ordered')
    if np.any(available<observed):raise ValueError('event_available_before_observation')
    if max_age_ms is not None and max_age_ms<0:raise ValueError('negative_event_max_age')
    result=np.searchsorted(available,decision,side='right')-1
    valid=result>=0
    if max_age_ms is not None:
        valid[valid]&=decision[valid]-observed[result[valid]]<=max_age_ms
    result[~valid]=-1
    return result


def gather_windows(values,rows):
    """Storage padding and absent source fields keep independent NaN masks."""
    values=np.asarray(values);rows=np.asarray(rows,int)
    result=np.full((*rows.shape,values.shape[1]),np.nan,dtype=values.dtype)
    present=rows>=0;result[present]=values[rows[present]]
    return result,np.isfinite(result)


def normalize_market_windows(raw):
    """Only scale raw channels; a training fold must later fit its own scaler."""
    raw=np.asarray(raw,float)
    if raw.ndim!=3 or raw.shape[2]!=9:raise ValueError('expected_batch_time_nine_fields')
    out=np.full_like(raw,np.nan,dtype=np.float32)
    for row in range(len(raw)):
        present=np.isfinite(raw[row,:,3]);where=np.flatnonzero(present)
        if not len(where):continue
        window=raw[row,where]
        if np.any(window[:,:4]<=0) or np.any(window[:,4:][np.isfinite(window[:,4:])]<0):
            raise ValueError('invalid_native_market_sequence')
        out[row,where,:4]=np.log(window[:,:4]/window[0,3])
        out[row,where,4:]=np.log1p(window[:,4:])
    return out


def relative_activity_windows(raw):
    """Experimental complete-input scaling; never changes the stored dataset.

    Prices retain the existing relative-close transform. Activity is relative
    to the median total activity in the observed input window. Total and taker
    buy fields share denominators, preserving their ratio in log differences.
    A training-only channel scaler must still be fitted afterward.
    """
    raw=np.asarray(raw,float)
    if (raw.ndim!=3 or raw.shape[2]!=9 or raw.shape[1]<1
            or not np.isfinite(raw).all() or np.any(raw<=0)):
        raise ValueError('relative_activity_requires_complete_positive_nine_fields')
    out=normalize_market_windows(raw)
    reference=np.median(raw[:,:,4:7],axis=1)
    denominators=reference[:,[0,1,2,0,1]]
    out[:,:,4:]=np.log(raw[:,:,4:]/denominators[:,None,:])
    return out


def center_asset_activity(sequence,asset,train):
    """Center existing log1p activity by each asset's mature training rows.

    Total/buy fields share the total-field reference. No window-level activity
    baseline is removed. Return references explicitly for later inference.
    """
    sequence=np.asarray(sequence);asset=np.asarray(asset);train=np.asarray(train)
    if (sequence.ndim!=3 or sequence.shape[2]!=9 or not np.isfinite(sequence).all()
            or asset.shape!=(len(sequence),) or asset.dtype.kind not in 'iu'
            or np.any(asset<0) or train.ndim!=1 or train.dtype.kind not in 'iu'
            or not len(train) or np.any(train<0) or np.any(train>=len(sequence))):
        raise ValueError('invalid_asset_centering_inputs')
    out=sequence.copy();centers=np.zeros((int(asset.max())+1,5),np.float32)
    for a in np.unique(asset):
        own=train[asset[train]==a]
        if not len(own):raise ValueError('asset_missing_from_training_fold')
        reference=sequence[own,:,4:7].mean(axis=(0,1),dtype=np.float64)
        centers[a]=reference[[0,1,2,0,1]]
        out[asset==a,:,4:]-=centers[a]
    return out,centers
