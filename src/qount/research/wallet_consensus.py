"""As-of position changes and distinct-address consensus for offline research."""
from decimal import Decimal

import numpy as np


def snapshot_anchored_states(reconstructed, positions, snapshot_ms):
    """Anchor known snapshot markets; withdraw each broken chain from its gap.

    A later fill's startPosition is never backfilled into an earlier snapshot.
    Unknown values remain unknown; later fills do not silently repair a gap.
    """
    out=[];failures=[]
    for coin,quantity in positions.items():
        expected=Decimal(str(quantity))
        out.append(dict(time_ms=snapshot_ms,coin=coin,before=str(expected),after=str(expected)))
        events=[(s['time_ms'],False,s) for s in reconstructed['states']
                if s['coin']==coin and s['time_ms']>snapshot_ms]
        events += [(e['time_ms'],True,e) for e in reconstructed['errors']
                   if e['coin']==coin and e['time_ms']>snapshot_ms]
        for stamp,error,row in sorted(events,key=lambda e:(e[0],not e[1])):
            if error or Decimal(row['before'])!=expected:
                failures.append(dict(coin=coin,time_ms=stamp,reason='unreconstructed_group' if error else 'snapshot_or_position_gap'))
                out.append(dict(time_ms=stamp,coin=coin,before=str(expected),after='nan'))
                break
            out.append(row);expected=Decimal(row['after'])
    return sorted(out,key=lambda s:(s['time_ms'],s['coin'])),failures


def persistent_asset_profile(states, *, start_ms, split_ms):
    """Discovery-only durations, including observed lower bounds of open runs.

    The first known position is never backfilled to the calendar start.
    Closed and censored intervals both end at or before the discovery cutoff.
    """
    rows=sorted((s for s in states if start_ms<=s["time_ms"]<split_ms),key=lambda s:s["time_ms"])
    if not rows:
        return dict(eligible=False,reason="no_discovery_position",observed_days=0.,long_exposure_share=0.)
    first=rows[0]["time_ms"];run_start=first;side=int(np.sign(float(rows[0]["after"])))
    intervals=[]
    for row in rows[1:]:
        direction=int(np.sign(float(row["after"])))
        if direction!=side:
            if side:intervals.append(row["time_ms"]-run_start)
            run_start,side=row["time_ms"],direction
    censored=split_ms-run_start if side else 0
    if censored:intervals.append(censored)
    total=sum(intervals)
    long_share=sum(d for d in intervals if d>=6*3_600_000)/total if total else 0.
    changes=sum(np.sign(float(s["before"]))!=np.sign(float(s["after"])) for s in rows)
    frequency=changes/((split_ms-start_ms)/86_400_000)
    age=(split_ms-first)/86_400_000
    eligible=age>=14 and long_share>=.5 and frequency<=1
    return dict(eligible=bool(eligible),observed_days=age,long_exposure_share=long_share,
                changes_per_day=frequency,observed_exposure_hours=total/3_600_000,
                right_censored_hours=censored/3_600_000,intervals=len(intervals),
                reason=None if eligible else "insufficient_age_persistence_or_high_frequency")


def position_votes(states, times, *, lookback_ms=86_400_000):
    """One address, one asset: new risk, holdings, and valid lookback masks.

    A buy closing a short is not new long risk. Missing earlier position is
    unknown, never zero. Magnitude is deliberately not pooled across wallets.
    """
    times=np.asarray(times,np.int64)
    if not states:
        return np.zeros(len(times),int),np.zeros(len(times),int),np.zeros(len(times),bool)
    rows=sorted(states,key=lambda s:s["time_ms"])
    stamps=np.asarray([s["time_ms"] for s in rows],np.int64)
    quantity=np.asarray([float(s["after"]) for s in rows])
    now=np.searchsorted(stamps,times,side="right")-1
    past=np.searchsorted(stamps,times-lookback_ms,side="right")-1
    current=quantity[np.maximum(now,0)]
    previous=quantity[np.maximum(past,0)]
    valid=(now>=0)&(past>=0)&np.isfinite(current)&np.isfinite(previous)
    delta=current-previous
    tolerance=1e-10*np.maximum(1,np.maximum(np.abs(current),np.abs(previous)))
    additions=valid&(current*delta>0)&(np.abs(delta)>tolerance)
    votes=np.where(additions,np.sign(current),0).astype(int)
    holdings=np.where((now>=0)&np.isfinite(current),np.sign(current),0).astype(int)
    return votes,holdings,valid


def consensus(votes, *, minimum=2):
    """At least two distinct addresses and a strict majority over opposition."""
    votes=np.asarray(votes,int)
    if votes.ndim!=2:
        raise ValueError("address_by_time_matrix_required")
    positive=np.sum(votes>0,axis=0)
    negative=np.sum(votes<0,axis=0)
    target=np.where((positive>=minimum)&(positive>negative),1,
                    np.where((negative>=minimum)&(negative>positive),-1,0))
    return target,positive,negative


def target_signals(times, target):
    """Emit only causal target changes, including an initial flat target."""
    out=[];previous=None
    for stamp,direction in zip(times,target):
        if int(direction)!=previous:
            out.append(dict(time_ms=int(stamp),target=int(direction),reason="address_consensus"))
            previous=int(direction)
    return out


def relative_addition_targets(positive, negative):
    """Long unique strongest vote balance, short unique weakest; ties abstain.

    This ranks assets at each observation, with no future normalization.
    Equal entry notional is not a certification of beta-neutral exposure.
    """
    positive=np.asarray(positive,float);negative=np.asarray(negative,float)
    assert positive.shape==negative.shape and positive.ndim==2
    assert np.all(np.isfinite(positive)) and np.all(np.isfinite(negative))
    assert np.all(positive>=0) and np.all(negative>=0)
    total=positive+negative
    score=np.divide(positive-negative,total,out=np.zeros_like(total),where=total>0)
    targets=np.zeros_like(score,dtype=int)
    for t in range(score.shape[1]):
        if np.any(total[:,t]==0):continue
        top=np.flatnonzero(score[:,t]==score[:,t].max())
        bottom=np.flatnonzero(score[:,t]==score[:,t].min())
        if len(top)==len(bottom)==1 and top[0]!=bottom[0]:
            targets[top[0],t]=1;targets[bottom[0],t]=-1
    return targets,score


def vote_policies(votes,holdings):
    votes=np.asarray(votes,int);holdings=np.asarray(holdings,int)
    new,pos,neg=consensus(votes)
    held,_,_=consensus(holdings)
    one,_,_=consensus(votes,minimum=1)
    supported=np.where(((held==1)&(pos>0))|((held==-1)&(neg>0)),held,0)
    return dict(newrisk_min2=new,position_min2=held,any_newrisk=one,
                addition_supported_by_holdings=supported,
                initial_position_consensus=np.full(len(held),held[0]),
                reverse_newrisk=-new,buyhold=np.ones(len(held),int))
