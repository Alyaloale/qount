"""Future-state probability vectors and cost-aware action scores, offline only."""
from __future__ import annotations

from collections import defaultdict

import numpy as np

from qount.research.market_model_profit import bracket_exit,execution_price
from qount.research.market_stages import ACTION_STATES


STATE_NAMES=ACTION_STATES+('shock','unknown')
ACTIONS=('trend_long','trend_short','range_fade')
FEATURES=('ema20_distance_atr','ema50_distance_atr','ema200_distance_atr','momentum5_sigma',
    'momentum20_sigma','efficiency20','relative_volatility','volatility_change5','ema50_slope5_atr',
    'range_position','action_age','event_age','return1_sigma','benchmark_direction',
    'benchmark_efficiency','relative_momentum20_sigma','turnover_relative20_126','funding_rate7d')


def state_code(name):return STATE_NAMES.index(str(name).split(':')[0])


def state_feature_matrix(parent,indices,assets):
    """Known features only; never read outcome or maturity arrays at inference."""
    indices=np.atleast_1d(indices).astype(int);names=list(parent['feature_names']);cols=[names.index(n) for n in FEATURES]
    values=parent['X'][indices][:,cols].astype(float)
    if np.any(parent['feature_available_at'][indices][:,cols]>parent['known_at'][indices,None]):
        raise ValueError('state_score_future_feature')
    current=[state_code(parent['state'][i]) for i in indices]
    identity=[list(assets).index(str(parent['asset'][i])) for i in indices]
    return np.c_[np.nan_to_num(values,nan=0),np.isnan(values),np.eye(len(STATE_NAMES))[current],np.eye(len(assets))[identity]]


def unit_payoff(bars,entry_index,decision,events,rules):
    """One-unit counterfactual, same bracket/cost assumptions as portfolio replay.

    Returns a no-fill zero when a delayed entry fails the fixed geometry check;
    these outcomes stay in training. No lot/capital screen in this economic
    label; actual portfolio replay separately enforces lots/capacity and risk.
    All outcomes wait until the entire horizon candle is available, even if a
    stop happened earlier. Event tuples are (timestamp_ms, rate*settlement_mark).
    """
    end_index=entry_index+int(decision['max_bars'])
    if end_index>=len(bars):return None
    start=int(bars[entry_index,0]);end=int(bars[end_index,6]);side=decision['side']
    fee=rules['fee'];slip=rules['slippage'];tick=rules['tick']
    entry=execution_price(float(bars[entry_index,1]),side,opening=True,slippage=slip,tick=tick)
    stop=decision['stop'];target=decision.get('target')
    valid=side*(float(bars[entry_index,1])-stop)>0 and side*(entry-stop)>0
    if target is not None:
        valid&=side*(target-entry)>0 and side*(target-entry)/entry>=8*(fee+slip)
    if not valid:return dict(net_return=0.,net_unit=0.,filled=False,exit_at=start,available_at=end+60001,reason='no_fill')
    stamps,values=events;funding=0.
    for j in range(entry_index,end_index+1):
        b=bars[j];t=int(b[0]);close=int(b[6]);at_open=j==end_index
        reference,reason=(float(b[1]),'horizon') if at_open else bracket_exit(b,side,stop,target)
        left=int(np.searchsorted(stamps,max(start+1,t),side='left'))
        right=int(np.searchsorted(stamps,t if at_open else close,side='right'))
        for stamp,value in zip(stamps[left:right],values[left:right]):
            payment=-side*float(value)
            if reference is None or stamp==t or payment<0:funding+=payment
        if reference is not None:
            exit_=execution_price(reference,side,opening=False,slippage=slip,tick=tick)
            net=side*(exit_-entry)-fee*(entry+exit_)+funding
            return dict(net_return=net/entry,net_unit=net,filled=True,exit_at=t if at_open else close,
                        available_at=end+60001,reason=reason)
    raise ValueError('score_missing_exit')


def payoff_table(states,returns,clocks,*,classes=len(STATE_NAMES),shrink_dates=50.):
    """Conditional net R by future state/action, shrunk using date counts.

    Date means prevent same-day correlated assets/actions from counting as
    independent evidence. The error penalty is a heuristic, not a certified
    confidence bound; probabilities also have model uncertainty.
    """
    states=np.asarray(states,int);returns=np.asarray(returns,float);clocks=np.asarray(clocks)
    means=np.zeros((classes,returns.shape[1]));errors=np.ones_like(means)
    counts=np.zeros_like(means,dtype=int)
    for a in range(returns.shape[1]):
        valid=np.isfinite(returns[:,a]);all_dates=defaultdict(list)
        for v,t in zip(returns[valid,a],clocks[valid]):all_dates[int(t)].append(float(v))
        all_values=np.array([np.mean(v) for v in all_dates.values()])
        if not len(all_values):continue
        prior=float(all_values.sum()/(len(all_values)+shrink_dates))
        typical=float(np.std(all_values,ddof=1)) if len(all_values)>1 else 1.
        for s in range(classes):
            dates=defaultdict(list);mask=valid&(states==s)
            for v,t in zip(returns[mask,a],clocks[mask]):dates[int(t)].append(float(v))
            values=np.array([np.mean(v) for v in dates.values()]);n=len(values);counts[s,a]=n
            means[s,a]=(values.sum()+shrink_dates*prior)/(n+shrink_dates)
            errors[s,a]=(max(float(np.std(values,ddof=1)),typical*.25)/np.sqrt(n) if n>=10 else typical)
    return dict(mean=means,error=errors,date_counts=counts)


def action_scores(probabilities,table,*,penalty=1.):
    p=np.asarray(probabilities,float)
    if p.ndim!=2 or p.shape[1]!=len(STATE_NAMES) or np.any(p<0) or not np.allclose(p.sum(1),1):
        raise ValueError('score_invalid_state_probabilities')
    expected=p@table['mean'];uncertainty=p@table['error']
    return expected,expected-penalty*uncertainty


def action_probability_scores(probabilities):
    """0--100 state scores aggregated into explicitly defined strategy groups.

    Failed downside breaks support a bullish reversal hypothesis, and vice
    versa. This grouping is an economic hypothesis, not a probability of profit.
    Shock/transition/unknown contribute to none of the three entry groups.
    """
    p=np.asarray(probabilities,float)
    if p.ndim!=2 or p.shape[1]!=len(STATE_NAMES) or not np.allclose(p.sum(1),1) or np.any(p<0):
        raise ValueError('score_invalid_state_probabilities')
    groups=(('up_trend','up_breakout','failed_down_breakout'),
            ('down_trend','down_breakout','failed_up_breakout'),('compression','range','wide_range'))
    return np.stack([100*p[:,[STATE_NAMES.index(s) for s in group]].sum(1) for group in groups],axis=1)


def past_score_threshold(scores,known_at,cutoff,*,floor=.10,quantile=.90,minimum=30):
    """A fixed high-score policy: at least .10 net R and past top decile.

    No future outcomes or score distributions enter this threshold. One best
    action score per asset decision, date-balanced distribution across assets.
    """
    scores=np.asarray(scores,float);known_at=np.asarray(known_at)
    mask=(known_at<cutoff)&np.isfinite(scores)
    if len(np.unique(known_at[mask]))<minimum:return float('inf')
    clocks,counts=np.unique(known_at[mask],return_counts=True);weights=1/counts[np.searchsorted(clocks,known_at[mask])]
    values=scores[mask];order=np.argsort(values);cumulative=np.cumsum(weights[order]);index=np.searchsorted(cumulative,quantile*cumulative[-1])
    return max(floor,float(values[order[min(index,len(order)-1)]]))
