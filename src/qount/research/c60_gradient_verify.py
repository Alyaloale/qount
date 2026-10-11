"""Independent cash/unit replay of saved gradient ledgers; no shared fee solver."""
from __future__ import annotations

import math
import datetime as dt


def verify_ledger(records, raw, opens, *, cost_bps, deadband):
    cash, units, nav = 1., {}, 1.
    largest = 0.
    checked = 0

    def compare(a, b):
        nonlocal largest, checked
        error = abs(a-b)/max(1., abs(a), abs(b))
        largest = max(largest, error)
        checked += 1
        if error > 2e-10 or not math.isfinite(error):
            raise ValueError('independent_ledger_reconciliation_failed')

    for row in records:
        day = row['date']
        prior_day = (dt.date.fromisoformat(day)-dt.timedelta(days=1)).isoformat()
        # A missing asset is conservatively written off, as in the frozen
        # historical policy; a valid open must not be silently manufactured.
        values = {}
        for asset_id, quantity in units.items():
            symbol = asset_id.split('@')[0]
            price = opens.get(symbol, {}).get(day)
            values[asset_id] = quantity*price if price is not None else 0.
        pre_nav = cash+sum(values.values())
        pre = {k: v/pre_nav for k,v in values.items() if v>0}
        for k in set(pre) | set(row['pretrade_weights']):
            compare(pre.get(k,0.),row['pretrade_weights'].get(k,0.))
        requested = row['requested_weights']
        target = {}
        # This study has no stale-buy cancellation; all requests use a finalized
        # historical close. The first account starts from cash independently.
        for k,w in requested.items():
            symbol = k.split('@')[0]
            if day in opens.get(symbol,{}) and prior_day in raw.get(symbol,{}):
                target[k] = w
        suggested = sum(abs(target.get(k,0.)-pre.get(k,0.)) for k in set(target)|set(pre))
        compare(suggested,row['suggested_turnover'])
        suppress = deadband>0 and suggested<=deadband+1e-12
        if suppress != row['deadband_suppressed']:
            raise ValueError('independent_deadband_decision_disagrees')
        if suppress:
            target = pre
        for k in set(target)|set(row['weights']):
            compare(target.get(k,0.),row['weights'].get(k,0.))
        # Currency-domain bisection, independent of the production fixed point.
        rate = cost_bps/10000
        lo,hi = 0.,pre_nav
        for _ in range(80):
            fee=(lo+hi)/2
            traded=sum(abs((pre_nav-fee)*target.get(k,0.)-values.get(k,0.))
                       for k in set(values)|set(target))
            if fee>rate*traded:hi=fee
            else:lo=fee
        fee=(lo+hi)/2
        compare(fee/pre_nav,row['cost_fraction'])
        compare(sum(abs((pre_nav-fee)*target.get(k,0.)-values.get(k,0.))
                    for k in set(values)|set(target))/pre_nav,row['actual_turnover'])
        post=pre_nav-fee
        cash=post*(1-sum(target.values()))
        units={k:post*w/opens[k.split('@')[0]][day] for k,w in target.items() if w>0}
        close_value=0.
        for k,quantity in units.items():
            quote=raw.get(k.split('@')[0],{}).get(day)
            close_value+=quantity*quote[0] if quote else 0.
        units={k:q for k,q in units.items() if day in raw.get(k.split('@')[0],{})}
        current_nav=cash+close_value
        compare(current_nav/nav-1,row['return'])
        compare(cash/pre_nav,row['post_fee_cash'])
        nav=current_nav
    return {'records':len(records),'numeric_checks':checked,'maximum_relative_error':largest,
            'final_nav':nav,'status':'passed'}
