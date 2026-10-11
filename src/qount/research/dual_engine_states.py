"""Fifteenth-round causal states and scoped acceleration research.

State names are hypotheses, not labels of an independently identified economic
regime. No forward return or prospective observation enters a decision.
"""
from __future__ import annotations

import json
import math
import statistics as stats
import sys
from collections import Counter
from pathlib import Path

from qount.research import dual_engine_features as previous
from qount.research.dual_engine_state_clock import replay_state_clock
from qount.research.dual_engine_execution_study import load_cache, read_opens, verify_manifest, paired_year_exclusion
from qount.research.dual_engine_holdings import analyze_units
from qount.research.dual_engine_registry import POLICY

old = previous.old
CANDIDATES = ('mature_half', 'rebound_half', 'mature_rebound_half',
              'transition_fill', 'mature_transition_fill', 'guarded_transition_fill')
CONTROLS = ('agreement', 'sat_week', 'satellite_staged', 'uniform75')
EVENT_RULES = CANDIDATES[3:]
STATES = ('unknown', 'rebound', 'fading', 'mature', 'accelerating', 'balanced')
MECHANISMS = {
    'rank': 'current60-log-return efficiency midrank against previous252 calendar-day efficiencies, excluding current; at least60 valid past efficiencies; unqualified history unknown',
    'state_priority': 'unknown if rank unavailable; otherwise BTC rebound first, own r20<=0 fading, own r60>0 and efficiency rank>=.75 and r20<=prior nonoverlapping20 return mature, own r20>0 and r20>prior20 accelerating, else balanced',
    'market_rebound': 'BTC20-day simple return>0 and60-day simple return<0 and stdev(last20 log returns)>stdev(last60 log returns); all from current closed history',
    'sizing': 'original agreement nominal weights; mature_half halves mature; rebound_half halves rebound; mature_rebound_half and guarded_transition_fill halve either; mature_transition_fill halves mature; transition_fill unchanged; no redistribution or PAXG change',
    'events': 'additional acquisition of each already source-positive asset on non-unknown non-accelerating to accelerating transition; union with original sat_week scope; no full-core coupling from this event alone; covariance gate and cash financing retained',
    'late_cancel': 'event-only asset removed from acquisition scope when latest closed state is not accelerating; held units frozen, not sold merely to cancel top-up; latest closed nominal zero retains original exit/cancellation behavior',
    'clock': 'original Sunday satellite refresh, coupled core zero-to-positive recovery/refill, off-Sunday new recovery half and next-close refill; same vintage-owned complement reductions and60-day60% covariance gate',
    'objective': 'all four cells CAGR higher, MaxDD no worse and closed net episode win rate higher than agreement; separately report original sat_week comparison; ranking unchanged',
}


def read_contract(path):
    c = json.loads(path.read_text())
    expected = {'study_id': 'dual_engine_states_20261005', 'research_only': True,
                'orders_authorized': False, 'promotion_evidence': False,
                'new_candidate_trials': 6, 'planned_curves': 40,
                'data_role': 'consumed_historical_discovery_pool'}
    if any(c.get(k) != v for k, v in expected.items()):
        raise ValueError('state_contract_invalid')
    p = Path(__file__).resolve().parents[3]/'config/dual-engine-features-20261005.json'
    prior = previous.read_contract(p)
    for key in ('start', 'end', 'horizons', 'risk_window', 'annual_volatility_cap', 'core_weight', 'satellite_weight', 'cost_bps', 'delays'):
        if c['c60'][key] != prior['c60'][key]:
            raise ValueError('state_comparison_changed')
    if (tuple(c['c60']['candidates']) != CANDIDATES or tuple(c['c60']['controls']) != CONTROLS
            or c['mechanisms'] != MECHANISMS or c['selection_policy'] != POLICY
            or c['paired_bootstrap'] != prior['paired_bootstrap']
            or c['selection_exclusions'] != [c['study_id']+'/c60/uniform75']
            or c['state_settings'] != {'reference_days':252,'minimum_history':60,'mature_rank':.75}):
        raise ValueError('state_mechanism_changed')
    return c


def efficiency(prices):
    if prices is None or len(prices) != 61 or any(not math.isfinite(p) or p <= 0 for p in prices):
        raise ValueError('state_efficiency_history_invalid')
    moves = [math.log(b/a) for a,b in zip(prices[:-1], prices[1:], strict=True)]
    length = math.fsum(abs(r) for r in moves)
    return min(1., abs(math.fsum(moves))/length) if length else 0.


def market_rebound(prices):
    if prices is None or len(prices) != 61:
        return False
    moves = [math.log(b/a) for a,b in zip(prices[:-1], prices[1:], strict=True)]
    return prices[-1]>prices[-21] and prices[-1]<prices[0] and stats.stdev(moves[-20:])>stats.stdev(moves)


def classify_state(*, rank, r20, r60, prior20, rebound):
    if rank is None:
        return 'unknown'
    if rebound:
        return 'rebound'
    if r20 <= 0:
        return 'fading'
    if r60 > 0 and rank >= .75 and r20 <= prior20:
        return 'mature'
    if r20 > prior20:
        return 'accelerating'
    return 'balanced'


def state_panel(source, assets):
    """Empirical ranks use every prior calendar day, not selected opportunities."""
    btc = next(a for a in assets.values() if a.symbol == 'BTCUSDT')
    needed = {}
    for t, weights in source.items():
        for k,w in weights.items():
            if w > 0 and assets[k].symbol != 'PAXGUSDT':
                needed[k] = max(t, needed.get(k, t))
    cached = {k:{j:efficiency(assets[k].window(j,61))
                 for j in range(assets[k].start+60, last+1)} for k,last in needed.items()}
    market = {t:market_rebound(btc.window(t,61)) for t in source}
    output = {}
    for t, weights in source.items():
        row = {}
        for k,w in weights.items():
            if w <= 0 or assets[k].symbol == 'PAXGUSDT':
                continue
            prices = assets[k].window(t,61)
            if prices is None:
                raise ValueError('positive_source_state_history_missing')
            current = cached[k][t]
            history = [cached[k][j] for j in range(max(assets[k].start+60,t-252),t)]
            rank = (sum(x<current for x in history)+.5*sum(x==current for x in history))/len(history) if len(history)>=60 else None
            r20 = prices[-1]/prices[-21]-1
            r60 = prices[-1]/prices[0]-1
            prior20 = prices[-21]/prices[-41]-1
            state = classify_state(rank=rank,r20=r20,r60=r60,prior20=prior20,rebound=market[t])
            row[k] = {'state':state, 'rank':rank, 'efficiency':current, 'history_count':len(history),
                      'r20':r20, 'r60':r60, 'prior20':prior20, 'market_rebound':market[t]}
        output[t] = row
    return output


def candidate_targets(agreement, states, rule):
    if rule not in CANDIDATES:
        raise ValueError('state_rule_unknown')
    cut = {'mature_half':{'mature'}, 'rebound_half':{'rebound'}, 'mature_rebound_half':{'mature','rebound'},
           'transition_fill':set(), 'mature_transition_fill':{'mature'}, 'guarded_transition_fill':{'mature','rebound'}}[rule]
    return {t:{k:w*(.5 if states[t].get(k,{}).get('state') in cut else 1.) for k,w in weights.items()}
            for t,weights in agreement.items()}


def transition_events(source, states):
    return {t:sorted(k for k,f in row.items() if f['state']=='accelerating'
            and source.get(t-1,{}).get(k,0)>0 and source[t].get(k,0)>0
            and states.get(t-1,{}).get(k,{}).get('state','unknown') not in ('unknown','accelerating'))
            for t,row in states.items()}


def candidate_replay(rule, axis, assets, closes, opens, targets, states, events, *, settings, cost, delay):
    if rule not in EVENT_RULES:
        return previous.prior.candidate_replay('c60','sat_week',axis.dates,closes,opens,targets,
            settings=settings,delay=delay,cost=cost,assets=assets)
    def risk_scale(t, weights):
        returns = {k:previous.prior.base.daily_returns(assets[k].window(t,61)) for k in weights}
        return min(1.,.6/max(previous.prior.base.portfolio_sigma(returns,weights,365),1e-6))
    cores = tuple(k for k,a in assets.items() if a.symbol in ('BTCUSDT','ETHUSDT'))
    return replay_state_clock(axis.dates,closes,opens,targets,start=settings['start'],lag=1+delay,
        cost_bps=cost,core_assets=cores,risk_scale=risk_scale,states=states,events=events)


def run_study(*, contract_path, pit_cache, open_root, prior_results, out, repo):
    previous.ex.require_storage(out)
    c = read_contract(contract_path)
    if out.exists():
        raise ValueError('immutable_state_result_exists')
    if str(prior_results) != c['prior_result']['root']:
        raise ValueError('state_prior_root_changed')
    files = verify_manifest(prior_results,expected_hash=c['prior_result']['manifest_sha256'])
    raw, hashes = load_cache(pit_cache); opens, open_files = read_opens(open_root)
    audit = json.loads((prior_results/'input-audit.json').read_text())
    if hashes!=audit['cache_sha256'] or open_files!=audit['open_files']:
        raise ValueError('state_input_identity_changed')
    settings = c['c60']; axis, assets = old.build_crypto_assets(raw,end=settings['end'])
    closes, opns = previous.prior.base.crypto_prices(axis,assets,opens)
    btc = next(k for k,a in assets.items() if a.symbol=='BTCUSDT')
    def read_targets(rule):
        return {int(t):w for t,w in json.loads((prior_results/f'c60-{rule}-targets.json').read_text()).items()}
    source = read_targets('sat_week'); agreement = read_targets('agreement')
    states = state_panel(source,assets); events = transition_events(source,states)
    out.mkdir(parents=True)
    old.write_json(out/'contract.json',c)
    old.write_json(out/'input-audit.json',{'cache_sha256':hashes,'open_files':open_files,
        'source_targets_sha256':files['c60-sat_week-targets.json'],'agreement_targets_sha256':files['c60-agreement-targets.json'],
        'prior_manifest_sha256':old.file_hash(prior_results/'manifest.json'),
        'paths':{'pit_cache':str(pit_cache),'open_root':str(open_root)}})
    old.write_json(out/'closed-states.json',states);old.write_json(out/'transition-events.json',events)
    runs = {}; summaries = {}; exposures = []; checks = {}; diagnostics = {}
    for rule in CONTROLS+CANDIDATES:
        targets = read_targets(rule) if rule in CONTROLS else candidate_targets(agreement,states,rule)
        old.write_json(out/f'c60-{rule}-targets.json',targets)
        (out/f'c60-{rule}-selection.json').write_bytes((prior_results/'c60-sat_week-selection.json').read_bytes())
        for cost in settings['cost_bps']:
            for delay in settings['delays']:
                cell = f'c{cost}-d{delay}'; key = f'c60-{rule}-{cell}'
                if rule in CANDIDATES:
                    run = candidate_replay(rule,axis,assets,closes,opns,targets,states,events,settings=settings,cost=cost,delay=delay)
                else:
                    engine = previous.zonal if rule=='satellite_staged' else previous.prior
                    run = engine.candidate_replay('c60',rule if rule in ('sat_week','satellite_staged') else 'sat_week',
                        axis.dates,closes,opns,targets,settings=settings,delay=delay,cost=cost,assets=assets)
                runs[key] = run;old.write_json(out/f'{key}-ledger.json',run)
                holding = analyze_units(run,axis.dates,closes,opns,market=btc)
                old.write_json(out/f'{key}-holdings.json',holding)
                summaries.setdefault(rule,{})[cell] = {**old.summarize(run,365),
                    'mean_risk_gross':stats.fmean(r['risk_gross'] for r in run['records']),
                    'wins':previous.win_statistics(holding,run)}
                diagnostics[key] = {'event_decisions':sum(bool(d.get('event_assets')) for d in run.get('decisions',[])),
                    'event_only_fill_rows':sum(bool(r.get('intent',{}).get('event_only_assets')) for r in run['records'] if r.get('intent')),
                    'cancelled_event_assets':sum(len(r.get('cancelled_state_events',[])) for r in run['records']),
                    'event_only_buy_notional':sum(r.get('state_event_buy_notional',0) for r in run['records']),
                    'total_buy_notional':sum(r.get('risk_buy_notional',0) for r in run['records'])}
                exposures.append({'curve':key,'role':'candidate' if rule in CANDIDATES else 'control'})
                if rule in CONTROLS:
                    prior = json.loads((prior_results/f'{key}-ledger.json').read_text())
                    if [r['date'] for r in prior['records']] != [r['date'] for r in run['records']]:
                        raise ValueError('state_control_dates_changed')
                    error = max(abs(a['return']-b['return']) for a,b in zip(run['records'],prior['records'],strict=True))
                    if error>1e-12:
                        raise ValueError('state_control_reproduction_failed')
                    checks[key] = error
        print(json.dumps({'replayed':rule}),flush=True)
    pairs = [(r,b) for r in CANDIDATES for b in ('agreement','sat_week','uniform75')]
    pairs += [('mature_transition_fill','mature_half'),('guarded_transition_fill','mature_rebound_half'),
              ('guarded_transition_fill','transition_fill')]
    contrasts = {}
    for rule,base in pairs:
        for cell in ('c25-d0','c50-d1'):
            a,b = runs[f'c60-{rule}-{cell}'],runs[f'c60-{base}-{cell}']
            contrasts[f'{rule}-vs-{base}-{cell}'] = {'paired':previous.ex.paired_fast(a,b,annual=365,settings=c['paired_bootstrap']),
                'same_baseline_best_year_exclusion':paired_year_exclusion(a,b,annual=365)}
    sources = {contract_path.resolve(),repo/'scripts/research/dual_engine_states.py',
               repo/'src/qount/research/dual_engine_states_verify.py',
               repo/'src/qount/research/dual_engine_execution_verify.py'}
    for name,module in tuple(sys.modules.items()):
        path = Path(module.__file__).resolve() if getattr(module,'__file__',None) else None
        if name.startswith('qount') and path and path.suffix=='.py':
            if not path.is_relative_to(repo.resolve()/'src'):
                raise ValueError('state_source_outside_public_delivery')
            sources.add(path)
    source_hashes = {}
    for path in sorted(sources):
        relative = path.relative_to(repo); saved = out/'source'/relative
        saved.parent.mkdir(parents=True,exist_ok=True);saved.write_bytes(path.read_bytes());source_hashes[str(relative)] = old.file_hash(path)
    counts = Counter(f['state'] for t,row in states.items() if settings['start']<=axis.dates[t]<=settings['end'] for f in row.values())
    result = {'study_id':c['study_id'],'research_only':True,'orders_authorized':False,'promotion_evidence':False,
        'data_role':c['data_role'],'summaries':{'c60':summaries},'contrasts':contrasts,'account_diagnostics':diagnostics,
        'objective_gates':{r:previous.objective_gate(summaries[r],summaries['agreement']) for r in CANDIDATES},
        'original_reference_gates':{r:previous.objective_gate(summaries[r],summaries['sat_week']) for r in CANDIDATES},
        'state_counts':dict(counts),'transition_asset_events':sum(len(a) for t,a in events.items() if axis.dates[t]>=settings['start']),
        'baseline_reproduction':checks,'curve_exposures':exposures,'candidate_trials':6,'source_sha256':source_hashes,
        'global_trial_count':None,'dsr_pbo':c['dsr_pbo']}
    if len(exposures)!=40:
        raise ValueError('state_curve_inventory_changed')
    old.write_json(out/'results.json',result)
    old.write_json(out/'manifest.json',{'research_only':True,'orders_authorized':False,
        'files':{str(p.relative_to(out)):old.file_hash(p) for p in sorted(out.rglob('*')) if p.is_file()}})
    return result
