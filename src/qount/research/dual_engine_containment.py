"""Daily closed exposure containment over funded monthly capital books."""
from __future__ import annotations

import statistics as stats

from qount.research.dual_engine_books import changed_scopes, settle_book

from qount.research.dual_engine_capital import SHARES, split_target, aggregate_units


from qount.research.dual_engine_redistribution import allocation_decision, allocate_capital

def cap_decision(day, books, closes, nav, epochs, limit):
    """Freeze unit ceilings from actual closed exposure, never future marks."""
    plans = {}
    for name in ('equity_crisis', 'gold'):
        book = books[name]
        value = sum(q * closes[k] for k, q in book['units'].items() if k != 'BIL')
        if value <= limit * nav + 1e-12: continue
        ratio = limit * nav / value
        plans[name] = {'decision': day, 'epoch': epochs[name], 'closed_nav': nav,
            'closed_risk_value': value, 'limit': limit,
            'decision_units': {k: q for k, q in book['units'].items() if k != 'BIL'},
            'unit_ceilings': {k: q * ratio for k, q in book['units'].items() if k != 'BIL'}}
    return plans


def execute_cap(book, marks, plan, cost_bps):
    """Reduce to dated unit ceilings; retain financing in the same book's BIL.

    Repeated delayed plans cannot sell the same requested reduction twice. The
    caller invalidates plans when a regular source fill changes the book epoch.
    """
    rate = cost_bps / 10000
    if not 0 <= rate < .5: raise ValueError('containment_cost_invalid')
    units = dict(book['units']); cash = book['cash']; sales = {}; traded = {}
    for k, ceiling in plan['unit_ceilings'].items():
        if k == 'BIL' or ceiling < 0: raise ValueError('containment_ceiling_invalid')
        q = max(0., units.get(k, 0.) - ceiling)
        if q <= 0: continue
        sales[k] = q; traded[k] = q * marks[k]
        units[k] -= q
        if units[k] <= 0: units.pop(k)
    fee = rate * sum(traded.values()); cash += sum(traded.values()) - fee
    if sales:
        if marks.get('BIL', 0.) <= 0: raise ValueError('containment_funding_price_missing')
        amount = cash / (1 + rate); fee += amount * rate
        units['BIL'] = units.get('BIL', 0.) + amount / marks['BIL']
        cash -= amount * (1 + rate); traded['BIL'] = amount
    if cash < -1e-10: raise ValueError('containment_unfunded')
    return {'cash': cash, 'units': units}, {'sales': sales, 'fee': fee, 'traded_notional': traded}


def replay_containment(dates, closes, opens, targets, *, start, lag, cost_bps, full_refresh, limit):
    """Monthly funded shares plus dated daily source risk-unit ceilings.

    Original monthly transfers stay explicit; daily excess exposure sells fund
    same-book BIL. Delay and price movement can overshoot the decision ceiling.
    """
    if limit not in (.2, .4): raise ValueError('containment_limit_invalid')
    policy = 'sweep20' if limit == .2 else 'cap40'
    if lag < 1: raise ValueError('capital_lag_invalid')
    first = next(i for i, d in enumerate(dates) if d >= start)
    if first < lag: raise ValueError('capital_warmup_insufficient')
    desired = {t: split_target(aim) for t, aim in targets.items()}
    scopes = {b: changed_scopes({t: aim[b] for t, aim in desired.items()}, full_refresh) for b in SHARES}
    books = {b: {'cash': share, 'units': {}} for b, share in SHARES.items()}
    rows = []; caps = {}; epochs = {b: 0 for b in SHARES}
    allocations = {t: allocation_decision(dates[t], dict(SHARES), desired[t], policy, warmup=True)
                   for t in full_refresh if first - lag <= t < first and t in desired}
    for t in range(first, len(dates)):
        day = dates[t]; signal = t - lag; aim = desired.get(signal); cap_plan = caps.get(signal, {})
        old_units = aggregate_units(books); old_cash = sum(b['cash'] for b in books.values())
        previous_nav = old_cash + sum(q * closes[k][dates[t - 1]] for k, q in old_units.items())
        names = set(old_units) | {k for shape in (aim or {}).values() for k in shape}
        marks = {}
        for k in names:
            if day not in opens.get(k, {}): raise ValueError('required_capital_open_missing:' + k + ':' + day)
            marks[k] = opens[k][day]
        if cap_plan: names.add('BIL'); marks['BIL'] = opens['BIL'][day]
        open_nav = old_cash + sum(q * marks[k] for k, q in old_units.items())
        full = aim is not None and (t == first or signal in full_refresh)
        details = {}; before = {b: {'cash': v['cash'], 'units': dict(v['units'])} for b, v in books.items()}
        if aim is not None and (t == first or full):
            shares = dict(SHARES) if t == first else allocations[signal]['shares']
            books, details = allocate_capital(books, marks, aim, cost_bps, shares)
            epochs = {b: epoch + 1 for b, epoch in epochs.items()}
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
                epochs[name] += 1
                details[name] = dict(pretrade_nav=own_nav, fee=fee, capital_transfer=0., traded_notional=traded, scope=scope, funding_cap=cap)
        cap_actions = {}
        for name, plan in cap_plan.items():
            if epochs[name] != plan['epoch']:
                cap_actions[name] = {'plan': plan, 'cancelled_epoch': True, 'sales': {}, 'fee': 0.}
                continue
            original = books[name]
            book, extra = execute_cap(original, marks, plan, cost_bps)
            books[name] = book; detail = details[name]
            detail['fee'] += extra['fee']
            for k, amount in extra['traded_notional'].items():
                detail['traded_notional'][k] = detail['traded_notional'].get(k, 0.) + amount
            if extra['sales'] and detail['scope'] is not None:
                detail['scope'] = tuple(sorted(set(detail['scope']) | set(extra['sales'])))
            cap_actions[name] = {'plan': plan, 'cancelled_epoch': False, **extra}
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
            cap_actions=cap_actions, source_epochs=dict(epochs), cap_signal_date=dates[signal] if cap_plan else None,
            book_risk_weights={b: sum(q * closes[k][day] for k, q in book['units'].items() if k != 'BIL') / nav for b, book in books.items()},
            requested_book_targets=aim, full_refresh=full, capital_reset=bool(aim is not None and (t == first or full)),
            capital_allocation=({'decision_date': dates[first-lag], 'shares': dict(SHARES), 'initial': True} if t == first else allocations.get(signal)) if full else None,
            asset_trade_notional=asset_flow, gross_book_traded_notional=gross_flow, net_external_traded_notional=net_flow,
            internal_opposite_traded_notional=max(0., gross_flow - net_flow), untouched_books_units_max_error=unchanged))
        rows[-1]['return'] = rows[-1].pop('return_')
        caps[t] = cap_decision(day, books, {k: closes[k][day] for k in units}, nav, epochs, limit)
        if t in full_refresh and t in desired:
            current = {b: books[b]['cash'] + sum(q * closes[k][day] for k, q in books[b]['units'].items()) for b in SHARES}
            allocations[t] = allocation_decision(day, current, desired[t], policy)
    return dict(records=rows, research_only=True, orders_authorized=False,
                capital_policy=policy, allocation_decisions=allocations, containment_decisions=caps, risk_limit=limit,
                initial_capital_shares=dict(SHARES), cost_policy='gross independent book turnover, no internal crossing discount')
