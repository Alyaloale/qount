"""Frozen price-stability/momentum discovery, with no runtime or order interface."""
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

from qount.research.ashare_lowrisk import LowriskBook
from qount.research.ashare_strategy import ROOT, REAL_ESTATE, digest, make_features, metrics, write_json

RULES = {
    'capital_cny': 1_000_000, 'start': '20150101', 'end': '20260930',
    'eligibility': '252_past_valid_raw_observations_including_today_201_consecutive_valid_sessions_ADV20_ge50m',
    'quality': '126_log_return_population_vol_annualized_le1.2_times_same_day_base_eligible_industry_median_before_trend',
    'trend': 'adjusted_close_gt_MA120_and_MA60_gt_MA120',
    'ranking': 'simple_60_session_return_divided_by_annualized_60_log_return_population_vol_desc_symbol_tie_zero_vol_excluded',
    'control': 'same_base_trend_caps_exit_clock_costs_ADV20_desc_symbol_tie_no_quality_filter',
    'industry_snapshot': '20261009_not_PIT_unknown_shared_group_single_member_median_allowed',
    'maximum_positions': 10, 'new_entry_fraction': .1, 'industry_slots': 2, 'real_estate_slots': 4,
    'review_clock': 'first_2015_session_then_every10_exchange_sessions',
    'retention_rank': 20, 'rank_caps': 'top20_greedily_industry_diversified_for_each_curve',
    'exit_priority': ['portfolio_drawdown20', 'trailing18_close', 'below_MA120_close', 'age_gt252', 'review_rank_exit'],
    'portfolio_risk': '20pct_anchor_drawdown_cancel_pending_buys_liquidate_63_full_subsequent_sessions_and_all_exits_complete_before_reset',
    'execution': 'frozen_ashare_strategy_Book_costs_open_guard_Tplus1_1pct_prior_ADV_synthetic_adjusted_units',
    'curves': ['sector_base', 'sector_double_cost', 'sector_extra_day', 'price_control'],
    'quality_is_fundamental': False, 'independent_OOS': False,
}
GATE = {'all_three_primary_unknown_zero_CAGR_positive': True, 'base_CAGR_positive': True,
        'maximum_drawdown_magnitude': .4, 'minimum_closed_trades': 100,
        'increment_over_control_required': False, 'failure_action': 'retain_and_stop_frozen_implementation_no_parameter_rescue'}


@dataclasses.dataclass
class QualityFeatures:
    base: object
    ma120: array
    vol126: array
    vol60: array
    score: array


def rolling(s, length, *, volatility=False):
    """Exact exchange-session windows; missing days never compress time."""
    result = array('d', [math.nan]) * len(s.valid)
    window = collections.deque()
    total = squares = 0.
    count = 0
    for j in range(len(s.valid)):
        value = math.nan
        if s.valid[j]:
            if not volatility:
                value = s.adj_close[j]
            elif j and s.valid[j-1]:
                value = math.log(s.adj_close[j] / s.adj_close[j-1])
        window.append(value)
        if math.isfinite(value):
            total += value; squares += value * value; count += 1
        if len(window) > length:
            old = window.popleft()
            if math.isfinite(old):
                total -= old; squares -= old * old; count -= 1
        if len(window) == length and count == length:
            result[j] = (math.sqrt(max(0., squares / length - (total / length) ** 2)) * math.sqrt(252)
                         if volatility else total / length)
    return result


def quality_features(s):
    base = make_features(s)
    ma120, v126, v60 = rolling(s, 120), rolling(s, 126, volatility=True), rolling(s, 60, volatility=True)
    score = array('d', [math.nan]) * len(s.valid)
    for j in range(60, len(s.valid)):
        if base.eligible[j] and math.isfinite(v60[j]) and v60[j] > 0:
            score[j] = (s.adj_close[j] / s.adj_close[j-60] - 1) / v60[j]
    return QualityFeatures(base, ma120, v126, v60, score)


def industry(metadata, code):
    return metadata.get(code, {}).get('industry') or '__unclassified__'


def diversify(codes, metadata):
    counts = collections.Counter(); real = 0; result = []
    for code in codes:
        group = industry(metadata, code)
        if counts[group] >= 2 or (group in REAL_ESTATE and real >= 4):
            continue
        result.append(code); counts[group] += 1; real += group in REAL_ESTATE
        if len(result) == 20:
            break
    return result


def select(j, panel, features, metadata):
    eligible = [c for c, f in features.items() if f.base.eligible[j] and math.isfinite(f.vol126[j])]
    groups = collections.defaultdict(list)
    for c in eligible:
        groups[industry(metadata, c)].append(features[c].vol126[j])
    medians = {g: statistics.median(values) for g, values in groups.items()}
    trend = [c for c in eligible if panel[c].adj_close[j] > features[c].ma120[j]
             and features[c].base.ma60[j] > features[c].ma120[j]]
    quality = [c for c in trend if features[c].vol126[j] <= 1.2 * medians[industry(metadata, c)]
               and math.isfinite(features[c].score[j])]
    primary = diversify(sorted(quality, key=lambda c: (-features[c].score[j], c)), metadata)
    control = diversify(sorted(trend, key=lambda c: (-features[c].base.adv20[j], c)), metadata)
    return {'eligible_count': len(eligible), 'trend_count': len(trend), 'quality_count': len(quality),
            'industry_medians': medians, 'sector_rank': primary, 'price_rank': control,
            'eligible_retired': sum(panel[c].source_kind == 'tushare_retired' for c in eligible)}


class QualityMomentumBook(LowriskBook):
    # The liquidity control keeps the same exposure caps to isolate selection.
    @property
    def sector_rules(self):
        return True

    def decisions(self, j, day, panel, features, selection, review, last_j):
        nav = self.nav()
        if self.cooldown_until >= 0 and j >= self.cooldown_until and not self.positions and not self.pending_sells:
            self.cooldown_until = -1; self.anchor_peak = nav
        self.anchor_peak = max(self.anchor_peak, nav)
        if self.cooldown_until < 0 and nav <= self.anchor_peak * .8:
            self.cooldown_until = j + 64
            self.risk_events.append({'date': day, 'j': j, 'nav_carry_proxy_cny': nav,
                                     'anchor_peak': self.anchor_peak, 'cooldown_until_j': self.cooldown_until})
            self.blocks['risk_cancelled_pending_buy'] += sum(i['side'] == 'buy' for i in self.pending)
            self.pending = [i for i in self.pending if i['side'] != 'buy']; self.pending_buys.clear()
        cooling = self.cooldown_until >= 0
        ranking = selection['price_rank' if self.name == 'price_control' else 'sector_rank']
        exits = {}
        for code, p in self.positions.items():
            close = panel[code].adj_close[j] if panel[code].valid[j] else math.nan
            ma = features[code].ma120[j]
            reason = ('portfolio_drawdown20' if cooling else
                      'trailing18_close' if math.isfinite(close) and p.peak > 0 and close <= p.peak * .82 else
                      'below_MA120_close' if math.isfinite(close) and math.isfinite(ma) and close < ma else
                      'age_gt252' if j - p.entry_j > 252 else
                      'review_rank_exit' if review and code not in ranking else None)
            if reason:
                exits[code] = reason
        for code, reason in sorted(exits.items()):
            if code in self.pending_sells or j + 1 + self.delay > last_j:
                continue
            values = features[code].base.adv20
            adv = next((values[k] for k in range(j, -1, -1) if math.isfinite(values[k])), 0.)
            self.plan(j, code, 'sell', reason, adv20=adv)
        if not review or cooling or j + 1 + self.delay > last_j:
            return
        reserved = [c for c in self.positions if c not in exits]
        reserved.extend(c for c in self.pending_buys if c not in reserved)
        for code in ranking:
            if code in self.positions or code in reserved or len(reserved) >= 10:
                continue
            group = industry(self.metadata, code)
            if sum(industry(self.metadata, c) == group for c in reserved) >= 2:
                continue
            if group in REAL_ESTATE and sum(industry(self.metadata, c) in REAL_ESTATE for c in reserved) >= 4:
                continue
            budget = nav * .1
            shares = math.floor(budget / panel[code].raw_close[j] / 100) * 100
            self.plan(j, code, 'buy', 'quality_momentum_review_entry', raw_shares=shares,
                      budget_cny=budget, adv20=features[code].base.adv20[j])
            reserved.append(code)


def backtest(sessions, panel, metadata):
    features = {c: quality_features(s) for c, s in panel.items()}
    start = next(j for j, day in enumerate(sessions) if day >= RULES['start'])
    books = {name: QualityMomentumBook(name, metadata) for name in RULES['curves']}
    signals = []
    for j in range(start, len(sessions)):
        day = sessions[j]; review = (j - start) % 10 == 0
        for book in books.values():
            book.execute(j, day, panel); book.mark(j, day, panel)
        selection = select(j, panel, features, metadata) if review else {'sector_rank': [], 'price_rank': []}
        if review:
            signals.append({'date': day, 'j': j, **selection})
        for book in books.values():
            book.decisions(j, day, panel, features, selection, review, len(sessions)-1)
    return books, signals, features


def evaluate_gate(results):
    base = results['sector_base']
    checks = {
        'all_primary_unknown_zero_CAGR_positive': all(
            results[n]['CAGR_unknown_zero_recovery'] is not None and results[n]['CAGR_unknown_zero_recovery'] > 0
            for n in RULES['curves'][:3]),
        'base_CAGR_positive': base['CAGR_carry_proxy'] > 0,
        'base_drawdown_le40pct': base['max_drawdown_carry_proxy'] >= -.4,
        'base_closed_ge100': base['closed_trades'] >= 100,
    }
    return {'checks': checks, 'passed': all(checks.values()),
            'action': 'retain_candidate_wait_fresh_confirmation' if all(checks.values()) else GATE['failure_action'],
            'increment_over_control_CAGR_descriptive': base['CAGR_carry_proxy'] - results['price_control']['CAGR_carry_proxy'],
            'production_or_profitability_certification': False}


def validate_contract(contract):
    if (contract.get('rules') != RULES or contract.get('research_gate') != GATE
        or contract.get('authorization') != {'backtest': True, 'orders': False, 'services': False}
        or contract.get('research_only') is not True or contract.get('orders_authorized') is not False
        or contract.get('promotion_evidence') is not False):
        raise ValueError('quality_momentum_contract_invalid')
    required = {'src/qount/research/ashare_quality_momentum.py', 'src/qount/research/ashare_lowrisk.py',
                'src/qount/research/ashare_strategy.py', 'src/qount/research/ashare_backtest_data.py',
                'scripts/research/ashare_quality_momentum.py', 'tests/test_ashare_quality_momentum.py'}
    if not required <= contract.get('implementation_sha256', {}).keys():
        raise ValueError('required_frozen_sources_missing')
    for name, sha in contract['implementation_sha256'].items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT) or digest(path) != sha:
            raise ValueError('frozen_code_mismatch:' + name)
    if sys.version.split()[0] != contract['python_version']:
        raise ValueError('python_version_mismatch')


def run(contract_path, out):
    from qount.research.ashare_backtest_data import load_panel
    contract = json.loads(contract_path.read_text())
    validate_contract(contract)
    root = Path('/mnt/e/qount_data/qount/artifacts/equity_selection')
    if sys.platform != 'linux' or out.exists() or not out.resolve().is_relative_to(root):
        raise ValueError('fresh_WSL_E_required')
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    sessions, panel, metadata, diagnostics = load_panel(contract)
    out.mkdir(parents=True); write_json(out / 'contract.json', contract)
    books, signals, features = backtest(sessions, panel, metadata)
    summary = {'research_only': True, 'orders_authorized': False, 'promotion_evidence': False,
               'status': 'completed_price_stability_momentum_discovery', 'started_at': started,
               'finished_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'price_cutoff': sessions[-1],
               'contract_sha256': digest(contract_path), 'source': diagnostics, 'results': {},
               'formal_cash_NAV_certified': False, 'historical_PIT_certified': False, 'independent_OOS': False,
               'financial_signal_backtested': False, 'DSR_or_PBO': 'not_computed',
               'registered_strategy_rule_sets': 1, 'cumulative_primary_rule_sets': contract['trials']['cumulative_primary_rule_sets'],
               'registered_curves': 4, 'parameter_searches': 0}
    write_json(out / 'signals.json', signals)
    for name, book in books.items():
        result = metrics(book.curve, book.closed)
        result.update(fees_cny=sum(t['fees_cny'] for t in book.trades), fills=len(book.trades),
                      blocked=dict(book.blocks), final_open_positions=len(book.positions), portfolio_risk_events=len(book.risk_events))
        result['yearly'] = {y: metrics([r for r in book.curve if r['date'].startswith(y)], [],
            initial=next((r['nav_carry_proxy_cny'] for r in reversed(book.curve) if r['date'] < y+'0101'), 1_000_000))
            for y in sorted({r['date'][:4] for r in book.curve})}
        result['segments'] = {label: metrics([r for r in book.curve if lo <= r['date'] <= hi], [],
            initial=next((r['nav_carry_proxy_cny'] for r in reversed(book.curve) if r['date'] < lo), 1_000_000))
            for label, lo, hi in [('2015–2018','20150101','20181231'), ('2019–2022','20190101','20221231'), ('2023–2026','20230101','20260930')]}
        result['exit_reasons'] = {reason: {'closed': len(rows), 'pnl_cny': sum(t['pnl_cny'] for t in rows)}
            for reason in sorted({t['reason'] for t in book.closed})
            for rows in [[t for t in book.closed if t['reason'] == reason]]}
        summary['results'][name] = result
        for suffix, data in [('curve',book.curve), ('fills',book.trades), ('closed',book.closed), ('intents',book.intents), ('risk-events',book.risk_events)]:
            with gzip.open(out / (name+'-'+suffix+'.jsonl.gz'), 'wt', encoding='utf-8') as stream:
                for row in data:
                    stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False)+'\n')
        holdings = []
        for code, p in sorted(book.positions.items()):
            ma = features[code].ma120[-1]
            holdings.append({'symbol': code, 'name': metadata.get(code, {}).get('name'), 'industry_snapshot': industry(metadata, code),
                **dataclasses.asdict(p), 'entry_date': sessions[p.entry_j], 'weight_carry_proxy': p.units*p.last_mark/book.nav(),
                'current_mark_missing': p.last_mark_j != len(sessions)-1, 'MA120_exit_level': ma if math.isfinite(ma) else None,
                'trailing_exit_level': p.peak*.82, 'first_age_exit_j': p.entry_j+253, 'current_tradability': 'not_certified'})
        write_json(out / (name+'-holdings.json'), holdings)
        write_json(out / (name+'-management.json'), {'asof': sessions[-1], 'cash_cny': book.cash, 'NAV_carry_proxy_cny': book.nav(),
            'anchor_peak': book.anchor_peak, 'cooldown_until_j': book.cooldown_until, 'pending_intents_after_horizon': book.pending,
            'scheduled': False, 'orders_authorized': False})
    summary['decision'] = evaluate_gate(summary['results'])
    write_json(out / 'summary.json', summary)
    write_json(out / 'manifest.json', {p.name: digest(p) for p in sorted(out.iterdir()) if p.is_file()})
    return summary
