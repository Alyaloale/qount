"""Round16 explicit family-clock fork; scoped recovery and small-buy inaction."""
from __future__ import annotations

import copy
import datetime as dt
import math

from qount.research.dual_engine_books import settle_book


from qount.research.dual_engine_intents import (sync_vintages, reduction_intent, execute_reductions)


def recovery_scope(day, triggers, cores, names, local):
    if not local:
        from qount.research.dual_engine_family_clock import family_scope
        return family_scope(day, 'sat_week', triggers, cores, names)
    cores, names, triggers = set(cores), set(names), set(triggers)
    scheduled = names-cores if dt.date.fromisoformat(day).weekday()==6 else set()
    scope = set(scheduled)
    if triggers&cores: scope |= names&cores
    if triggers-cores: scope |= names-cores
    return scope, scheduled


def topup_scope(scope, aim, units, marks, nav, plan, band):
    """Suppress only small increases in already-owned, unprotected positions.

    Reduction, zero exits, initial funding, new recovery and continuation never
    enter this filter. Units removed from scope are frozen by the cash solver.
    """
    active = set(aim)|set(units) if scope is None else set(scope)
    if not band or 'decision_weights' not in plan:
        return scope, []
    protected = set(plan['recovered_assets'])|set(plan['continuing_assets'])
    skipped = sorted(k for k in active-protected if units.get(k,0)>0 and marks.get(k,0)>0
        and aim.get(k,0)>0 and 0 < aim[k]*nav/(units[k]*marks[k])-1 <= band)
    return active-set(skipped), skipped


def replay_acquisition(dates, closes, opens, targets, *, start, lag, cost_bps,
                   band=0., local=False, core_assets=(), risk_scale=None):
    """Declared family refreshes and staged recovery acquisition scopes.

    Explicit exits own the whole account; ordinary reductions own vintage units.
    Full and scoped acquisitions cancel assets absent from latest closed targets.
    """
    clock_mode = 'sat_week_local' if local else 'sat_week'
    if band not in (0.,.1,.25) or type(local) is not bool or lag < 1:
        raise ValueError('intent_protocol_invalid')
    if not 0 <= cost_bps < 5000: raise ValueError('intent_cost_invalid')
    first = next(t for t, d in enumerate(dates) if d >= start)
    if first < lag: raise ValueError('intent_warmup_insufficient')
    plans = {t: dict(kind='full', target=dict(targets[t]), nominal_target=dict(targets[t]), version=0, decision=dates[t])
             for t in range(first - lag, first) if t in targets}
    units = {}; cash = 1.; vintages = {}; version = 0; rows = []; decisions = []
    cores = set(core_assets)
    for t in range(first, len(dates)):
        day = dates[t]; signal = t - lag; plan = plans.get(signal)
        old = dict(units)
        previous_nav = cash + sum(q * closes.get(k, {}).get(dates[t - 1], 0.) for k, q in units.items())
        names = set(units) | set(plan.get('target', {}) if plan else {})
        if plan: names |= set(plan.get('sells', {})) | set(plan.get('zeros', []))
        latest = targets.get(t - 1, {})
        marks = {}; missing = []
        for k in names:
            value = opens.get(k, {}).get(day)
            if value is None:
                if day in closes.get(k, {}): raise ValueError('required_intent_open_missing:' + k + ':' + day)
                value = 0.; missing.append(k)
            marks[k] = value
        open_nav = cash + sum(q * marks[k] for k, q in units.items())
        if open_nav <= 0: raise ValueError('intent_bankrupt')
        pre = {k: q * marks[k] / open_nav for k, q in units.items() if marks[k] > 0}
        fee = notional = 0.; cancelled = []; requested = actual = {}; cap = False
        before_version = version; vintage_snapshot = copy.deepcopy(vintages)
        execution_risk = None; suppressed = []; acquisition_units = None; acquisition_nav = None; fill_scope = None; fill_aim = None
        if plan:
            if plan['kind'] == 'full':
                aim = dict(plan['target'])
                for k in aim:
                    if aim[k] > 0 and latest.get(k, 0) <= 0:
                        aim[k] = 0.; cancelled.append(k)
                acquisition_units = dict(units); acquisition_nav = open_nav; fill_aim = dict(aim)
                fill_scope, suppressed = topup_scope(None, aim, units, marks, open_nav, plan, band)
                new, cash, fee, _, cap = settle_book(open_nav, cash, units, marks, aim, cost_bps=cost_bps, scope=fill_scope)
                notional = sum(abs(new.get(k, 0) - units.get(k, 0)) * marks.get(k, 0) for k in set(new) | set(units))
                sync_vintages(vintages, units, new, version + 1); units = new
            else:
                units, cash, fee, notional, requested, actual = execute_reductions(
                    units, vintages, plan['sells'], plan['zeros'], marks, cash, cost_bps)
                if plan['kind'] == 'recover':
                    before_recovery = dict(units)
                    acquisition_scope = set(plan['scope_assets'])
                    recovery_target = dict(plan['target'])
                    for k in acquisition_scope:
                        if recovery_target.get(k, 0.) > 0 and latest.get(k, 0.) <= 0:
                            recovery_target[k] = 0.; cancelled.append(k)
                    recovery_nav = cash + sum(q * marks[k] for k, q in units.items())
                    acquisition_units = dict(units); acquisition_nav = recovery_nav; fill_aim = dict(recovery_target)
                    fill_scope, suppressed = topup_scope(acquisition_scope, recovery_target, units, marks, recovery_nav, plan, band)
                    units, cash, recovery_fee, _, cap = settle_book(recovery_nav, cash, units, marks,
                        recovery_target, cost_bps=cost_bps, scope=fill_scope)
                    recovery_flow = sum(abs(units.get(k, 0) - before_recovery.get(k, 0)) * marks.get(k, 0) for k in set(units) | set(before_recovery))
                    fee += recovery_fee; notional += recovery_flow
                    sync_vintages(vintages, before_recovery, units, version + 1)
            if notional > 1e-15: version += 1
        close_marks = {k: closes.get(k, {}).get(day, 0.) for k in units}
        missing.extend(k for k, value in close_marks.items() if value <= 0)
        nav = cash + sum(q * close_marks[k] for k, q in units.items())
        if nav <= 0: raise ValueError('intent_bankrupt_at_close')
        weights = {k: q * close_marks[k] / nav for k, q in units.items() if close_marks[k] > 0}
        post_open = open_nav - fee
        effective = {k: q * marks[k] / post_open for k, q in units.items() if marks[k] > 0} if plan else None
        buys = {k: max(units.get(k, 0) - old.get(k, 0), 0.) for k in set(old) | set(units)}
        version_error = max((abs(sum(v.values()) - units.get(k, 0.)) for k, v in vintages.items()), default=0.)
        relative_error = max((abs(math.fsum(v.values()) - units.get(k, 0.)) / max(1., units.get(k, 0.)) for k, v in vintages.items()), default=0.)
        if relative_error > 1e-12: raise ValueError('intent_vintage_units_mismatch')
        rows.append(dict(date=day, signal_date=dates[signal] if plan else None, return_=nav / previous_nav - 1,
            nav=nav, cash_return=0., turnover=notional / open_nav, cost_fraction=fee / open_nav,
            gross=sum(weights.values()), risk_gross=sum(weights.values()), weights=weights,
            target_weights=effective, pretrade_weights=pre, cash=cash, units=dict(units), missing_marks=missing,
            no_fills=[k for k in (plan.get('target', {}) if plan else {}) if plan['target'][k] > 0 and marks.get(k, 0) <= 0],
            trade_clock=plan['kind'] if plan else 'hold', intent=copy.deepcopy(plan), account_version_before=before_version,
            account_version_after=version, version_mismatch=bool(plan and plan['version'] != before_version),
            vintages_before=vintage_snapshot, vintages=copy.deepcopy(vintages), requested_sale_units=requested,
            actual_sale_units=actual, execution_risk=execution_risk, cancelled_stale=cancelled, funding_cap=cap,
            requested_scope=copy.deepcopy(plan.get('scope_assets')) if plan else None,
            risk_buy_notional=sum(buys[k] * marks.get(k, 0) for k in buys),
            core_buy_notional=sum(buys.get(k, 0) * marks.get(k, 0) for k in cores), vintage_units_max_error=version_error,
            suppressed_topups=suppressed, acquisition_before_units=acquisition_units,
            acquisition_open_nav=acquisition_nav, effective_acquisition_scope=sorted(fill_scope) if fill_scope is not None else None,
            execution_acquisition_target=fill_aim,
            vintage_units_relative_error=relative_error))
        rows[-1]['return'] = rows[-1].pop('return_')
        vanished = {k for k, value in close_marks.items() if value <= 0}
        for k in vanished: units.pop(k, None); vintages.pop(k, None)
        if t in targets:
            weekly = dt.date.fromisoformat(day).weekday() == 6
            nominal = targets[t]
            prior_nominal = targets.get(t - 1, {})
            recovered = sorted(k for k, w in nominal.items() if w > 0 and prior_nominal.get(k, 0.) <= 0)
            continuing = sorted(k for k in plans.get(t - 1, {}).get('recovered_assets', []) if nominal.get(k, 0.) > 0)
            triggers = set(recovered) | set(continuing)
            scope, scheduled = recovery_scope(day, triggers, cores, set(nominal) | set(units), local)
            full = scope is None
            acquire = bool(scope) and not full
            if full:
                desired = dict(nominal)
            else:
                desired = {k: w if acquire and k in scope else min(w, weights.get(k, 0.)) for k, w in nominal.items()}
            if not weekly:
                for k in recovered: desired[k] *= .5
            desired = {k: w for k, w in desired.items() if w > 0}
            scale = risk_scale(t, desired) if risk_scale else 1.
            desired = {k: w * scale for k, w in desired.items()}
            pending = sorted({k for j in range(t - lag + 1, t + 1) if j in plans and plans[j]['kind'] in ('full', 'recover')
                              for k, w in plans[j]['target'].items() if w > 0})
            # A scoped fill owns its active-zone trades. Ordinary vintage reductions
            # own the complement; no asset is sold and repurchased by both paths.
            reduction_scope = (set(units) | set(pending)) - scope if acquire else None
            sells, zeros = reduction_intent(units, weights, vintages, nominal, scale,
                                           scope=reduction_scope, pending_assets=pending)
            plan = dict(kind='full' if full else 'recover' if acquire else 'reduce', target=desired,
                        sells={} if full else sells, zeros=[] if full else zeros, version=version, decision=day,
                        recovered_assets=recovered, continuing_assets=continuing, weekly=weekly, clock_mode=clock_mode,
                        scope_assets=sorted(scope) if acquire else None, refresh_assets=sorted(scheduled),
                        decision_units=dict(units), decision_weights=dict(weights), nominal_target=dict(nominal),
                        risk_scale=scale, pending_buy_assets=pending)
            plans[t] = plan; decisions.append(copy.deepcopy(plan))
    return dict(records=rows, decisions=decisions, clock_mode=clock_mode, topup_band=band, local_recovery=local, research_only=True, orders_authorized=False)
