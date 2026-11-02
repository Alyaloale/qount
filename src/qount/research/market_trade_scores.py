"""Execution-aligned payoff distributions and selection-aware score calibration.

Future market-state probabilities remain a separate output. These heads learn
actual net trade outcomes from known context, rather than assigning a static
payoff to a future moving-average state. No exchange client is imported.
"""
from __future__ import annotations

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler


OUTCOMES=('no_fill','stop_net_loss','target_net_gain','other_net_gain','other_net_loss')


def outcome_code(value):
    if not value['filled']:return 0
    if value['reason'].startswith('stop') and value['net_unit']<0:return 1
    if value['reason'].startswith('target') and value['net_unit']>0:return 2
    return 3 if value['net_unit']>0 else 4


def context_matrix(known,close,decision,action,rules,delay):
    """Only the signal-time geometry, never the future fill price or label."""
    stop=abs(close-decision['stop'])/close
    target=decision.get('target');reward=0. if target is None else abs(target-close)/close
    risk=max(stop+2*(rules['fee']+rules['slippage']),1e-10)
    geometry=[decision['side'],stop,reward,float(target is not None),reward/risk,
              rules['fee']/risk,rules['slippage']/risk,decision['max_bars'],delay]
    return np.r_[known,np.eye(3)[action],geometry]


def date_weights(clocks):
    unique,counts=np.unique(clocks,return_counts=True)
    weights=1/counts[np.searchsorted(unique,clocks)]
    return weights*len(weights)/weights.sum()


def conditional_matrix(X,outcome):
    p=np.eye(len(OUTCOMES))[np.asarray(outcome,int)]
    # Current price/path context and known stop/reward/cost geometry interact
    # with the eventual trade outcome, not with a test-time true market state.
    columns=(0,3,4,5,6,9,12,16)+tuple(range(X.shape[1]-9,X.shape[1]))
    return np.c_[X,p,(X[:,columns,None]*p[:,None,:]).reshape(len(X),-1)]


def fit_trade_heads(X,net_r,outcome,actions,clocks):
    weights=date_weights(clocks)
    path=HistGradientBoostingClassifier(max_iter=80,max_leaf_nodes=7,max_depth=3,
        min_samples_leaf=60,l2_regularization=10,learning_rate=.05,early_stopping=False,random_state=17)
    path.fit(X,outcome,sample_weight=weights)
    conditional=conditional_matrix(X,outcome);scaler=StandardScaler().fit(conditional)
    payoff=Ridge(alpha=200.).fit(scaler.transform(conditional),net_r,sample_weight=weights)
    direct={}
    for a in range(3):
        valid=actions==a
        if valid.sum()<80:continue
        scale=StandardScaler().fit(X[valid]);model=Ridge(alpha=200.).fit(
            scale.transform(X[valid]),net_r[valid],sample_weight=date_weights(clocks[valid]))
        direct[a]=(scale,model)
    return dict(path=path,payoff=payoff,payoff_scaler=scaler,direct=direct,
                input_columns=X.shape[1],classes=list(OUTCOMES))


def predict_trade_heads(bundle,X,actions):
    n=len(X);p=np.zeros((n,len(OUTCOMES)))
    p[:,bundle['path'].classes_.astype(int)]=bundle['path'].predict_proba(X)
    expanded=conditional_matrix(np.repeat(X,len(OUTCOMES),axis=0),np.tile(np.arange(len(OUTCOMES)),n))
    conditional=bundle['payoff'].predict(bundle['payoff_scaler'].transform(expanded)).reshape(n,len(OUTCOMES))
    # Signs follow the definitions of the economic outcome labels. No-fill is
    # identically zero; no observed realized return is clipped in evaluation.
    conditional[:,0]=0.;conditional[:,[1,4]]=np.minimum(conditional[:,[1,4]],0.)
    conditional[:,[2,3]]=np.maximum(conditional[:,[2,3]],0.)
    mixture=np.sum(p*conditional,axis=1);direct=np.full(n,np.nan)
    for a,(scale,model) in bundle['direct'].items():
        use=actions==a
        if use.any():direct[use]=model.predict(scale.transform(X[use]))
    return dict(probabilities=p,conditional_net_R=conditional,path_mean=mixture,direct_mean=direct,
                probability_net_gain=p[:,2]+p[:,3])


def fit_score_calibration(history,cutoff,*,minimum_dates=40,penalty_dates=50.,threshold=None,minimum_tail_dates=20):
    """Calibrate past OOS *selected* actions, using strictly matured outcomes.

    Date-weighted ridge on raw winner score corrects selection optimism. The
    date-cluster sandwich SE is heuristic under serial dependence, not a
    certified lower bound. Unsupported history must abstain.
    """
    rows=[r for r in history if 0<r['maturity']<cutoff and np.isfinite(r['raw']) and np.isfinite(r['actual'])]
    dates=np.array([r['known_at'] for r in rows],np.int64)
    unique,counts=np.unique(dates,return_counts=True)
    result=dict(ready=False,rows=len(rows),dates=len(unique),last_maturity=max([r['maturity'] for r in rows],default=0),
                tail_ready=False,tail_dates=0,tail_mean_R=None,tail_mean_minus_error_R=None)
    if len(unique)<minimum_dates:return result
    raw=np.array([r['raw'] for r in rows]);truth=np.array([r['actual'] for r in rows])
    weight=1/counts[np.searchsorted(unique,dates)]
    center=float(np.average(raw,weights=weight));scale=max(float(np.sqrt(np.average((raw-center)**2,weights=weight))),.02)
    order=np.argsort(raw);cumulative=np.cumsum(weight[order])
    lo,hi=[float(raw[order[min(int(np.searchsorted(cumulative,q*cumulative[-1])),len(raw)-1)]]) for q in (.05,.95)]
    x=np.clip((raw-center)/scale,(lo-center)/scale,(hi-center)/scale)
    design=np.c_[np.ones(len(x)),x];bread=np.linalg.inv(design.T@(weight[:,None]*design)+penalty_dates*np.eye(2))
    beta=bread@(design.T@(weight*truth))
    if beta[1]<0:beta=np.array([np.sum(weight*truth)/(weight.sum()+penalty_dates),0.])
    residual=truth-design@beta;meat=np.zeros((2,2));cluster_residual=[]
    for date in unique:
        mask=dates==date;v=np.sum(weight[mask,None]*design[mask]*residual[mask,None],axis=0)
        meat+=np.outer(v,v);cluster_residual.append(float(np.sum(weight[mask]*residual[mask])))
    covariance=bread@meat@bread
    floor=float(np.std(cluster_residual,ddof=1)/np.sqrt(len(unique)))
    if threshold is None:
        index=min(int(np.searchsorted(cumulative,.90*cumulative[-1])),len(raw)-1)
        threshold=max(.10,float(raw[order[index]]))
    tail=raw>=threshold;tail_values=[]
    for date in np.unique(dates[tail]):tail_values.append(float(np.mean(truth[tail&(dates==date)])))
    tail_mean=float(np.mean(tail_values)) if tail_values else None
    tail_lower=(tail_mean-float(np.std(tail_values,ddof=1))/np.sqrt(len(tail_values))) if len(tail_values)>=2 else None
    return dict(result,ready=True,center=center,scale=scale,lower=float(lo),upper=float(hi),
                coefficients=beta.tolist(),covariance=covariance.tolist(),error_floor=floor,
                tail_ready=bool(len(tail_values)>=minimum_tail_dates and tail_lower>0),tail_dates=len(tail_values),
                tail_mean_R=tail_mean,tail_mean_minus_error_R=tail_lower,tail_cut=threshold)


def calibrated_score(calibration,raw):
    raw=np.asarray(raw,float)
    if not calibration['ready']:return np.full(raw.shape,np.nan),np.full(raw.shape,np.nan)
    clipped=np.clip(raw,calibration['lower'],calibration['upper'])
    x=(clipped-calibration['center'])/calibration['scale'];design=np.c_[np.ones(raw.size),x.ravel()]
    mean=design@np.array(calibration['coefficients'])
    variance=np.einsum('ni,ij,nj->n',design,np.array(calibration['covariance']),design)
    error=np.maximum(np.sqrt(np.maximum(variance,0)),calibration['error_floor'])
    return mean.reshape(raw.shape),(mean-error).reshape(raw.shape)
