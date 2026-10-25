"""Causal G20 carrier substitution; no leverage multiplication or order access."""
from __future__ import annotations

import math
from statistics import covariance, variance

from qount.dual_engine.contracts import G20_EXECUTION_TO_PROXY


def match_portfolio_risk(leveraged, proxy, bills, weight):
    """Match past sample variance of w*risky+(1-w)*BIL, bounded to cash/1x.

    Inputs are already completed daily returns. Fund leverage changes and fees
    embedded in prices are observed, never replaced by today's stated multiple.
    A 100% proxy cap can prevent matching; expose that failure rather than borrow.
    """
    if (len(leveraged) != len(proxy) or len(proxy) != len(bills) or len(proxy) < 2
            or not math.isfinite(weight) or not 0 <= weight <= 1
            or not all(math.isfinite(r) and r > -1 for series in (leveraged,proxy,bills) for r in series)):
        raise ValueError("carrier_risk_inputs_invalid")
    target=variance([weight*l+(1-weight)*b for l,b in zip(leveraged,bills)])
    excess=[p-b for p,b in zip(proxy,bills)]
    a,b,c=variance(excess),2*covariance(excess,bills),variance(bills)
    if weight==0:
        chosen=0.
    elif a <= 1e-24:
        chosen=0.
    else:
        discriminant=b*b+4*a*(target-c)
        roots=[] if discriminant < -1e-24 else [(-b+sign*math.sqrt(max(0.,discriminant)))/(2*a) for sign in (-1,1)]
        valid=[min(1.,max(0.,x)) for x in roots if -1e-12 <= x <= 1+1e-12]
        if valid:
            chosen=max(valid)
        else:
            candidates={0.,1.,min(1.,max(0.,-b/(2*a)))}
            chosen=min(candidates,key=lambda x:(abs(a*x*x+b*x+c-target),x))
    achieved=variance([chosen*p+(1-chosen)*v for p,v in zip(proxy,bills)])
    target_vol,actual_vol=math.sqrt(target*252),math.sqrt(achieved*252)
    matched=math.isclose(target_vol,actual_vol,rel_tol=1e-8,abs_tol=1e-10)
    return dict(weight=chosen,target_volatility=target_vol,achieved_volatility=actual_vol,
        risk_gap=actual_vol-target_vol,matched=matched,
        status="matched" if matched else "cap_under_target" if chosen==1 and achieved<target else "unmatchable")


def proxy_schedule(dates, prices, leveraged_schedule, *, window=20, proxy_mapping=None):
    """Same sector and decision sessions; only the carrier and causal weight change."""
    if not isinstance(window,int) or window<2:
        raise ValueError("carrier_window_invalid")
    mapping=G20_EXECUTION_TO_PROXY if proxy_mapping is None else proxy_mapping
    targets,diagnostics={},[]
    for i,target in sorted(leveraged_schedule.items()):
        if (i < window or i >= len(dates) or any(not math.isfinite(v) or v<0 for v in target.values())
                or not math.isclose(sum(target.values()),1,abs_tol=1e-10)):
            raise ValueError("carrier_target_invalid")
        names=[s for s,w in target.items() if s!="BIL" and w>0]
        if not names:
            targets[i]={"BIL":1.};continue
        if len(names)!=1 or names[0] not in mapping:
            raise ValueError("carrier_single_sector_required")
        symbol=names[0];proxy=mapping[symbol]
        returns={s:[prices[s][j]/prices[s][j-1]-1 for j in range(i-window+1,i+1)] for s in (symbol,proxy,"BIL")}
        match=match_portfolio_risk(returns[symbol],returns[proxy],returns["BIL"],target[symbol])
        targets[i]={proxy:match["weight"],"BIL":1-match["weight"]}
        diagnostics.append(dict(index=i,date=dates[i],selected=symbol,proxy=proxy,
            anchor_weight=target[symbol],**match))
    return targets,diagnostics
