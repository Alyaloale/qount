"""Small probability calibration fitted only on matured historical forecasts."""
from __future__ import annotations

import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp


def identity_calibration(classes):
    return dict(temperature=1.,bias=[0.]*classes,rows=0,classes=classes)


def apply_calibration(probability,calibration):
    probability=np.asarray(probability,float);bias=np.asarray(calibration['bias'],float)
    temperature=float(calibration['temperature'])
    if (probability.ndim!=2 or probability.shape[1]!=len(bias) or not np.isfinite(probability).all()
            or np.any(probability<0) or not np.allclose(probability.sum(1),1,atol=1e-5)
            or not np.isfinite(bias).all() or not np.isfinite(temperature) or temperature<=0):
        raise ValueError('invalid_calibration_input')
    logits=np.log(np.maximum(probability,1e-8))/temperature+bias
    return np.exp(logits-logsumexp(logits,axis=1)[:,None])


def fit_calibration(probability,actual):
    probability=np.asarray(probability,float);actual=np.asarray(actual)
    if probability.ndim!=2 or len(actual)!=len(probability) or actual.dtype.kind not in 'iu':raise ValueError('invalid_calibration_targets')
    classes=probability.shape[1];initial=identity_calibration(classes)
    apply_calibration(probability,initial)
    if np.any(actual<0) or np.any(actual>=classes):raise ValueError('calibration_class_out_of_range')
    if len(actual)<200 or np.any(np.bincount(actual,minlength=classes)<5):return initial
    logp=np.log(np.maximum(probability,1e-8))
    def objective(params):
        logits=logp/np.exp(params[0])+np.r_[params[1:],0]
        loss=np.mean(logsumexp(logits,axis=1)-logits[np.arange(len(actual)),actual])
        return loss+.01*np.sum(params**2)
    fitted=minimize(objective,np.zeros(classes),method='L-BFGS-B',bounds=[(-.7,.7)]+[(-1.5,1.5)]*(classes-1))
    if not fitted.success or not np.isfinite(fitted.fun):return initial
    return dict(temperature=float(np.exp(fitted.x[0])),bias=np.r_[fitted.x[1:],0].tolist(),
        rows=len(actual),classes=classes,penalty=.01)


def mature_calibration_rows(decision,available,probability,cutoff,*,history_days=365):
    """Only earlier forecasts whose answers have matured before this cutoff."""
    decision=np.asarray(decision);available=np.asarray(available);probability=np.asarray(probability)
    if decision.shape!=available.shape or probability.ndim!=2 or len(probability)!=len(decision):raise ValueError('invalid_calibration_clocks')
    return np.flatnonzero((decision<cutoff)&(available<cutoff)&(decision>=cutoff-history_days*86400000)&np.isfinite(probability).all(1))
