"""Frozen C60 path-quality research; all targets use closed history only.

Feature labels and holding tags are descriptive discovery evidence. They never
feed a fit, choose a threshold, or grant paper/order authority.
"""
from __future__ import annotations

import calendar
import json
import math
import statistics as stats
import sys
from pathlib import Path

from qount.research import dual_engine_optimization as old
from qount.research import dual_engine_zorder as prior
from qount.research import dual_engine_renewal as renewal
from qount.research import dual_engine_zonal as zonal
from qount.research import dual_engine_expansion as ex
from qount.research.dual_engine_execution_study import load_cache, read_opens, verify_manifest, paired_year_exclusion
from qount.research.dual_engine_holdings import analyze_units
from qount.research.dual_engine_registry import POLICY

CANDIDATES = ('agreement', 'efficiency', 'downside', 'joint_quality')
CONTROLS = ('sat_week', 'satellite_staged', 'staged_risk4', 'uniform75')
FEATURES = ('agreement', 'efficiency', 'downside_quality')
MECHANISM = {
    'agreement': 'fraction of strictly positive 20/60/90-day close returns',
    'efficiency': 'absolute sum of last60 log returns / sum of absolute last60 log returns; flat path zero',
    'downside_quality': '1 - sum of squared negative last60 log returns / sum of squared last60 log returns; flat path .5',
    'sizing': 'multiply positive original nominal weight by .5+.5*quality; joint uses minimum of three qualities; PAXG unchanged; no redistribution or leverage',
    'clock': 'original sat_week family clock and60-day60% covariance gate; original monthly selection and20/60/90 horizons',
    'uniform75': 'fixed .75 multiplier on same non-PAXG source nominal weights and sat_week clock; diagnostic de-risking control, not volatility matched or selection eligible',
    'labels': 'source-positive decisions; T+2 open to20 holding-day close; actual prices with50bps each side; last incomplete or missing labels censored; four equal-width bins; descriptive, overlapping and correlated',
    'success': 'all four cells: CAGR strictly higher, MaxDD no worse, closed net episode win rate strictly higher than sat_week; no automatic promotion',
}


def read_contract(path):
    c = json.loads(path.read_text())
    expected = {'study_id': 'dual_engine_features_20261005', 'research_only': True,
                'orders_authorized': False, 'promotion_evidence': False,
                'new_candidate_trials': 4, 'planned_curves': 32,
                'data_role': 'consumed_historical_discovery_pool'}
    if any(c.get(k) != v for k, v in expected.items()):
        raise ValueError('feature_contract_invalid')
    settings = json.loads((Path(__file__).resolve().parents[3] / 'config/dual-engine-zorder-20261005.json').read_text())['c60']
    for key in ('start', 'end', 'horizons', 'risk_window', 'annual_volatility_cap', 'core_weight', 'satellite_weight', 'cost_bps', 'delays'):
        if c['c60'][key] != settings[key]:
            raise ValueError('feature_comparison_protocol_changed')
    if (tuple(c['c60']['candidates']) != CANDIDATES or tuple(c['c60']['controls']) != CONTROLS
            or c['mechanisms'] != MECHANISM or c['selection_policy'] != POLICY
            or c['paired_bootstrap'] != {'block_lengths': [40, 60, 120], 'draws': 400, 'seed': 20261004}
            or c['selection_exclusions'] != [c['study_id'] + '/c60/uniform75']):
        raise ValueError('feature_mechanism_changed')
    return c


def path_features(prices):
    if prices is None or len(prices) < 91 or any(not math.isfinite(p) or p <= 0 for p in prices):
        raise ValueError('feature_history_invalid')
    logs = [math.log(b / a) for a, b in zip(prices[-61:-1], prices[-60:], strict=True)]
    length = math.fsum(abs(r) for r in logs)
    squares = math.fsum(r*r for r in logs)
    return {'agreement': sum(prices[-1] > prices[-1-h] for h in (20, 60, 90)) / 3.,
            'efficiency': min(1., abs(math.fsum(logs)) / length) if length else 0.,
            'downside_quality': 1. - math.fsum(r*r for r in logs if r < 0) / squares if squares else .5}


def feature_panel(targets, assets):
    return {t: {k: path_features(assets[k].window(t, 91))
                for k, w in weights.items() if w > 0 and assets[k].symbol != 'PAXGUSDT'}
            for t, weights in targets.items()}


def sized_targets(targets, features, rule):
    if rule not in CANDIDATES + ('uniform75',):
        raise ValueError('feature_rule_unknown')
    output = {}
    for t, weights in targets.items():
        result = {}
        for k, w in weights.items():
            f = features[t].get(k)
            scale = 1.
            if f is not None:
                if rule == 'uniform75':
                    scale = .75
                else:
                    quality = min(f.values()) if rule == 'joint_quality' else f['downside_quality' if rule == 'downside' else rule]
                    scale = .5 + .5 * quality
            result[k] = w * scale
        output[t] = result
    return output


def win_statistics(holding, run):
    closed = [e for e in holding['episodes'] if e['status'] == 'closed']
    wins = [e['net_pnl'] for e in closed if e['net_pnl'] > 0]
    losses = [e['net_pnl'] for e in closed if e['net_pnl'] < 0]
    months = {}
    for row in run['records']:
        key = row['date'][:7]
        months.setdefault(key, []).append(row)
    complete = [rows for key, rows in months.items()
                if rows[0]['date'] == key + '-01'
                and int(rows[-1]['date'][-2:]) == calendar.monthrange(int(key[:4]), int(key[5:]))[1]]
    return {'closed_episodes': len(closed), 'winning_episodes': len(wins), 'losing_episodes': len(losses),
            'flat_episodes': len(closed)-len(wins)-len(losses),
            'closed_net_win_rate': len(wins)/len(closed) if closed else None,
            'open_censored_episodes': sum(e['status'] != 'closed' for e in holding['episodes']),
            'mean_win_initial_nav': stats.fmean(wins) if wins else None,
            'mean_loss_initial_nav': stats.fmean(losses) if losses else None,
            'payoff_ratio': stats.fmean(wins)/-stats.fmean(losses) if wins and losses else None,
            'profit_factor': math.fsum(wins)/-math.fsum(losses) if losses else None,
            'closed_net_pnl': math.fsum(e['net_pnl'] for e in closed),
            'fees_flip_gross_winners': sum(e['fees_flip_gross_profit'] for e in closed),
            'complete_months': len(complete),
            'positive_complete_month_rate': sum(math.prod(1+r['return'] for r in rows)>1 for rows in complete)/len(complete) if complete else None,
            'positive_day_rate': sum(r['return'] > 0 for r in run['records'])/len(run['records']),
            'fees_initial_nav': math.fsum(a['allocated_fees'] for a in holding['assets'].values()),
            'gross_pnl_initial_nav': math.fsum(a['gross_pnl'] for a in holding['assets'].values())}


def forward_diagnostics(features, targets, dates, closes, opens, *, start, end):
    """Matured labels stay outside target generation; no interpolation of gaps."""
    rows = []; censored = 0
    for t, values in features.items():
        if not start <= dates[t] <= end:
            continue
        fill, finish = t+2, t+21
        for k, f in values.items():
            if finish >= len(dates) or dates[finish] > end:
                censored += 1
                continue
            entry = opens.get(k, {}).get(dates[fill]); exit_price = closes.get(k, {}).get(dates[finish])
            # An uninterrupted known price path is required only by this label,
            # never used to select a target or decide whether to trade.
            if entry is None or any(d not in closes.get(k, {}) for d in dates[fill:finish+1]):
                censored += 1
                continue
            net = exit_price * .995 / (entry * 1.005) - 1.
            rows.append({'decision': dates[t], 'asset': k, 'fill': dates[fill], 'end': dates[finish],
                         'source_weight': targets[t][k], **f, 'forward_net_return': net})
    bins = {}
    for name in FEATURES:
        bins[name] = []
        for b in range(4):
            group = [r for r in rows if min(3, int(r[name]*4)) == b]
            bins[name].append({'low': b/4., 'high': (b+1)/4., 'count': len(group),
                'unique_decision_days': len({r['decision'] for r in group}),
                'assets': len({r['asset'] for r in group}),
                'mean_net_return': stats.fmean(r['forward_net_return'] for r in group) if group else None,
                'win_rate': sum(r['forward_net_return']>0 for r in group)/len(group) if group else None})
    return {'rows': rows, 'bins': bins, 'censored': censored,
            'status': 'descriptive_consumed_history_no_independent_inference',
            'limitation': 'overlapping20-day labels, common market and repeated assets; counts are not independent samples; no bins or labels select candidates'}


def objective_gate(candidate, reference):
    checks = {}
    for cell, row in candidate.items():
        base = reference[cell]
        a, b = row['wins']['closed_net_win_rate'], base['wins']['closed_net_win_rate']
        checks[cell] = {'cagr_higher': row['cagr'] > base['cagr'],
                        'drawdown_no_worse': row['max_drawdown'] >= base['max_drawdown'],
                        'win_rate_higher': a is not None and b is not None and a > b}
    passed = all(all(v.values()) for v in checks.values())
    return {'passed': passed, 'checks': checks,
            'status': 'retain_for_prospective_design_only' if passed else 'joint_objective_not_met',
            'promotion_evidence': False}


def verify_study(*, out, pit_cache, open_root, repo):
    """Check source prices, cash accounting and closed-feature decisions.

    This does not rerun a strategy. The cash oracle reconstructs from fills;
    episode PnL is independently checked against buys, sales and end marks.
    """
    from qount.research.dual_engine_execution_verify import verify_ledger
    files = verify_manifest(out)
    c = read_contract(out/'contract.json')
    result = json.loads((out/'results.json').read_text())
    raw, hashes = load_cache(pit_cache); opens, open_files = read_opens(open_root)
    audit = json.loads((out/'input-audit.json').read_text())
    if hashes != audit['cache_sha256'] or open_files != audit['open_files']:
        raise ValueError('feature_verifier_input_identity_changed')
    source = Path(c['prior_result']['root'])
    verify_manifest(source, expected_hash=c['prior_result']['manifest_sha256'])
    original = {int(t): w for t, w in json.loads((source/'c60-sat_week-targets.json').read_text()).items()}
    axis, assets = old.build_crypto_assets(raw, end=c['c60']['end'])
    closes, opns = prior.base.crypto_prices(axis, assets, opens)
    saved_features = json.loads((out/'closed-features.json').read_text())
    target_checks = 0; feature_error = 0.
    for t, weights in original.items():
        for k, w in weights.items():
            if w <= 0 or assets[k].symbol == 'PAXGUSDT':
                continue
            p = assets[k].window(t, 91)
            moves = [math.log(p[i]/p[i-1]) for i in range(len(p)-60, len(p))]
            abs_sum = sum(abs(x) for x in moves); variance = sum(x*x for x in moves)
            values = [sum(p[-1]/p[-h-1]-1 > 0 for h in (20,60,90))/3,
                      abs(sum(moves))/abs_sum if abs_sum else 0.,
                      1-sum(x*x for x in moves if x<0)/variance if variance else .5]
            feature_error = max(feature_error, *(abs(saved_features[str(t)][k][name]-v) for name,v in zip(FEATURES,values,strict=True)))
    if feature_error > 1e-12:
        raise ValueError('feature_verifier_closed_history_mismatch')
    for rule in CONTROLS+CANDIDATES:
        targets = json.loads((out/f'c60-{rule}-targets.json').read_text())
        if set(targets) != {str(t) for t in original}:
            raise ValueError('feature_verifier_target_dates_changed')
        for t, weights in original.items():
            if set(targets[str(t)]) != set(weights):
                raise ValueError('feature_verifier_source_assets_changed')
            for k,w in weights.items():
                values = saved_features[str(t)].get(k)
                factor = 1.
                if values is not None and rule in CANDIDATES+('uniform75',):
                    factor = .75 if rule=='uniform75' else .5+.5*(min(values.values()) if rule=='joint_quality' else values['downside_quality' if rule=='downside' else rule])
                if abs(targets[str(t)][k]-w*factor)>1e-12:
                    raise ValueError('feature_verifier_sizing_mismatch')
                target_checks += 1
        if (out/f'c60-{rule}-selection.json').read_bytes() != (source/'c60-sat_week-selection.json').read_bytes():
            raise ValueError('feature_verifier_selection_changed')
    curves = []; wealth_error = 0.; risk_decisions = 0
    for exposure in result['curve_exposures']:
        key = exposure['curve']; _, rule, cost_token, delay_token = key.split('-')
        cell = cost_token+'-'+delay_token
        run = json.loads((out/f'{key}-ledger.json').read_text())
        holding = json.loads((out/f'{key}-holdings.json').read_text())
        previous = {}; adapted = []
        for row in run['records']:
            day = row['date']; units = row['units']
            pre_nav = row['cash']+sum(q*opns[k][day] for k,q in units.items())
            post = {k:q*opns[k][day]/pre_nav for k,q in units.items()}
            fee = sum(abs(units.get(k,0)-previous.get(k,0))*opns[k][day]
                      for k in set(units)|set(previous))*int(cost_token[1:])/10000
            # pre_nav is post-fee open NAV, recovered independently from cash.
            if abs(fee/pre_nav - row['cost_fraction']/(1-row['cost_fraction'])) > 1e-12:
                raise ValueError('feature_verifier_actual_fee_mismatch')
            adapted.append({**row, 'post_open_weights':post})
            previous = units
        cash_check = verify_ledger({'records':adapted}, {'dates':axis.dates,'opens':opns,'closes':closes},365,cost_bps=int(cost_token[1:]))
        summary = result['summaries']['c60'][rule][cell]
        for name in ('cagr','cash_excess_sharpe','max_drawdown','annual_turnover'):
            if abs(summary[name]-cash_check[name])>1e-10:
                raise ValueError('feature_verifier_metric_mismatch')
        for episode in holding['episodes']:
            net = episode['sell_notional']-episode['buy_notional']-episode['allocated_fees']
            if episode['status'] == 'open_censored':
                net += run['records'][-1]['units'].get(episode['asset'],0)*closes[episode['asset']][run['records'][-1]['date']]
            wealth_error = max(wealth_error, abs(net-episode['net_pnl']))
        if wealth_error>1e-9:
            raise ValueError('feature_verifier_episode_cashflow_mismatch')
        closed = [e for e in holding['episodes'] if e['status']=='closed']
        wins = summary['wins']
        if wins['closed_episodes']!=len(closed) or wins['winning_episodes']!=sum(e['net_pnl']>0 for e in closed):
            raise ValueError('feature_verifier_win_denominator_changed')
        for decision in run.get('decisions',[]):
            t = axis.dates.index(decision['decision']); weights = decision['target']
            returns = {k:prior.base.daily_returns(assets[k].window(t,61)) for k in weights}
            if prior.base.portfolio_sigma(returns,weights,365)>.6+1e-10:
                raise ValueError('feature_verifier_risk_gate_changed')
            risk_decisions += 1
        curves.append({'curve':key,**cash_check})
    for name,digest in result['source_sha256'].items():
        if old.file_hash(repo/name)!=digest or old.file_hash(out/'source'/name)!=digest:
            raise ValueError('feature_verifier_source_drift')
    if len(curves)!=32:
        raise ValueError('feature_verifier_curve_inventory_changed')
    return {'verified':True,'research_only':True,'orders_authorized':False,'curve_count':32,
        'manifest_sha256':old.file_hash(out/'manifest.json'),'output_files':len(files),
        'curves_verified':curves,'target_values_checked':target_checks,'max_feature_error':feature_error,
        'max_episode_cashflow_error':wealth_error,'closed_risk_decisions':risk_decisions,
        'source_files_checked':len(result['source_sha256']),
        'limitation':'Accounting and causal feature identity verified; no independent OOS, statistical selection correction or stability certification.'}


def run_study(*, contract_path, pit_cache, open_root, prior_results, out, repo):
    ex.require_storage(out)
    c = read_contract(contract_path)
    if out.exists():
        raise ValueError('immutable_result_exists')
    if str(prior_results) != c['prior_result']['root']:
        raise ValueError('feature_prior_root_changed')
    files = verify_manifest(prior_results, expected_hash=c['prior_result']['manifest_sha256'])
    raw, hashes = load_cache(pit_cache)
    opens, open_files = read_opens(open_root)
    audit = json.loads((prior_results/'input-audit.json').read_text())
    if hashes != audit['cache_sha256'] or open_files != audit['open_files']:
        raise ValueError('feature_input_identity_changed')
    axis, assets = old.build_crypto_assets(raw, end=c['c60']['end'])
    closes, opns = prior.base.crypto_prices(axis, assets, opens)
    btc = next(k for k, a in assets.items() if a.symbol == 'BTCUSDT')
    source = {int(t): weights for t, weights in json.loads((prior_results/'c60-sat_week-targets.json').read_text()).items()}
    features = feature_panel(source, assets)
    settings = c['c60']; out.mkdir(parents=True)
    old.write_json(out/'contract.json', c)
    old.write_json(out/'input-audit.json', {'cache_sha256': hashes, 'open_files': open_files,
        'source_targets_sha256': files['c60-sat_week-targets.json'],
        'prior_manifest_sha256': old.file_hash(prior_results/'manifest.json'),
        'paths': {'pit_cache': str(pit_cache), 'open_root': str(open_root)}})
    old.write_json(out/'closed-features.json', features)
    labels = forward_diagnostics(features, source, axis.dates, closes, opns, start=settings['start'], end=settings['end'])
    old.write_json(out/'forward-labels.json', labels)
    runs = {}; summaries = {}; exposures = []; checks = {}
    for rule in CONTROLS + CANDIDATES:
        targets = sized_targets(source, features, rule) if rule in CANDIDATES + ('uniform75',) else source
        old.write_json(out/f'c60-{rule}-targets.json', targets)
        (out/f'c60-{rule}-selection.json').write_bytes((prior_results/'c60-sat_week-selection.json').read_bytes())
        for cost in settings['cost_bps']:
            for delay in settings['delays']:
                cell = f'c{cost}-d{delay}'; key = f'c60-{rule}-{cell}'
                replay = zonal if rule == 'satellite_staged' else renewal if rule == 'staged_risk4' else prior
                run = replay.candidate_replay('c60', rule if rule in CONTROLS[:3] else 'sat_week',
                    axis.dates, closes, opns, targets, settings=settings, delay=delay, cost=cost, assets=assets)
                old.write_json(out/f'{key}-ledger.json', run); runs[key] = run
                holding = analyze_units(run, axis.dates, closes, opns, market=btc)
                old.write_json(out/f'{key}-holdings.json', holding)
                summaries.setdefault(rule, {})[cell] = {**old.summarize(run, 365),
                    'mean_risk_gross': stats.fmean(r['risk_gross'] for r in run['records']),
                    'wins': win_statistics(holding, run)}
                exposures.append({'curve': key, 'role': 'candidate' if rule in CANDIDATES else 'control'})
                if rule in CONTROLS[:3]:
                    previous = json.loads((prior_results/f'{key}-ledger.json').read_text())
                    if [r['date'] for r in run['records']] != [r['date'] for r in previous['records']]:
                        raise ValueError('feature_baseline_dates_changed')
                    error = max(abs(a['return']-b['return']) for a, b in zip(run['records'], previous['records'], strict=True))
                    if error > 1e-12:
                        raise ValueError('feature_baseline_reproduction_failed')
                    checks[key] = error
        print(json.dumps({'replayed': rule}), flush=True)
    contrasts = {}
    for rule in CANDIDATES:
        for reference in ('sat_week', 'uniform75'):
            for cell in ('c25-d0', 'c50-d1'):
                a, b = runs[f'c60-{rule}-{cell}'], runs[f'c60-{reference}-{cell}']
                contrasts[f'{rule}-vs-{reference}-{cell}'] = {
                    'paired': ex.paired_fast(a, b, annual=365, settings=c['paired_bootstrap']),
                    'same_baseline_best_year_exclusion': paired_year_exclusion(a, b, annual=365)}
    sources = {contract_path.resolve(), repo/'scripts/research/dual_engine_features.py'}
    for name, module in tuple(sys.modules.items()):
        path = Path(module.__file__).resolve() if getattr(module, '__file__', None) else None
        if name.startswith('qount') and path and path.suffix == '.py':
            if not path.is_relative_to(repo.resolve()/'src'):
                raise ValueError('feature_source_outside_public_delivery')
            sources.add(path)
    source_hashes = {}
    for path in sorted(sources):
        relative = path.relative_to(repo); saved = out/'source'/relative
        saved.parent.mkdir(parents=True, exist_ok=True); saved.write_bytes(path.read_bytes())
        source_hashes[str(relative)] = old.file_hash(path)
    result = {'study_id': c['study_id'], 'research_only': True, 'orders_authorized': False,
        'promotion_evidence': False, 'data_role': c['data_role'], 'summaries': {'c60': summaries},
        'contrasts': contrasts, 'objective_gates': {r: objective_gate(summaries[r], summaries['sat_week']) for r in CANDIDATES},
        'feature_diagnostics': {k: v for k, v in labels.items() if k != 'rows'},
        'baseline_reproduction': checks, 'curve_exposures': exposures, 'candidate_trials': 4,
        'source_sha256': source_hashes, 'global_trial_count': None, 'dsr_pbo': c['dsr_pbo']}
    if len(exposures) != c['planned_curves']:
        raise ValueError('feature_curve_inventory_changed')
    old.write_json(out/'results.json', result)
    old.write_json(out/'manifest.json', {'research_only': True, 'orders_authorized': False,
        'files': {str(p.relative_to(out)): old.file_hash(p) for p in sorted(out.rglob('*')) if p.is_file()}})
    return result
