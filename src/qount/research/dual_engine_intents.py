"""Research-only causal risk intents tied to observed position vintages."""
from __future__ import annotations

import copy
import datetime as dt
import math

from qount.research.dual_engine_books import settle_book


def sync_vintages(vintages, old_units, new_units, version):
    """Full fills sell oldest owned units; new purchases receive a new version."""
    for asset in sorted(set(old_units) | set(new_units)):
        lots = vintages.setdefault(asset, {})
        delta = new_units.get(asset, 0.) - old_units.get(asset, 0.)
        if delta > 0:
            lots[version] = lots.get(version, 0.) + delta
        elif delta < 0:
            remaining = -delta
            for vintage in sorted(lots):
                sold = min(remaining, lots[vintage])
                lots[vintage] -= sold; remaining -= sold
            if remaining > 1e-12 * max(1., old_units.get(asset, 0.)):
                raise ValueError('intent_unowned_full_sale')
        vintages[asset] = {v: q for v, q in lots.items() if q > 0}
        expected = new_units.get(asset, 0.)
        residual = expected - math.fsum(vintages[asset].values())
        if abs(residual) > 1e-12 * max(1., expected):
            raise ValueError('intent_full_vintage_reconciliation_failed')
        if expected <= 0:
            vintages[asset] = {}
        elif residual and vintages[asset]:
            # Only reconcile floating-point summation, never create ownership.
            latest = max(vintages[asset])
            vintages[asset][latest] += residual


def reduction_intent(units, weights, vintages, nominal, scale, *, scope=None, pending_assets=()):
    """Snapshot unit reductions; nominal zero is an explicit account-wide exit."""
    names = set(units) | set(pending_assets)
    if scope is not None: names &= set(scope)
    sells = {}; zeros = []
    for asset in sorted(names):
        if nominal.get(asset, 0.) <= 0:
            zeros.append(asset)
            continue
        held_weight = weights.get(asset, 0.)
        if held_weight <= 0: continue
        desired = min(nominal.get(asset, 0.), held_weight) * scale
        fraction = max(0., 1 - desired / held_weight)
        if fraction > 0:
            sells[asset] = {v: q * fraction for v, q in vintages.get(asset, {}).items()}
    return sells, zeros


def execute_reductions(units, vintages, sells, zeros, marks, cash, cost_bps):
    """A captured sale cannot consume units bought after its decision."""
    new = dict(units); requested = {}; actual = {}; zero_set = set(zeros)
    for asset in sorted(set(sells) | zero_set):
        lots = vintages.setdefault(asset, {})
        requests = dict(lots) if asset in zero_set else sells.get(asset, {})
        quantity = 0.
        for vintage, amount in requests.items():
            sold = min(amount, lots.get(vintage, 0.))
            lots[vintage] = lots.get(vintage, 0.) - sold
            quantity += sold
        vintages[asset] = {v: q for v, q in lots.items() if q > 0}
        requested[asset] = math.fsum(requests.values())
        remaining = math.fsum(vintages[asset].values())
        quantity = units.get(asset, 0.) - remaining
        if quantity < -1e-12 * max(1., units.get(asset, 0.)): raise ValueError('intent_unowned_reduction')
        actual[asset] = max(0., quantity)
        if remaining > 0: new[asset] = remaining
        else: new.pop(asset, None)
    notional = sum(q * marks.get(k, 0.) for k, q in actual.items())
    fee = notional * cost_bps / 10000
    return new, cash + notional - fee, fee, notional, requested, actual


def replay_intents(dates, closes, opens, targets, *, start, lag, cost_bps,
                   mode='vintage', cancel_stale=False, core_assets=(), risk_scale=None):
    """Weekly full buys, daily causal reductions, optionally daily satellites.

    No execution-day close is available at the open. Vintage mode uses the
    original delayed decision; current mode uses only the latest closed nominal
    target. Explicit nominal-zero exits and optional cancellation stay distinct.
    """
    if mode not in ('vintage', 'current', 'core_weekly') or lag < 1:
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
        if mode == 'current' and plan and plan['kind'] != 'full': names |= set(latest)
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
        execution_risk = None
        if plan:
            if plan['kind'] == 'full':
                aim = dict(plan['target'])
                if cancel_stale:
                    for k in aim:
                        if aim[k] > 0 and latest.get(k, 0) <= 0:
                            aim[k] = 0.; cancelled.append(k)
                new, cash, fee, _, cap = settle_book(open_nav, cash, units, marks, aim, cost_bps=cost_bps)
                notional = sum(abs(new.get(k, 0) - units.get(k, 0)) * marks.get(k, 0) for k in set(new) | set(units))
                sync_vintages(vintages, units, new, version + 1); units = new
            elif mode == 'current':
                weights = {k: q * closes.get(k, {}).get(dates[t - 1], 0.) / previous_nav for k, q in units.items()}
                aim = {k: min(w, weights.get(k, 0)) for k, w in latest.items() if w > 0 and weights.get(k, 0) > 0}
                scale = risk_scale(t - 1, aim) if risk_scale else 1.
                aim = {k: w * scale for k, w in aim.items()}
                execution_risk = {'date': dates[t - 1], 'target': aim, 'risk_scale': scale}
                new, cash, fee, _, cap = settle_book(open_nav, cash, units, marks, aim, cost_bps=cost_bps, sell_only=True)
                notional = sum(abs(new.get(k, 0) - units.get(k, 0)) * marks.get(k, 0) for k in set(new) | set(units))
                sync_vintages(vintages, units, new, version + 1); units = new
            else:
                units, cash, fee, notional, requested, actual = execute_reductions(
                    units, vintages, plan['sells'], plan['zeros'], marks, cash, cost_bps)
                if mode == 'core_weekly':
                    before_sat = dict(units)
                    sat_scope = (set(units) | set(plan['target'])) - cores
                    after_core_nav = cash + sum(q * marks[k] for k, q in units.items())
                    units, cash, sat_fee, _, cap = settle_book(after_core_nav, cash, units, marks,
                        plan['target'], cost_bps=cost_bps, scope=sat_scope)
                    sat_flow = sum(abs(units.get(k, 0) - before_sat.get(k, 0)) * marks.get(k, 0) for k in set(units) | set(before_sat))
                    fee += sat_fee; notional += sat_flow
                    sync_vintages(vintages, before_sat, units, version + 1)
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
            risk_buy_notional=sum(buys[k] * marks.get(k, 0) for k in buys),
            core_buy_notional=sum(buys.get(k, 0) * marks.get(k, 0) for k in cores), vintage_units_max_error=version_error,
            vintage_units_relative_error=relative_error))
        rows[-1]['return'] = rows[-1].pop('return_')
        vanished = {k for k, value in close_marks.items() if value <= 0}
        for k in vanished: units.pop(k, None); vintages.pop(k, None)
        if t in targets:
            full = dt.date.fromisoformat(day).weekday() == 6
            nominal = targets[t]
            desired = dict(nominal) if full else {k: min(w, weights.get(k, 0)) if mode != 'core_weekly' or k in cores else w
                                                 for k, w in nominal.items()}
            desired = {k: w for k, w in desired.items() if w > 0}
            scale = risk_scale(t, desired) if risk_scale else 1.
            desired = {k: w * scale for k, w in desired.items()}
            pending = sorted({k for j in range(t - lag + 1, t + 1) if j in plans and plans[j]['kind'] == 'full'
                              for k, w in plans[j]['target'].items() if w > 0})
            sells, zeros = reduction_intent(units, weights, vintages, nominal, scale,
                                           scope=cores if mode == 'core_weekly' else None, pending_assets=pending)
            plan = dict(kind='full' if full else 'mixed' if mode == 'core_weekly' else 'reduce', target=desired,
                        sells={} if full else sells, zeros=[] if full else zeros, version=version, decision=day,
                        decision_units=dict(units), nominal_target=dict(nominal), risk_scale=scale, pending_buy_assets=pending)
            plans[t] = plan; decisions.append(copy.deepcopy(plan))
    return dict(records=rows, decisions=decisions, research_only=True, orders_authorized=False)
