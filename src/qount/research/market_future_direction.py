"""Observed-price supervision for multiple future horizons, without state labels."""
from __future__ import annotations

import numpy as np

from qount.research.market_state_dataset import DAY_MS

HORIZONS = (3, 5, 7, 9, 11, 13, 14)
TASK_NAMES = ('future_close_above_current', 'future_mean_close_above_current',
              'executable_long_net_profit')
PATTERN_NAMES = ('all_above', 'all_below', 'above_then_below', 'below_then_above',
                 'multiple_crossings_end_above', 'multiple_crossings_end_below')


def price_targets(open_at, close, anchor_at, *, n=14, horizons=HORIZONS, release_delay=60001):
    """C[k+h] compared with the SAME C[k]; exact ties are masked, never relabelled.

    The release delay is measured from native bar close (end of day minus 1ms).
    Future prices are supervision only. Incomplete horizons remain invalid.
    """
    clock=np.asarray(open_at,np.int64);close=np.asarray(close,float)
    anchor=np.asarray(anchor_at,np.int64);h=np.asarray(horizons,np.int64)
    if (clock.ndim!=1 or close.shape!=clock.shape or anchor.ndim!=1 or not len(clock)
            or np.any(np.diff(clock)!=DAY_MS) or np.any(~np.isfinite(close)) or np.any(close<=0)
            or h.ndim!=1 or not len(h) or np.any(h<2) or np.any(h>n) or np.any(np.diff(h)<=0)
            or release_delay<1):
        raise ValueError('invalid_direction_history_or_horizons')
    index=np.searchsorted(clock,anchor)
    if np.any(index>=len(clock)) or np.any(clock[index]!=anchor):raise ValueError('missing_anchor_price')
    future=index[:,None]+h[None,:];available=future<len(clock)
    future_close=np.full(future.shape,np.nan)
    future_close[available]=close[future[available]]
    returns=future_close/close[index,None]-1
    cumulative=np.r_[0.,np.cumsum(close)]
    mean_close=np.full(future.shape,np.nan)
    i,j=np.nonzero(available)
    mean_close[i,j]=(cumulative[future[i,j]+1]-cumulative[index[i]+1])/h[j]
    mean_returns=mean_close/close[index,None]-1
    return dict(returns=returns,above=returns>0,valid=available&(returns!=0),
                mean_returns=mean_returns,mean_above=mean_returns>0,
                mean_valid=available&(mean_returns!=0),mean_close=mean_close,
                observed=available,reference_close=close[index],future_close=future_close,
                available_at=anchor[:,None]+(h[None,:]+1)*DAY_MS-1+release_delay)


def slope_targets(open_at, close, anchor_at, *, horizon=7, release_delay=60001):
    """Sign of the least-squares slope across the next ``horizon`` closes.

    The fit uses future closes C[k+1] ... C[k+h] against their ordered day
    numbers.  A zero slope is left invalid rather than assigned a direction.
    The future sequence is supervision only; ``available_at`` is its final
    close plus the same release delay used by :func:`price_targets`.
    """
    clock=np.asarray(open_at,np.int64);close=np.asarray(close,float)
    anchor=np.asarray(anchor_at,np.int64)
    if (clock.ndim!=1 or close.shape!=clock.shape or anchor.ndim!=1 or not len(clock)
            or np.any(np.diff(clock)!=DAY_MS) or np.any(~np.isfinite(close)) or np.any(close<=0)
            or horizon<2 or release_delay<1):
        raise ValueError('invalid_slope_history_or_horizon')
    index=np.searchsorted(clock,anchor)
    if np.any(index>=len(clock)) or np.any(clock[index]!=anchor):raise ValueError('missing_anchor_price')
    future=index[:,None]+np.arange(1,horizon+1)[None,:]
    observed=np.all(future<len(clock),axis=1)
    values=np.full((len(index),horizon),np.nan)
    rows=np.flatnonzero(observed)
    values[rows]=close[future[rows]]
    x=np.arange(1,horizon+1,dtype=float)
    xc=x-x.mean();den=float(np.dot(xc,xc))
    slopes=np.full(len(index),np.nan)
    slopes[rows]=((values[rows]-values[rows].mean(1,keepdims=True))*xc).sum(1)/den
    return dict(slopes=slopes,up=slopes>0,valid=observed&(slopes!=0),observed=observed,
                reference_close=close[index],future_closes=values,
                available_at=anchor+(horizon+1)*DAY_MS-1+release_delay)


def long_profit_targets(open_at, market, decision_at, funding_time, funding_rate,
                        *, horizons=HORIZONS, fee=.0005, slippage=.0002):
    """Unit-notional long, entry next observable DAILY open, exit h days later.

    Assumed 5bp fee and 2bp adverse slippage EACH side. Actual funding rates,
    daily-open mark proxies; settlement in first minute precedes that day's
    orders (entry settlement excluded, exit settlement included). No fills,
    lot rounding, tick/spread/impact or liquidation are certified by this label.
    Funding is a realised target component, never an input feature.
    """
    clock=np.asarray(open_at,np.int64);bars=np.asarray(market,float)
    decision=np.asarray(decision_at,np.int64);ft=np.asarray(funding_time,np.int64)
    fr=np.asarray(funding_rate,float);h=np.asarray(horizons,np.int64)
    if (bars.shape!=(len(clock),9) or np.any(~np.isfinite(bars)) or np.any(bars[:,:4]<=0)
            or np.any(np.diff(clock)!=DAY_MS) or ft.ndim!=1 or fr.shape!=ft.shape or not len(ft)
            or np.any(np.diff(ft)<=0) or np.any(np.diff(ft)>8*3600000+60000)
            or np.any(~np.isfinite(fr)) or decision.ndim!=1 or h.ndim!=1 or not len(h)
            or np.any(h<2) or np.any(np.diff(h)<=0) or fee<0 or not 0<=slippage<1):
        raise ValueError('invalid_profit_target_history')
    entry_at=(decision//DAY_MS+1)*DAY_MS;exit_at=entry_at[:,None]+h[None,:]*DAY_MS
    entry=np.searchsorted(clock,entry_at);exit_index=np.searchsorted(clock,exit_at)
    observed=(entry[:,None]<len(clock))&(exit_index<len(clock))&(entry_at[:,None]>=ft[0])&(exit_at<=ft[-1])
    observed&=(entry_at[:,None]>=clock[0])&(exit_at>=clock[0])
    net=np.full(exit_at.shape,np.nan);funding=np.full_like(net,np.nan)
    # Prices at funding instants are unavailable as marks; daily open is an explicit proxy.
    in_history=(ft>=clock[0])&(ft<clock[-1]+DAY_MS)
    times=ft[in_history];rates=fr[in_history]
    day=(times-clock[0])//DAY_MS
    prefix=np.r_[0.,np.cumsum(rates*bars[day,0])]
    i,j=np.nonzero(observed)
    start=np.searchsorted(times,entry_at[i]+60000,side='right')
    end=np.searchsorted(times,exit_at[i,j]+60000,side='right')
    entry_price=bars[entry[i],0];exit_price=bars[exit_index[i,j],0]
    funding[i,j]=(prefix[end]-prefix[start])/entry_price
    buy=entry_price*(1+slippage);sell=exit_price*(1-slippage)
    net[i,j]=(sell-buy-fee*(buy+sell))/entry_price-funding[i,j]
    return dict(net_returns=net,profitable=net>0,valid=observed&(net!=0),observed=observed,
                entry_at=entry_at,exit_at=exit_at,available_at=exit_at+60001,
                funding_proxy_returns=funding)


def direction_patterns(above):
    """Descriptive sampled crossings of today's level, not joint probabilities.

    No sideways class: endpoint signs alone cannot establish price-path shape.
    """
    signs=np.asarray(above,bool)
    if signs.ndim!=2 or signs.shape[1]<2:raise ValueError('expected_ordered_horizon_signs')
    changes=np.sum(signs[:,1:]!=signs[:,:-1],axis=1)
    result=np.where(signs[:,-1],4,5)
    result[(changes==0)&signs[:,0]]=0;result[(changes==0)&~signs[:,0]]=1
    result[(changes==1)&signs[:,0]]=2;result[(changes==1)&~signs[:,0]]=3
    return result


def mature_split(decision_at, available_at, observed, cutoff, end):
    """All heads use the same fully matured past prefix, including near boundaries."""
    decision=np.asarray(decision_at);available=np.asarray(available_at)
    complete=np.asarray(observed).all(1)
    train=np.flatnonzero(complete&(decision<cutoff)&(available.max(1)<cutoff))
    test=np.flatnonzero(complete&(decision>=cutoff)&(decision<end))
    return train,test
