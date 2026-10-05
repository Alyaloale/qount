"""Offline scoped cash/unit accounting with independent trading clocks."""
from __future__ import annotations
import datetime as dt
import math


def changed_scopes(targets, full_refresh):
    """Change only requested instruments; cash ETF funds changes."""
    result={};previous=None
    for t,aim in sorted(targets.items()):
        result[t]=None if previous is None or t in full_refresh else tuple(sorted(
            k for k in set(previous)|set(aim) if k!='BIL' and previous.get(k,0)!=aim.get(k,0)))
        previous=aim
    return result


def solve_trade(open_nav, units, marks, desired, *, scope=None, cash_asset=None, sell_only=False):
    if open_nav<=0 or any(w<0 or not math.isfinite(w) for w in desired.values()) or sum(desired.values())>1+1e-12:
        raise ValueError('book_target_invalid')
    names=set(units)|set(desired)
    active=names if scope is None else set(scope)
    active.discard(cash_asset)
    frozen={k:u for k,u in units.items() if k not in active and k!=cash_asset and marks.get(k,0)>0}
    frozen_value=sum(u*marks[k] for k,u in frozen.items())
    return active,frozen,frozen_value


def settle_book(open_nav, cash, units, marks, desired, *, cost_bps, scope=None, cash_asset=None, sell_only=False):
    active,frozen,frozen_value=solve_trade(open_nav,units,marks,desired,scope=scope,cash_asset=cash_asset,sell_only=sell_only)
    rate=cost_bps/10000
    if not 0<=rate<.5:raise ValueError('book_cost_invalid')
    def values(post_nav):
        wanted={k:post_nav*desired.get(k,0) for k in active if marks.get(k,0)>0}
        if sell_only:wanted={k:min(v,units.get(k,0)*marks[k]) for k,v in wanted.items()}
        available=max(0,post_nav-frozen_value);total=sum(wanted.values())
        if total>available and total>0:
            factor=available/total;wanted={k:v*factor for k,v in wanted.items()}
        result={k:u*marks[k] for k,u in frozen.items()};result.update(wanted)
        rest=max(0,post_nav-sum(result.values()))
        if cash_asset:
            if marks.get(cash_asset,0)<=0:raise ValueError('cash_funding_price_missing')
            result[cash_asset]=rest
        turnover=sum(abs(result.get(k,0)-units.get(k,0)*marks.get(k,0)) for k in set(result)|set(units))
        return result,rest,turnover
    low,high=0.,open_nav
    for _ in range(100):
        mid=(low+high)/2;_,_,turnover=values(mid)
        if mid+rate*turnover>open_nav:high=mid
        else:low=mid
    post_nav=(low+high)/2
    amounts,rest,turnover=values(post_nav)
    new={k:v/marks[k] for k,v in amounts.items() if v>0 and marks.get(k,0)>0}
    # Preserve untouched units exactly, rather than recomputing their ratio.
    new.update(frozen)
    fee=rate*sum(abs(new.get(k,0)-units.get(k,0))*marks.get(k,0) for k in set(new)|set(units))
    new_cash=cash-sum((new.get(k,0)-units.get(k,0))*marks.get(k,0) for k in set(new)|set(units))-fee
    if new_cash<-1e-10:raise ValueError('book_unfunded_trade')
    if sell_only and any(new.get(k,0)>units.get(k,0)+1e-12 for k in active):raise ValueError('reduce_clock_bought_units')
    actual_nav=new_cash+sum(new[k]*marks[k] for k in new)
    weights={k:new[k]*marks[k]/actual_nav for k in new}
    cap=sum(post_nav*desired.get(k,0) for k in active)>max(0,post_nav-frozen_value)+1e-12
    return new,new_cash,fee,weights,cap


def replay_books(dates,closes,opens,targets,*,start,lag,cost_bps,cash_asset=None,scopes=None,
                 weekly=False,cancel_stale=False,risk_scale=None):
    """Decisions use their close state; fixed future-open delay remains causal.

    Weekly full buys are Sunday decisions. Other C60 decisions can only reduce
    actual units. Pending delayed buys may optionally be cancelled by the latest
    already-closed gate. Funding uses actual open capital, never future prices.
    """
    if lag<1:raise ValueError('book_lag_invalid')
    first=next(i for i,d in enumerate(dates) if d>=start)
    if first<lag:raise ValueError('book_warmup_insufficient')
    cash=1.;units={};last_marks={};plans={};records=[];decisions=[]
    for signal in range(first-lag,first):
        if signal in targets:plans[signal]=(dict(targets[signal]),False)
    if not weekly:plans={t:(dict(w),False) for t,w in targets.items()}
    for t in range(first,len(dates)):
        day=dates[t];signal=t-lag;plan=plans.get(signal);aim=dict(plan[0]) if plan else None
        reduce_only=bool(plan and plan[1]);scope=scopes.get(signal) if scopes is not None else None
        if t==first:scope=None
        previous_nav=cash+sum(u*last_marks[k] for k,u in units.items())
        names=set(units)|set(aim or {})
        if cash_asset and aim is not None:names.add(cash_asset)
        marks={};missing=[]
        for k in names:
            opn=opens.get(k,{}).get(day)
            if opn is None:
                if day in closes.get(k,{}):raise ValueError('required_book_open_missing:'+k+':'+day)
                opn=0.;missing.append(k)
            marks[k]=opn
        open_nav=cash+sum(u*marks[k] for k,u in units.items())
        if open_nav<=0:raise ValueError('book_bankrupt')
        pre={k:u*marks[k]/open_nav for k,u in units.items() if marks[k]>0}
        cancelled=[];cap=False;no_fills=[]
        if aim is not None:
            if cancel_stale:
                latest=targets.get(t-1,{})
                for k in list(aim):
                    if aim[k]>0 and latest.get(k,0)<=0:
                        aim[k]=0.;cancelled.append(k)
            no_fills=[k for k,w in aim.items() if w>0 and marks.get(k,0)<=0]
            new,new_cash,fee,effective,cap=settle_book(open_nav,cash,units,marks,aim,cost_bps=cost_bps,scope=scope,cash_asset=cash_asset,sell_only=reduce_only)
            turnover=sum(abs(new.get(k,0)-units.get(k,0))*marks.get(k,0) for k in set(new)|set(units))/open_nav
            untouched=[k for k in units if scope is not None and k not in scope and k!=cash_asset]
            invariant=max((abs(new.get(k,0)-units[k]) for k in untouched),default=0.)
            buys=sum(max(new.get(k,0)-units.get(k,0),0)*marks.get(k,0) for k in set(new)|set(units) if k!=cash_asset)
            units,cash=new,new_cash
        else:fee=turnover=buys=invariant=0.;effective=None
        close_marks={k:closes.get(k,{}).get(day,0) for k in units}
        missing.extend(k for k,v in close_marks.items() if v<=0)
        nav=cash+sum(u*close_marks[k] for k,u in units.items())
        if nav<=0:raise ValueError('book_bankrupt_at_close')
        weights={k:u*close_marks[k]/nav for k,u in units.items() if close_marks[k]>0}
        records.append(dict(date=day,signal_date=dates[signal] if aim is not None else None,return_=nav/previous_nav-1,nav=nav,
            cash_return=closes[cash_asset][day]/closes[cash_asset][dates[t-1]]-1 if cash_asset else 0.,turnover=turnover,cost_fraction=fee/open_nav,
            gross=sum(weights.values()),risk_gross=sum(w for k,w in weights.items() if k!=cash_asset),weights=weights,target_weights=effective,
            pretrade_weights=pre,cash=cash,units=dict(units),missing_marks=missing,no_fills=no_fills,requested_target=aim,
            trade_clock='reduce_only' if reduce_only else 'scoped' if scope is not None else 'full' if aim is not None else 'hold',
            requested_scope=scope,untouched_units_max_error=invariant,risk_buy_notional=buys,funding_cap=cap,cancelled_stale=cancelled))
        records[-1]['return']=records[-1].pop('return_')
        units={k:u for k,u in units.items() if close_marks[k]>0};last_marks=close_marks
        if weekly and t in targets:
            full=dt.date.fromisoformat(day).weekday()==6
            desired=dict(targets[t]) if full else {k:min(w,weights.get(k,0)) for k,w in targets[t].items()}
            desired={k:w for k,w in desired.items() if w>0}
            scale=risk_scale(t,desired) if risk_scale else 1.
            desired={k:w*scale for k,w in desired.items()}
            plans[t]=(desired,not full)
            decisions.append(dict(date=day,full_refresh=full,risk_scale=scale,target=desired))
    return dict(records=records,decisions=decisions,research_only=True,orders_authorized=False)
