"""Round16 explicit coordinator fork; carried source and latest-zero ownership."""
from __future__ import annotations

from qount.research.dual_engine_books import changed_scopes, settle_book
from qount.research.dual_engine_capital import SHARES, split_target, aggregate_units
from qount.research.dual_engine_redistribution import allocation_decision, allocate_capital


def ownership_plan(day, books, marks, source, scopes, limit, *, shares=None):
    """Freeze a feasible closed portfolio shape; binding budgets expand scope.

    A binding budget is a full book rebalance, including possible risk buys at
    execution. It is not a sell-only unit ceiling or a continuous exposure cap.
    """
    if limit not in (.2, .4): raise ValueError('joint_limit_invalid')
    values = {b:book['cash']+sum(q*marks[k] for k,q in book['units'].items()) for b,book in books.items()}
    nav = sum(values.values())
    if nav <= 0: raise ValueError('joint_closed_nav_invalid')
    plans = {}
    for b,book in books.items():
        share = shares[b] if shares is not None else values[b]/nav
        original = scopes[b]
        held = {k:q*marks[k]/values[b] for k,q in book['units'].items() if k!='BIL'} if values[b]>0 else {}
        aim = source.get(b,{})
        if original is None:
            shape = {k:w for k,w in aim.items() if k!='BIL' and w>0}
        else:
            frozen = {k:w for k,w in held.items() if k not in original and aim.get(k,0)>0}
            active = {k:aim.get(k,0.) for k in original if k!='BIL' and aim.get(k,0.)>0}
            available = max(0.,1-sum(frozen.values())); wanted = sum(active.values())
            funding = min(1.,available/wanted) if wanted>0 else 1.
            shape = {**frozen,**{k:w*funding for k,w in active.items()}}
        risk = sum(shape.values())*share
        factor = min(1.,limit/risk) if b!='reserve' and risk>0 else 1.
        binding = risk>limit+1e-12 and b!='reserve'
        if binding:
            target = {k:w*factor for k,w in shape.items()}; target['BIL']=max(0.,1-sum(target.values()))
            scope = None
        else:
            target = dict(aim); scope = original
        rejected = sorted(k for k in held if aim.get(k,0)<=0)
        plans[b] = {'source_zero_held_assets':rejected, 'decision':day,'source_scope':original,'scope':scope,'source_target':dict(aim),
            'target':target,'binding':binding,'budget_factor':factor,'projected_risk_weight':risk,
            'planned_risk_weight':risk*factor,'closed_book_nav':values[b],'closed_nav':nav,
            'book_share':share,'closed_units':dict(book['units']),'feasible_shape':shape}
    return {'decision':day,'books':plans,'monthly':shares is not None,'shares':shares}


def replay_ownership(dates, closes, opens, targets, *, start, lag, cost_bps, full_refresh, limit):
    """Original monthly funding plus dated joint source/risk instructions."""
    if lag<1 or limit not in (.2,.4): raise ValueError('joint_protocol_invalid')
    first=next(i for i,d in enumerate(dates) if d>=start)
    if first<lag: raise ValueError('joint_warmup_insufficient')
    policy='sweep20' if limit==.2 else 'cap40'
    desired={t:split_target(aim) for t,aim in targets.items()}
    scopes={b:changed_scopes({t:aim[b] for t,aim in desired.items()},full_refresh) for b in SHARES}
    books={b:{'cash':w,'units':{}} for b,w in SHARES.items()}; plans={}; allocations={}; rows=[]
    carried = None; latest_by_t = {}
    for j in range(first-lag,len(dates)):
        if j in desired: carried = desired[j]
        if carried is None: raise ValueError('ownership_initial_source_missing')
        latest_by_t[j] = carried
    for t in range(first-lag,first):
        if t in desired:
            monthly = t==first-lag or t in full_refresh
            warm_scopes = {b:None if monthly else scopes[b].get(t,()) for b in books}
            plans[t]=ownership_plan(dates[t],books,{},desired[t],warm_scopes,limit,shares=dict(SHARES) if monthly else None)
            if monthly: allocations[t]=allocation_decision(dates[t],dict(SHARES),desired[t],policy,warmup=True)
    for t in range(first,len(dates)):
        day=dates[t];signal=t-lag;plan=plans.get(signal)
        old=aggregate_units(books);old_cash=sum(b['cash'] for b in books.values())
        previous=old_cash+sum(q*closes[k][dates[t-1]] for k,q in old.items())
        names=set(old)|{'BIL'}|{k for p in (plan or {}).get('books',{}).values() for k in p['target']}
        marks={k:opens[k][day] for k in names};open_nav=old_cash+sum(q*marks[k] for k,q in old.items())
        before={b:{'cash':book['cash'],'units':dict(book['units'])} for b,book in books.items()}
        reset=bool(plan and (t==first or plan['monthly']))
        latest = latest_by_t[t-1]
        executed = {}; vetoes = {}
        for b,p in (plan or {}).get('books',{}).items():
            vetoes[b] = sorted(k for k,w in p['target'].items() if k!='BIL' and w>0 and latest[b].get(k,0)<=0)
            executed[b] = dict(p['target'])
            if vetoes[b]:
                for k in vetoes[b]: executed[b][k] = 0.
                executed[b]['BIL'] = max(0.,1-sum(w for k,w in executed[b].items() if k!='BIL'))
        if reset:
            shape=executed
            shares=dict(SHARES) if t==first else plan['shares']
            books,details=allocate_capital(books,marks,shape,cost_bps,shares)
        else:
            details={}
            for b,book in books.items():
                p=plan['books'][b] if plan else None;scope=p['scope'] if p else ()
                own_nav=book['cash']+sum(q*marks[k] for k,q in book['units'].items())
                if scope==():
                    details[b]=dict(pretrade_nav=own_nav,fee=0.,capital_transfer=0.,traded_notional={},scope=(),funding_cap=False)
                    continue
                new,cash,fee,_,cap=settle_book(own_nav,book['cash'],book['units'],marks,executed[b],cost_bps=cost_bps,scope=scope,cash_asset='BIL')
                traded={k:abs(new.get(k,0.)-book['units'].get(k,0.))*marks[k] for k in set(new)|set(book['units'])}
                books[b]={'units':new,'cash':cash};details[b]=dict(pretrade_nav=own_nav,fee=fee,capital_transfer=0.,traded_notional=traded,scope=scope,funding_cap=cap)
        units=aggregate_units(books);cash=sum(book['cash'] for book in books.values());nav=cash+sum(q*closes[k][day] for k,q in units.items())
        fee=sum(d['fee'] for d in details.values());flow=sum(sum(d['traded_notional'].values()) for d in details.values())
        net=sum(abs(units.get(k,0.)-old.get(k,0.))*marks[k] for k in set(units)|set(old));asset_flow={};book_rows={};unchanged=0.
        for b,book in books.items():
            d=details[b]
            for k,v in d['traded_notional'].items():asset_flow[k]=asset_flow.get(k,0.)+v
            book_rows[b]={**book,'nav':book['cash']+sum(q*closes[k][day] for k,q in book['units'].items()),**d}
            if d['scope']==():unchanged=max(unchanged,max((abs(book['units'].get(k,0.)-q) for k,q in before[b]['units'].items()),default=0.))
        if cash<-1e-9 or nav<=0:raise ValueError('joint_bankrupt_or_unfunded')
        weights={k:q*closes[k][day]/nav for k,q in units.items()}
        rows.append(dict(date=day,signal_date=dates[signal] if plan else None,return_=nav/previous-1,nav=nav,
            cash_return=closes['BIL'][day]/closes['BIL'][dates[t-1]]-1,turnover=flow/open_nav,cost_fraction=fee/open_nav,
            gross=sum(weights.values()),risk_gross=sum(w for k,w in weights.items() if k!='BIL'),weights=weights,
            pretrade_weights={k:q*marks[k]/open_nav for k,q in old.items()},target_weights={k:q*marks[k]/(open_nav-fee) for k,q in units.items()} if plan else None,
            cash=cash,units=units,missing_marks=[],no_fills=[],books=book_rows,joint_plan=plan,
            book_risk_weights={b:sum(q*closes[k][day] for k,q in book['units'].items() if k!='BIL')/nav for b,book in books.items()},
            latest_source=latest, source_zero_vetoes=vetoes, execution_book_targets=executed,
            requested_book_targets={b:p['target'] for b,p in plan['books'].items()} if plan else None,
            full_refresh=reset,capital_reset=reset,capital_allocation=({'decision_date':dates[first-lag],'shares':dict(SHARES),'initial':True} if t==first else allocations.get(signal)) if reset else None,
            asset_trade_notional=asset_flow,gross_book_traded_notional=flow,net_external_traded_notional=net,
            internal_opposite_traded_notional=max(0.,flow-net),untouched_books_units_max_error=unchanged))
        rows[-1]['return']=rows[-1].pop('return_')
        source=latest_by_t[t];source_scopes={b:scopes[b].get(t,()) for b in books}
        shares=None
        if t in full_refresh and t in desired:
            allocations[t]=allocation_decision(day,{b:book['nav'] for b,book in book_rows.items()},source,policy)
            shares=allocations[t]['shares']
        plans[t]=ownership_plan(day,books,{k:closes[k][day] for k in units},source,source_scopes,limit,shares=shares)
    return dict(records=rows,joint_decisions=plans,allocation_decisions=allocations,risk_limit=limit,
        source_ownership=True,capital_policy=policy,initial_capital_shares=dict(SHARES),cost_policy='gross independent book turnover; one fill per source book',research_only=True,orders_authorized=False)
