"""Behavior clustering and fixed supervised models; no trading or RL execution."""
from __future__ import annotations

from collections import Counter
import math
import warnings

import numpy as np
from sklearn.cluster import KMeans
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.exceptions import ConvergenceWarning
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from qount.research.market_learning_data import STYLE_COLUMNS, STYLE_NAMES
from qount.research.market_state_profiles import CATEGORIES, KEYS


def fit_behavior(data, indices, *, seed=17):
    """Fixed four clusters on PRIOR behavior, with equal total weight per asset."""
    if len(indices)<80:raise ValueError("insufficient_behavior_history")
    raw=data["X"][indices][:,STYLE_COLUMNS]
    imputer=SimpleImputer(strategy="median",keep_empty_features=True).fit(raw)
    values=imputer.transform(raw)
    sizes=Counter(data["asset"][indices])
    weights=np.array([1/sizes[a] for a in data["asset"][indices]])
    weights*=len(weights)/weights.sum()
    scaler=StandardScaler().fit(values,sample_weight=weights)
    transformed=scaler.transform(values)
    model=KMeans(n_clusters=4,n_init=10,random_state=seed).fit(transformed,sample_weight=weights)
    centers=scaler.inverse_transform(model.cluster_centers_)
    order=np.argsort(centers[:,0])  # IDs are ordered by volatility, not persistent economic names.
    distances=model.transform(transformed)[:,order]
    labels=distances.argmin(axis=1)
    thresholds=np.maximum(np.array([np.quantile(distances[labels==i,i],.99) if np.sum(labels==i)>=20
        else np.quantile(distances.min(axis=1),.99) for i in range(4)])
        ,1e-8)
    silhouette=float(silhouette_score(transformed,labels,sample_size=min(600,len(indices)),random_state=17))
    return dict(imputer=imputer,scaler=scaler,model=model,order=order,thresholds=thresholds,
        centers=centers[order],silhouette=silhouette,training_indices=np.array(indices),labels=labels)


def behavior_features(data, indices, fitted):
    raw=data["X"][indices][:,STYLE_COLUMNS]
    values=fitted["scaler"].transform(fitted["imputer"].transform(raw))
    distances=fitted["model"].transform(values)[:,fitted["order"]]
    labels=distances.argmin(axis=1)
    outside=distances[np.arange(len(indices)),labels]>fitted["thresholds"][labels]
    onehot=np.eye(4)[labels]
    onehot[outside]=0
    augmented=np.c_[onehot,np.minimum(distances/fitted["thresholds"],10),outside.astype(float)]
    return augmented,np.where(outside,-1,labels)


def behavior_summary(data, cutoff, *, asof):
    training=np.flatnonzero((data["known_at"]<cutoff)&(data["bar_index"]%20==5))
    models=[fit_behavior(data,training,seed=seed) for seed in (17,29,41)]
    primary=models[0]
    latest=[]
    for asset in sorted(set(data["asset"])):
        eligible=np.flatnonzero((data["asset"]==asset)&(data["known_at"]<=asof))
        latest.append(eligible[-1])
    _,labels=behavior_features(data,np.array(latest),primary)
    groups=[]
    for k in range(4):
        groups.append(dict(cluster=k,centroid={name:float(v) for name,v in zip(STYLE_NAMES,primary["centers"][k])},
            training_observations=int(np.sum(primary["labels"]==k)),
            members=[str(data["asset"][i]) for i,label in zip(latest,labels) if label==k]))
    return dict(training_cutoff=int(cutoff),profile_asof=int(asof),
        last_training_feature=int(data["known_at"][training].max()),
        silhouette=primary["silhouette"],
        seed_adjusted_rand=[float(adjusted_rand_score(primary["labels"],m["labels"])) for m in models[1:]],
        groups=groups,
        by_asset=[dict(asset=str(data["asset"][i]),economic_category=str(data["economic_category"][i]),
            known_at=int(data["known_at"][i]),cluster=int(label),
            style={name:float(v) for name,v in zip(STYLE_NAMES,data["X"][i,list(STYLE_COLUMNS)])})
            for i,label in zip(latest,labels)],
        outside_members=[str(data["asset"][i]) for i,label in zip(latest,labels) if label<0])


def model_matrix(data, *, feature_mask=None, include_asset=True, include_category=True, state_detail="fine"):
    """Features/missingness plus optional known identities; never targets.

    Asset identity already determines economic category in this panel. Category
    ablations therefore also need an arm without asset ID. State ablations here
    remove categorical state tokens, not state-derived continuous information.
    """
    if state_detail not in ("fine","coarse",None):raise ValueError("unknown_state_detail")
    categories=sorted(set(CATEGORIES.values()))
    assets=sorted(CATEGORIES)
    keys=KEYS if state_detail=="fine" else tuple(dict.fromkeys(k.split(":")[0] for k in KEYS))
    identity=np.array([([float(c==family) for family in categories] if include_category else [])
                       +([float(a==s) for s in assets] if include_asset else [])
                       +([float((k if state_detail=="fine" else k.split(":")[0])==state) for state in keys]
                         if state_detail else [])
                       for a,c,k in zip(data["asset"],data["economic_category"],data["state"])])
    selected=np.asarray(feature_mask if feature_mask is not None else
        data.get("default_feature_mask",np.ones(data["X"].shape[1],bool)),bool)
    if selected.shape!=(data['X'].shape[1],):raise ValueError('invalid_model_feature_mask')
    return np.c_[data["X"][:,selected],data["missing"][:,selected].astype(float),identity]


def fit_candidate(kind, matrix, outcomes, *, seed=17):
    """Fixed CPU pilots. No random validation split or evaluation-based stopping."""
    if kind=="linear":
        learner=LogisticRegression(C=.1,max_iter=400,solver="lbfgs")
    elif kind=="tree":
        learner=HistGradientBoostingClassifier(max_iter=80,max_leaf_nodes=7,max_depth=3,
            min_samples_leaf=60,l2_regularization=10,learning_rate=.05,
            early_stopping=False,random_state=seed)
    elif kind=="mlp":
        learner=MLPClassifier(hidden_layer_sizes=(32,16),activation="relu",solver="adam",alpha=1.,
            batch_size=min(128,len(outcomes)),learning_rate_init=.001,max_iter=40,
            early_stopping=False,n_iter_no_change=41,tol=0.,random_state=seed)
    else:raise ValueError("unknown_market_learning_model")
    model=make_pipeline(SimpleImputer(strategy="median",keep_empty_features=True),StandardScaler(),learner)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always",ConvergenceWarning)
        model.fit(matrix,outcomes)
    warning_count=sum(issubclass(w.category,ConvergenceWarning) for w in caught)
    if kind=="linear" and warning_count:raise RuntimeError("linear_fit_not_converged")
    return model,dict(seed=seed,convergence_warnings=warning_count,
        fixed_epochs=40 if kind=="mlp" else None,
        training_first_loss=float(learner.loss_curve_[0]) if kind=="mlp" else None,
        training_last_loss=float(learner.loss_curve_[-1]) if kind=="mlp" else None)


def range_geometry_probability(close, low, high, sigma, *, horizon=5):
    """Zero-drift Gaussian path baseline; not a trading or true-market model.

    A fixed antithetic simulation predicts discrete future closes inside known
    bounds. No fitted or future parameter; sigma is the already observed vol20.
    """
    if not 0<low<high or close<=0 or sigma<=0:raise ValueError("invalid_range_geometry")
    return range_geometry_from_distances(math.log(close/low)/sigma,math.log(high/close)/sigma,horizon=horizon)


def range_geometry_from_distances(lower_distance,upper_distance,*,horizon=5):
    """Same zero-drift path baseline from already known normalized distances."""
    if lower_distance+upper_distance<=0:raise ValueError("invalid_normalized_range")
    rng=np.random.default_rng(43)
    shocks=rng.normal(size=(1024,horizon))
    paths=np.cumsum(np.r_[shocks,-shocks],axis=1)
    bottom=-lower_distance
    top=upper_distance
    probability=float(np.mean(np.all((paths>=bottom)&(paths<=top),axis=1)))
    return float(np.clip(probability,.001,.999))
