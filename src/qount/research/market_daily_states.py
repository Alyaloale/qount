"""Canonical per-day state labels and variable-length, state-pure chunks.

The labeler is supplied by the caller. Sequence length never defines a state,
changes a daily label, pads a state across a boundary or closes a censored spell.
"""
from __future__ import annotations

import numpy as np

LOCAL_STATES = ('uptrend', 'downtrend', 'rotation', 'compression', 'low_efficiency_chop')


def summarize_state_probabilities(probabilities, *, threshold=.70):
    """Presentation only: uncertain forecasts never become a training class.

    The model's probability vector is preserved. The existing 70% research
    threshold is a configurable display convention, not a calibration claim.
    """
    if set(probabilities)!=set(LOCAL_STATES) or not 0<=threshold<=1:
        raise ValueError('daily_state_incompatible_probability_schema')
    values=np.array([probabilities[name] for name in LOCAL_STATES],float)
    if np.any(~np.isfinite(values)) or np.any(values<0) or not np.isclose(values.sum(),1.):
        raise ValueError('daily_state_invalid_probabilities')
    order=np.argsort(values);first=int(order[-1]);second=int(order[-2])
    confident=bool(values[first]>=threshold and values[first]>values[second]+1e-12)
    return dict(status='confident' if confident else 'uncertain',
                predicted_state=LOCAL_STATES[first] if confident else None,
                top_state=LOCAL_STATES[first],top_probability=float(values[first]),
                top_two_margin=float(values[first]-values[second]),threshold=threshold)


def centered_daily_state(bars, k, n):
    """Retrospective label from n bars through k plus n future bars: 2n total.

    Inclusive [k-n+1,k+n]. Requires future confirmation at k+n. The weighted
    local price slope describes the center day, not a majority label copied
    over the entire window. This output must never be a current-time feature.
    """
    if n<3 or not 0<=k<len(bars):
        raise ValueError('centered_daily_invalid_index')
    if k<n-1 or k+n>=len(bars):
        return dict(state=-1,features=None,first_index=None,last_index=None,mature_index=None)
    start=k-n+1;stop=k+n+1;window=bars[start:stop]
    evidence=centered_window_evidence(window,n-1,n)
    return dict(evidence,first_index=start,last_index=stop-1,mature_index=k+n,window_bars=2*n,half_life=n/3)


def centered_window_evidence(window, center_index, n, *, slope_threshold=.5,
                             efficiency_threshold=.10, compression_threshold=.65,
                             half_life_factor=1/3):
    """Describe a point using only the supplied window, including near edges.

    Boundary experiments may move the weighting center inside one *fixed*
    2n window. They do not read neighboring labels whose future clocks would
    extend beyond this window.
    """
    if (n<3 or len(window)!=2*n or not 0<=center_index<len(window)
            or slope_threshold<=0 or efficiency_threshold<0
            or compression_threshold<=0 or half_life_factor<=0):
        raise ValueError('centered_window_shape')
    t=np.arange(len(window),dtype=float)-center_index
    weights=np.exp2(-np.abs(t)/max(n*half_life_factor,1.));weights/=weights.sum()
    log_price=np.log([b.c for b in window])
    center=float(weights@t);mean=float(weights@log_price)
    slope=float(weights@((t-center)*(log_price-mean)))/float(weights@((t-center)**2))
    returns=np.diff(log_price)
    rw=(weights[:-1]+weights[1:])/2;rw/=rw.sum()
    volatility=float(np.sqrt(rw@((returns-float(rw@returns))**2)))
    true_ranges=np.array([max(np.log(b.h/b.l),abs(np.log(b.h/a.c)),abs(np.log(b.l/a.c)))
                          for a,b in zip(window[:-1],window[1:])])
    score=slope*np.sqrt(n)/max(volatility,1e-10)
    efficiency=abs(slope)/max(float(rw@true_ranges),1e-12)
    near=np.abs((t[:-1]+t[1:])/2)<=max(1,n/3)
    range_ratio=float(np.mean(true_ranges[near]))/max(float(np.mean(true_ranges[~near])),1e-12)
    signs=np.sign(log_price-mean);signs=signs[signs!=0]
    crossings=int(np.sum(signs[1:]!=signs[:-1]))
    if score>=slope_threshold and efficiency>=efficiency_threshold:state='uptrend'
    elif score<=-slope_threshold and efficiency>=efficiency_threshold:state='downtrend'
    elif range_ratio<=compression_threshold:state='compression'
    # Insufficient directional progress relative to daily ranges is observed
    # chop, even when its fitted slope tilts one way. Resolve by the actual
    # two-sided crossings, never by an epistemic "transition/uncertain" class.
    elif crossings>=2:state='rotation'
    else:state='low_efficiency_chop'
    return dict(state=LOCAL_STATES.index(state),features=[score,efficiency,range_ratio,crossings,volatility,slope])


def local_daily_state(bars, k, n):
    """Owner's literal inclusive [k-n-1, k] window with recency weighting.

    No earlier volatility, EMA, label or future bar is read. The n+2 closes
    supply n+1 local returns. Fixed half-life n/3 is an exploratory setting,
    not an empirically selected optimum. n is also the next-period offset.
    """
    if n < 3 or not 0 <= k < len(bars):
        raise ValueError('local_daily_invalid_index')
    if k < n+1:
        return dict(state=-1, features=None, first_index=None, last_index=k)
    window=bars[k-n-1:k+1]
    closes=np.array([b.c for b in window],float)
    returns=np.diff(np.log(closes))
    weights=np.exp2(-np.arange(len(returns)-1,-1,-1)/max(n/3,1.))
    weights/=weights.sum()
    true_ranges=np.array([max(np.log(b.h/b.l),abs(np.log(b.h/a.c)),abs(np.log(b.l/a.c)))
                          for a,b in zip(window[:-1],window[1:])])
    drift=float(weights@returns)
    directional_score=drift/max(float(weights@np.abs(returns)),1e-12)
    efficiency=abs(drift)/max(float(weights@true_ranges),1e-12)
    recent=max(1,n//3)
    range_ratio=float(np.mean(true_ranges[-recent:]))/max(float(np.mean(true_ranges[:-recent])),1e-12)
    center=float(np.r_[weights[0],weights]@closes/np.r_[weights[0],weights].sum())
    signs=np.sign(closes-center);signs=signs[signs!=0]
    crossings=int(np.sum(signs[1:]!=signs[:-1]))
    if directional_score>=.35 and efficiency>=.15:
        state='uptrend'
    elif directional_score<=-.35 and efficiency>=.15:
        state='downtrend'
    elif range_ratio<=.65:
        state='compression'
    elif crossings>=2:
        state='rotation'
    else:
        state='low_efficiency_chop'
    return dict(state=LOCAL_STATES.index(state),first_index=k-n-1,last_index=k,
        features=[directional_score,efficiency,min(range_ratio,10.),crossings,
                  float(np.sqrt(weights@((returns-drift)**2))),drift],
        half_life=n/3,window_bars=n+2)


def daily_targets(asset, states, available_at, *, maximum=30):
    """Link each observation to the actual next daily labels of the SAME asset.

    Every future day has its own maturity and mask. A five-day window may
    contain three down labels followed by two up labels; it is never reduced
    to a single majority class. No end-of-cache label is invented.
    """
    if maximum < 1 or len(asset) != len(states) or len(states) != len(available_at):
        raise ValueError('daily_state_shape')
    n = len(asset)
    targets = np.full((n, maximum), -1, np.int16)
    future_rows = np.full((n, maximum), -1, np.int64)
    maturity = np.zeros((n, maximum), np.int64)
    for name in sorted(set(asset)):
        indices = np.flatnonzero(asset == name)
        valid_indices=indices[states[indices]>=0]
        if np.any(np.diff(available_at[valid_indices]) <= 0):
            raise ValueError('daily_state_unordered_asset')
        for horizon in range(1, maximum+1):
            if horizon >= len(indices):
                break
            source = indices[:-horizon]; destination = indices[horizon:]
            valid = states[destination] >= 0
            source = source[valid]; destination = destination[valid]
            targets[source, horizon-1] = states[destination]
            future_rows[source, horizon-1] = destination
            maturity[source, horizon-1] = available_at[destination]
    return dict(future_state=targets, future_row=future_rows,
                future_available_at=maturity, future_mask=targets >= 0)


def state_chunks(asset, states, available_at, *, maximum=5):
    """Nonoverlapping storage chunks, at most maximum days, within real spells.

    Short completed spells are kept as-is. Residual chunks at cache end are
    explicitly censored. A short chunk's termination becomes known only when
    the next differently-labeled day arrives; full chunks need no such peek.
    IDs are shared by chunks from one spell, so 10 up days are not two episodes.
    """
    if maximum < 1 or len(asset) != len(states) or len(states) != len(available_at):
        raise ValueError('daily_state_shape')
    chunks = []; spells = []
    for name in sorted(set(asset)):
        indices = np.flatnonzero(asset == name)
        valid_indices=indices[states[indices]>=0]
        if np.any(np.diff(available_at[valid_indices]) <= 0):
            raise ValueError('daily_state_unordered_asset')
        start = 0
        for end in range(1, len(indices)+1):
            if end < len(indices) and states[indices[end]] == states[indices[start]]:
                continue
            members = indices[start:end]; state = int(states[members[0]])
            if state < 0:
                start = end
                continue
            censored = end == len(indices) or states[indices[end]] < 0
            spell_id = len(spells)
            completed_at = None if censored else int(available_at[indices[end]])
            spells.append(dict(id=spell_id, asset=str(name), state=state,
                first_row=int(members[0]), last_row=int(members[-1]), length=len(members),
                right_censored=bool(censored), completed_at=completed_at))
            for offset in range(0, len(members), maximum):
                selected = members[offset:offset+maximum]
                partial = len(selected) < maximum
                chunk_maturity = (completed_at if partial and not censored
                                  else int(available_at[selected[-1]]))
                chunks.append(dict(asset=str(name), spell_id=spell_id, state=state,
                    rows=selected.tolist(), length=len(selected),
                    available_at=chunk_maturity, short=partial,
                    short_right_censored=bool(partial and censored)))
            start = end
    return spells, chunks


def training_mask(targets, cutoff, *, horizon):
    """Per-target loss mask: only labels actually available before a fold.

    Training can use the first three known days of a longer requested sequence
    without teaching the model fabricated fourth/fifth days.
    """
    if not 1 <= horizon <= targets['future_state'].shape[1]:
        raise ValueError('daily_state_invalid_horizon')
    return targets['future_mask'][:, :horizon] & (targets['future_available_at'][:, :horizon] < cutoff)
