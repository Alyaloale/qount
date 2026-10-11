"""No-order BTC carry feasibility: separate spot capital, margin and settlement."""
from __future__ import annotations

import datetime as dt
import json
import math
import shutil
from pathlib import Path

from qount.research import dual_engine_optimization as old
from qount.research.dual_engine_execution_study import verify_manifest
from qount.research.dual_engine_expansion import require_storage
from qount.research.dual_engine_cashflow_data import UTC, acquire

RULES = ('btc_fully_funded_monthly', 'cash', 'hedge_no_funding')


def read_contract(path: Path):
    c = json.loads(path.read_text())
    if (c.get('study_id') != 'dual_engine_cashflow_20261005' or c.get('research_only') is not True
            or c.get('orders_authorized') is not False or c.get('promotion_evidence') is not False
            or c.get('evaluation') != {'first': '2021-01-01', 'last': '2026-08-31'}
            or c.get('candidate_rules') != list(RULES[:1]) or c.get('control_rules') != list(RULES[1:])
            or c.get('cost_bps_per_leg_per_side') != [25, 50] or c.get('delay_days') != [0, 1]
            or c.get('candidate_trials') != 1 or c.get('curve_count') != 12
            or c.get('acquisition') != {'first_month': '2020-12', 'last_month': '2026-08', 'symbol': 'BTCUSDT', 'workers': 6}):
        raise ValueError('cashflow_frozen_contract_changed')
    return c


def replay(prices, events, *, rule, cost_bps, delay):
    """Monthly fully closed paired book; incomplete margin qualification is explicit."""
    if rule not in RULES or cost_bps not in (25, 50) or delay not in (0, 1):
        raise ValueError('cashflow_undeclared_cell')
    days = sorted(prices)
    fee = cost_bps / 10000
    byday = {d: [] for d in days}
    for e in events:
        byday[e['day']].append(e)
        when = dt.datetime.fromtimestamp(e['timestamp_ms'] / 1000, UTC)
        if ((when.day == 1 + delay and when.hour == 1) or (e['day'] == days[-1] and when.hour == 23)):
            raise ValueError('cashflow_funding_collides_with_trade_hour')
    wallet = previous_nav = 1.0
    q = entry_perp = 0.0
    active = None
    records, payments, trades, episodes, breaches, unknown = [], [], [], [], [], []
    for day in days:
        p = prices[day]
        date = dt.date.fromisoformat(day)
        for hour in range(24):
            epoch = int(dt.datetime.combine(date, dt.time(hour), UTC).timestamp() * 1000)
            # Actual archive milliseconds remain intact. Trades are 01:00 or 23:00,
            # well outside the documented +/-15s nominal funding boundary.
            hour_events = [e for e in byday[day] if epoch <= e['timestamp_ms'] < epoch + 3600000]
            start_wallet = wallet
            negative_lower = 0.0
            for e in hour_events:
                payment = q * e['rate'] * e['mark_proxy'] if rule == RULES[0] else 0.0
                lower = q * e['rate'] * (e['mark_lower'] if e['rate'] >= 0 else e['mark_upper']) if rule == RULES[0] else 0.0
                upper = q * e['rate'] * (e['mark_upper'] if e['rate'] >= 0 else e['mark_lower']) if rule == RULES[0] else 0.0
                wallet += payment
                negative_lower += min(lower, 0.0)
                if q:
                    row = {**e, 'quantity': q, 'payment': payment, 'lower': lower, 'upper': upper, 'episode_id': active['id']}
                    payments.append(row)
                    active['funding'] += payment
                    active['funding_lower'] += lower
                    active['funding_upper'] += upper
            boundary = date.day == 1 + delay and hour == 1
            terminal = day == days[-1] and hour == 23
            if boundary or terminal:
                s, f = p['spot_open' + str(hour)], p['perp_open' + str(hour)]
                if q:
                    close_fee = fee * q * (s + f)
                    wallet += q * (s + entry_perp - f) - close_fee
                    active.update(exit_ms=epoch, exit_spot=s, exit_perp=f, exit_fee=close_fee,
                        basis_pnl=q * ((s - active['entry_spot']) + (entry_perp - f)),
                        ending_nav=wallet, net_pnl=wallet - active['starting_nav'])
                    episodes.append(active)
                    trades.append({'timestamp_ms': epoch, 'side': 'close', 'quantity': q, 'spot': s, 'perp': f,
                                   'fees': close_fee, 'wallet_after': wallet, 'episode_id': active['id']})
                    q = entry_perp = 0.0
                    active = None
                if boundary and not terminal and rule != 'cash':
                    starting = wallet
                    q = wallet / (2 * s + fee * (s + f))
                    entry_fee = fee * q * (s + f)
                    wallet -= q * s + entry_fee
                    entry_perp = f
                    active = {'id': len(episodes) + 1, 'entry_ms': epoch, 'entry_spot': s, 'entry_perp': f,
                              'quantity': q, 'starting_nav': starting, 'entry_fee': entry_fee,
                              'funding': 0.0, 'funding_lower': 0.0, 'funding_upper': 0.0}
                    trades.append({'timestamp_ms': epoch, 'side': 'open', 'quantity': q, 'spot': s, 'perp': f,
                                   'fees': entry_fee, 'wallet_after': wallet, 'episode_id': active['id']})
            if q:
                # At an opening/reset hour all funding precedes trades; use the new
                # wallet. Otherwise worst price is combined with all hour debits.
                stress_wallet = wallet if boundary else start_wallet + negative_lower
                high = p['mark_hour_high'][hour]
                if not p.get('mark_hour_complete', [True] * 24)[hour]:
                    unknown.append({'day': day, 'hour': hour, 'episode_id': active['id']})
                if high <= 0:
                    continue
                margin_equity = stress_wallet + q * (entry_perp - high)
                reserve = q * high * (0.05 + fee)
                if margin_equity <= reserve:
                    breaches.append({'day': day, 'hour': hour, 'equity': margin_equity, 'reserve': reserve,
                                     'episode_id': active['id'], 'role': 'conservative maintenance proxy; not historical liquidation'})
        nav = wallet + q * (p['spot_close'] + entry_perp - p['mark_close'])
        if not math.isfinite(nav) or nav <= 0 or wallet <= 0:
            raise ValueError('cashflow_book_insolvent')
        records.append({'date': day, 'nav': nav, 'return': nav / previous_nav - 1, 'wallet': wallet,
                        'quantity': q, 'entry_perp': entry_perp, 'spot_close': p['spot_close'], 'mark_close': p['mark_close']})
        previous_nav = nav
    if q or active:
        raise ValueError('cashflow_terminal_not_flat')
    total_funding = math.fsum(e['payment'] for e in payments)
    total_basis = math.fsum(e['basis_pnl'] for e in episodes)
    total_fees = math.fsum(t['fees'] for t in trades)
    if abs(total_funding + total_basis - total_fees - (wallet - 1)) > 1e-10:
        raise ValueError('cashflow_wealth_identity')
    m = old._metrics([r['return'] for r in records], 365)
    m.update(first=days[0], last=days[-1], annual_turnover=math.fsum(t['quantity'] * (t['spot'] + t['perp']) for t in trades) * 365 / len(days),
             closed_episodes=len(episodes), winning_episodes=sum(e['net_pnl'] > 1e-12 for e in episodes),
             net_closed_win_rate=sum(e['net_pnl'] > 1e-12 for e in episodes) / len(episodes) if episodes else None,
             funding_pnl=total_funding, basis_pnl=total_basis, total_fees=total_fees,
             funding_lower=math.fsum(e['lower'] for e in payments), funding_upper=math.fsum(e['upper'] for e in payments),
             ending_wealth_lower=wallet - total_funding + math.fsum(e['lower'] for e in payments),
             ending_wealth_upper=wallet - total_funding + math.fsum(e['upper'] for e in payments),
             funding_bounds_role='conditional on recorded units and settlement mark lying within the previous/current archive minute range; no alternative-compounding replay or exact receipt certification',
             margin_breach_hours=len(breaches), terminal_nav=wallet,
             unknown_margin_hours=len(unknown),
             qualification='diagnostic_counterfactual_margin_breach' if breaches else
             ('diagnostic_incomplete_mark_stress_coverage' if unknown else 'diagnostic_margin_tiers_and_fills_unqualified'))
    return {'records': records, 'payments': payments, 'trades': trades, 'episodes': episodes, 'breaches': breaches, 'unknown_margin_hours': unknown, 'metrics': m}


def run_study(*, contract_path: Path, out: Path, repo: Path, input_root: Path):
    c = read_contract(contract_path)
    require_storage(out)
    if out.exists():
        raise ValueError('immutable_cashflow_result_exists')
    files = verify_manifest(input_root)
    prices = json.loads((input_root / 'prices.json').read_text())
    events = json.loads((input_root / 'funding.json').read_text())
    expected = [dt.date(2021, 1, 1) + dt.timedelta(days=i) for i in range((dt.date(2026, 8, 31) - dt.date(2021, 1, 1)).days + 1)]
    if list(prices) != [d.isoformat() for d in expected]:
        raise ValueError('cashflow_evaluation_calendar')
    out.mkdir(parents=True)
    source = out / 'source'
    source.mkdir()
    names = ('dual_engine_cashflow', 'dual_engine_cashflow_data', 'dual_engine_cashflow_verify',
             'dual_engine_information_data', 'dual_engine_execution_study', 'dual_engine_optimization', 'dual_engine_expansion',
             'dual_engine_cashflow_inputs', 'dual_engine_cashflow_qualification', 'dual_engine_cashflow_mark_repair')
    hashes = {}
    for name in names:
        p = repo / 'src/qount/research' / (name + '.py')
        shutil.copyfile(p, source / p.name)
        hashes[str(p.relative_to(repo))] = old.file_hash(p)
    shutil.copyfile(contract_path, out / 'contract.json')
    old.write_json(out / 'input-audit.json', {'input_root': str(input_root), 'manifest_sha256': old.file_hash(input_root / 'manifest.json'),
        'files': files, 'information_manifest_sha256': c['information_manifest_sha256'], 'btc_cache_sha256': c['btc_cache_sha256']})
    summaries, curves = {}, []
    for rule in RULES:
        summaries[rule] = {}
        for cost in c['cost_bps_per_leg_per_side']:
            for delay in c['delay_days']:
                cell = f'c{cost}-d{delay}'
                run = replay(prices, events, rule=rule, cost_bps=cost, delay=delay)
                summaries[rule][cell] = run['metrics']
                filename = f'cashflow-{rule}-{cell}-ledger.json'
                old.write_json(out / filename, run)
                curves.append({'line': 'cashflow', 'rule': rule, 'cell': cell, 'ledger': filename,
                               'role': 'diagnostic_feasibility' if rule == RULES[0] else 'diagnostic_control'})
    gate = {cell: {'positive_net_cagr': m['cagr'] > 0, 'positive_lower_bound_wealth': m['ending_wealth_lower'] > 1,
                   'no_margin_breach': m['margin_breach_hours'] == 0,
                   'complete_mark_stress_coverage': m['unknown_margin_hours'] == 0} for cell, m in summaries[RULES[0]].items()}
    result = {'study_id': c['study_id'], 'research_only': True, 'orders_authorized': False, 'promotion_evidence': False,
              'candidate_trials': 1, 'curve_exposures': curves, 'source_sha256': hashes, 'summaries': {'cashflow': summaries},
              'feasibility_checks': gate, 'feasibility_passed': all(all(v.values()) for v in gate.values()),
              'selection_eligible': False, 'joint_c60_goal_tested': False, 'missing_data': 0,
              'status': 'historical_cashflow_feasibility_only; exact receipts, historical margin tiers and executable fills unqualified'}
    old.write_json(out / 'results.json', result)
    old.write_json(out / 'manifest.json', {'research_only': True, 'orders_authorized': False,
        'files': {str(p.relative_to(out)): old.file_hash(p) for p in sorted(out.rglob('*')) if p.is_file()}})
    return result
