"""Q-DIV-IVOL research primitives and dated screening; no order interface.

Announcement filtering of a downloaded vendor snapshot is conditional evidence,
not certification that historical revisions were available at that time.
"""
from __future__ import annotations

import collections
import datetime as dt
import math
import statistics


RULES = {
    'capital_cny': 1_000_000, 'price_cutoff': '20260930',
    'universe': 'existing_3211_original_plus196_retired_panel_not_all_A',
    'maturity': '252_past_valid_raw_observations_and220_consecutive_valid_exchange_sessions',
    'liquidity': 'ADV20_ge30m_and_keep_top80pct_of_mature_price_valid_panel_symbol_tie',
    'risk_warning': 'dated_stock_st_list_complete_for_signal_date_missing_status_unknown',
    'turnover': 'daily_basic_turnover_rate_percent_mean20_exact_sessions_keep_lowest85pct_of_liquid_nonST_pool_symbol_tie',
    'financial_scope': 'industrial_comp_type1_only_financial_cashflow_not_comparable',
    'quality': 'parent_profit_TTM_positive_ROE_TTM_ge8pct_CFO_TTM_div_parent_profit_TTM_ge0.8_debt_assets_lt0.70',
    'TTM': 'current_YTD_plus_previous_full_year_minus_previous_same_period_YTD_annual_used_directly',
    'ROE_TTM': 'parent_profit_TTM_div_mean_parent_equity_current_and_prior_same_period_both_positive',
    'report_clock': 'max_ann_date_f_ann_date_strictly_before_signal_date_210day_period_age_limit_conflicting_same_date_values_unknown',
    'dividend': 'three_previous_completed_fiscal_years_each_positive_implemented_cash_and_implemented_paid_TTM_yield_ge2.5pct',
    'dividend_clock': 'implementation_ann_strictly_before_signal_date_ex_date_and_pay_date_le_signal_date_no_proposals',
    'dividend_yield': 'sum_cash_div_tax_CNY_per_share_times_base_share_10k_div_current_total_mv_10k_CNY_last365calendar_days',
    'IVOL': '120_exact_simple_adjusted_returns_single_market_OLS_with_intercept_population_residual_std_times_sqrt252',
    'market_proxy': '399300.SZ_price_index_close_div_pre_close_minus1_not_all_A_total_return_index',
    'rate_proxy': 'previous_exchange_session_SHIBOR_ON_percent_div100_div252_not_certified_risk_free',
    'trend': 'adjusted_close_gt_MA200_and_MA200_ge_MA200_20sessions_ago',
    'entry': 'Bias60_in_closed_interval_minus3pct_plus12pct_Bias120_lt20pct_return60_le30pct_raw_volume5_le0.85_volume60',
    'ranking': 'IVOL_ascending_symbol_tie', 'maximum_positions': 20,
    'entry_rank': 20, 'retention_rank': 35, 'review_sessions': 10,
    'industry_slots': 3, 'industry_weight_cap': .20, 'stock_weight_cap': .08,
    'weighting': 'DY_div_IVOL_iterative_capped_proportional_cash_for_infeasible_capacity',
    'industry': '20261009_snapshot_not_PIT_unknown_shared_group_not_industry_neutral',
    'exit_priority': ['known_fundamental_loss_or_cancel_or_investigation_or_ST',
                      'three_consecutive_valid_closes_below0.97_MA200',
                      'DY_lt1.5pct_or_Bias60_gt30pct', 'review_rank_beyond35'],
    'exit_execution': 'next_session_open_or_extra_one_session_Tplus1_limit_and_liquidity_guards_no_guaranteed_stop_price',
    'portfolio_freeze': '12pct_anchor_drawdown_cancel_new_buys_no_forced_liquidation_resume_after20_full_sessions_reset_anchor',
    'weight_caps_scope': 'target_weights_only_price_drift_and_failed_fills_may_exceed_targets',
    'curves': ['base', 'double_cost', 'extra_day', 'equal_industry_control'],
    'control': 'same_qualified_pool_clock_exits_industry_slots_equal_weight_among_industries_then_names_same_caps',
    'fees': 'reuse_frozen_ashare_strategy_cost_schedule_1pct_prior_ADV_adjusted_unit_proxy_no_extra_dividend_cash',
    'snapshot_scope': 'all_technical_passers_fundamental_collection_max120_by_IVOL_not_full_historical_pool',
    'snapshot_shortlist_limit': 120, 'independent_OOS': False,
}
GATE = {
    'minimum_each_primary_unknown_zero_CAGR_strict': .08,
    'maximum_base_drawdown_strict': .25, 'minimum_base_daily_Sharpe_strict': .8,
    'minimum_closed_trades': 100, 'historical_PIT_required': True,
    'failure_action': 'retain_and_stop_frozen_implementation_no_parameter_rescue',
}


class DataUnknown(ValueError):
    """Required evidence is absent or ambiguous; never interpret it as zero."""


def number(value):
    if value is None or isinstance(value, bool):
        raise DataUnknown('missing_number')
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise DataUnknown('invalid_number') from exc
    if not math.isfinite(result):
        raise DataUnknown('nonfinite_number')
    return result


def date(value):
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        raise DataUnknown('invalid_date')
    try:
        return dt.datetime.strptime(value, '%Y%m%d').date()
    except ValueError as exc:
        raise DataUnknown('invalid_date') from exc


def report_map(rows, asof, fields):
    """Last dated consolidated version; conflicting same-date values fail closed.

    update_flag describes the vendor's latest record, not when its revision was
    first public. It is deliberately not used as a historical version clock.
    """
    date(asof)
    groups = collections.defaultdict(list)
    for row in rows:
        if str(row.get('report_type')) != '1':
            continue
        announced = max(row.get('ann_date') or '', row.get('f_ann_date') or '')
        date(announced); date(row.get('end_date'))
        if announced >= asof or row['end_date'] > asof:
            continue
        groups[row['end_date']].append((announced, row))
    result = {}
    for period, versions in groups.items():
        latest = max(a for a, _ in versions)
        candidates = [r for a, r in versions if a == latest]
        signatures = {tuple(r.get(k) for k in fields) + (str(r.get('comp_type')),)
                      for r in candidates}
        if len(signatures) != 1:
            raise DataUnknown('ambiguous_same_date_financial_revision:' + period)
        result[period] = candidates[0]
    return result


def previous_year(period):
    date(period)
    return str(int(period[:4])-1) + period[4:]


def ttm(reports, period, field):
    try:
        current = number(reports[period][field])
        if period.endswith('1231'):
            return current
        return (current + number(reports[str(int(period[:4])-1)+'1231'][field])
                - number(reports[previous_year(period)][field]))
    except KeyError as exc:
        raise DataUnknown('missing_TTM_components:' + field) from exc


def fundamentals(income, cashflow, balance, asof):
    inc = report_map(income, asof, ['n_income_attr_p'])
    cf = report_map(cashflow, asof, ['n_cashflow_act'])
    bal = report_map(balance, asof, ['total_hldr_eqy_exc_min_int', 'total_liab', 'total_assets'])
    if not inc:
        raise DataUnknown('no_dated_income')
    period = max(inc)
    if period not in cf or period not in bal or previous_year(period) not in bal:
        raise DataUnknown('latest_report_components_not_aligned')
    if (date(asof)-date(period)).days > 210:
        raise DataUnknown('stale_latest_period')
    if any(str(r.get('comp_type')) != '1' for r in (inc[period], cf[period], bal[period])):
        return {'passed': False, 'reason': 'financial_or_nonindustrial_excluded', 'period': period}
    profit, operating = ttm(inc, period, 'n_income_attr_p'), ttm(cf, period, 'n_cashflow_act')
    equity = [number(bal[p]['total_hldr_eqy_exc_min_int']) for p in (period, previous_year(period))]
    assets, debt = number(bal[period]['total_assets']), number(bal[period]['total_liab'])
    if min(equity) <= 0 or assets <= 0 or debt < 0:
        return {'passed': False, 'reason': 'invalid_or_nonpositive_equity_assets', 'period': period}
    roe, leverage = profit / statistics.fmean(equity), debt / assets
    cash_ratio = operating/profit if profit > 0 else None
    passed = profit > 0 and roe >= .08 and cash_ratio >= .8 and leverage < .7
    return {'passed': passed, 'reason': 'pass' if passed else 'quality_threshold',
            'period': period, 'parent_profit_TTM_cny': profit, 'CFO_TTM_cny': operating,
            'ROE_TTM': roe, 'CFO_to_parent_profit_TTM': cash_ratio, 'debt_to_assets': leverage,
            'historical_vintage_certified': False}


def dividends(rows, asof, market_value_10k):
    now = date(asof); market = number(market_value_10k)
    if market <= 0:
        raise DataUnknown('nonpositive_market_value')
    events = {}
    for row in rows:
        if row.get('div_proc') != '实施':
            continue
        fiscal = date(row.get('end_date'))
        if fiscal.year < now.year-3 and (not row.get('pay_date') or row['pay_date'] <= (now-dt.timedelta(days=365)).strftime('%Y%m%d')):
            continue
        announcement = row.get('imp_ann_date')
        if not announcement:
            raise DataUnknown('implemented_dividend_missing_implementation_announcement')
        date(announcement)
        if announcement >= asof:
            continue
        for key in ('end_date', 'ex_date', 'pay_date'):
            date(row.get(key))
        if row['ex_date'] > asof or row['pay_date'] > asof:
            continue
        cash = number(row.get('cash_div_tax'))
        if cash <= 0:
            continue
        recent = now-dt.timedelta(days=365) < date(row['pay_date'])
        shares = number(row.get('base_share')) if recent else None
        if recent and shares <= 0:
            raise DataUnknown('dividend_cash_base_missing')
        key = (row['end_date'], row['ex_date'], row['pay_date'])
        event = (cash, shares)
        if key in events and events[key] != event:
            raise DataUnknown('ambiguous_implemented_dividend')
        events[key] = event
    years = {int(k[0][:4]) for k in events}
    required = set(range(now.year-3, now.year))
    # Units cancel: base_share and total_mv are both reported in ten-thousands.
    total_cash_10k = sum(cash*shares for (_, _, paid), (cash, shares) in events.items()
                         if now-dt.timedelta(days=365) < date(paid) <= now)
    dy = total_cash_10k / market
    passed = required <= years and dy >= .025
    return {'passed': passed, 'reason': 'pass' if passed else 'dividend_threshold',
            'yield_TTM': dy, 'required_fiscal_years': sorted(required),
            'implemented_fiscal_years': sorted(years & required), 'implemented_events': len(events)}


def ivol(stock_returns, market_returns, rate_returns):
    if not (len(stock_returns) == len(market_returns) == len(rate_returns) == 120):
        raise DataUnknown('IVOL_requires120_exact_sessions')
    xs = [number(m)-number(r) for m, r in zip(market_returns, rate_returns)]
    ys = [number(s)-number(r) for s, r in zip(stock_returns, rate_returns)]
    xm, ym = statistics.fmean(xs), statistics.fmean(ys)
    xx = sum((x-xm)**2 for x in xs)
    if xx <= 0:
        raise DataUnknown('zero_market_variance')
    beta = sum((x-xm)*(y-ym) for x, y in zip(xs, ys))/xx
    residuals = [y-ym-beta*(x-xm) for x, y in zip(xs, ys)]
    vol = math.sqrt(sum(e*e for e in residuals)/120)*math.sqrt(252)
    if vol <= 1e-12:
        raise DataUnknown('zero_residual_volatility')
    return {'IVOL': vol, 'beta': beta, 'alpha_daily': ym-beta*xm}


def price_features(series, j):
    if j < 219 or series.history[j] < 252 or not all(series.valid[j-219:j+1]):
        raise DataUnknown('maturity_or_exact220session_window')
    close = number(series.adj_close[j])
    mean = lambda values, n, end=j: statistics.fmean(number(x) for x in values[end-n+1:end+1])
    ma60, ma120, ma200, lag200 = (mean(series.adj_close, n, end)
                                for n, end in ((60,j),(120,j),(200,j),(200,j-20)))
    if min(close, ma60, ma120, ma200, lag200) <= 0:
        raise DataUnknown('invalid_adjusted_price')
    v5, v60 = mean(series.volume, 5), mean(series.volume, 60)
    if v60 <= 0:
        raise DataUnknown('nonpositive_volume_window')
    bias60, bias120 = close/ma60-1, close/ma120-1
    ret60 = close/number(series.adj_close[j-60])-1
    return {'ADV20_cny': mean(series.amount_cny,20), 'close_adjusted': close,
            'MA200': ma200, 'MA200_lag20': lag200, 'Bias60': bias60, 'Bias120': bias120,
            'return60': ret60, 'volume5_div60': v5/v60,
            'trend_pass': close > ma200 and ma200 >= lag200,
            'entry_pass': -.03 <= bias60 <= .12 and bias120 < .20 and ret60 <= .30 and v5 <= .85*v60}


def liquid_codes(features):
    mature = sorted(features, key=lambda c: (-features[c]['ADV20_cny'], c))
    # Floor the number excluded; boundary ties have a frozen symbol order.
    keep = len(mature)-math.floor(.2*len(mature))
    return [c for c in mature[:keep] if features[c]['ADV20_cny'] >= 30_000_000]


def low_turnover_codes(values):
    ranked = sorted(values, key=lambda c: (values[c], c))
    return ranked[:len(ranked)-math.floor(.15*len(ranked))]


def target_weights(candidates, *, control=False):
    """Deterministic proportional water filling with cash for infeasible caps."""
    groups = collections.Counter(c['industry'] for c in candidates)
    scores = {c['symbol']: (1/groups[c['industry']] if control else c['yield_TTM']/c['IVOL'])
              for c in candidates}
    if len(scores) != len(candidates) or any(not math.isfinite(s) or s <= 0 for s in scores.values()):
        raise DataUnknown('invalid_weight_scores')
    industry = {c['symbol']: c['industry'] for c in candidates}
    weights = dict.fromkeys(scores, 0.)
    active = set(scores)
    remaining = 1.
    while active and remaining > 1e-12:
        total = sum(scores[c] for c in sorted(active))
        allocation = {c: remaining*scores[c]/total for c in active}
        scale = 1.
        for c in active:
            scale = min(scale, (.08-weights[c])/allocation[c])
        for group in sorted(set(industry[c] for c in active)):
            members = [c for c in active if industry[c] == group]
            amount = sum(allocation[c] for c in members)
            used = sum(w for c,w in weights.items() if industry[c] == group)
            scale = min(scale, (.20-used)/amount)
        scale = max(0., scale)
        for c in sorted(active):
            weights[c] += scale*allocation[c]
        remaining = max(0., 1-sum(weights.values()))
        if scale >= 1-1e-12:
            break
        full_groups = {g for g in set(industry.values())
                       if sum(w for c,w in weights.items() if industry[c] == g) >= .20-1e-12}
        saturated = {c for c in active if weights[c] >= .08-1e-12 or industry[c] in full_groups}
        if not saturated:
            raise RuntimeError('weight_solver_no_progress')
        active -= saturated
    return weights


def select_candidates(rows, held=()):
    ranked = sorted(rows, key=lambda r: (r['IVOL'], r['symbol']))
    if len({r['symbol'] for r in ranked}) != len(ranked):
        raise DataUnknown('duplicate_candidate')
    ranks = {r['symbol']: i+1 for i,r in enumerate(ranked)}
    kept = [r for r in ranked if r['symbol'] in held and ranks[r['symbol']] <= 35]
    new = [r for r in ranked[:20] if r['symbol'] not in held]
    result, counts = [], collections.Counter()
    for row in kept+new:
        if len(result) >= 20:
            break
        if counts[row['industry']] >= 3:
            continue
        result.append({**row, 'rank': ranks[row['symbol']]}); counts[row['industry']] += 1
    return result


def exit_reason(*, fundamental_bad, below_ma97, dividend_yield, bias60, rank, review):
    if fundamental_bad:
        return 'known_fundamental_or_ST_event'
    if len(below_ma97) == 3 and all(x is True for x in below_ma97):
        return 'confirmed_MA200_break'
    if dividend_yield is not None and dividend_yield < .015:
        return 'yield_below1.5pct'
    if bias60 is not None and bias60 > .30:
        return 'Bias60_above30pct'
    if review and (rank is None or rank > 35):
        return 'rank_exit'
    return None


def historical_readiness(evidence):
    required = ('financial_vintages', 'dated_risk_events', 'historical_turnover',
                'implemented_dividends', 'market_and_rate', 'execution_status', 'settlement')
    missing = [k for k in required if evidence.get(k) != 'qualified']
    return {'status': 'ready' if not missing else 'blocked_missing_historical_evidence',
            'missing': missing, 'historical_backtest_run': False,
            'returns_produced': False, 'research_only': True, 'orders_authorized': False}
