"""Offline capital sleeves with explicit transfers and gross sleeve costs."""
from __future__ import annotations

import statistics as stats

from qount.research.dual_engine_books import changed_scopes, settle_book

SHARES = {'equity_crisis': .2, 'gold': .2, 'reserve': .6}


def split_target(target):
    """Keep the old 20% equity/defense budget and its 20% base gold distinct."""
    gold = min(.2, target.get('GLD', 0.))
    risk = {k: w for k, w in target.items() if k not in ('GLD', 'BIL') and w > 0}
    if target.get('GLD', 0.) > gold: risk['GLD'] = target['GLD'] - gold
    if sum(risk.values()) > .2 + 1e-12: raise ValueError('capital_source_budget_invalid')
    risk = {k: w / .2 for k, w in risk.items()}
    risk['BIL'] = max(0., 1 - sum(risk.values()))
    return {'equity_crisis': risk, 'gold': {'GLD': gold / .2, 'BIL': 1 - gold / .2}, 'reserve': {'BIL': 1.}}


def aggregate_units(books):
    result = {}
    for book in books.values():
        for k, q in book['units'].items(): result[k] = result.get(k, 0.) + q
    return result


def reset_capital(books, marks, desired, cost_bps):
    """A monthly transfer is funded by real trades; opposite sleeve fills cost."""
    old = {b + '::' + k: q for b, book in books.items() for k, q in book['units'].items()}
    virtual_marks = {b + '::' + k: v for b in books for k, v in marks.items()}
    targets = {b + '::' + k: SHARES[b] * w for b, aim in desired.items() for k, w in aim.items()}
    cash = sum(book['cash'] for book in books.values())
    nav = cash + sum(q * virtual_marks[k] for k, q in old.items())
    new, new_cash, total_fee, _, _ = settle_book(nav, cash, old, virtual_marks, targets, cost_bps=cost_bps)
    rate = cost_bps / 10000; output = {}; details = {}
    for name, book in books.items():
        units = {k.split('::', 1)[1]: q for k, q in new.items() if k.startswith(name + '::')}
        old_nav = book['cash'] + sum(q * marks[k] for k, q in book['units'].items())
        traded = {k: abs(units.get(k, 0.) - book['units'].get(k, 0.)) * marks[k] for k in set(units) | set(book['units'])}
        fee = rate * sum(traded.values()); own_cash = new_cash * SHARES[name]
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


def replay_capital(dates, closes, opens, targets, *, start, lag, cost_bps, full_refresh, reset_monthly):
    """Three funded source books; locked books reinvest their own gains/losses.

    Equity and crisis sources share the declared original 20% source budget and
    their own BIL financing. Base gold and reserve have separate capital. The
    only cross-book transfer is an explicit monthly reset in the reset variant.
    """
    if lag < 1: raise ValueError('capital_lag_invalid')
    first = next(i for i, d in enumerate(dates) if d >= start)
    if first < lag: raise ValueError('capital_warmup_insufficient')
    desired = {t: split_target(aim) for t, aim in targets.items()}
    scopes = {b: changed_scopes({t: aim[b] for t, aim in desired.items()}, full_refresh) for b in SHARES}
    books = {b: {'cash': share, 'units': {}} for b, share in SHARES.items()}
    rows = []
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
        if aim is not None and (t == first or full and reset_monthly):
            books, details = reset_capital(books, marks, aim, cost_bps)
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
            requested_book_targets=aim, full_refresh=full, capital_reset=bool(aim is not None and (t == first or full and reset_monthly)),
            asset_trade_notional=asset_flow, gross_book_traded_notional=gross_flow, net_external_traded_notional=net_flow,
            internal_opposite_traded_notional=max(0., gross_flow - net_flow), untouched_books_units_max_error=unchanged))
        rows[-1]['return'] = rows[-1].pop('return_')
    return dict(records=rows, research_only=True, orders_authorized=False,
                capital_policy='monthly_reset' if reset_monthly else 'self_financing_locked',
                initial_capital_shares=dict(SHARES), cost_policy='gross independent book turnover, no internal crossing discount')


def capital_contributions(run, dates, closes, opens):
    """Transfers are financing, not profits; assign actual gross book fees."""
    index = {d: t for t, d in enumerate(dates)}
    asset_pnl = {}; book_pnl = {b: {'gross_pnl': 0., 'fees': 0., 'net_pnl': 0., 'capital_transfers': 0.} for b in SHARES}
    old_units = {}; old_books = {b: {'cash': w, 'units': {}, 'nav': w} for b, w in SHARES.items()}
    prior_nav = 1.; max_error = 0.
    for row in run['records']:
        day = row['date']; previous = dates[index[day] - 1]
        gross = {}
        for k in set(old_units) | set(row['units']):
            gross[k] = old_units.get(k, 0.) * (opens[k][day] - closes[k][previous]) + row['units'].get(k, 0.) * (closes[k][day] - opens[k][day])
        for name, book in row['books'].items():
            old = old_books[name]; bpnl = 0.; detail = book_pnl[name]
            for k in set(old['units']) | set(book['units']):
                value = old['units'].get(k, 0.) * (opens[k][day] - closes[k][previous]) + book['units'].get(k, 0.) * (closes[k][day] - opens[k][day])
                bpnl += value
            detail['gross_pnl'] += bpnl; detail['fees'] += book['fee']; detail['net_pnl'] += bpnl - book['fee']
            detail['capital_transfers'] += book['capital_transfer']
            max_error = max(max_error, abs(book['nav'] - old['nav'] - book['capital_transfer'] - bpnl + book['fee']))
        fee = sum(b['fee'] for b in row['books'].values()); flow = sum(row['asset_trade_notional'].values())
        for k in set(gross) | set(row['asset_trade_notional']):
            value = asset_pnl.setdefault(k, {'gross_pnl': 0., 'allocated_fees': 0., 'net_pnl': 0., 'yearly': {}})
            allocated = fee * row['asset_trade_notional'].get(k, 0.) / flow if flow else 0.
            net = gross.get(k, 0.) - allocated
            value['gross_pnl'] += gross.get(k, 0.); value['allocated_fees'] += allocated; value['net_pnl'] += net
            value['yearly'][day[:4]] = value['yearly'].get(day[:4], 0.) + net
        max_error = max(max_error, abs(sum(gross.values()) - fee - row['nav'] + prior_nav))
        prior_nav = row['nav']; old_units = row['units']; old_books = row['books']
    net = run['records'][-1]['nav'] - 1
    max_error = max(max_error, abs(sum(a['net_pnl'] for a in asset_pnl.values()) - net), abs(sum(b['net_pnl'] for b in book_pnl.values()) - net))
    if max_error > 1e-9: raise ValueError('capital_attribution_mismatch')
    return {'status': 'capital_books_reconciled', 'net_wealth_change': net, 'assets': asset_pnl, 'books': book_pnl,
            'max_error': max_error, 'methodology': 'actual aggregate units price PnL; fees on gross independent book fills; transfers excluded from profits; initial NAV units, not CAGR',
            'mean_capital_weights': {b: stats.fmean(r['books'][b]['nav'] / r['nav'] for r in run['records']) for b in SHARES}}
