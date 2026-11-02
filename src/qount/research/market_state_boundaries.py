"""Bounded offline boundary refinement, never a production trading signal.

All local checks use the original [k-n+1,k+n] raw window. Final labels retain
their k+n maturity; no global smoothing or recursive neighbor-label merging
is allowed. Duration alone is never evidence that a price move is noise.
"""
from __future__ import annotations

import numpy as np

from qount.research.market_daily_states import centered_window_evidence


def swing_pivots(log_closes, minimum_move):
    """Price extrema confirmed by a reversal of minimum_move, close prices only.

    A leg owns (left pivot, right pivot], so the peak/trough day closes the
    preceding leg. The next daily return starts the new leg. The last active
    leg has an unconfirmed endpoint and is explicitly marked as such.
    """
    values=np.asarray(log_closes,float)
    if len(values)<2 or minimum_move<=0:
        raise ValueError('boundary_invalid_swing')
    low=high=0;direction=0;pivots=[]
    for i in range(1,len(values)):
        if direction==0:
            if values[i]<values[low]:low=i
            if values[i]>values[high]:high=i
            if values[i]-values[low]>=minimum_move:
                pivots.append(low);high=i;direction=1
            elif values[high]-values[i]>=minimum_move:
                pivots.append(high);low=i;direction=-1
        elif direction==1:
            if values[i]>=values[high]:high=i
            elif values[high]-values[i]>=minimum_move:
                pivots.append(high);low=i;direction=-1
        else:
            if values[i]<=values[low]:low=i
            elif values[i]-values[low]>=minimum_move:
                pivots.append(low);high=i;direction=1
    legs=[]
    for a,b in zip(pivots[:-1],pivots[1:]):
        legs.append(dict(start=a,end=b,side=1 if values[b]>values[a] else -1,
                         endpoint_confirmed=True,extreme=b))
    if pivots and pivots[-1]<len(values)-1:
        legs.append(dict(start=pivots[-1],end=len(values)-1,side=direction,
                         endpoint_confirmed=False,extreme=high if direction==1 else low))
    return pivots,legs


def window_refinement(window,n,*,radius=3,swing_atr=1.5,strong_atr=2.,minimum_efficiency=.55,
                      evidence_parameters=None):
    """Return independent conservative noise and price-boundary candidates."""
    if len(window)!=2*n or n<5 or not 1<=radius<n-1:
        raise ValueError('boundary_invalid_window')
    center=n-1
    kwargs=evidence_parameters or {}
    point=centered_window_evidence(window,center,n,**kwargs)
    base=point['state'];score,efficiency,ratio,*_=point['features']
    closes=np.log([b.c for b in window])
    ranges=np.array([max(np.log(b.h/b.l),abs(np.log(b.h/a.c)),abs(np.log(b.l/a.c)))
                     for a,b in zip(window[:-1],window[1:])])
    atr=max(float(np.median(ranges)),1e-10)
    offsets=range(-radius,radius+1)
    evidence=[centered_window_evidence(window,center+d,n,**kwargs) for d in offsets]
    labels=[e['state'] for e in evidence]
    left=right=radius
    while left>0 and labels[left-1]==base:left-=1
    while right<len(labels)-1 and labels[right+1]==base:right+=1
    island_length=right-left+1
    noise=base;reason=None
    # A small temporary compression/rotation switch near the existing cutoff
    # is eligible. Short up/down legs are never removed by this noise filter.
    if base==3 and left>0 and right<len(labels)-1 and island_length<=2:
        surrounding=labels[left-1]
        if surrounding==labels[right+1] and surrounding in (2,4):
            a=center+left-radius;b=center+right-radius
            excursion=float(np.max(np.abs(closes[a:b+1]-closes[a-1])))/atr
            marginal_compression=.55<=ratio<=.65
            if excursion<1. and marginal_compression:
                noise=surrounding;reason='small_marginal_nondirectional_island'
    boundary=base;leg_info=None
    pivots,legs=swing_pivots(closes,swing_atr*atr)
    for leg in legs:
        a=leg['start'];b=leg['end']
        if not a<center<=b:continue
        extremum=leg['extreme']
        displacement=abs(float(closes[extremum]-closes[a]))
        path=float(np.abs(np.diff(closes[a:extremum+1])).sum())
        leg_info=dict(**leg,amplitude_atr=displacement/atr,
                      efficiency=displacement/max(path,1e-12))
        near_boundary=(center-a<=radius or (leg['endpoint_confirmed'] and b-center<=radius))
        # A clear, large leg can own nearby reversal days; quiet contraction
        # is left for its own shape-based treatment, not overwritten by drift.
        if base!=3 and near_boundary and leg_info['amplitude_atr']>=strong_atr and leg_info['efficiency']>=minimum_efficiency:
            boundary=0 if leg['side']==1 else 1
        break
    combined=boundary if boundary!=base else noise
    supported=base
    if boundary!=base:
        # A price pivot alone must not invent a new trend inside a range.
        # Require three consecutive same-window evidence points supporting
        # that trend, then extend only within two days of this existing core.
        core=[]
        for i in range(len(labels)-2):
            if labels[i:i+3]==[boundary]*3:core.extend(range(i,i+3))
        close_core=bool(core and min(abs(i-radius) for i in core)<=2)
        current_strong_shock=abs(closes[center]-closes[center-1])>=2*atr
        same_shock_direction=(closes[center]-closes[center-1])*(1 if boundary==0 else -1)>0
        if close_core and (base not in (0,1) or (current_strong_shock and same_shock_direction)):
            supported=boundary
    conservative=supported if supported!=base else noise
    pair_boundary=base
    switches=np.flatnonzero(np.diff(labels)!=0)+1
    if len(switches)==1:
        cut=int(switches[0]);a=labels[0];b=labels[-1]
        # Relocate an existing A|B edge, not add a third regime or an island.
        # Both sides must have a core within this same fixed raw window.
        if cut>=3 and len(labels)-cut>=3 and (a in (0,1) or b in (0,1)):
            is_peak=a==0 or b==1
            is_trough=a==1 or b==0
            if is_peak!=is_trough:
                left=center-2;right=center+3
                pivot=left+int(np.argmax(closes[left:right]) if is_peak else np.argmin(closes[left:right]))
                # An interior extremum needs meaningful movement on both
                # sides. Flat pauses do not get forced onto a price pivot.
                if left<pivot<right-1:
                    before=closes[center-radius:pivot+1]
                    after=closes[pivot:center+radius+1]
                    enter=(closes[pivot]-float(np.min(before))) if is_peak else (float(np.max(before))-closes[pivot])
                    leave=(closes[pivot]-float(np.min(after))) if is_peak else (float(np.max(after))-closes[pivot])
                    if enter>=atr and leave>=atr:
                        pair_boundary=a if center<=pivot else b
    pair_combined=pair_boundary if pair_boundary!=base else noise
    return dict(baseline=base,noise_only=noise,boundary_only=boundary,combined=combined,
                supported_boundary=supported,conservative_combined=conservative,
                pair_boundary=pair_boundary,pair_combined=pair_combined,
                noise_reason=reason,boundary_changed=boundary!=base,
                bounded_run_length=island_length,local_atr_log=atr,leg=leg_info,
                pivot_indices=pivots)
