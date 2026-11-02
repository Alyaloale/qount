"""Three directional states plus independent realized-path attributes.

Labels use the same centered 2n window as the five-class contrast. Model
inputs use completed past bars only. Attribute independence means separate
outputs, not a claim of statistical independence from price direction.
"""
from __future__ import annotations

import numpy as np

from qount.research.market_daily_states import centered_window_evidence

MAIN_STATES=('upward','downward','sideways')
ATTRIBUTE_NAMES=('compression_ratio','is_compression','volatility_daily','path_efficiency')
INPUT_NAMES=('direction_score','slope_range_efficiency','local_range_ratio','mean_crossings',
             'volatility_daily','weighted_drift','path_efficiency','return1_sigma',
             'return3_sigma','return_n_sigma','range_position','candle_body_fraction')


def merge_five(values):
    values=np.asarray(values)
    if np.any((values < -1)|(values > 4)):
        raise ValueError('factorization_invalid_five_class')
    return np.where(values<0,-1,np.where(values<2,values,2)).astype(np.int16)


def project_five_probabilities(probabilities):
    values=np.asarray(probabilities,float)
    if (values.ndim!=2 or values.shape[1]!=5 or np.any(~np.isfinite(values))
            or np.any(values<0) or not np.allclose(values.sum(1),1)):
        raise ValueError('factorization_invalid_probabilities')
    return np.c_[values[:,:2],values[:,2:].sum(1)]


def path_efficiency(window):
    log=np.log([bar.c for bar in window])
    travel=float(np.abs(np.diff(log)).sum())
    return abs(float(log[-1]-log[0]))/max(travel,1e-12)


def factored_window(window,n,*,slope_threshold=.5,efficiency_threshold=.10,
                    compression_threshold=.65,half_life_factor=1/3):
    """Main direction is not gated by compression or path efficiency.

    efficiency_threshold is accepted as a contrast parameter but intentionally
    does not change the directional class. The measured efficiency remains
    available as a continuous independent attribute.
    """
    evidence=centered_window_evidence(window,n-1,n,slope_threshold=slope_threshold,
        efficiency_threshold=efficiency_threshold,compression_threshold=compression_threshold,
        half_life_factor=half_life_factor)
    score,_,ratio,_,volatility,_=evidence['features']
    state=0 if score>=slope_threshold else 1 if score<=-slope_threshold else 2
    return dict(state=state,attributes=np.array([ratio,float(ratio<=compression_threshold),
                volatility,path_efficiency(window)],float))


def causal_inputs(bars,k,n):
    """Same past 2n OHLC observations for all candidate label architectures."""
    if k<2*n-1:return None
    window=bars[k-2*n+1:k+1]
    evidence=centered_window_evidence(window,len(window)-1,n)['features']
    closes=np.log([b.c for b in window]);sigma=max(evidence[4],1e-8)
    high=max(b.h for b in window);low=min(b.l for b in window);last=window[-1]
    return np.array([*evidence,path_efficiency(window),
        (closes[-1]-closes[-2])/sigma,
        (closes[-1]-closes[-4])/(sigma*np.sqrt(3)),
        (closes[-1]-closes[-1-n])/(sigma*np.sqrt(n)),
        (last.c-low)/max(high-low,1e-12),
        (last.c-last.o)/max(last.h-last.l,1e-12)],float)


def purged_quarter(rows, known_at, maturity, cutoff, end):
    """No overlapping test folds and no unconfirmed target in a training fold."""
    rows=np.asarray(rows,int)
    train=rows[maturity[rows]<cutoff]
    test=rows[(known_at[rows]>=cutoff)&(known_at[rows]<end)]
    if np.any(known_at[train]>=cutoff):raise ValueError('factorization_future_training_input')
    return train,test
