"""One frozen hourly information hypothesis; labels only, no order interfaces."""
from __future__ import annotations

import bisect
import datetime as dt
import json
import math
import statistics
from pathlib import Path

from qount.research_data.event_stats import event_summary

HOUR = 3600000
UTC = dt.timezone.utc
RULES = ('flow_reclaim', 'price_reclaim_control', 'cash')


def utc(stamp):
    return dt.datetime.fromtimestamp(stamp / 1000, UTC).isoformat()


def bounds(contract):
    first = int(dt.datetime.fromisoformat(contract['evaluation']['first']).replace(tzinfo=UTC).timestamp() * 1000)
    last = int((dt.datetime.fromisoformat(contract['evaluation']['last']).replace(tzinfo=UTC)
                + dt.timedelta(days=1)).timestamp() * 1000)
    return first, last


def read_contract(path: Path):
    c = json.loads(path.read_text())
    expected = {
        'study_id': 'short_horizon_opportunity_20261009', 'schema_version': 1,
        'research_only': True, 'orders_authorized': False, 'promotion_evidence': False,
        'holdout_role': 'discovery', 'automatic_restart_authorized': False,
        'candidate_trials_activated': 1, 'candidate_trials_reserved': 1,
        'symbols': ['BTCUSDT', 'ETHUSDT'], 'rules': list(RULES),
        'acquisition': {'first_month': '2020-12', 'last_month': '2026-08', 'workers': 6},
        'evaluation': {'first': '2021-01-01', 'last': '2026-08-31'},
        'signal': {'volume_lookback_hours': 168, 'low_lookback_hours': 24, 'shock_return_max': -.01,
                   'volume_multiple_min': 3., 'shock_buy_fraction_max': .35, 'confirm_buy_fraction_min': .55},
        'execution': {'hold_hours': 6, 'cooldown_hours': 72, 'max_entries_per_utc_month': 4,
                      'cost_bps_per_side': [10, 25], 'extra_delay_hours': [0, 1],
                      'funding_ownership': 'entry_inclusive_exit_exclusive_proxy', 'stops': 'none_fixed_horizon_labels_only'},
        'gate': {'min_events': 60, 'min_seven_day_blocks': 30, 'min_net_win_rate': .6,
                 'win_interval_lower_min': .5, 'bootstrap_samples': 1000, 'bootstrap_seed': 20261009},
        'leverage_diagnostic': {'multiples': [1, 3, 5, 10, 20], 'maintenance_rate_assumptions': [.005, .01],
                                'exit_cost_bps': 25, 'historical_brackets_verified': False, 'safe_leverage_certified': False},
        'ashare': {'candidate': 'forecast_upgrade_3session', 'universe': 'PIT_SSE_SZSE_main_board_including_delisted',
                   'minimum_listed_sessions': 120, 'median_quote20_min_cny': 100000000, 'hold_sessions': 3,
                   'monthly_entry_cap': 4, 'financing_authorized': False, 'returns_run_authorized': False,
                   'data_gate': 'pending', 'required_evidence': ['historical_security_master',
                       'original_disclosure_timestamps_and_revision_links', 'same_period_net_profit_ranges',
                       'unadjusted_ohlcv_including_delisted', 'corporate_actions_cash_and_shares',
                       'historical_st_and_suspensions', 'daily_price_limits_and_fill_evidence', 'calendar_and_dated_costs']},
    }
    if any(type(c.get(k)) is not type(v) or c.get(k) != v for k, v in expected.items()):
        raise ValueError('opportunity_frozen_contract_invalid')
    if c.get('ashare', {}).get('returns_run_authorized') is not False or c['ashare'].get('financing_authorized') is not False:
        raise ValueError('ashare_not_authorized_for_returns')
    return c


def signals(bars, contract, rule):
    """Only complete contiguous closed prefixes may create an opportunity."""
    if rule not in RULES:
        raise ValueError('unknown_opportunity_rule')
    if rule == 'cash':
        return [], {'missing_feature_windows': 0}
    first, last = bounds(contract)
    s = contract['signal']
    lookback = s['volume_lookback_hours']
    found, missing = [], 0
    # Mapping by timestamp makes gaps explicit, never a shorter rolling window.
    for t in range(first, last, HOUR):
        confirm = bars.get(t)
        shock = bars.get(t - HOUR)
        if confirm is None or shock is None:
            missing += 1
            continue
        history = [bars.get(t - (i + 2) * HOUR) for i in range(lookback)]
        if any(x is None for x in history):
            missing += 1
            continue
        price_ok = (shock['close'] / shock['open'] - 1 <= s['shock_return_max']
                    and shock['low'] < min(x['low'] for x in history[:s['low_lookback_hours']])
                    and confirm['close'] > (shock['high'] + shock['low']) / 2
                    and confirm['close'] > confirm['open'])
        if not price_ok:
            continue
        volume_ratio = shock['quote'] / statistics.median(x['quote'] for x in history)
        flow_ok = (volume_ratio >= s['volume_multiple_min'] and shock['buy_quote'] / shock['quote'] <= s['shock_buy_fraction_max']
                   and confirm['buy_quote'] / confirm['quote'] >= s['confirm_buy_fraction_min'])
        if rule == 'flow_reclaim' and not flow_ok:
            continue
        found.append({'decision_ms': t + HOUR, 'feature_closed_ms': t + HOUR - 1,
                      'shock_ms': t - HOUR, 'volume_ratio': volume_ratio,
                      'shock_buy_fraction': shock['buy_quote'] / shock['quote'],
                      'confirm_buy_fraction': confirm['buy_quote'] / confirm['quote']})
    return found, {'missing_feature_windows': missing}


def accept_events(candidates, contract, delay):
    """Plan using signal times only; future missing labels never free a slot."""
    first, last = bounds(contract)
    ex = contract['execution']
    result, counts, previous, capped, cooling, censored = [], {}, None, 0, 0, 0
    for event in sorted(candidates, key=lambda e: (e['decision_ms'], e['symbol'])):
        entry = event['decision_ms'] + delay * HOUR
        month = utc(entry)[:7]
        if previous is not None and entry - previous < ex['cooldown_hours'] * HOUR:
            cooling += 1
            continue
        if counts.get(month, 0) >= ex['max_entries_per_utc_month']:
            capped += 1
            continue
        # Do not inspect any label or future quote to accept/reject this event.
        previous = entry
        counts[month] = counts.get(month, 0) + 1
        row = {**event, 'entry_ms': entry, 'exit_ms': entry + ex['hold_hours'] * HOUR,
               'entry_utc': utc(entry)}
        if entry < first or row['exit_ms'] >= last:
            row['censored'] = True
            censored += 1
        result.append(row)
    return result, {'cooldown_rejections': cooling, 'monthly_cap_rejections': capped,
                    'accepted_events': len(result), 'boundary_censored': censored, 'entries_per_month': counts}


def label(event, bars, marks, funding, *, cost_bps, leverage):
    """Per entry-notional label with signed funding bounds and mark stress.

    Hourly extrema do not establish historical liquidation/settlement execution.
    The fixed ownership convention is [entry, exit), including entry boundary.
    """
    if event.get('censored'):
        return {**event, 'qualified': False, 'reason': 'boundary_censored'}
    entry, exit_ = event['entry_ms'], event['exit_ms']
    times = list(range(entry, exit_, HOUR))
    if any(t not in bars for t in times + [exit_]) or any(t not in marks for t in times + [exit_]):
        return {**event, 'qualified': False, 'reason': 'holding_price_or_mark_missing'}
    if any(bars[t]['quote'] <= 0 for t in times + [exit_]):
        return {**event, 'qualified': False, 'reason': 'zero_volume_fill_or_path'}
    stamps = [e['timestamp_ms'] for e in funding]
    lo, hi = bisect.bisect_left(stamps, entry), bisect.bisect_left(stamps, exit_)
    # Bracketing settlements prove the observed archive crosses both boundaries.
    if lo == 0 or hi >= len(funding):
        return {**event, 'qualified': False, 'reason': 'funding_boundary_missing'}
    surrounding = funding[lo - 1:hi + 1]
    for old, new in zip(surrounding, surrounding[1:]):
        gap = new['timestamp_ms'] - old['timestamp_ms']
        if gap <= 0 or abs(gap - new['interval_hours'] * HOUR) > 1000:
            return {**event, 'qualified': False, 'reason': 'funding_schedule_gap_or_unknown'}
    price, end_price = bars[entry]['open'], bars[exit_]['open']
    gross = end_price / price - 1
    cost = cost_bps / 10000 * (1 + end_price / price)
    paid, paid_low, paid_high, positive_paid_bound, payments = 0., 0., 0., 0., []
    for f in funding[lo:hi]:
        t = f['timestamp_ms'] // HOUR * HOUR
        mark = marks.get(t)
        if mark is None:
            return {**event, 'qualified': False, 'reason': 'funding_mark_missing'}
        rate = f['rate']
        proxy = rate * mark['open'] / price
        lower, upper = sorted((rate * mark['low'] / price, rate * mark['high'] / price))
        paid += proxy
        paid_low += lower
        paid_high += upper
        positive_paid_bound += max(0, upper)
        payments.append({'timestamp_ms': f['timestamp_ms'], 'rate': rate, 'paid_proxy': proxy,
                         'paid_lower': lower, 'paid_upper': upper})
    # Observe the exit boundary, without consuming the following hour's low.
    lowest = min([marks[t]['low'] for t in times] + [marks[exit_]['open']]) / price
    diagnostic = []
    for multiple in leverage['multiples']:
        for maintenance in leverage['maintenance_rate_assumptions']:
            exit_fee = leverage['exit_cost_bps'] / 10000
            # Conservative conjunction of worst observed mark and all positive fees.
            buffer = (1 / multiple - cost_bps / 10000 - positive_paid_bound + lowest - 1
                      - (maintenance + exit_fee) * lowest)
            diagnostic.append({'leverage': multiple, 'maintenance_assumption': maintenance,
                               'buffer_per_entry_notional': buffer, 'assumption_stress_breach': buffer <= 0,
                               'historical_liquidation_verified': False, 'safe_leverage_certified': False})
    return {**event, 'qualified': True, 'entry_price': price, 'exit_price': end_price,
            'gross_return': gross, 'total_cost': cost, 'funding_paid_proxy': paid,
            'net_proxy': gross - cost - paid, 'net_lower': gross - cost - paid_high,
            'net_upper': gross - cost - paid_low,
            'mark_mae': lowest - 1, 'trade_mfe': max(bars[t]['high'] for t in times) / price - 1,
            'payments': payments, 'leverage_diagnostics': diagnostic}


def evaluate(data, contract):
    first, last = bounds(contract)
    results, summaries, exposure = {}, {}, []
    for rule in RULES:
        raw, feature_audits = [], {}
        for symbol in contract['symbols']:
            events, audit = signals(data[symbol]['bars'], contract, rule)
            raw.extend({**e, 'symbol': symbol} for e in events)
            feature_audits[symbol] = audit
        for delay in contract['execution']['extra_delay_hours']:
            planned, plan_audit = accept_events(raw, contract, delay)
            for cost in contract['execution']['cost_bps_per_side']:
                key = f'{rule}/cost{cost}/delay{delay}'
                rows = [label(e, **data[e['symbol']], cost_bps=cost, leverage=contract['leverage_diagnostic']) for e in planned]
                qualified = [e for e in rows if e['qualified']]
                summary = event_summary(qualified, first_ms=first, last_ms=last - 1, gate=contract['gate'])
                unknown = len(rows) - len(qualified)
                feature_unknown = any(a['missing_feature_windows'] for a in feature_audits.values())
                summary.update({'raw_signals': len(raw), 'unknown_or_censored_events': unknown,
                                'plan': plan_audit, 'feature_coverage': feature_audits,
                                'full_signal_plan_known': not feature_unknown,
                                'diagnostic_gate_passed': summary['diagnostic_gate_passed'] and unknown == 0 and not feature_unknown,
                                'label_type': 'fixed_horizon_per_entry_notional_not_executable_nav',
                                'net_certified': False, 'safe_leverage_certified': False})
                summary['leverage_stress_counts'] = [
                    {'leverage': lev, 'maintenance_assumption': mm,
                     'assumption_stress_breaches': sum(d['assumption_stress_breach'] for e in qualified
                         for d in e['leverage_diagnostics'] if d['leverage'] == lev and d['maintenance_assumption'] == mm),
                     'unknown_events': unknown, 'safe_leverage_certified': False}
                    for lev in contract['leverage_diagnostic']['multiples']
                    for mm in contract['leverage_diagnostic']['maintenance_rate_assumptions']]
                results[key], summaries[key] = rows, summary
                exposure.append({'cell': key, 'candidate': rule == 'flow_reclaim', 'selection_eligible': False})
    passed = all(s['diagnostic_gate_passed'] for k, s in summaries.items() if k.startswith('flow_reclaim/'))
    return {'study_id': contract['study_id'], 'research_only': True, 'orders_authorized': False,
            'promotion_evidence': False, 'holdout_role': 'discovery', 'new_candidate_trials': 1,
            'diagnostic_cells': 12, 'candidate_diagnostic_gate_passed': passed,
            'decision': 'retain_hypothesis_for_fresh_evidence' if passed else 'stop_frozen_candidate_no_threshold_rescue',
            'ashare_status': 'data_gate_pending_returns_not_run', 'summaries': summaries,
            'curve_exposures': exposure, 'events': results,
            'dsr_pbo': 'not_run_consumed_history_single_new_hypothesis_no_selection_claim',
            'safe_leverage_certified': False}
