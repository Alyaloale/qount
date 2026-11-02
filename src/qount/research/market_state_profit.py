"""Daily linear-futures replay for frozen state predictions; offline only."""
from __future__ import annotations

from collections import Counter
import math

import numpy as np

from qount.research.market_model_profit import execution_price
from qount.research.market_state_dataset import DAY_MS,validate_market_inputs


def complete_history(ds):
    """Recover complete native bars from retained overlapping windows."""
    d=ds.data
    with np.load(ds.root/'latest_inputs.npz',allow_pickle=False) as z:latest={k:z[k] for k in z.files}
    validate_market_inputs(latest)
    size=int(max(d['two_n_source_rows'].max(),latest['two_n_source_rows'].max()))+1
    bars=np.full((size,9),np.nan);clock=np.full(size,-1,np.int64);assets=np.full(size,'',dtype='U12')
    for data in (d,latest):
        ids=data['two_n_source_rows'].reshape(-1);raw=data['two_n_raw_market'].reshape(-1,9)
        length=data['two_n_source_rows'].shape[1]
        stamps=(data['bar_open_at'][:,None]+np.arange(-length+1,1)*DAY_MS).reshape(-1)
        names=np.repeat(data['asset'],length)
        unique,first=np.unique(ids,return_index=True);present=np.isfinite(bars[unique]).all(1)
        if not np.array_equal(bars[unique[present]],raw[first[present]]):raise ValueError('profit_conflicting_history')
        bars[unique]=raw[first];clock[unique]=stamps[first];assets[unique]=names[first]
        if not np.array_equal(bars[ids],raw) or not np.array_equal(clock[ids],stamps) or not np.array_equal(assets[ids],names):
            raise ValueError('profit_conflicting_overlaps_or_asset_clock')
    output={}
    for asset in ds.asset_names:
        rows=np.flatnonzero(assets==asset);rows=rows[np.argsort(clock[rows])]
        if np.any(np.diff(clock[rows])!=DAY_MS):raise ValueError('profit_missing_daily_history')
        output[asset]=dict(open_at=clock[rows],market=bars[rows])
    return output


def execution_schedule(decision_at,bar_open_at):
    """First DAILY open strictly after the release clock, not the past open."""
    decision=np.asarray(decision_at,np.int64);bar=np.asarray(bar_open_at,np.int64)
    if decision.shape!=bar.shape or np.any(decision<=bar+DAY_MS-1):raise ValueError('profit_signal_not_after_close')
    result=(decision//DAY_MS+1)*DAY_MS
    if np.any(result<=decision):raise ValueError('profit_fill_before_signal')
    return result


def target_quantity(equity,price,old,weight,rules):
    """Target post-cost exposure, then round toward zero and apply lot limits."""
    if equity<=0 or price<=0 or not np.isfinite(weight) or abs(weight)>1:raise ValueError('profit_invalid_target')
    preliminary=weight*equity/price;direction=np.sign(preliminary-old)
    if not direction:return old
    execution=execution_price(price,int(direction),opening=True,slippage=rules['slippage'],tick=rules['tick'])
    cost=abs(execution-price)+rules['fee']*execution
    target=weight*(equity+direction*cost*old)/(price+weight*direction*cost)
    target=np.sign(target)*min(math.floor(abs(target)/rules['step']+1e-10)*rules['step'],rules['max_qty'])
    if abs(target)<rules['min_qty'] or abs(target)*price<rules['min_notional']:target=0.
    return float(target)


def replay(market,open_at,weights,known_at,capacity,funding_time,funding_rate,*,initial,rules,
           fixed_quantity=False,adverse_funding=False):
    """N daily holding periods plus a terminal open, with exact quantity PnL.

    Standard policies rebalance to target exposure daily. Buy/hold is fixed
    initial quantity. Funding timestamps within the first minute belong to
    the opening settlement window. Base convention settles old quantity
    before orders; adverse mode uses the less favourable old/new payment.
    Intraday marks are approximated by daily open, or adverse high/low stress.
    """
    market=np.asarray(market,float);open_at=np.asarray(open_at,np.int64);weights=np.asarray(weights,float)
    known_at=np.asarray(known_at,np.int64);capacity=np.asarray(capacity,float);n=len(weights)
    funding_time=np.asarray(funding_time,np.int64);funding_rate=np.asarray(funding_rate,float)
    if (market.shape!=(n+1,9) or len(open_at)!=n+1 or known_at.shape!=(n,) or capacity.shape!=(n,)
            or np.any(np.diff(open_at)!=DAY_MS) or np.any(known_at>=open_at[:-1]) or np.any(abs(weights)>1)
            or not np.isfinite(market).all() or not np.isfinite(funding_rate).all()
            or funding_time.shape!=funding_rate.shape or np.any(np.diff(funding_time)<=0)):
        raise ValueError('profit_invalid_replay_calendar_or_values')
    if len(funding_time):
        before=funding_time[funding_time<=open_at[0]+60000];after=funding_time[funding_time>=open_at[-1]]
        near=(funding_time>=open_at[0]-8*3600000)&(funding_time<=open_at[-1]+8*3600000)
        if not len(before) or not len(after) or open_at[0]-before[-1]>8*3600000+60000 or after[0]-open_at[-1]>8*3600000+60000:
            raise ValueError('profit_incomplete_funding_coverage')
        if np.any(np.diff(funding_time[near])>8*3600000+60000):raise ValueError('profit_funding_gap')
    # Empty funding is allowed only in targeted synthetic unit tests.
    rates_open=np.zeros(n+1);rates_intraday=[[] for _ in range(n)]
    for stamp,rate in zip(funding_time,funding_rate):
        day=int((stamp-open_at[0])//DAY_MS)
        if day<0 or day>n:continue
        if stamp-open_at[day]<60000:rates_open[day]+=rate
        elif day<n:rates_intraday[day].append(float(rate))
    cash=float(initial);quantity=0.;last_price=float(market[0,0]);nav=[];close_nav=[];samples=[];notional=[]
    orders=[];totals=dict(price_pnl=0.,funding_pnl=0.,fees=0.,slippage_and_rounding=0.)
    skips=Counter();minimum_margin=float('inf');max_entry=0.;max_participation=0.;max_known_participation=0.
    liquidation=False
    for i in range(n+1):
        price=float(market[i,0]);gap=quantity*(price-last_price);cash+=gap;totals['price_pnl']+=gap
        opening_payment=-quantity*price*rates_open[i];cash+=opening_payment;totals['funding_pnl']+=opening_payment
        old=quantity;terminal=i==n
        if terminal:target=0.
        elif fixed_quantity and i:target=quantity
        else:target=target_quantity(cash,price,old,float(weights[i]),rules)
        nav.append(cash);samples.append(cash)
        delta=target-old
        if abs(delta)>=rules['step']/2:
            reduce_only=old*delta<0 and abs(delta)<=abs(old)+1e-9
            execution=execution_price(price,1 if delta>0 else -1,opening=True,slippage=rules['slippage'],tick=rules['tick'])
            if not terminal and (abs(delta)<rules['min_qty'] or (not reduce_only and abs(delta)*execution<rules['min_notional'])):
                skips['minimum_order']+=1;delta=0.
            elif abs(delta)>rules['max_qty']+1e-9:raise ValueError('profit_order_exceeds_snapshot_max_quantity')
            if delta:
                fee=abs(delta)*execution*rules['fee'];slip=abs(delta)*abs(execution-price)
                cash-=fee+slip;totals['fees']+=fee;totals['slippage_and_rounding']+=slip;quantity+=delta
                if not terminal:
                    past_ratio=abs(delta)*price/max(capacity[i],1e-10)
                    actual_ratio=abs(delta)*price/max(market[i,5],1e-10)
                    max_known_participation=max(max_known_participation,past_ratio)
                    max_participation=max(max_participation,actual_ratio)
                    if past_ratio>.001 or actual_ratio>.001:raise ValueError('profit_capacity_assumption_exceeded')
                    max_entry=max(max_entry,abs(quantity)*price/cash)
                orders.append(dict(time=int(open_at[i]),quantity_change=float(delta),reference=price,execution=execution,
                    fee=fee,slippage_and_rounding=slip,terminal=terminal))
        if adverse_funding and rates_open[i]:
            new_payment=-quantity*price*rates_open[i]
            adjustment=min(opening_payment,new_payment)-opening_payment
            cash+=adjustment;totals['funding_pnl']+=adjustment
        samples.append(cash)
        if terminal:
            nav[-1]=cash;break
        worst=float(market[i,2] if quantity>=0 else market[i,1]);worst_equity=cash+quantity*(worst-price)
        for rate in rates_intraday[i]:
            debit=-quantity*(market[i,1] if quantity*rate>0 else market[i,2])*rate
            worst_equity+=min(debit,0)
        if quantity:
            margin=worst_equity/(abs(quantity)*worst);minimum_margin=min(minimum_margin,margin)
            if margin<=.01:
                # A conservative solvency failure, not an exact exchange liquidation replay.
                cash=0.;liquidation=True;close_nav.append(0.);samples.append(0.);notional.append(0.)
                for _ in range(i+1,n):nav.append(0.);close_nav.append(0.);samples.extend([0.,0.,0.]);notional.append(0.)
                nav.append(0.);samples.extend([0.,0.]);break
        close=float(market[i,3]);move=quantity*(close-price);cash+=move;totals['price_pnl']+=move
        for rate in rates_intraday[i]:
            mark=(market[i,1] if quantity*rate>0 else market[i,2]) if adverse_funding else price
            payment=-quantity*float(mark)*rate;cash+=payment;totals['funding_pnl']+=payment
        if cash<=0:raise ValueError('profit_nonpositive_equity_without_margin_detection')
        close_nav.append(cash);samples.append(cash);notional.append(abs(quantity)*close);last_price=close
    if not liquidation and abs(cash-initial-totals['price_pnl']-totals['funding_pnl']+totals['fees']+totals['slippage_and_rounding'])>1e-7*max(initial,1):
        raise ValueError('profit_equity_reconciliation')
    return dict(nav=np.array(nav),close_nav=np.array(close_nav),samples=np.array(samples),notional=np.array(notional),orders=orders,
        components=totals,skips=dict(skips),minimum_stressed_margin=None if not np.isfinite(minimum_margin) else minimum_margin,
        max_entry_notional_ratio=max_entry,max_realized_participation=max_participation,max_known_participation=max_known_participation,
        solvency_failure=liquidation)


def portfolio(sleeves,open_at,initial):
    nav=np.sum([s['nav'] for s in sleeves.values()],axis=0);sample=np.sum([s['samples'] for s in sleeves.values()],axis=0)
    close=np.sum([s['close_nav'] for s in sleeves.values()],axis=0);gross=np.sum([s['notional'] for s in sleeves.values()],axis=0)
    peak=np.maximum.accumulate(np.r_[initial,sample]);mdd=float(np.max(1-np.r_[initial,sample]/peak))
    years=(int(open_at[-1])-int(open_at[0]))/(365.25*DAY_MS)
    total=float(nav[-1]/initial-1);cagr=float((nav[-1]/initial)**(1/years)-1) if nav[-1]>0 else -1.
    returns=nav[1:]/np.maximum(nav[:-1],1e-12)-1
    sharpe=float(returns.mean()/returns.std()*np.sqrt(365.25)) if returns.std()>0 and np.all(nav>0) else None
    labels=open_at[:-1].astype('datetime64[ms]').astype('datetime64[Y]').astype(str);yearly={};previous=initial
    for year in np.unique(labels):
        value=float(nav[1:][labels==year][-1]);yearly[str(year)]=value/previous-1;previous=value
    components={k:float(sum(s['components'][k] for s in sleeves.values())) for k in next(iter(sleeves.values()))['components']}
    stats=dict(initial=initial,final_equity=float(nav[-1]),total_return=total,cagr=cagr,mdd_daily_sampled=mdd,
        calmar=cagr/mdd if mdd>0 else None,sharpe_zero_risk_free=sharpe,
        orders=sum(len(s['orders']) for s in sleeves.values()),average_gross_exposure=float(np.mean(gross/np.maximum(close,1e-12))),
        yearly_returns=yearly,components=components,solvency_failures=[a for a,s in sleeves.items() if s['solvency_failure']],
        minimum_stressed_margin=min((s['minimum_stressed_margin'] for s in sleeves.values() if s['minimum_stressed_margin'] is not None),default=None),
        max_realized_participation=max(s['max_realized_participation'] for s in sleeves.values()),
        max_entry_notional_ratio=max(s['max_entry_notional_ratio'] for s in sleeves.values()))
    return stats,nav
