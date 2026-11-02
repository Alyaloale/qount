"""Small geometric-offset models and source-level negative controls."""
from __future__ import annotations

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit,logit
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler


COMPACT_FEATURES=(
    'lower_boundary_distance_sigma20','upper_boundary_distance_sigma20',
    'efficiency20','relative_volatility','volatility_change5',
    'momentum5_sigma','return1_sigma','intraday_range_atr',
)
OFFSET_FEATURES=('efficiency20','relative_volatility','volatility_change5','return1_sigma')


def fit_geometry_offset(values,outcomes,geometry,*,penalty=20.,sample_weight=None):
    """p=sigmoid(logit(geometry)+intercept+standardized risk features @ beta).

    All coefficients including the intercept have an L2 prior at zero. The
    geometric forecast is thus the explicit starting point. This models a
    residual correction; it is not refitting boundary geometry from scratch.
    Callers must supply mature training targets only.
    """
    values=np.asarray(values,float);outcomes=np.asarray(outcomes)
    geometry=np.asarray(geometry,float)
    if values.ndim!=2 or outcomes.ndim!=1 or not len(values) or len(values)!=len(outcomes) or geometry.shape!=outcomes.shape:
        raise ValueError('offset_training_shape')
    if np.any(~np.isin(outcomes,[0,1])) or np.any(~np.isfinite(geometry)) or np.any((geometry<=0)|(geometry>=1)):
        raise ValueError('offset_invalid_target_or_geometry')
    outcomes=outcomes.astype(int)
    if not np.isfinite(penalty) or penalty<=0:raise ValueError('offset_positive_penalty_required')
    weight=np.ones(len(values)) if sample_weight is None else np.asarray(sample_weight,float)
    if weight.shape!=(len(values),) or np.any(~np.isfinite(weight)) or np.any(weight<=0):
        raise ValueError('offset_invalid_sample_weight')
    weight=weight/weight.mean()  # Keep the L2 scale comparable; no implicit parameter search.
    imputer=scaler=None
    if values.shape[1]:
        imputer=SimpleImputer(strategy='median',keep_empty_features=True).fit(values)
        scaler=StandardScaler().fit(imputer.transform(values),sample_weight=None if sample_weight is None else weight)
        design=np.c_[np.ones(len(values)),scaler.transform(imputer.transform(values))]
    else:design=np.ones((len(values),1))
    offset=logit(geometry)
    def objective(beta):
        logits=offset+design@beta
        loss=np.sum(weight*(np.logaddexp(0,logits)-outcomes*logits))+penalty/2*(beta@beta)
        gradient=design.T@(weight*(expit(logits)-outcomes))+penalty*beta
        return float(loss),gradient
    result=minimize(objective,np.zeros(design.shape[1]),method='L-BFGS-B',jac=True,
                    options=dict(maxiter=200,ftol=1e-12,gtol=1e-7))
    if not result.success or not np.all(np.isfinite(result.x)):raise RuntimeError('offset_not_converged')
    return dict(imputer=imputer,scaler=scaler,coefficients=result.x,penalty=penalty,
                training_rows=len(values),iterations=int(result.nit))


def predict_geometry_offset(fitted,values,geometry):
    values=np.asarray(values,float);geometry=np.asarray(geometry,float)
    if values.ndim!=2 or geometry.shape!=(len(values),):raise ValueError('offset_prediction_shape')
    if values.shape[1]!=len(fitted['coefficients'])-1:raise ValueError('offset_prediction_columns')
    if np.any(~np.isfinite(geometry)) or np.any((geometry<=0)|(geometry>=1)):
        raise ValueError('offset_invalid_geometry')
    if fitted['scaler'] is None:design=np.ones((len(values),1))
    else:
        design=np.c_[np.ones(len(values)),fitted['scaler'].transform(fitted['imputer'].transform(values))]
    p=expit(logit(geometry)+design@fitted['coefficients'])
    return np.c_[1-p,p]


def permute_context_dates(values,known_at,columns,*,seed=17):
    """Training-only null: permute whole shared context vectors by past date.

    Assets at one clock retain the same macro vector. Features outside columns
    and the caller's data are unchanged. This is a diagnostic negative control,
    never an eligible trade predictor or a point-in-time source construction.
    """
    result=np.array(values,copy=True)
    clocks=np.unique(known_at)
    rows=[]
    for clock in clocks:
        selected=result[np.asarray(known_at)==clock][:,columns]
        if not np.allclose(selected,selected[0],equal_nan=True):raise ValueError('context_not_shared_by_date')
        rows.append(selected[0])
    shuffled=np.random.default_rng(seed).permutation(len(clocks))
    rows=np.asarray(rows)
    for j,clock in enumerate(clocks):
        result[np.ix_(np.asarray(known_at)==clock,columns)]=rows[shuffled[j]]
    return result


VOL_CONTEXT_NAMES=('relative63','low_fraction63','low_run63','positive252','negative252','negative_x_fraction63')


def volatility_context(bars):
    """Strictly trailing volatility references and calm persistence; no labels.

    sigma20 uses20 completed log returns. Both references exclude the current
    sigma. A low observation has sigma20/prior252-median <0.8, evaluated using
    the reference actually known at that observation. Warmup rows stay NaN.
    """
    closes=np.array([b.c for b in bars],float)
    returns=np.r_[0.,np.diff(np.log(closes))]
    sigma=np.full(len(bars),np.nan);relative=np.full(len(bars),np.nan)
    for i in range(20,len(bars)):sigma[i]=np.std(returns[i-19:i+1],ddof=1)
    result=np.full((len(bars),len(VOL_CONTEXT_NAMES)),np.nan)
    low_run=0
    for i in range(21,len(bars)):
        previous=sigma[max(20,i-252):i]
        reference=max(float(np.median(previous)),1e-12)
        relative[i]=np.log(max(sigma[i],1e-12)/reference)
        low_run=min(63,low_run+1) if relative[i]<np.log(.8) else 0
        if i<84:continue
        short=max(float(np.median(sigma[i-63:i])),1e-12)
        fraction=float(np.mean(relative[i-62:i+1]<np.log(.8)))
        negative=min(relative[i],0.)
        result[i]=[np.log(max(sigma[i],1e-12)/short),fraction,low_run/63,
                   max(relative[i],0.),negative,negative*fraction]
    return result


def discounted_probability_mix(reference,expert,*,conditional=False,half_life_days=180.,penalty=1.):
    """Date-balanced, discounted Brier-optimal mixture of mature forecasts.

    Experts and references are historical time-out-of-fit predictions. Current
    outcomes never affect current weights. Optional `context` values must be
    known at prediction time. Context estimates partially pool toward the
    global estimate; both use one fixed penalty, not result-selected weights.
    """
    from collections import Counter,defaultdict
    if not np.all(np.isfinite([half_life_days,penalty])) or half_life_days<=0 or penalty<=0:
        raise ValueError('mix_positive_parameters_required')
    def identity(row):return row['asset'],row['known_at']
    alternative={identity(r):r for r in expert}
    if len(alternative)!=len(expert) or len({identity(r) for r in reference})!=len(reference):
        raise ValueError('mix_duplicate_origins')
    if set(alternative)!={identity(r) for r in reference}:raise ValueError('mix_origins_mismatch')
    for row in reference:
        other=alternative[identity(row)]
        p,q=np.asarray(row['probabilities']),np.asarray(other['probabilities'])
        if p.ndim!=1 or len(p)<2 or p.shape!=q.shape or not np.all(np.isfinite(np.r_[p,q])):
            raise ValueError('mix_invalid_probability')
        if np.any(np.r_[p,q]<0) or np.any(np.r_[p,q]>1) or not np.allclose([p.sum(),q.sum()],1):
            raise ValueError('mix_invalid_probability')
        if row['mature_at']<=row['known_at'] or not 0<=row['outcome']<len(p):raise ValueError('mix_invalid_target')
        if (row['outcome'],row['mature_at'])!=(other['outcome'],other['mature_at']):raise ValueError('mix_target_mismatch')
        if conditional and 'context' not in row:raise ValueError('mix_context_missing')
    ordered=sorted(reference,key=lambda r:(r['known_at'],r['asset']))
    pending=sorted(reference,key=lambda r:r['mature_at'])
    totals=Counter(r['known_at'] for r in reference)
    stats=np.zeros(3);cells=defaultdict(lambda:np.zeros(3))
    pointer=0;latest=None;previous=None;result=[]
    decay_rate=np.log(2)/(half_life_days*86400)
    for row in ordered:
        now=row['known_at']
        if previous is not None:
            decay=np.exp(-decay_rate*(now-previous));stats*=decay
            for cell in cells.values():cell*=decay
        previous=now
        while pointer<len(pending) and pending[pointer]['mature_at']<now:
            old=pending[pointer];other=alternative[identity(old)]
            base=np.asarray(old['probabilities']);delta=np.asarray(other['probabilities'])-base
            actual=np.eye(len(base))[old['outcome']]
            amount=np.exp(-decay_rate*(now-old['mature_at']))/totals[old['known_at']]
            update=amount*np.array([delta@delta,delta@(actual-base),1.])
            stats+=update
            if conditional:cells[old['context']]+=update
            latest=old['mature_at'];pointer+=1
        global_weight=float(np.clip(stats[1]/(stats[0]+penalty),0,1))
        cell=cells[row['context']] if conditional else stats
        weight=float(np.clip((cell[1]+penalty*global_weight)/(cell[0]+penalty),0,1)) if conditional else global_weight
        p=(1-weight)*np.asarray(row['probabilities'])+weight*np.asarray(alternative[identity(row)]['probabilities'])
        result.append(dict(row,probabilities=p.tolist(),expert_weight=weight,global_weight=global_weight,
            weight_training_maturity=latest,discounted_date_mass=float(stats[2]),context_mass=float(cell[2])))
    return result
