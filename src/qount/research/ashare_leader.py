"""Frozen technical-leader breakout discovery with close-confirmed risk exits.

A leader here means industry-relative price strength and liquidity, not verified
business leadership. Prices and NAV use the existing synthetic adjusted-unit
accounting; this module has no account, service or order integration.
"""
from __future__ import annotations

import collections
import dataclasses
import datetime as dt
import gzip
import json
import math
import statistics
import sys
from array import array
from pathlib import Path

from qount.research.ashare_strategy import (
    Book, REAL_ESTATE, ROOT, digest, make_features, metrics, write_json,
)

RULES = {
    'capital_cny': 1_000_000,
    'risk_style': 'aggressive_unlevered_technical_leader_trend_close_confirmed_exits',
    'start': '20150101', 'end': '20260930',
    'same_base_eligibility': '252past_raw_201valid_meanamount20_ge50m_no_current_status_or_ST_filter',
    'industry_descriptor': 'modern_snapshot_not_PIT_unknown_shared___unclassified___not_real_sector',
    'sector_gate': 'at_least10_eligible_median_return63_gt0_fraction_close_gtMA60_ge0.60',
    'sector_ranking': 'median_return63_desc_industry_lexical_tie_top5',
    'technical_leader': 'intersection_of_floor20pct_min1_return63_rank_and_ceil50pct_ADV20_rank_within_eligible_industry_symbol_ties',
    'entry_trend': 'close_gtMA20_gtMA60_gtMA200_and_MA60_gtMA60[t-20]_and_return63_gt0',
    'entry_breakout': 'close_gt_max_prior20_exact_exchange_closes_excluding_current',
    'primary_ranking': 'return63_desc_ADV20_desc_symbol_asc_top16_with_industry_caps',
    'control_ranking': 'same_eligible_trend_breakout_ADV20_desc_symbol_asc_top16_no_sector_or_leader_filter_no_industry_caps',
    'review_clock': 'every_exchange_session_close_from_first2015_session',
    'maximum_positions': 8, 'signal_buffer': 16, 'ranking_exit': False,
    'new_entry_fraction': min(.125, .0075/.07),
    'entry_risk_budget': 'min12.5pctNAV_or0.75pctNAV_divided_by7pct_initial_stop_fees_included_budget_not_loss_cap',
    'industry_slots': 2, 'unknown_industry_slots': 1, 'real_estate_slots': 2,
    'entry_basis': 'all_in_entry_cost_divided_by_synthetic_adjusted_units',
    'exit_priority': ['portfolio_drawdown12', 'initial_stop7', 'profit_trail5', 'profit_trail8', 'below_MA20', 'age126'],
    'initial_stop': 'qualified_close_le_entry_basis_times0.93',
    'profit_trail': 'postentry_valid_close_peak_ge1.30basis_then_close_le0.95peak_else_peak_ge1.15basis_then_close_le0.92peak',
    'stock_trend_exit': 'qualified_close_strictly_lt_qualified_MA20',
    'max_holding_sessions': 126,
    'portfolio_drawdown': '12pct_anchor_peak_cancel_pending_buys_persistent_all_exits_then20_complete_sessions_and_all_exits_complete_before_reset',
    'execution': 'close_signal_scheduled_open_buy_single_attempt_sell_persistent_extra_day_variant_no_intraday_high_low_stop_or_partial_profit',
    'market_breadth_entry_filter': False,
    'cost_and_execution': 'unchanged_frozen_ashare_strategy_v1_costs_open_guard_Tplus1_100raw_lot_1pct_priorADV_synthetic_adjusted_units',
    'financial_policy_overlay': 'not_backtested_no_historical_PIT_data',
    'curves': ['sector_base', 'sector_double_cost', 'sector_extra_day', 'price_control'],
    'prior_candidates_unchanged': True, 'no_claim_independent_OOS': True,
}


@dataclasses.dataclass
class LeaderFeatures:
    ma20: array
    ma60_lag20: array
    return63: array
    prior20_high: array


def make_leader_features(s, base=None):
    """Exact calendar windows; missing observations never compress the clock."""
    base = make_features(s) if base is None else base
    n = len(s.valid)
    ma20, lag, ret, high = (array('d', [math.nan])*n for _ in range(4))
    total = 0.
    counts = {20: 0, 64: 0}
    peaks = collections.deque()
    for j in range(n):
        while peaks and peaks[0] < j-20:
            peaks.popleft()
        # Counts[20] still describes [j-20,j-1], so today's close is excluded.
        if j >= 20 and counts[20] == 20:
            high[j] = s.adj_close[peaks[0]]
        c = s.adj_close[j]
        good = bool(s.valid[j]) and math.isfinite(c) and c > 0
        total += c if good else 0.
        if j >= 20 and s.valid[j-20] and math.isfinite(s.adj_close[j-20]) and s.adj_close[j-20] > 0:
            total -= s.adj_close[j-20]
        for length in counts:
            counts[length] += good
            if j >= length:
                old = s.adj_close[j-length]
                counts[length] -= bool(s.valid[j-length]) and math.isfinite(old) and old > 0
        if j >= 19 and counts[20] == 20:
            ma20[j] = total/20
        if j >= 20:
            lag[j] = base.ma60[j-20]
        if j >= 63 and counts[64] == 64:
            ret[j] = c/s.adj_close[j-63]-1
        if good:
            while peaks and s.adj_close[peaks[-1]] <= c:
                peaks.pop()
            peaks.append(j)
    return LeaderFeatures(ma20, lag, ret, high)


def group(code, metadata):
    return metadata.get(code, {}).get('industry') or '__unclassified__'


def trend_breakout(j, code, panel, features, leader_features):
    c, f, extra = panel[code].adj_close[j], features[code], leader_features[code]
    return (c > extra.ma20[j] > f.ma60[j] > f.ma200[j]
            and f.ma60[j] > extra.ma60_lag20[j]
            and extra.return63[j] > 0 and c > extra.prior20_high[j])


def select(j, panel, features, leader_features, metadata):
    eligible = [c for c, f in features.items() if f.eligible[j]]
    trend = [c for c in eligible if trend_breakout(j, c, panel, features, leader_features)]
    trend_set = set(trend)
    sectors = collections.defaultdict(list)
    for code in eligible:
        sectors[group(code, metadata)].append(code)
    available = []
    for industry, codes in sectors.items():
        median = statistics.median(leader_features[c].return63[j] for c in codes)
        breadth = sum(panel[c].adj_close[j] > features[c].ma60[j] for c in codes)/len(codes)
        if len(codes) >= 10 and median > 0 and breadth >= .6:
            available.append((industry, median, breadth, codes))
    available.sort(key=lambda x: (-x[1], x[0]))
    pool = []
    for industry, _, _, codes in available[:5]:
        leaders = sorted(codes, key=lambda c: (-leader_features[c].return63[j], c))[:max(1, math.floor(len(codes)*.2))]
        liquid = set(sorted(codes, key=lambda c: (-features[c].adv20[j], c))[:math.ceil(len(codes)*.5)])
        pool.extend(c for c in leaders if c in liquid and c in trend_set)
    pool.sort(key=lambda c: (-leader_features[c].return63[j], -features[c].adv20[j], c))
    counts, real, ranking = collections.Counter(), 0, []
    for code in pool:
        industry = group(code, metadata)
        if counts[industry] >= (1 if industry == '__unclassified__' else 2):
            continue
        if industry in REAL_ESTATE and real >= 2:
            continue
        ranking.append(code)
        counts[industry] += 1
        real += industry in REAL_ESTATE
        if len(ranking) == 16:
            break
    return {
        'market_on': bool(trend), 'eligible_count': len(eligible), 'trend_breakout_count': len(trend),
        'sector_rank': ranking,
        'price_rank': sorted(trend, key=lambda c: (-features[c].adv20[j], c))[:16],
        'selected_sectors': [row[0] for row in available[:5]],
        'sector_diagnostics': [{'industry_snapshot': i, 'median_return63': m, 'fraction_above_MA60': b,
                                'eligible_members': len(codes)} for i, m, b, codes in available[:5]],
        'eligible_retired': sum(panel[c].source_kind == 'tushare_retired' for c in eligible),
    }


def exit_state(position, close, ma20, j):
    """Price triggers are close-confirmed; levels are never assumed fill prices."""
    basis = position.entry_cost/position.units
    stage = 5 if position.peak >= basis*1.30 else 8 if position.peak >= basis*1.15 else None
    initial = basis*.93
    trail = position.peak*(.95 if stage == 5 else .92) if stage else None
    known_close = math.isfinite(close) and close > 0
    reason = ('initial_stop7' if known_close and close <= initial else
              'profit_trail5' if known_close and stage == 5 and close <= trail else
              'profit_trail8' if known_close and stage == 8 and close <= trail else
              'below_MA20' if known_close and math.isfinite(ma20) and close < ma20 else
              'age126' if j-position.entry_j >= 126 else None)
    levels = [('initial_stop7', initial)]
    if trail is not None:
        levels.append(('profit_trail'+str(stage), trail))
    if math.isfinite(ma20):
        levels.append(('below_MA20', ma20))
    active_reason, active_level = max(levels, key=lambda x: x[1])
    return {'reason': reason, 'entry_adjusted_basis': basis, 'initial_stop7_level': initial,
            'trailing_stage_pct': stage, 'profit_trail_level': trail,
            'MA20_exit_level': ma20 if math.isfinite(ma20) else None,
            'active_exit_threshold': active_level, 'active_exit_trigger': active_reason,
            'active_exit_comparison': 'strictly_below' if active_reason == 'below_MA20' else 'at_or_below',
            'max_age_exit_j': position.entry_j+126}


class LeaderBook(Book):
    def __init__(self, name, metadata):
        super().__init__(name, metadata)
        self.anchor_peak = self.nav()
        self.cooldown_until = -1
        self.risk_events = []

    def slots_allow(self, code, excluded=()):
        held = [c for c in self.positions if c not in excluded]
        if len(held) >= 8:
            return False
        if not self.sector_rules:
            return True
        industry = group(code, self.metadata)
        if sum(group(c, self.metadata) == industry for c in held) >= (1 if industry == '__unclassified__' else 2):
            return False
        return not (industry in REAL_ESTATE and sum(group(c, self.metadata) in REAL_ESTATE for c in held) >= 2)

    def decisions(self, j, day, panel, features, leader_features, selection, last_j):
        nav = self.nav()
        if self.cooldown_until >= 0 and j >= self.cooldown_until and not self.positions and not self.pending_sells:
            self.cooldown_until = -1
            self.anchor_peak = nav
        self.anchor_peak = max(self.anchor_peak, nav)
        if self.cooldown_until < 0 and nav <= self.anchor_peak*.88:
            self.cooldown_until = j+20
            self.risk_events.append({'date': day, 'j': j, 'nav_carry_proxy_cny': nav,
                                     'anchor_peak': self.anchor_peak, 'cooldown_until_j': self.cooldown_until})
            self.blocks['risk_cancelled_pending_buy'] += sum(i['side'] == 'buy' for i in self.pending)
            self.pending = [i for i in self.pending if i['side'] != 'buy']
            self.pending_buys.clear()
        cooling = self.cooldown_until >= 0
        exits = {}
        for code, position in self.positions.items():
            close = panel[code].adj_close[j] if panel[code].valid[j] else math.nan
            reason = 'portfolio_drawdown12' if cooling else exit_state(position, close, leader_features[code].ma20[j], j)['reason']
            if reason:
                exits[code] = reason
        for code, reason in sorted(exits.items()):
            if code in self.pending_sells or j+1+self.delay > last_j:
                continue
            adv = features[code].adv20[j]
            if not math.isfinite(adv):
                adv = next((features[code].adv20[k] for k in range(j, -1, -1) if math.isfinite(features[code].adv20[k])), 0.)
            self.plan(j, code, 'sell', reason, adv20=adv)
        if cooling or not selection['market_on'] or j+1+self.delay > last_j:
            return
        ranking = selection['sector_rank' if self.sector_rules else 'price_rank']
        # Delayed buys reserve both slots and industry capacity until their attempt.
        reserved = [c for c in self.positions if c not in exits]
        reserved.extend(c for c in sorted(self.pending_buys) if c not in reserved)
        for code in ranking:
            if code in self.positions or code in self.pending_buys or len(reserved) >= 8:
                continue
            industry = group(code, self.metadata)
            if self.sector_rules:
                if sum(group(c, self.metadata) == industry for c in reserved) >= (1 if industry == '__unclassified__' else 2):
                    continue
                if industry in REAL_ESTATE and sum(group(c, self.metadata) in REAL_ESTATE for c in reserved) >= 2:
                    continue
            budget = nav*RULES['new_entry_fraction']
            shares = math.floor(budget/panel[code].raw_close[j]/100)*100
            self.plan(j, code, 'buy', 'daily_technical_leader_breakout' if self.sector_rules else 'daily_liquid_breakout',
                      adv20=features[code].adv20[j], raw_shares=shares, budget_cny=budget)
            reserved.append(code)


def backtest(sessions, panel, metadata):
    features = {c: make_features(s) for c, s in panel.items()}
    extra = {c: make_leader_features(s, features[c]) for c, s in panel.items()}
    start = next(j for j, day in enumerate(sessions) if day >= RULES['start'])
    end = len(sessions)-1
    books = {name: LeaderBook(name, metadata) for name in RULES['curves']}
    signals = []
    for j in range(start, end+1):
        day = sessions[j]
        for book in books.values():
            book.execute(j, day, panel)
            book.mark(j, day, panel)
        selection = select(j, panel, features, extra, metadata)
        signals.append({'date': day, 'j': j, **selection})
        for book in books.values():
            book.decisions(j, day, panel, features, extra, selection, end)
    return books, signals


def run(contract_path, out):
    from qount.research.ashare_backtest_data import load_panel
    contract = json.loads(contract_path.read_text())
    if (contract.get('rules') != RULES or contract.get('research_only') is not True
            or contract.get('orders_authorized') is not False or contract.get('promotion_evidence') is not False
            or contract.get('authorization') != {'backtest': True, 'orders': False, 'services': False}):
        raise ValueError('leader_contract_invalid')
    if (sys.platform != 'linux' or out.exists()
            or not out.resolve().is_relative_to(Path('/mnt/e/qount_data/qount/artifacts/equity_selection'))):
        raise ValueError('fresh_WSL_E_output_required')
    for name, sha in contract['implementation_sha256'].items():
        target = (ROOT/name).resolve()
        if not target.is_relative_to(ROOT) or digest(target) != sha:
            raise ValueError('frozen_code_mismatch:'+name)
    if sys.version.split()[0] != contract['python_version']:
        raise ValueError('python_version_mismatch')
    sessions, panel, metadata, diagnostics = load_panel(contract)
    out.mkdir(parents=True)
    write_json(out/'contract.json', contract)
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    books, signals = backtest(sessions, panel, metadata)
    summary = {'research_only': True, 'orders_authorized': False, 'promotion_evidence': False,
               'status': 'conditional_technical_leader_breakout_adjusted_unit_discovery_backtest',
               'started_at': started, 'finished_at': dt.datetime.now(dt.timezone.utc).isoformat(),
               'price_cutoff': sessions[-1], 'formal_cash_NAV_certified': False, 'historical_PIT_certified': False,
               'financial_or_policy_signal_backtested': False, 'independent_OOS': False,
               'DSR_or_PBO': 'not_computed_new_registered_discovery_after_two_prior_strategy_results',
               'registered_strategy_rule_sets': 1, 'registered_curves': 4, 'parameter_searches': 0,
               'source': diagnostics, 'results': {}}
    write_json(out/'signals.json', signals)
    for name, book in books.items():
        result = metrics(book.curve, book.closed)
        result.update(fees_cny=sum(t['fees_cny'] for t in book.trades), fills=len(book.trades),
                      blocked=dict(book.blocks), final_open_positions=len(book.positions),
                      portfolio_risk_events=len(book.risk_events))
        result['yearly'] = {year: metrics([r for r in book.curve if r['date'].startswith(year)], [],
            initial=next((r['nav_carry_proxy_cny'] for r in reversed(book.curve) if r['date'] < year+'0101'), 1_000_000))
            for year in sorted({r['date'][:4] for r in book.curve})}
        result['segments'] = {label: metrics([r for r in book.curve if lo <= r['date'] <= hi], [],
            initial=next((r['nav_carry_proxy_cny'] for r in reversed(book.curve) if r['date'] < lo), 1_000_000))
            for label, lo, hi in [('2015–2018', '20150101', '20181231'),
                                 ('2019–2022', '20190101', '20221231'), ('2023–2026', '20230101', '20260930')]}
        summary['results'][name] = result
        for suffix, data in [('curve', book.curve), ('fills', book.trades), ('closed', book.closed),
                             ('intents', book.intents), ('risk-events', book.risk_events)]:
            with gzip.open(out/(name+'-'+suffix+'.jsonl.gz'), 'wt', encoding='utf-8') as stream:
                for row in data:
                    stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False)+'\n')
        holdings = []
        for code, position in sorted(book.positions.items()):
            s = panel[code]
            base = make_features(s)
            extra = make_leader_features(s, base)
            close = s.adj_close[-1] if s.valid[-1] else math.nan
            state = exit_state(position, close, extra.ma20[-1], len(sessions)-1)
            if book.cooldown_until >= 0:
                state['reason'] = 'portfolio_drawdown12'
            holdings.append({'symbol': code, 'name': metadata.get(code, {}).get('name'),
                'industry_snapshot': metadata.get(code, {}).get('industry'), **dataclasses.asdict(position), **state,
                'weight_carry_proxy': position.units*position.last_mark/book.nav(),
                'unrealized_proxy_pnl_cny': position.units*position.last_mark-position.entry_cost,
                'current_mark_missing': position.last_mark_j != len(sessions)-1,
                'mark_stale_sessions': len(sessions)-1-position.last_mark_j,
                'entry_date': sessions[position.entry_j],
                'max_age_exit_date': sessions[position.entry_j+126] if position.entry_j+126 < len(sessions) else None,
                'dated_ST_board_tradability': 'pending',
                'fundamental_review': 'latest_financial_valuation_review_pending_not_historical_signal'})
        write_json(out/(name+'-holdings.json'), holdings)
        write_json(out/(name+'-management.json'), {'asof': sessions[-1], 'cash_cny': book.cash,
            'NAV_carry_proxy_cny': book.nav(), 'anchor_peak': book.anchor_peak,
            'cooldown_until_j': book.cooldown_until, 'pending_intents_after_horizon': book.pending,
            'scheduled': False, 'orders_authorized': False})
    primary = summary['results']['sector_base']
    control = summary['results']['price_control']
    summary['decision'] = {
        'historical_proxy_profitable': primary['total_return_carry_proxy'] > 0,
        'all_primary_cost_delay_cells_positive': all(summary['results'][n]['final_unknown_zero_recovery_return'] > 0 for n in RULES['curves'][:3]),
        'sector_increment_total_return_over_price_control': primary['total_return_carry_proxy']-control['total_return_carry_proxy'],
        'production_or_profitability_certification': False,
    }
    write_json(out/'summary.json', summary)
    write_json(out/'manifest.json', {p.name: digest(p) for p in sorted(out.iterdir()) if p.is_file()})
    return summary
