"""Dated dividend/profit diagnostics for frozen Q-DIV candidates; no re-selection.

Cash paid in a trailing window and profit earned in a reporting window have
separate clocks. Their ratio is a diagnostic, never the statutory payout ratio
or a forecast. Operating cash flow is consolidated and precedes capex.
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import math
from pathlib import Path

from qount.research import q_div as strategy
from qount.research.q_div_data import bundle, digest, fresh_output, validate_contract, write


def paid_events(rows, asof):
    """Collapse identical implemented events and retain the fiscal/payment clocks."""
    now = strategy.date(asof)
    boundary = now - dt.timedelta(days=365)
    events = {}
    for row in rows:
        if row.get('div_proc') != '实施':
            continue
        fiscal = strategy.date(row.get('end_date'))
        if fiscal.year < now.year - 3 and (not row.get('pay_date') or strategy.date(row['pay_date']) <= boundary):
            continue
        announced = strategy.date(row.get('imp_ann_date'))
        if announced >= now:
            continue
        ex, paid = strategy.date(row.get('ex_date')), strategy.date(row.get('pay_date'))
        if ex > now or paid > now:
            continue
        cash = strategy.number(row.get('cash_div_tax'))
        if cash <= 0:
            continue
        base = row.get('base_share')
        shares = None if base is None else strategy.number(base)
        if shares is not None and shares <= 0:
            raise strategy.DataUnknown('nonpositive_dividend_base')
        if paid > boundary and shares is None:
            raise strategy.DataUnknown('missing_recent_dividend_base')
        key = (row['end_date'], row['ex_date'], row['pay_date'])
        signature = (cash, shares)
        if key in events and events[key]['signature'] != signature:
            raise strategy.DataUnknown('conflicting_paid_event')
        # Identical vendor revisions collapse. Preserve the later known
        # implementation date rather than invent a first-public timestamp.
        prior_ann = events.get(key, {}).get('implementation_announcement', '')
        events[key] = {
            'signature': signature, 'fiscal_period': row['end_date'],
            'implementation_announcement': max(prior_ann, row['imp_ann_date']),
            'ex_date': row['ex_date'], 'pay_date': row['pay_date'],
            'cash_per_share_cny': cash, 'base_shares_10k': shares,
            'cash_cny': None if shares is None else cash * shares * 10000,
            'in_trailing_payment_window': paid > boundary,
        }
    return [{k: v for k, v in event.items() if k != 'signature'}
            for _, event in sorted(events.items())]


def growth(current, previous):
    """A nonpositive comparison base is not an ordinary growth rate."""
    a, b = strategy.number(current), strategy.number(previous)
    return (a / b - 1) if b > 0 else None


def diagnose(candidate, financial, asof):
    symbol = candidate['symbol']
    for rows in financial.values():
        if any(row.get('ts_code') != symbol for row in rows):
            raise ValueError('review_source_identity_mismatch')
    quality = strategy.fundamentals(financial['income'], financial['cashflow'], financial['balancesheet'], asof)
    div = strategy.dividends(financial['dividend'], asof, candidate['total_mv_10k'])
    if not quality['passed'] or not div['passed']:
        raise ValueError('frozen_selected_candidate_no_longer_ties')
    for field in ('parent_profit_TTM_cny', 'CFO_TTM_cny', 'ROE_TTM', 'debt_to_assets'):
        if not math.isclose(quality[field], candidate['quality'][field], rel_tol=1e-12, abs_tol=1e-5):
            raise ValueError('review_quality_snapshot_mismatch:' + field)
    if not math.isclose(div['yield_TTM'], candidate['yield_TTM'], rel_tol=1e-12):
        raise ValueError('review_yield_snapshot_mismatch')
    events = paid_events(financial['dividend'], asof)
    recent = [e for e in events if e['in_trailing_payment_window']]
    cash = sum(e['cash_cny'] for e in recent)
    market = strategy.number(candidate['total_mv_10k']) * 10000
    if not math.isclose(cash / market, div['yield_TTM'], rel_tol=1e-12):
        raise ValueError('review_event_cash_yield_mismatch')
    profit, cfo = quality['parent_profit_TTM_cny'], quality['CFO_TTM_cny']
    inc = strategy.report_map(financial['income'], asof, ['n_income_attr_p'])
    cf = strategy.report_map(financial['cashflow'], asof, ['n_cashflow_act'])
    period = quality['period']
    previous = strategy.previous_year(period)
    annual = []
    for year in range(strategy.date(asof).year - 3, strategy.date(asof).year):
        fiscal_events = [e for e in events if int(e['fiscal_period'][:4]) == year]
        annual_period = str(year) + '1231'
        annual_profit = strategy.number(inc[annual_period]['n_income_attr_p']) if annual_period in inc else None
        annual_cfo = strategy.number(cf[annual_period]['n_cashflow_act']) if annual_period in cf else None
        known_cash = bool(fiscal_events) and all(e['cash_cny'] is not None for e in fiscal_events)
        paid = sum(e['cash_cny'] for e in fiscal_events) if known_cash else None
        annual.append({
            'fiscal_year': year, 'parent_profit_cny': annual_profit, 'CFO_cny': annual_cfo,
            'paid_for_fiscal_year_through_cutoff_cny': paid,
            'paid_events': len(fiscal_events),
            'cash_to_matched_fiscal_profit': paid / annual_profit if paid is not None and annual_profit is not None and annual_profit > 0 else None,
            'CFO_to_cash': annual_cfo / paid if paid is not None and paid > 0 and annual_cfo is not None else None,
            'scope': 'implemented_and_paid_through_cutoff_not_future_fiscal_entitlement',
        })
    profit_growth = growth(inc[period]['n_income_attr_p'], inc[previous]['n_income_attr_p']) if previous in inc else None
    cfo_growth = growth(cf[period]['n_cashflow_act'], cf[previous]['n_cashflow_act']) if previous in cf else None
    flags = []
    if cash > profit:
        flags.append('trailing_cash_exceeds_latest_TTM_profit')
    if cash > cfo:
        flags.append('trailing_cash_exceeds_latest_TTM_CFO')
    if profit_growth is not None and profit_growth < 0:
        flags.append('latest_YTD_profit_declined')
    if cfo_growth is not None and cfo_growth < 0:
        flags.append('latest_YTD_CFO_declined')
    return {
        'symbol': symbol, 'name': candidate.get('name'), 'industry': candidate.get('industry'),
        'snapshot_rank': candidate['rank'], 'unchanged_target_weight': candidate['target_weight'],
        'price_asof': asof, 'latest_financial_period': period,
        'market_value_A_quote_proxy_cny': market,
        'PE_parent_TTM_A_quote_proxy': market / profit,
        'earnings_yield_TTM': profit / market, 'paid_dividend_yield': cash / market,
        'parent_profit_TTM_cny': profit, 'CFO_TTM_cny': cfo, 'paid_cash_365d_cny': cash,
        'cash_paid_365d_to_latest_TTM_profit': cash / profit,
        'CFO_TTM_to_paid_cash_365d': cfo / cash,
        'CFO_TTM_less_paid_cash_365d_cny': cfo - cash,
        'latest_YTD_parent_profit_growth': profit_growth,
        'latest_YTD_CFO_growth': cfo_growth, 'annual': annual,
        'paid_events': events, 'flags': flags,
        'capex_and_FCF': 'not_collected; CFO_is_not_FCF_or_parent_distributable_cash',
        'historical_PIT_certified': False, 'future_dividend_forecast': False,
    }


def run_review(contract_path, out):
    """WSL/E authoritative rerun of an additive, hash-bound diagnostic contract."""
    plan = json.loads(Path(contract_path).read_text())
    if (plan.get('research_only') is not True or plan.get('orders_authorized') is not False
            or plan.get('promotion_evidence') is not False or plan.get('new_strategy_rules') != 0):
        raise ValueError('review_research_boundary')
    base_path = Path(plan['strategy_contract'])
    if digest(base_path) != plan['strategy_contract_sha256']:
        raise ValueError('review_strategy_contract_hash_mismatch')
    base = validate_contract(base_path)
    from qount.research.q_div_data import ROOT
    for name, sha in plan['implementation_sha256'].items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT) or digest(path) != sha:
            raise ValueError('review_code_hash_mismatch:' + name)
    snapshot = Path(plan['snapshot_root'])
    if digest(snapshot / 'manifest.json') != plan['snapshot_manifest_sha256']:
        raise ValueError('review_snapshot_manifest_mismatch')
    for name, sha in json.loads((snapshot / 'manifest.json').read_text()).items():
        path = (snapshot / name).resolve()
        if not path.is_relative_to(snapshot.resolve()) or digest(path) != sha:
            raise ValueError('review_snapshot_file_hash_mismatch')
    if digest(snapshot / 'contract.json') != digest(base_path):
        raise ValueError('review_snapshot_strategy_mismatch')
    financial_root = Path(plan['financial_root'])
    if digest(financial_root / 'contract.json') != plan['financial_contract_sha256']:
        raise ValueError('review_financial_contract_mismatch')
    data, fingerprint = bundle(financial_root)
    saved_fingerprint = json.loads((snapshot / 'financial-input-manifest.json').read_text())
    if fingerprint != saved_fingerprint:
        raise ValueError('review_financial_input_manifest_mismatch')
    per_symbol = collections.defaultdict(dict)
    for spec, rows in data:
        symbol, api = spec['params'].get('ts_code'), spec['api_name']
        if api in per_symbol[symbol]:
            raise ValueError('review_duplicate_financial_request')
        per_symbol[symbol][api] = rows
    selected = json.loads((snapshot / 'selected.json').read_text())
    if len(selected) != plan['expected_candidates'] or len({r['symbol'] for r in selected}) != len(selected):
        raise ValueError('review_candidate_inventory_mismatch')
    results = [diagnose(r, per_symbol[r['symbol']], base['price_cutoff']) for r in selected]
    flag_counts = collections.Counter(flag for r in results for flag in r['flags'])
    summary = {
        'status': 'completed_dated_dividend_diagnostics_not_return_experiment',
        'research_only': True, 'orders_authorized': False, 'promotion_evidence': False,
        'price_asof': base['price_cutoff'], 'candidates': len(results),
        'financial_requests_verified': len(data), 'flag_counts': dict(flag_counts),
        'cash_exceeds_profit_symbols': [r['symbol'] for r in results if 'trailing_cash_exceeds_latest_TTM_profit' in r['flags']],
        'target_weighted_historical_paid_yield': sum(r['unchanged_target_weight'] * r['paid_dividend_yield'] for r in results),
        'minimum_CFO_to_paid_cash': min(r['CFO_TTM_to_paid_cash_365d'] for r in results),
        'annual_missing_cash_or_profit_cells': sum(a['cash_to_matched_fiscal_profit'] is None for r in results for a in r['annual']),
        'historical_backtest_run': False, 'returns_produced': False,
        'new_strategy_rules': 0, 'parameter_searches': 0, 'frozen_selection_changed': False,
        'historical_PIT_certified': False, 'FCF_certified': False,
        'review_contract_sha256': digest(contract_path),
        'strategy_contract_sha256': digest(base_path),
        'snapshot_manifest_sha256': plan['snapshot_manifest_sha256'],
        'interpretation': 'cash_paid_365d_and_latest_TTM_profit_have_different_clocks; not_statutory_payout_or_forecast',
    }
    out = fresh_output(out)
    write(out / 'contract.json', plan)
    write(out / 'summary.json', summary)
    write(out / 'diagnostics.json', results)
    write(out / 'financial-input-manifest.json', fingerprint)
    write(out / 'manifest.json', {p.name: digest(p) for p in sorted(out.iterdir()) if p.is_file()})
    return summary
