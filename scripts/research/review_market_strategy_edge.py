"""Separate traditional strategy edge from incremental state-model routing.

Fixed existing strategies/70% threshold, retained public caches only. Separate
strategy portfolios are diagnostics, never an additive deployable portfolio.
Counterfactual opportunities can overlap and are not independent observations.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import datetime as dt
import json
from pathlib import Path

import numpy as np

from qount.research.market_model_profit import replay_asset, summarize_portfolio
from qount.research.market_stages import market_state_machine
from qount.research.market_strategy_router import STATE_NAMES, STRATEGIES, StrategyRoute, traditional_entry
from study_binance_market_states import load_markets
from study_market_model_profit import DAILY, RAW, daily_bars, exchange_rules, load_npz
from study_market_strategy_router import PANEL, REFERENCE, known_time, model_route, open_time


SEED = 311026
POLICIES = ('rules_full', 'rules_common', 'persist5_common', 'model_argmax', 'model70', 'rules_and_model70')
STRATEGY_NAMES = tuple(s for s in STRATEGIES.values() if s is not None)


def quarter(stamp):
    d = dt.datetime.fromtimestamp(int(stamp) / 1000, dt.timezone.utc)
    return f'{d.year}Q{(d.month - 1) // 3 + 1}'


def cluster_interval(values, clocks, *, weights=None):
    """Resample whole calendar quarters, sharing shocks across all assets.

    With weights, estimate a weighted mean (e.g. mean payoff per trade).
    Otherwise estimate the mean of quarter totals, including supplied zeros.
    These exploratory intervals are not multiple-comparison adjusted.
    """
    sums = defaultdict(float); counts = defaultdict(float)
    for v, t, w in zip(values, clocks, np.ones(len(values)) if weights is None else weights):
        q = quarter(t); sums[q] += float(v); counts[q] += float(w)
    keys = sorted(sums); a = np.array([sums[k] for k in keys]); b = np.array([counts[k] for k in keys])
    point = (float(a.sum() / b.sum()) if b.sum() else None) if weights is not None else (float(a.mean()) if len(a) else None)
    result = dict(quarter_clusters=len(keys), mean=point, interval95=None)
    if len(keys) >= 4:
        ix = np.random.default_rng(SEED).integers(0, len(a), (5000, len(a)))
        if weights is None: draws = a[ix].mean(1)
        else:
            den = b[ix].sum(1); draws = a[ix].sum(1)[den > 0] / den[den > 0]
        if len(draws): result['interval95'] = np.quantile(draws, [.025, .975]).tolist()
    return result


def payoff_stats(trades):
    if not trades: return dict(trades=0, mean_net_notional=None, interval95=None)
    y = np.array([t['net_pnl'] / (t['quantity'] * t['entry']) for t in trades])
    clocks = [t['entry_at'] for t in trades]
    result = cluster_interval(y, clocks, weights=np.ones(len(y)))
    pnl = [t['net_pnl'] for t in trades]
    result.update(trades=len(trades), mean_net_notional=float(y.mean()), win_rate=float(np.mean(y > 0)),
        profit_factor=sum(v for v in pnl if v > 0) / max(-sum(v for v in pnl if v < 0), 1e-12),
        exit_reasons=dict(Counter(t['reason'] for t in trades)),
        net_pnl_without_best_trade=sum(pnl) - max(pnl),
        asset_pnl={a: sum(t['net_pnl'] for t in trades if t['asset'] == a) for a in sorted({t['asset'] for t in trades})})
    result['net_pnl_without_best_asset'] = sum(pnl) - max(result['asset_pnl'].values())
    if all('net_R' in t for t in trades):
        result['planned_R'] = cluster_interval([t['net_R'] for t in trades], clocks, weights=np.ones(len(trades)))
    return result


def message(book, at, bars, group):
    ix = int(np.searchsorted(book['known_at'], at, side='right') - 1)
    if ix < 0: return None
    i = int(book['bar_index'][ix])
    if i + 5 >= len(bars) or at >= known_time(bars[i + 5], group): return None
    return ix


def opportunity_universe(markets, states, books):
    rows = []; observations = defaultdict(Counter)
    for group, assets in markets.items():
        for asset, bars in assets.items():
            book = books[asset]
            for i, bar in enumerate(bars):
                at = i + (2 if group == 'crypto' else 1)
                known = known_time(bar, group)
                if known < 1672531200000 or at >= len(bars): continue
                f = states[group][asset][bar.t]
                if f['action_state'] in ('unknown', 'shock'): continue
                entry_at = open_time(bars[at], group)
                left = message(book, known, bars, group); right = message(book, entry_at, bars, group)
                coverage = left is not None and right is not None
                routes = {threshold: (model_route(book, known, bars, group, threshold)[0],
                                     model_route(book, entry_at, bars, group, threshold)[0]) for threshold in (0., .7)}
                past_states = [None, None]
                if coverage:
                    past_states = [states[group][asset][bars[int(book['bar_index'][j])].t]['action_state'] for j in (left, right)]
                for assigned_state, strategy in STRATEGIES.items():
                    if strategy is None: continue
                    rule = traditional_entry(StrategyRoute(assigned_state, 1., strategy, 'counterfactual'), bar, f, allow_short=group == 'crypto')
                    if rule is None: continue
                    model = {threshold: bool(coverage and all(r.strategy == strategy for r in route)) for threshold, route in routes.items()}
                    current = STRATEGIES[f['action_state']] == strategy
                    masks = dict(rules_full=current, rules_common=current and coverage,
                        persist5_common=coverage and all(STRATEGIES[s] == strategy for s in past_states),
                        model_argmax=model[0.], model70=model[.7], rules_and_model70=current and model[.7],
                        ungated_common=coverage)
                    source_index = int(book['bar_index'][left]) if left is not None else None
                    future = states[group][asset][bars[source_index + 5].t]['action_state'] if source_index is not None else None
                    rows.append(dict(group=group, asset=asset, assigned_state=assigned_state, current_state=f['action_state'],
                        known_at=known, entry_at=entry_at, capacity=float(bar.v * bar.c * .001),
                        coverage=coverage, masks=masks, endpoint_actual=future,
                        forecast_state=routes[0.][0].state, forecast_confidence=routes[0.][0].probability,
                        model_known_at=int(book['known_at'][left]) if left is not None else None, **rule))
                    observations[group][strategy] += 1
    return rows, {g: dict(v) for g, v in observations.items()}


def replay(rows, prices, raw, filters, group, policy, cost, strategy=None):
    selected = [r for r in rows if r['group'] == group and r['masks'][policy] and (strategy is None or r['strategy'] == strategy)]
    by_asset = defaultdict(list)
    for r in selected: by_asset[r['asset']].append(r)
    sleeves = {}
    for asset, bars in prices[group].items():
        rules = execution_rules(filters, group, asset, cost)
        s = replay_asset(bars, by_asset[asset], [] if group == 'etf_proxy' else raw[asset + '_funding'], initial=10000 / len(prices[group]), rules=rules)
        s['start_at'] = int(bars[0, 0]); sleeves[asset] = s
    summary, clocks, nav, trades = summarize_portfolio(sleeves, 10000, continuous=True)
    lookup = {(r['asset'], r['known_at']): r for r in selected}
    for t in trades:
        d = lookup[t['asset'], t['known_at']]; rules = execution_rules(filters, group, t['asset'], cost)
        distance = abs(t['entry'] - d['stop']) + t['entry'] * 2 * (rules['fee'] + rules['slippage'])
        t['net_R'] = t['net_pnl'] / (t['quantity'] * distance)
        t['strategy'] = d['strategy']
    return dict(group=group, policy=policy, cost_multiplier=cost, strategy=strategy,
                proposals=len(selected), summary=summary, trade_payoffs=payoff_stats(trades)), clocks, nav, trades


def execution_rules(filters, group, asset, cost):
    rules = dict(tick=0., step=1., min_qty=1., min_notional=0.) if group == 'etf_proxy' else filters[asset].copy()
    rules.update(fee=.0005 * cost, slippage=(.0015 if group == 'etf_proxy' else .0002) * cost, continuous_clock=group == 'crypto')
    return rules


def independent_opportunities(rows, prices, raw, filters):
    """One fixed-capital bracket per setup; overlaps are diagnostic only."""
    funding = {}
    for asset, events in raw.items():
        if asset.endswith('_funding'):
            stamps = np.array([int(e['fundingTime']) for e in events]); order = np.argsort(stamps)
            funding[asset[:-8]] = (stamps[order], [events[int(i)] for i in order])
    for row in rows:
        if not row['coverage']: continue
        group = row['group']; asset = row['asset']; bars = prices[group][asset]
        i = int(np.searchsorted(bars[:, 0], row['entry_at'])); end = i + row['max_bars']
        if end >= len(bars): continue
        events = []
        if group == 'crypto':
            stamps, values = funding[asset]
            lo = int(np.searchsorted(stamps, int(bars[i, 0]))); hi = int(np.searchsorted(stamps, int(bars[end, 6]), side='right'))
            events = values[lo:hi]
        s = replay_asset(bars[i:end + 1], [row], events, initial=10000 / len(prices[group]), rules=execution_rules(filters, group, asset, 1))
        if s['trades']:
            t = s['trades'][0]
            distance = abs(t['entry'] - row['stop']) + t['entry'] * (.001 + ( .003 if group == 'etf_proxy' else .0004))
            row['standalone'] = dict(filled=True, net_R=t['net_pnl'] / (t['quantity'] * distance),
                net_notional=t['net_pnl'] / (t['quantity'] * t['entry']), net_pnl=t['net_pnl'],
                gross_pnl=t['gross_pnl'], friction=t['fees'] + t['slippage_and_rounding'], funding=t['funding'], reason=t['reason'])
        else: row['standalone'] = dict(filled=False, net_R=0., net_notional=0., net_pnl=0., reason=next(iter(s['skips']), 'no_fill'))


def selection_diagnostics(rows, group, strategy=None, *, selection='model70', pool_policy='ungated_common'):
    pool = [r for r in rows if r['group'] == group and 'standalone' in r
            and r['masks'].get(pool_policy, pool_policy == 'ungated_common') and (strategy is None or r['strategy'] == strategy)]
    selected = [r for r in pool if r['masks'][selection]]
    if not selected: return dict(group=group, strategy=strategy, selection=selection, pool=pool_policy, selected_proposals=0)
    rejected = [r for r in pool if not r['masks'][selection]]
    def stats(v):
        if not v: return dict(proposals=0)
        y = [r['standalone']['net_R'] for r in v]
        result = cluster_interval(y, [r['known_at'] for r in v], weights=np.ones(len(v)))
        result.update(proposals=len(v), filled=sum(r['standalone']['filled'] for r in v), mean_net_R=float(np.mean(y)),
            mean_net_notional=float(np.mean([r['standalone']['net_notional'] for r in v])),
            correct_future_state=sum(r['forecast_state'] == r['endpoint_actual'] for r in v) / len(v))
        return result
    strata = defaultdict(list)
    for r in pool: strata[r['asset'], r['strategy'], quarter(r['known_at'])].append(r)
    draws = np.zeros(3000); rng = np.random.default_rng(SEED)
    for values in strata.values():
        k = sum(r['masks'][selection] for r in values)
        if not k: continue
        y = np.array([r['standalone']['net_R'] for r in values])
        # Exactly the same proposal count per asset/strategy/quarter.
        ix = np.argsort(rng.random((len(draws), len(values))), axis=1)[:, :k]
        draws += y[ix].sum(1) / len(selected)
    actual = float(np.mean([r['standalone']['net_R'] for r in selected]))
    correct = [r for r in selected if r['forecast_state'] == r['endpoint_actual']]
    incorrect = [r for r in selected if r['forecast_state'] != r['endpoint_actual']]
    a = stats(correct); b = stats(incorrect)
    win = a.get('mean_net_R'); loss = b.get('mean_net_R')
    breakeven = -loss / (win - loss) if win is not None and loss is not None and win > 0 > loss else None
    return dict(group=group, strategy=strategy, selection=selection, pool=pool_policy,
        selected_proposals=len(selected), selected=stats(selected), rejected=stats(rejected),
        correct_endpoint=stats(correct), incorrect_endpoint=stats(incorrect),
        same_sample_break_even_endpoint_precision=breakeven,
        matched_random=dict(draws=len(draws), mean_net_R=float(draws.mean()), interval95=np.quantile(draws, [.025, .975]).tolist(),
            observed_minus_random_mean=actual - float(draws.mean()), percentile=float(np.mean(draws <= actual)),
            note='Fixed-capital overlapping counterfactuals, not portfolio returns or independent-sample p-values.'))


def forecast_diagnostics(panel, archive):
    out = []
    for group in ('crypto', 'etf_proxy'):
        mask = panel['group'][archive['index']] == group; ix = archive['index'][mask]; p = archive['probabilities'][mask]
        y = panel['outcome'][ix]; top = p.argmax(1); confidence = p.max(1); current = panel['current_state'][ix]
        for s, name in enumerate(STATE_NAMES[:-1]):
            high = (top == s) & (confidence >= .7); chosen = top == s
            out.append(dict(group=group, state=name, actual_count=int(sum(y == s)), total_forecasts=len(y),
                top_predictions=int(sum(chosen)), high_predictions=int(sum(high)), maximum_probability=float(p[:, s].max()),
                top_precision=float(np.mean(y[chosen] == s)) if chosen.any() else None,
                high_precision=float(np.mean(y[high] == s)) if high.any() else None,
                high_mean_probability=float(confidence[high].mean()) if high.any() else None,
                persistence_accuracy=float(np.mean(current == y)), overall_accuracy=float(np.mean(top == y))))
    return out


def portfolio_comparison(a, b, *, exposure_match=False):
    ra, ta, na = a; rb, tb, nb = b
    if not np.array_equal(ta, tb): raise ValueError('review_paired_calendar')
    ar = np.diff(np.log(np.r_[10000., na])); br = np.diff(np.log(np.r_[10000., nb]))
    scale = ra['summary']['average_exposure'] / rb['summary']['average_exposure'] if exposure_match and rb['summary']['average_exposure'] else 1.
    diff = ar - br * scale
    result = cluster_interval(diff, ta)
    result.update(group=ra['group'], left=ra['policy'], right=rb['policy'], exposure_matched=exposure_match,
        reference_scale=scale, total_log_excess=float(diff.sum()),
        positive_years=int(sum(sum(v for v, t in zip(diff, ta) if str(np.datetime64(int(t), 'ms'))[:4] == y) > 0 for y in ra['summary']['yearly_returns'])))
    return result


def report(r):
    lines = ['# 传统策略净优势与模型路由增量复审', '',
        '固定既有规则和70%阈值，未训练或搜索参数。历史已消费，所有区间均为探索性，未做多重比较调整。', '',
        '## 对应当前状态：独立策略组合（共同预测覆盖期，基础成本）', '',
        '|市场/策略|交易|净收益|双摩擦收益|每笔计划净R及季度簇95%区间|去最大赢家净盈亏|',
        '|---|---:|---:|---:|---|---:|']
    def pct(x): return '—' if x is None else f'{x:+.3%}'
    for x in r['strategy_runs']:
        if x['policy'] != 'rules_common' or x['cost_multiplier'] != 1: continue
        stress = next(z for z in r['strategy_runs'] if all(z[k] == x[k] for k in ('group', 'strategy', 'policy')) and z['cost_multiplier'] == 2)
        t = x['trade_payoffs']; risk = t.get('planned_R', {}); ci = risk.get('interval95')
        lines.append(f"|{x['group']}/{x['strategy']}|{t['trades']}|{pct(x['summary']['total_return'])}|{pct(stress['summary']['total_return'])}|{risk.get('mean')}; {ci if ci else '不足4季度'}|{t.get('net_pnl_without_best_trade',0):+.3f}|")
    lines += ['', '每个策略独立分配10,000、每标的等额袖套，策略之间结果不可相加；每策略每标的一仓。', '',
        '## 对应状态策略的年度、成本与集中度', '',
        '|市场/策略|各年收益|价格毛盈亏|资金费|费用及滑点|剔除最大盈利资产后的静态净盈亏|',
        '|---|---|---:|---:|---:|---:|']
    for x in r['strategy_runs']:
        if x['policy'] != 'rules_common' or x['cost_multiplier'] != 1 or not x['summary']['trades']: continue
        s = x['summary']; c = s['components']; years = ', '.join(f'{y}:{pct(v)}' for y, v in s['yearly_returns'].items())
        lines.append(f"|{x['group']}/{x['strategy']}|{years}|{c['gross_pnl']:+.3f}|{c['funding']:+.3f}|{c['fees']+c['slippage_and_rounding']:.3f}|{x['trade_payoffs']['net_pnl_without_best_asset']:+.3f}|")
    lines += ['', '静态剔除只检查集中度，不是删掉资产后的可执行回测；价格毛盈亏未扣滑点/手续费，资金费单列。', '',
        '## 组合路由对照', '', '|市场/路由|成本倍数|交易|累计净收益|CAGR|收盘MDD|平均收盘名义敞口|', '|---|---:|---:|---:|---:|---:|---:|']
    for x in r['portfolio_runs']:
        s = x['summary']; lines.append(f"|{x['group']}/{x['policy']}|{x['cost_multiplier']}|{s['trades']}|{pct(s['total_return'])}|{pct(s['cagr'])}|{pct(s['mdd_close'])}|{s['average_exposure']:.3%}|")
    lines += ['', '## 模型组合相对规则：季度配对', '', '|市场/对照|敞口匹配|参考缩放|累计对数收益增量|平均季度增量95%区间|', '|---|---|---:|---:|---|']
    for x in r['portfolio_comparisons']:
        lines.append(f"|{x['group']}/{x['left']} vs {x['right']}|{x['exposure_matched']}|{x['reference_scale']:.4f}|{pct(x['total_log_excess'])}|{[pct(v) for v in x['interval95']] if x['interval95'] else '不足4季度'}|")
    lines += ['', '敞口匹配为事后按平均收盘名义敞口缩放对照的对数收益，不是可执行重跑，也不保证相同风险/周转；只用于区分减少持仓与选择增量。', '',
        '## 固定机会选择：模型70%与同资产/策略/季度等数量随机选择', '',
        '|市场/策略|选中提议/独立成交|平均净R及季度簇95%区间|随机均值净R|差值|相对随机分位|', '|---|---:|---|---:|---:|---:|']
    for x in r['selection_diagnostics']:
        if not x['selected_proposals']: continue
        s = x['selected']; p = x['matched_random']
        lines.append(f"|{x['group']}/{x['strategy'] or 'all'}|{s['proposals']}/{s['filled']}|{s['mean_net_R']:+.4f}; {s['interval95']}|{p['mean_net_R']:+.4f}|{p['observed_minus_random_mean']:+.4f}|{p['percentile']:.1%}|")
    lines += ['', '独立机会允许重叠、固定初始资金，未成交记0；不是组合净值或独立交易样本。随机分位不是经调整的显著性。', '',
        '## 当前状态过滤本身是否增加优势', '',
        '|市场/策略|当前状态选中提议|平均净R|同资产/策略/季度等量随机净R|差值|随机分位|', '|---|---:|---:|---:|---:|---:|']
    for x in r['state_filter_selection']:
        if not x['selected_proposals']: continue
        s = x['selected']; p = x['matched_random']
        lines.append(f"|{x['group']}/{x['strategy']}|{s['proposals']}|{s['mean_net_R']:+.4f}|{p['mean_net_R']:+.4f}|{p['observed_minus_random_mean']:+.4f}|{p['percentile']:.1%}|")
    lines += ['', '## 模型70%：预测对错与收益', '',
        '|市场|选中提议|状态命中率|状态正确时平均净R|错误时平均净R|同样本盈亏平衡命中率|', '|---|---:|---:|---:|---:|---:|']
    for x in r['selection_diagnostics']:
        if x['strategy'] is not None: continue
        lines.append(f"|{x['group']}|{x['selected_proposals']}|{pct(x['selected']['correct_future_state'])}|{x['correct_endpoint'].get('mean_net_R')}|{x['incorrect_endpoint'].get('mean_net_R')}|{pct(x['same_sample_break_even_endpoint_precision'])}|")
    lines += ['', '盈亏平衡命中率只由同批样本分组均值代数推算，没有收益预测能力或未来可迁移性保证；实际交易还受重叠占仓与风险定仓影响。', '',
        '## 状态预测覆盖', '', '|市场/状态|真实样本|最大预测概率|最大概率类别次数|≥70%次数|≥70%实测命中率|', '|---|---:|---:|---:|---:|---:|']
    for x in r['forecast_diagnostics']:
        lines.append(f"|{x['group']}/{x['state']}|{x['actual_count']}|{x['maximum_probability']:.2%}|{x['top_predictions']}|{x['high_predictions']}|{pct(x['high_precision'])}|")
    lines += ['', '## 限制与复核', '', *['- ' + x for x in r['limitations']], '',
        f"原12组组合回放复现：{r['old_control_matches']}；独立机会账本数：{r['opportunity_count']}。", '']
    return '\n'.join(lines)


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--output', type=Path, required=True); args = p.parse_args()
    if args.output.exists(): p.error('preserve prior artifacts; choose a new directory')
    parent = load_npz(DAILY); panel = load_npz(PANEL); archive = load_npz(REFERENCE / 'phase_predictions.npz')
    markets, _, sources = load_markets(); raw = json.loads(RAW.read_text())['data']; filters = exchange_rules()
    states = {g: {a: market_state_machine(b) for a, b in assets.items()} for g, assets in markets.items()}
    prices = {g: daily_bars(assets, g) for g, assets in markets.items()}; books = {}
    for asset in sorted(set(panel['asset'])):
        use = np.flatnonzero(panel['asset'][archive['index']] == asset); ix = archive['index'][use]; order = np.argsort(panel['known_at'][ix]); ix = ix[order]
        books[str(asset)] = dict(known_at=panel['known_at'][ix], bar_index=parent['bar_index'][panel['original_row'][ix]], probabilities=archive['probabilities'][use][order])
    rows, counts = opportunity_universe(markets, states, books)
    print('all strategy setups', len(rows), flush=True)
    portfolios = []; strategy_runs = []; curves = {}; trades = []; paired = {}; old_matches = 0
    old = json.loads(Path('state/research_runs/market_strategy_router_20261031/results.json').read_text())
    old_curves = load_npz(Path('state/research_runs/market_strategy_router_20261031/equity.npz'))
    for group in markets:
        for policy in POLICIES:
            for cost in (1, 2):
                run, clocks, nav, tt = replay(rows, prices, raw, filters, group, policy, cost)
                run['id'] = len(portfolios); portfolios.append(run); curves['time_' + str(run['id'])] = clocks; curves['nav_' + str(run['id'])] = nav
                trades.extend(dict(run_id=run['id'], **t) for t in tt)
                if cost == 1: paired[group, policy] = (run, clocks, nav)
                prior_policy = {'rules_full': 'rules_only', 'model_argmax': 'model_argmax', 'model70': 'model70'}.get(policy)
                if prior_policy:
                    prior = next(x for x in old['runs'] if x['group'] == group and x['policy'] == prior_policy and x['cost_multiplier'] == cost)
                    if run['summary']['trades'] != prior['summary']['trades'] or not np.isclose(run['summary']['final_equity'], prior['summary']['final_equity'], rtol=0, atol=1e-8):
                        raise ValueError('review_failed_original_control')
                    if (not np.array_equal(clocks, old_curves['times_' + str(prior['id'])])
                            or not np.allclose(nav, old_curves['nav_' + str(prior['id'])], rtol=0, atol=1e-8)):
                        raise ValueError('review_failed_original_nav_control')
                    old_matches += 1
                print(group, policy, cost, run['summary']['trades'], round(run['summary']['total_return'], 6), flush=True)
        for strategy in STRATEGY_NAMES:
            for policy in ('ungated_common', 'rules_common', 'model_argmax', 'model70'):
                for cost in (1, 2):
                    run, _, _, _ = replay(rows, prices, raw, filters, group, policy, cost, strategy); strategy_runs.append(run)
    independent_opportunities(rows, prices, raw, filters)
    comparisons = []
    for group in markets:
        for policy in ('model_argmax', 'model70', 'persist5_common', 'rules_and_model70'):
            comparisons.append(portfolio_comparison(paired[group, policy], paired[group, 'rules_common']))
        comparisons.append(portfolio_comparison(paired[group, 'model70'], paired[group, 'rules_common'], exposure_match=True))
    result = dict(research_only=True, orders_authorized=False, independent_oos=False, sources=sources,
        hypothesis='Whether existing traditional rules have net edge within current assigned states; whether fixed state-model routing adds incremental selection value.',
        strategy_runs=strategy_runs, portfolio_runs=portfolios, portfolio_comparisons=comparisons,
        selection_diagnostics=[selection_diagnostics(rows, g, s) for g in markets for s in (None,) + STRATEGY_NAMES],
        state_filter_selection=[selection_diagnostics(rows, g, s, selection='rules_common') for g in markets for s in STRATEGY_NAMES],
        model_on_current_opportunities=[selection_diagnostics(rows, g, s, pool_policy='rules_common') for g in markets for s in (None,) + STRATEGY_NAMES],
        forecast_diagnostics=forecast_diagnostics(panel, archive), setup_counts=counts, old_control_matches=old_matches,
        opportunity_count=sum('standalone' in r for r in rows),
        limitations=['七币种日线2023-01-01至2026-10-26，八现金ETF代理2023-01-03至2025-12-31；固定存续标的、历史已反复使用，不是新独立OOS。',
            '初始10,000、等额独立袖套、每笔最多袖套1%计划风险/1倍入场，宽震荡半风险；现金0利息。',
            '币种5bp手续费+2bp滑点每侧并计实际资金费，ETF5+15bp每侧、整数股且只做多；双摩擦另重跑。当前交易档位回套历史，ETF为复权现金代理，非Binance原生合约成交认证。',
            '日线币种i+2开盘、ETF次会话开盘；止损优先处理同棒双触，持仓最多5棒/假突破3棒；MDD/敞口只看收盘。',
            '共同覆盖要求信号时及计划入场时都有当时可用且未过期的模型预测；不读取未来预测撤历史订单。规则路由全窗12个原控制逐值复现。',
            '独立策略组合互相不占仓、不可相加。固定机会账本允许重叠，只检验选择；未来真实状态仅作事后诊断，不参与可交易筛选。',
            '季度整块重采样同时包含全资产，95%区间未按策略/成本/路由多重比较调整；季度少、制度漂移和幸存偏差仍限制解释。',
            '等敞口比较事后缩放对照对数收益；随机对照在同资产/策略/季度匹配提议数，但不保证相同风险/持仓日历，是探索性诊断。',
            '每5期预测第5期末状态，瞬时事件标签很少；状态识别与标签正确性未获外部真值认证。模型只输出概率，没有新增收益头。'])
    args.output.mkdir(parents=True)
    for name, value in (('results.json', result), ('opportunities.json', rows), ('portfolio_trades.json', trades)):
        (args.output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    np.savez_compressed(args.output / 'equity.npz', **curves)
    (args.output / 'report.md').write_text(report(result))
    print('saved', args.output, 'controls', old_matches, 'independent opportunities', result['opportunity_count'], flush=True)


if __name__ == '__main__': main()
