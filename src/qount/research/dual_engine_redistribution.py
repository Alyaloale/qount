"""Closed-decision profit sweeps and bounded source capital, research only."""
from __future__ import annotations

import statistics as stats

from qount.research.dual_engine_books import changed_scopes, settle_book

from qount.research.dual_engine_capital import SHARES, split_target, aggregate_units


def allocation_decision(day, book_nav, desired, policy, *, warmup=False):
    """Freeze shares from the known closed account, including all-cash warmup."""
    nav = sum(book_nav.values())
    if policy in ('sweep20', 'cap40'):
        limit = .2 if policy == 'sweep20' else .4
        shares = {b: min(book_nav[b] / nav, limit) for b in ('equity_crisis', 'gold')}
    else:
        shares = {b: .2 if sum(w for k, w in desired[b].items() if k != 'BIL') > 0 else 0.
                  for b in ('equity_crisis', 'gold')}
    shares['reserve'] = 1 - sum(shares.values())
    return {'decision_date': day, 'shares': shares, 'closed_book_nav': book_nav,
            'closed_nav': nav, 'policy': policy, 'initial': False, 'warmup': warmup}


def allocate_capital(books, marks, desired, cost_bps, shares):
    """Fund requested shares with gross virtual book fills and zero-sum transfers."""
    if set(shares) != set(SHARES) or min(shares.values()) < 0 or abs(sum(shares.values()) - 1) > 1e-12:
        raise ValueError("capital_allocation_unfunded")
    old = {b + '::' + k: q for b, book in books.items() for k, q in book['units'].items()}
    virtual_marks = {b + '::' + k: v for b in books for k, v in marks.items()}
    targets = {b + '::' + k: shares[b] * w for b, aim in desired.items() for k, w in aim.items()}
    cash = sum(book['cash'] for book in books.values())
    nav = cash + sum(q * virtual_marks[k] for k, q in old.items())
    new, new_cash, total_fee, _, _ = settle_book(nav, cash, old, virtual_marks, targets, cost_bps=cost_bps)
    rate = cost_bps / 10000; output = {}; details = {}
    for name, book in books.items():
        units = {k.split('::', 1)[1]: q for k, q in new.items() if k.startswith(name + '::')}
        old_nav = book['cash'] + sum(q * marks[k] for k, q in book['units'].items())
        traded = {k: abs(units.get(k, 0.) - book['units'].get(k, 0.)) * marks[k] for k in set(units) | set(book['units'])}
        fee = rate * sum(traded.values()); own_cash = new_cash * shares[name]
        after_nav = own_cash + sum(q * marks[k] for k, q in units.items())
        transfer = after_nav + fee - old_nav
        output[name] = {'cash': own_cash, 'units': units}
        details[name] = dict(pretrade_nav=old_nav, fee=fee, capital_transfer=transfer,
                             traded_notional=traded, scope=None, funding_cap=False)
    if abs(sum(d['fee'] for d in details.values()) - total_fee) > 1e-10:
        raise ValueError('capital_fee_allocation_mismatch')
    if abs(sum(d['capital_transfer'] for d in details.values())) > 1e-10:
        raise ValueError('capital_transfer_unfunded')
    return output, details


def replay_redistribution(dates, closes, opens, targets, *, start, lag, cost_bps, full_refresh, policy):
    """Monthly shares are decided at the signal close, filled after lag.

    Allocations do not enforce a continuous intramonth cap. Capital transfers
    fund actual gross source-book trades; all other signals keep scoped fills.
    """
    if policy not in ('sweep20', 'cap40', 'active20'): raise ValueError('redistribution_policy_invalid')
    if lag < 1: raise ValueError('capital_lag_invalid')
    first = next(i for i, d in enumerate(dates) if d >= start)
    if first < lag: raise ValueError('capital_warmup_insufficient')
    desired = {t: split_target(aim) for t, aim in targets.items()}
    scopes = {b: changed_scopes({t: aim[b] for t, aim in desired.items()}, full_refresh) for b in SHARES}
    books = {b: {'cash': share, 'units': {}} for b, share in SHARES.items()}
    rows = []
    allocations = {t: allocation_decision(dates[t], dict(SHARES), desired[t], policy, warmup=True)
                   for t in full_refresh if first - lag <= t < first and t in desired}
    for t in range(first, len(dates)):
        day = dates[t]; signal = t - lag; aim = desired.get(signal)
        old_units = aggregate_units(books); old_cash = sum(b['cash'] for b in books.values())
        previous_nav = old_cash + sum(q * closes[k][dates[t - 1]] for k, q in old_units.items())
        names = set(old_units) | {k for shape in (aim or {}).values() for k in shape}
        marks = {}
        for k in names:
            if day not in opens.get(k, {}): raise ValueError('required_capital_open_missing:' + k + ':' + day)
            marks[k] = opens[k][day]
        open_nav = old_cash + sum(q * marks[k] for k, q in old_units.items())
        full = aim is not None and (t == first or signal in full_refresh)
        details = {}; before = {b: {'cash': v['cash'], 'units': dict(v['units'])} for b, v in books.items()}
        if aim is not None and (t == first or full):
            shares = dict(SHARES) if t == first else allocations[signal]['shares']
            books, details = allocate_capital(books, marks, aim, cost_bps, shares)
        else:
            for name, book in books.items():
                own_nav = book['cash'] + sum(q * marks[k] for k, q in book['units'].items())
                scope = scopes[name].get(signal) if aim is not None else ()
                if aim is None or scope == ():
                    details[name] = dict(pretrade_nav=own_nav, fee=0., capital_transfer=0., traded_notional={}, scope=(), funding_cap=False)
                    continue
                units, cash, fee, _, cap = settle_book(own_nav, book['cash'], book['units'], marks,
                    aim[name], cost_bps=cost_bps, scope=scope, cash_asset='BIL')
                traded = {k: abs(units.get(k, 0.) - book['units'].get(k, 0.)) * marks[k] for k in set(units) | set(book['units'])}
                books[name] = {'cash': cash, 'units': units}
                details[name] = dict(pretrade_nav=own_nav, fee=fee, capital_transfer=0., traded_notional=traded, scope=scope, funding_cap=cap)
        units = aggregate_units(books); cash = sum(b['cash'] for b in books.values())
        nav = cash + sum(q * closes[k][day] for k, q in units.items())
        fee = sum(d['fee'] for d in details.values())
        gross_flow = sum(sum(d['traded_notional'].values()) for d in details.values())
        net_flow = sum(abs(units.get(k, 0.) - old_units.get(k, 0.)) * marks[k] for k in set(units) | set(old_units))
        asset_flow = {}
        book_rows = {}; unchanged = 0.
        for name, book in books.items():
            detail = details[name]
            for k, value in detail['traded_notional'].items(): asset_flow[k] = asset_flow.get(k, 0.) + value
            own_nav = book['cash'] + sum(q * closes[k][day] for k, q in book['units'].items())
            book_rows[name] = {**book, 'nav': own_nav, **detail}
            if detail['scope'] == ():
                unchanged = max(unchanged, max((abs(book['units'].get(k, 0.) - q) for k, q in before[name]['units'].items()), default=0.))
        if cash < -1e-9 or nav <= 0: raise ValueError('capital_bankrupt_or_unfunded')
        weights = {k: q * closes[k][day] / nav for k, q in units.items()}
        effective = {k: q * marks[k] / (open_nav - fee) for k, q in units.items()} if aim is not None else None
        rows.append(dict(date=day, signal_date=dates[signal] if aim is not None else None,
            return_=nav / previous_nav - 1, nav=nav,
            cash_return=closes['BIL'][day] / closes['BIL'][dates[t - 1]] - 1,
            turnover=gross_flow / open_nav, cost_fraction=fee / open_nav, gross=sum(weights.values()),
            risk_gross=sum(w for k, w in weights.items() if k != 'BIL'), weights=weights,
            pretrade_weights={k: q * marks[k] / open_nav for k, q in old_units.items()}, target_weights=effective,
            cash=cash, units=units, missing_marks=[], no_fills=[], books=book_rows,
            requested_book_targets=aim, full_refresh=full, capital_reset=bool(aim is not None and (t == first or full)),
            capital_allocation=({'decision_date': dates[first-lag], 'shares': dict(SHARES), 'initial': True} if t == first else allocations.get(signal)) if full else None,
            asset_trade_notional=asset_flow, gross_book_traded_notional=gross_flow, net_external_traded_notional=net_flow,
            internal_opposite_traded_notional=max(0., gross_flow - net_flow), untouched_books_units_max_error=unchanged))
        rows[-1]['return'] = rows[-1].pop('return_')
        if t in full_refresh and t in desired:
            current = {b: books[b]['cash'] + sum(q * closes[k][day] for k, q in books[b]['units'].items()) for b in SHARES}
            allocations[t] = allocation_decision(day, current, desired[t], policy)
    return dict(records=rows, research_only=True, orders_authorized=False,
                capital_policy=policy, allocation_decisions=allocations,
                initial_capital_shares=dict(SHARES), cost_policy='gross independent book turnover, no internal crossing discount')

