"""Small offline bracket replay; no exchange client or order permissions.

Each asset has its own funded sleeve. Signals are frozen before execution;
one position per sleeve, fixed quantity, at most 1x entry notional. Stops take
priority when both barriers occur in one candle. Execution prices are adverse
tick-rounded after slippage. Funding inside an uncertain exit candle charges
possible debits and excludes possible credits.
"""
from __future__ import annotations

from collections import Counter
import math

import numpy as np


def execution_price(reference, side, *, opening, slippage, tick):
    transaction_side=side if opening else -side
    value=reference*(1+transaction_side*slippage)
    if tick:
        value=(math.ceil(value/tick-1e-10) if transaction_side>0 else math.floor(value/tick+1e-10))*tick
    return value


def bracket_exit(bar, side, stop, target):
    """Reference price/reason; gaps through stops execute at the worse open."""
    o,h,l=map(float,bar[1:4])
    if side*(o-stop)<=0:return o,'stop_gap'
    if target is not None and side*(o-target)>=0:return target,'target_gap'
    stopped=l<=stop if side>0 else h>=stop
    targeted=target is not None and (h>=target if side>0 else l<=target)
    if stopped:return stop,'stop_both' if targeted else 'stop'
    if targeted:return target,'target'
    return None,None


def position_size(equity, entry, stop, fraction, rules, capacity):
    if equity<=0 or not 0<fraction<=1 or entry<=0 or entry==stop:return 0.
    # Costs are included in the risk distance and entry capital reserve.
    fee=rules['fee'];slip=rules['slippage']
    distance=abs(entry-stop)+entry*(2*fee+2*slip)
    qty=min(equity*fraction/(entry*(1+fee)),equity*.01*fraction/distance,
            capacity/entry,rules.get('max_qty',float('inf')))
    step=rules['step']
    qty=math.floor(qty/step+1e-10)*step
    if qty<rules['min_qty'] or qty*entry<rules['min_notional']:return 0.
    return qty


def replay_asset(bars,decisions,funding,*,initial,rules):
    """bars: Binance-style [open_ms,o,h,l,c,v,close_ms,...].

    decisions contain only known_at, entry_at, stop/target geometry, side,
    fraction, max_bars, and capacity known at decision. No future labels.
    Funding uses retained actual timestamps and marks; blank marks explicitly
    fall back to that candle's open (recorded). Open-time funding settles before
    exit/re-entry; a new position does not receive the same timestamp payment.
    """
    bars=np.asarray(bars,float)
    if len(bars)==0 or np.any(np.diff(bars[:,0])<=0):raise ValueError('profit_bar_clock')
    starts=bars[:,0].astype(np.int64);ends=bars[:,6].astype(np.int64)
    schedule={};skips=Counter();fund={};approx=0
    for d in decisions:
        if d['known_at']>=d['entry_at']:raise ValueError('profit_decision_clock')
        if d['entry_at'] in schedule:raise ValueError('profit_duplicate_entry')
        if d['entry_at'] not in starts:skips['entry_not_in_cache']+=1;continue
        schedule[d['entry_at']]=d
    for e in funding:
        t=int(e['fundingTime']);i=int(np.searchsorted(starts,t,side='right')-1)
        if i<0 or t>ends[i]:continue
        mark=float(e.get('markPrice') or bars[i,1]);approx+=not bool(e.get('markPrice'))
        value=float(e['fundingRate'])*mark
        fund.setdefault(i,[]).append((t,value))
    cash=float(initial);position=None;trades=[];nav=[];exposure=[];max_entry_notional=0.

    def settle(value):
        nonlocal cash
        cash+=value;position['funding']+=value

    def close(reference,time,reason):
        nonlocal cash,position
        p=position;exit_=execution_price(reference,p['side'],opening=False,
                                        slippage=rules['slippage'],tick=rules['tick'])
        fee=p['quantity']*exit_*rules['fee']
        cash+=p['side']*p['quantity']*(exit_-p['entry'])-fee
        gross=p['side']*p['quantity']*(reference-p['reference'])
        friction=p['quantity']*p['side']*((p['entry']-p['reference'])+(reference-exit_))
        trade=dict(known_at=p['known_at'],entry_at=p['entry_at'],exit_at=int(time),side=p['side'],
            quantity=p['quantity'],entry=p['entry'],exit=exit_,reason=reason,
            gross_pnl=gross,slippage_and_rounding=friction,fees=p['entry_fee']+fee,
            funding=p['funding'],net_pnl=gross-friction-p['entry_fee']-fee+p['funding'])
        trades.append(trade);position=None

    for i,b in enumerate(bars):
        t=int(b[0]);end=int(b[6]);bar_fund=fund.get(i,[])
        if position and i and rules.get('continuous_clock',True) and t>int(bars[i-1,6])+1:
            raise ValueError('profit_position_crosses_missing_prices')
        # Old positions own settlement at the open, before scheduled exits.
        if position:
            for stamp,value in bar_fund:
                if stamp==t and stamp>position['entry_at']:settle(-position['side']*position['quantity']*value)
            if i>=position['deadline']:close(float(b[1]),t,'horizon')
        d=schedule.get(t)
        if d:
            if position:skips['already_holding']+=1
            elif d['fraction']<=0:skips['model_cash']+=1
            else:
                side=d['side'];stop=float(d['stop']);target=d.get('target')
                entry=execution_price(float(b[1]),side,opening=True,slippage=rules['slippage'],tick=rules['tick'])
                valid=side*(float(b[1])-stop)>0 and side*(entry-stop)>0 and (target is None or side*(target-entry)>0)
                # Require midpoint reward to cover four assumed round trips.
                if target is not None:valid&=side*(target-entry)/entry>=8*(rules['fee']+rules['slippage'])
                if not valid:skips['entry_geometry_or_reward']+=1
                else:
                    qty=position_size(cash,entry,stop,float(d['fraction']),rules,float(d['capacity']))
                    if not qty:skips['lot_or_capacity']+=1
                    else:
                        entry_fee=qty*entry*rules['fee'];cash-=entry_fee
                        position=dict(d,quantity=qty,entry=entry,reference=float(b[1]),entry_fee=entry_fee,
                                      funding=0.,deadline=i+int(d['max_bars']))
                        max_entry_notional=max(max_entry_notional,qty*entry/(cash+entry_fee))
        # Barrier events are processed after entry; same-bar ties lose first.
        reference=reason=None
        if position:reference,reason=bracket_exit(b,position['side'],position['stop'],position.get('target'))
        if position:
            for stamp,value in bar_fund:
                if stamp<=t or stamp<=position['entry_at']:continue
                payment=-position['side']*position['quantity']*value
                if reference is None or payment<0:settle(payment)
            if reference is not None:close(reference,end,reason)
        if i==len(bars)-1 and position:close(float(b[4]),end,'cache_end')
        marked=cash if position is None else cash+position['side']*position['quantity']*(float(b[4])-position['entry'])
        if marked<=0:raise ValueError('profit_insolvent_sleeve')
        nav.append(marked);exposure.append(0. if position is None else position['quantity']*float(b[4])/marked)
    if abs(cash-initial-sum(r['net_pnl'] for r in trades))>1e-7*max(initial,1):raise ValueError('profit_cash_accounting')
    return dict(times=ends,nav=np.array(nav),exposure=np.array(exposure),
        trades=trades,skips=dict(skips),approximate_funding_marks=int(approx),max_entry_notional=max_entry_notional)


def summarize_portfolio(sleeves,initial,*,continuous):
    clocks=next(iter(sleeves.values()))['times']
    if any(not np.array_equal(s['times'],clocks) for s in sleeves.values()):raise ValueError('profit_portfolio_calendar')
    nav=np.sum([s['nav'] for s in sleeves.values()],axis=0);curve=np.r_[initial,nav]
    peak=np.maximum.accumulate(curve);mdd=float(np.max(1-curve/peak))
    years=(int(clocks[-1])-int(sleeves[next(iter(sleeves))]['start_at']))/(365.25*86400000)
    total=float(nav[-1]/initial-1)
    if abs(total)<1e-12:total=0.
    trades=[dict(asset=a,**r) for a,s in sleeves.items() for r in s['trades']]
    year_returns={};previous=initial
    years_labels=clocks.astype('datetime64[ms]').astype('datetime64[Y]').astype(str)
    for year in sorted(set(years_labels)):
        final=float(nav[np.flatnonzero(years_labels==year)[-1]])
        year_returns[year]=final/previous-1;previous=final
    totals={k:sum(t[k] for t in trades) for k in ['gross_pnl','fees','slippage_and_rounding','funding','net_pnl']}
    cagr=(1+total)**(1/years)-1 if continuous and years>0 else None
    return dict(initial=initial,final_equity=float(nav[-1]),total_return=total,cagr=cagr,mdd_close=mdd,
        calmar=cagr/mdd if cagr is not None and mdd>0 else None,
        trades=len(trades),win_rate=float(np.mean([t['net_pnl']>0 for t in trades])) if trades else None,
        average_exposure=float(np.mean(np.mean([s['exposure'] for s in sleeves.values()],axis=0))),
        yearly_returns=year_returns,components=totals,skips={a:s['skips'] for a,s in sleeves.items()},
        approximate_funding_marks=sum(s['approximate_funding_marks'] for s in sleeves.values()),
        max_entry_notional=max(s['max_entry_notional'] for s in sleeves.values())),clocks,nav,trades
