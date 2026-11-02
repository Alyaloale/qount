"""Fixed category hypotheses and causal state-detail predictors, offline only."""
from __future__ import annotations

from collections import defaultdict
import datetime as dt
import math

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from qount.research.market_state_validation import causal_probabilities, state_key
from qount.research.market_stages import ACTION_STATES


CATEGORIES = {
    "BTCUSDT": "crypto_major", "ETHUSDT": "crypto_major",
    "SOLUSDT": "crypto_other", "BNBUSDT": "crypto_other", "XRPUSDT": "crypto_other",
    "LTCUSDT": "crypto_other", "LINKUSDT": "crypto_other",
    "SPYUSDT": "equity_broad", "QQQUSDT": "equity_broad", "IWMUSDT": "equity_broad",
    "SMHUSDT": "equity_sector", "XLEUSDT": "equity_sector",
    "XAUUSDT": "gold", "COPPERUSDT": "copper", "CLUSDT": "oil",
}
FEATURE_NAMES = (
    "ema20_distance_atr", "ema50_distance_atr", "ema200_distance_atr",
    "momentum5_sigma", "momentum20_sigma", "efficiency20", "signed_efficiency20",
    "relative_volatility", "volatility_change5", "ema50_slope5_atr",
    "range_position", "action_age", "direction_age", "event_age", "event_distance_atr",
    "return1_sigma", "benchmark_direction", "benchmark_efficiency",
    "relative_momentum20_sigma",
)
INTERACTION_FEATURES = (0, 1, 3, 4, 5, 7, 11, 16)
KEYS = tuple(s for s in ACTION_STATES if s not in ("up_breakout", "down_breakout")) + (
    "up_breakout:pending", "up_breakout:confirmed", "down_breakout:pending",
    "down_breakout:confirmed", "shock", "unknown")


def category(asset):
    if asset not in CATEGORIES:
        raise ValueError("asset_category_not_defined")
    return CATEGORIES[asset]


def profile_samples(book, states, group, horizon, *, maximum_horizon=20, origin_stride=5, include_tail=False):
    """Same five-observation origins and common right cutoff for both horizons.

    Inputs stop at the signal close. Labels mature at the h-th future close.
    20-period labels overlap across origins and require clustered inference.
    Group calendars must match before cross-asset features are constructed.
    """
    if horizon not in (5, 20) or maximum_horizon < horizon or origin_stride < 1:
        raise ValueError("unsupported_profile_horizon")
    benchmark = "BTCUSDT" if group == "crypto" else "SPYUSDT"
    reference = book[benchmark]
    if any([b.t for b in bars] != [b.t for b in reference] for bars in book.values()):
        raise ValueError("profile_calendar_mismatch")
    samples = []
    for asset, bars in book.items():
        family = category(asset)
        ages, last, age = {}, None, 0
        for b in bars:
            key = state_key(states[asset][b.t])
            age = age+1 if key == last else 1
            ages[b.t], last = age, key
        for i in range(205, len(bars) if include_tail else len(bars)-maximum_horizon, origin_stride):
            b, r, old = bars[i], states[asset][bars[i].t], states[asset][bars[i-5].t]
            market = states[benchmark][reference[i].t]
            if "volatility20" not in old or "volatility20" not in r:
                continue
            sigma, atr = max(r["volatility20"],1e-10), max(r["atr14"],1e-10)
            mom5 = math.log(b.c/bars[i-5].c)
            mom20 = math.log(b.c/bars[i-20].c)
            market_momentum = math.log(reference[i].c/reference[i-20].c)
            event = r.get("event")
            vector = [
                (b.c-r["ema20"])/atr, (b.c-r["ema50"])/atr, (b.c-r["ema200"])/atr,
                mom5/(sigma*math.sqrt(5)), mom20/(sigma*math.sqrt(20)), r["er20"],
                r["er20"]*np.sign(mom20), math.log(sigma/max(r["volatility_reference"],1e-10)),
                math.log(sigma/max(old["volatility20"],1e-10)), (r["ema50"]-old["ema50"])/atr,
                r["range_position"], math.log1p(ages[b.t]), math.log1p(r["direction_streak"]),
                event["age"]/3 if event else 0., event["side"]*(b.c-event["boundary"])/atr if event else 0.,
                math.log(b.c/bars[i-1].c)/max(states[asset][bars[i-1].t]["volatility20"],1e-10),
                market["direction"], market["er20"], (mom20-market_momentum)/(sigma*math.sqrt(20)),
            ]
            mature=i+horizon<len(bars)
            future = math.log(bars[i+horizon].c/b.c) if mature else None
            bound = .5*sigma*math.sqrt(horizon)
            outcome = -1 if not mature else 2 if future > bound else 0 if future < -bound else 1
            samples.append(dict(asset=asset, category=family, known_at=b.t,
                mature_at=bars[i+horizon].t if mature else 0, key=state_key(r), outcome=outcome,
                bar_index=i,
                features=np.clip(vector,-8,8).tolist(), displacement=future,
                actionable=bool(r["route_side"]), route_class=r["route_side"]+1 if r["route_side"] else None,
                fixed_prediction=None))
    return sorted(samples,key=lambda s:(s["known_at"],s["asset"],s["key"]))


def category_probabilities(samples, *, strength=50., classes=3):
    """Category-state -> pooled-state -> asset prior, never independent tiny fits."""
    pooled = causal_probabilities(samples,classes,prior_strength=strength)
    mature = sorted(samples,key=lambda s:s["mature_at"])
    counts = defaultdict(lambda:np.zeros(classes))
    pointer, result = 0, []
    for row in pooled:
        while pointer<len(mature) and mature[pointer]["mature_at"]<row["known_at"]:
            old=mature[pointer]
            counts[old["category"],old["key"]][old["outcome"]]+=1
            pointer+=1
        cell=counts[row["category"],row["key"]]
        p=(cell+strength*np.array(row["probabilities"]))/ (cell.sum()+strength)
        result.append(dict(row,probabilities=p.tolist(),category_training_count=int(cell.sum())))
    return result


def design_matrix(samples, *, categorical=False, details=True):
    """Known fixed vocabulary; scaling is learned in each training fold only.

    Both variants include the same asset identifiers. Added category-interaction
    slopes test heterogeneity beyond merely learning asset frequency/intercepts.
    """
    assets = sorted(CATEGORIES)
    families = sorted(set(CATEGORIES.values()))
    vectors = []
    for row in samples:
        numeric = row["features"]
        vector = (numeric if details else [])+[float(row["key"]==k) for k in KEYS]+[float(row["asset"]==a) for a in assets]
        if categorical:
            if not details:
                raise ValueError("category_interactions_require_details")
            vector += [numeric[j] if row["category"]==family else 0.
                       for family in families for j in INTERACTION_FEATURES]
        vectors.append(vector)
    return np.asarray(vectors,float)


def fit_profile_model(matrix, outcomes):
    """One fixed ridge multinomial model; no class weighting or search."""
    model=make_pipeline(StandardScaler(),LogisticRegression(C=.1,solver="lbfgs",max_iter=300,tol=1e-5))
    model.fit(matrix,outcomes)
    if int(max(model[-1].n_iter_)) >= 300:
        raise RuntimeError("profile_model_not_converged")
    return model


def quarterly_predictions(samples, evaluation_start, *, categorical=False, details=True):
    """Refit each quarter with STRICTLY earlier mature labels, never future fits."""
    base=causal_probabilities(samples,3)
    matrix=design_matrix(base,categorical=categorical,details=details)
    outcomes=np.array([r["outcome"] for r in base],int)
    groups=defaultdict(list)
    for i,row in enumerate(base):
        date=dt.datetime.fromtimestamp(row["known_at"],dt.timezone.utc)
        if date.strftime("%Y-%m-%d")>=evaluation_start:
            groups[date.year,(date.month-1)//3*3+1].append(i)
    result, fits = [], []
    for (year,month),test in sorted(groups.items()):
        cutoff=int(dt.datetime(year,month,1,tzinfo=dt.timezone.utc).timestamp())
        train=[i for i,r in enumerate(base) if r["mature_at"]<cutoff]
        if len(train)<200 or len(np.unique(outcomes[train]))<3:
            raise ValueError("insufficient_profile_training")
        model=fit_profile_model(matrix[train],outcomes[train])
        probability=model.predict_proba(matrix[test])
        assert list(model[-1].classes_)==[0,1,2]
        latest=max(base[i]["mature_at"] for i in train)
        fits.append(dict(cutoff=cutoff,training_samples=len(train),last_training_maturity=latest,
            training_feature_mean=model[0].mean_.tolist()))
        for i,p in zip(test,probability):
            assert latest<cutoff<=base[i]["known_at"]
            result.append(dict(base[i],probabilities=p.tolist(),model_fit_cutoff=cutoff,
                               last_training_maturity=latest))
    return result,fits


def causal_shrink(reference, expert, *, category_aware=False, penalty=10.):
    """Online Brier-optimal convex shrinkage, using only mature forecasts.

    The global weight minimizes historical Brier plus penalty*weight^2.
    A category weight shrinks toward that global weight, not an independent
    noisy estimate. Synchronous assets get a combined date weight of one.
    No current/future forecast outcome can set its own mixture weight.
    """
    lookup={(r["asset"],r["known_at"]):r for r in expert}
    if len(lookup)!=len(reference):
        raise ValueError("shrink_origins_mismatch")
    ordered=sorted(reference,key=lambda r:(r["known_at"],r["asset"]))
    totals=defaultdict(int)
    for r in ordered:totals[r["known_at"]]+=1
    pending=sorted(ordered,key=lambda r:r["mature_at"])
    cells=defaultdict(lambda:np.zeros(2))
    global_stats=np.zeros(2)
    pointer,latest,result=0,None,[]
    for row in ordered:
        while pointer<len(pending) and pending[pointer]["mature_at"]<row["known_at"]:
            old=pending[pointer]
            other=lookup[old["asset"],old["known_at"]]
            assert old["outcome"]==other["outcome"] and old["mature_at"]==other["mature_at"]
            baseline=np.array(old["probabilities"])
            delta=np.array(other["probabilities"])-baseline
            actual=np.eye(len(baseline))[old["outcome"]]
            statistics=np.array([delta@delta,delta@(actual-baseline)])/totals[old["known_at"]]
            global_stats+=statistics
            cells[old["category"]]+=statistics
            latest=old["mature_at"]
            pointer+=1
        global_weight=float(np.clip(global_stats[1]/(global_stats[0]+penalty),0,1))
        cell=cells[row["category"]]
        weight=float(np.clip((cell[1]+penalty*global_weight)/(cell[0]+penalty),0,1)) if category_aware else global_weight
        alternative=lookup[row["asset"],row["known_at"]]
        p=(1-weight)*np.array(row["probabilities"])+weight*np.array(alternative["probabilities"])
        result.append(dict(row,probabilities=p.tolist(),expert_weight=weight,
            weight_training_maturity=latest))
    return result
