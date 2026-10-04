"""Past-three-year signal gates and a continuously executed ensemble selector."""
from __future__ import annotations

import numpy as np

from qount.research.etf_trader.env import Decision

from .diagnostics import block_interval, bridge_targets, ic_series, mean_finite
from .execution import simulate
from .postmortem import _path_utility
from .residual_data import BASELINES, FAMILIES, NEURALS, REAL, RIDGES


def prediction_stats(values,prediction):
    truth,mask = values["evaluation_y"],values["evaluation_mask"]
    if prediction.shape != truth.shape or not np.isfinite(prediction).all():
        raise ValueError("finite aligned standardized residual predictions required")
    _,rank = ic_series(prediction,truth,mask)
    error = np.abs(prediction-truth)
    loss = np.where(error<=1,.5*error**2,error-.5)
    counts = mask.sum(1)
    huber = np.where(mask,loss,0).sum(1)/np.maximum(counts,1)
    huber[counts==0] = np.nan
    return {"rank":rank,"huber":huber}


def total_forecast(values,residual):
    result = values["evaluation_base"].copy()
    if residual.shape != (len(result),8) or not np.isfinite(residual).all():
        raise ValueError("eight finite residual forecasts per execution date required")
    result[:,values["learned_columns"]] += residual*float(values["scale"])
    return result


def portfolio_metrics(curve,cash_returns):
    returns = curve["returns"][1:]
    rows = curve["rows"][1:]
    if not len(returns) or np.any(np.diff(curve["rows"])!=1):
        raise ValueError("a nonempty contiguous no-order ledger required")
    excess = returns-cash_returns[rows]
    sd = excess.std(ddof=1)
    equity = curve["equity"]
    maximum = float(np.max(np.convolve(curve["voluntary"][1:],np.ones(min(252,len(returns))),"valid")))
    report = {"cagr":float((equity[-1]/equity[0])**(252/len(returns))-1),
        "sharpe_excess_cash":float(excess.mean()*np.sqrt(252)/sd) if sd>1e-14 else 0.,
        "max_drawdown":float(np.max(1-equity/np.maximum.accumulate(equity))),
        "minimum_cash":float(curve["cash"].min()),"forced_breaches":int(curve["breach"].sum()),
        "max_rolling_voluntary":maximum,"total_costs":float(curve["costs"].sum()),"days":len(returns)}
    report["utility"] = report["sharpe_excess_cash"]-2*report["max_drawdown"]-.025*maximum/4
    report["hard_constraints"] = report["forced_breaches"]==0 and report["minimum_cash"]>=-1e-7 and maximum<=4+1e-7
    return report


def execute_path(panel,sequence,inputs,*,anchor,multiplier=2.):
    """A single account carries shares, cash, DD and turnover between all years."""
    if not sequence or any(len(rows)==0 for rows,_ in sequence):
        raise ValueError("nonempty continuous execution partitions required")
    rows = np.concatenate([rows for rows,_ in sequence])
    if rows.ndim!=1 or len(rows)<2 or np.any(np.diff(rows)!=1):
        raise ValueError("execution partitions must join without gaps or duplicate dates")
    mu = np.concatenate([mu for _,mu in sequence])
    targets = bridge_targets(panel,rows,mu,inputs)
    first,stop = int(rows[0]),int(rows[-1])
    def policy(obs):
        if (obs.t-anchor)%21:
            return Decision(None)
        return Decision(targets[obs.t],band=0,kappa=1)
    # A prior year's last close still decides its next-year opening fill.
    # Joining the forecasts before simulation prevents annual partition seams
    # from dropping that decision or using the new year's model a day early.
    result = simulate(panel,policy,start=first,stop=stop,inputs=inputs,cost_multiplier=multiplier)
    sl = slice(first,stop+1)
    curve = {"rows":rows,"equity":result.equity[sl],"returns":result.returns[sl],"cash":result.cash[sl],
        "voluntary":result.voluntary_turnover[sl],"forced":result.forced_turnover[sl],
        "breach":result.forced_breach[sl],"caps":result.gross_cap[sl],"costs":result.costs[sl]}
    return portfolio_metrics(curve,inputs.cash_returns),curve


def pooled(values):
    return np.concatenate(values)


def signal_gate(family,statistics,seed_statistics,*,samples=500):
    own = statistics[family]
    positive_years = sum((mean_finite(s["rank"]) or 0)>0 for s in own)
    rank = pooled([s["rank"] for s in own])
    own_loss = mean_finite(pooled([s["huber"] for s in own]))
    loss_ref = min(mean_finite(pooled([s["huber"] for s in statistics[n]])) for n in (BASELINES[0],RIDGES[0]))
    controls = (RIDGES[1],) if family==RIDGES[0] else NEURALS[1:]
    deltas,intervals,annual_deltas,paired_years = {},{},{},{}
    for control in controls:
        difference = rank-pooled([s["rank"] for s in statistics[control]])
        deltas[control] = mean_finite(difference)
        intervals[control] = {str(b):block_interval(difference,block=b,seed=20261003,samples=samples) for b in (40,60,120)}
        annual_deltas[control] = [mean_finite(a["rank"]-b["rank"]) for a,b in zip(own,statistics[control])]
        paired_years[control] = sum(d is not None and d>0 for d in annual_deltas[control])
    interval_ok = all(d.get("status")=="diagnostic" and d["lower"]>0 for c in intervals.values() for d in c.values())
    increment_ok = all(d is not None and d>.01 for d in deltas.values())
    agreements = None
    if family==NEURALS[0]:
        agreements = 0
        for seed in range(1000,1005):
            seed_rank = pooled([s["rank"] for s in seed_statistics[family][str(seed)]])
            positive = (mean_finite(seed_rank) or 0)>0
            increments = [mean_finite(seed_rank-pooled([s["rank"] for s in seed_statistics[c][str(seed)]])) for c in controls]
            agreements += bool(positive and all(d is not None and d>.01 for d in increments))
    annual_pair_ok = family!=RIDGES[0] or all(n>=2 for n in paired_years.values())
    qualified = positive_years>=2 and annual_pair_ok and increment_ok and interval_ok and own_loss<=1.05*loss_ref and (agreements is None or agreements>=3)
    return {"qualified":bool(qualified),"positive_inner_years":int(positive_years),"mean_rank_ic":mean_finite(rank),
        "mean_standardized_residual_huber":own_loss,"huber_reference":loss_ref,"paired_rank_increments":deltas,
        "paired_rank_intervals":intervals,"paired_positive_seed_count":agreements,
        "paired_annual_rank_increments":annual_deltas,"paired_positive_inner_years":paired_years,
        "deterministic_ridge_no_seed_vote":family==RIDGES[0]}


def utility_sensitivity(curves,cash_returns,metrics,eligible,winner,*,samples=400,seed=20261003):
    """Score perturbation of observed returns; no claim of an executable resample."""
    reference = curves[eligible[0]]["rows"]
    if any(not np.array_equal(reference,curves[n]["rows"]) for n in eligible):
        raise ValueError("selector portfolios must share all execution dates")
    size = len(reference)-1
    rng = np.random.default_rng(seed)
    result = {}
    for block in (40,60,120):
        wins = {n:0 for n in eligible}
        for _ in range(samples):
            starts = rng.integers(0,size-block+1,int(np.ceil(size/block)))
            indices = (starts[:,None]+np.arange(block)).ravel()[:size]
            scores = {}
            for name in eligible:
                curve = curves[name]
                penalty = .025*metrics[name]["max_rolling_voluntary"]/4
                scores[name] = float(_path_utility(curve["returns"][1:][indices],cash_returns[reference[1:]][indices],penalty)[0])
            chosen = min(eligible,key=lambda n:(-scores[n],0 if n==BASELINES[0] else 9 if n==RIDGES[0] else 161,n))
            wins[chosen] += 1
        result[str(block)] = {"samples":samples,"winner_retained":wins[winner]/samples,
                             "win_frequencies":{n:v/samples for n,v in wins.items()},"observed_hard_risk_fixed":True}
    return result


def select_from_past(year,slots,predictions,panel,inputs,*,anchor,interval_samples=500,stability_samples=400):
    """Only Y-3..Y-1 are accessed, even when later inner results exist."""
    years = list(range(year-3,year))
    statistics = {name:[] for name in (*RIDGES,*NEURALS,BASELINES[0])}
    seed_statistics = {name:{str(s):[] for s in range(1000,1005)} for name in NEURALS}
    sequences = {name:[] for name in FAMILIES}
    for inner_year in years:
        key = f"inner_{inner_year}"
        values = slots[key]
        rows = values["evaluation_rows"]
        if int(panel.dates[int(rows[-1])][:4]) != inner_year:
            raise ValueError("inner calendar year mismatch")
        for family in (*RIDGES,*NEURALS):
            members = predictions[key][family]
            required = list(range(1000,1005)) if family in NEURALS else [1000]
            if sorted(map(int,members)) != required:
                raise ValueError("complete fixed seed pairs required before selection")
            ps = [members[str(s)] for s in required]
            ensemble = np.mean(ps,axis=0)
            statistics[family].append(prediction_stats(values,ensemble))
            if family in NEURALS:
                for seed,pred in zip(required,ps):
                    seed_statistics[family][str(seed)].append(prediction_stats(values,pred))
            sequences[family].append((rows,total_forecast(values,ensemble)))
        statistics[BASELINES[0]].append(prediction_stats(values,np.zeros_like(values["evaluation_y"])))
        for name,column in zip(BASELINES,("evaluation_base","evaluation_asset_train_mean","evaluation_momentum120","evaluation_cash")):
            sequences[name].append((rows,values[column]))
    metrics,curves = {},{}
    for name,sequence in sequences.items():
        metrics[name],curves[name] = execute_path(panel,sequence,inputs,anchor=anchor)
    decisions = {}
    for family in REAL:
        signal = signal_gate(family,statistics,seed_statistics,samples=interval_samples)
        curve,base = curves[family],curves[BASELINES[0]]
        leave_years = {}
        for omit in years:
            dates = np.array([int(panel.dates[int(r)][:4]) for r in curve["rows"][1:]])
            keep = dates!=omit
            def score(name):
                c = curves[name]
                return float(_path_utility(c["returns"][1:][keep],inputs.cash_returns[c["rows"][1:]][keep],
                                          .025*metrics[name]["max_rolling_voluntary"]/4)[0])
            leave_years[str(omit)] = score(family)-score(BASELINES[0])
        portfolio_ok = metrics[family]["hard_constraints"] and metrics[BASELINES[0]]["hard_constraints"] and (
            metrics[family]["utility"]>metrics[BASELINES[0]]["utility"] and sum(v>0 for v in leave_years.values())>=2)
        decisions[family] = signal|{"portfolio_increment":bool(portfolio_ok),"leave_one_inner_year_utility_increments":leave_years,
                                    "qualified":bool(signal["qualified"] and portfolio_ok)}
    if not metrics[BASELINES[0]]["hard_constraints"]:
        raise ValueError("zero-residual fallback violated hard risk constraints")
    eligible = [BASELINES[0]]+[n for n in REAL if decisions[n]["qualified"]]
    chosen = min(eligible,key=lambda n:(-metrics[n]["utility"],0 if n==BASELINES[0] else 9 if n==RIDGES[0] else 161,n))
    stability = utility_sensitivity(curves,inputs.cash_returns,metrics,eligible,chosen,samples=stability_samples)
    stable = all(v["winner_retained"]>=.70 for v in stability.values())
    selected = chosen if stable else BASELINES[0]
    return {"outer_year":year,"inner_eval_years":years,"selected":selected,"score_winner":chosen,
            "winner_stable":bool(stable),"eligible_before_stability":eligible,"decisions":decisions,
            "winner_stability":stability,"ensemble_metrics_2x":metrics,"test_used":False,
            "ledger":"continuous three inner years; trade mean prediction before scoring"},curves
