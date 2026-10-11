"""Independent price/state, fill/cash and scoped decision checks; no replay."""
from __future__ import annotations

import datetime as dt
import json
import math
import statistics as stats
from pathlib import Path

from qount.research import dual_engine_features as previous
from qount.research.dual_engine_execution_study import load_cache, read_opens, verify_manifest
from qount.research.dual_engine_execution_verify import verify_ledger


def verify_study(*, out, pit_cache, open_root, repo):
    from qount.research.dual_engine_states import CANDIDATES, CONTROLS, EVENT_RULES, read_contract
    files = verify_manifest(out); c = read_contract(out/'contract.json')
    result = json.loads((out/'results.json').read_text())
    source_root = Path(c['prior_result']['root'])
    verify_manifest(source_root,expected_hash=c['prior_result']['manifest_sha256'])
    raw, hashes = load_cache(pit_cache); opens, open_files = read_opens(open_root)
    audit = json.loads((out/'input-audit.json').read_text())
    if hashes != audit['cache_sha256'] or open_files != audit['open_files']:
        raise ValueError('state_verification_input_drift')
    axis, assets = previous.old.build_crypto_assets(raw,end=c['c60']['end'])
    closes, opns = previous.prior.base.crypto_prices(axis,assets,opens)
    day_index = {d:i for i,d in enumerate(axis.dates)}
    source = {int(t):w for t,w in json.loads((source_root/'c60-sat_week-targets.json').read_text()).items()}
    agreement = {int(t):w for t,w in json.loads((source_root/'c60-agreement-targets.json').read_text()).items()}
    states = {int(t):w for t,w in json.loads((out/'closed-states.json').read_text()).items()}
    events = {int(t):a for t,a in json.loads((out/'transition-events.json').read_text()).items()}
    btc = next(a for a in assets.values() if a.symbol=='BTCUSDT')
    # Deliberately reconstruct log returns and each trailing efficiency from
    # supplied segment closes, without calling state/feature generation helpers.
    known = {}; state_error = 0.; state_checks = 0
    for t,weights in source.items():
        expected_names = {k for k,w in weights.items() if w>0 and assets[k].symbol!='PAXGUSDT'}
        if set(states[t]) != expected_names:
            raise ValueError('state_verification_asset_scope_changed')
        market_prices = btc.window(t,61)
        m = [math.log(market_prices[i]/market_prices[i-1]) for i in range(1,61)]
        rebound = market_prices[-1]/market_prices[-21]-1>0 and market_prices[-1]/market_prices[0]-1<0 and stats.stdev(m[-20:])>stats.stdev(m)
        for k in expected_names:
            asset = assets[k]; prices = asset.window(t,61)
            def efficient(j):
                if (k,j) not in known:
                    p = asset.window(j,61)
                    increments = [math.log(p[i]/p[i-1]) for i in range(1,61)]
                    distance = math.fsum(abs(x) for x in increments)
                    known[k,j] = min(1.,abs(math.fsum(increments))/distance) if distance else 0.
                return known[k,j]
            value = efficient(t)
            past = [efficient(j) for j in range(max(asset.start+60,t-252),t)]
            rank = (sum(x<value for x in past)+.5*sum(x==value for x in past))/len(past) if len(past)>=60 else None
            a = prices[-1]/prices[-21]-1; b = prices[-1]/prices[0]-1; p = prices[-21]/prices[-41]-1
            state = ('unknown' if rank is None else 'rebound' if rebound else 'fading' if a<=0 else
                     'mature' if b>0 and rank>=.75 and a<=p else 'accelerating' if a>p else 'balanced')
            saved = states[t][k]
            if saved['state']!=state or saved['history_count']!=len(past) or saved['market_rebound']!=rebound or saved['rank']!=rank:
                raise ValueError('state_verification_history_or_classifier_mismatch')
            state_error = max(state_error,*(abs(saved[key]-x) for key,x in (('efficiency',value),('r20',a),('r60',b),('prior20',p))))
            state_checks += 1
        expected_events = sorted(k for k,f in states[t].items() if f['state']=='accelerating'
            and source.get(t-1,{}).get(k,0)>0 and states.get(t-1,{}).get(k,{}).get('state','unknown') not in ('unknown','accelerating'))
        if events[t] != expected_events:
            raise ValueError('state_verification_transition_mismatch')
    if state_error>1e-12:
        raise ValueError('state_verification_feature_mismatch')
    target_checks = 0
    cut = {'mature_half':{'mature'},'rebound_half':{'rebound'},'mature_rebound_half':{'mature','rebound'},
           'transition_fill':set(),'mature_transition_fill':{'mature'},'guarded_transition_fill':{'mature','rebound'}}
    targets = {}
    for rule in CONTROLS+CANDIDATES:
        target = {int(t):w for t,w in json.loads((out/f'c60-{rule}-targets.json').read_text()).items()}
        targets[rule] = target
        expected = ({int(t):w for t,w in json.loads((source_root/f'c60-{rule}-targets.json').read_text()).items()}
                    if rule in CONTROLS else agreement)
        if set(target)!=set(expected):
            raise ValueError('state_verification_target_dates_changed')
        for t,weights in expected.items():
            if set(target[t])!=set(weights):
                raise ValueError('state_verification_target_assets_changed')
            for k,w in weights.items():
                factor = .5 if rule in CANDIDATES and states[t].get(k,{}).get('state') in cut[rule] else 1.
                if abs(target[t][k]-w*factor)>1e-12:
                    raise ValueError('state_verification_target_sizing_mismatch')
                target_checks += 1
        if (out/f'c60-{rule}-selection.json').read_bytes()!=(source_root/'c60-sat_week-selection.json').read_bytes():
            raise ValueError('state_verification_monthly_selection_changed')
    curves = []; cashflow_error = 0.; decisions_checked = 0; event_scope_checks = 0
    controls = {}; cores = {k for k,a in assets.items() if a.symbol in ('BTCUSDT','ETHUSDT')}
    for exposure in result['curve_exposures']:
        key = exposure['curve']; _,rule,cost_token,delay_token = key.split('-')
        cell = cost_token+'-'+delay_token; rate = int(cost_token[1:])/10000; lag = 1+int(delay_token[1:])
        run = json.loads((out/f'{key}-ledger.json').read_text()); previous_units = {}; adapted = []
        for row in run['records']:
            day = row['date']; t = day_index[day]; units = row['units']
            post_nav = row['cash']+math.fsum(q*opns[k][day] for k,q in units.items())
            turnover = math.fsum(abs(units.get(k,0)-previous_units.get(k,0))*opns[k][day] for k in set(units)|set(previous_units))
            if abs(turnover*rate/post_nav-row['cost_fraction']/(1-row['cost_fraction']))>1e-12:
                raise ValueError('state_verification_actual_fees_mismatch')
            adapted.append({**row,'post_open_weights':{k:q*opns[k][day]/post_nav for k,q in units.items()}})
            plan = row.get('intent')
            if plan and rule in EVENT_RULES:
                if row['signal_date']!=axis.dates[t-lag] or plan['decision']!=row['signal_date']:
                    raise ValueError('state_verification_future_or_early_fill')
                cancelled = row['cancelled_state_events']
                for k in plan.get('event_only_assets',[]):
                    latest = targets[rule].get(t-1,{}).get(k,0)
                    blocked = latest>0 and states.get(t-1,{}).get(k,{}).get('state')!='accelerating'
                    if (k in cancelled)!=blocked:
                        raise ValueError('state_verification_stale_event_cancel_mismatch')
                    if blocked and units.get(k,0)!=previous_units.get(k,0):
                        raise ValueError('state_verification_cancelled_event_changed_owned_units')
                    event_scope_checks += 1
                if plan['kind']=='recover':
                    scope = set(plan['scope_assets'])-set(cancelled)
                    for k in set(units)|set(previous_units):
                        if k not in scope and units.get(k,0)>previous_units.get(k,0)+1e-12:
                            raise ValueError('state_verification_purchase_outside_scope')
            previous_units = units
        cash_check = verify_ledger({'records':adapted},{'dates':axis.dates,'opens':opns,'closes':closes},365,cost_bps=int(cost_token[1:]))
        summary = result['summaries']['c60'][rule][cell]
        for name in ('cagr','cash_excess_sharpe','max_drawdown','annual_turnover'):
            if abs(summary[name]-cash_check[name])>1e-10:
                raise ValueError('state_verification_metric_mismatch')
        holding = json.loads((out/f'{key}-holdings.json').read_text())
        for e in holding['episodes']:
            net = e['sell_notional']-e['buy_notional']-e['allocated_fees']
            if e['status']=='open_censored':
                net += run['records'][-1]['units'].get(e['asset'],0)*closes[e['asset']][run['records'][-1]['date']]
            cashflow_error = max(cashflow_error,abs(net-e['net_pnl']))
        closed = [e for e in holding['episodes'] if e['status']=='closed']
        if summary['wins']['closed_episodes']!=len(closed) or summary['wins']['winning_episodes']!=sum(e['net_pnl']>0 for e in closed):
            raise ValueError('state_verification_net_win_denominator_mismatch')
        if rule in CONTROLS:
            prior = json.loads((source_root/f'{key}-ledger.json').read_text())
            if [r['date'] for r in prior['records']]!=[r['date'] for r in run['records']]:
                raise ValueError('state_verification_control_dates_changed')
            error = max(abs(a['return']-b['return']) for a,b in zip(prior['records'],run['records'],strict=True))
            if error>1e-12:raise ValueError('state_verification_control_return_changed')
            controls[key] = error
        if any(r['missing_marks'] or r['no_fills'] for r in run['records']):
            raise ValueError('state_verification_missing_price_or_fill')
        decision_map = {d['decision']:d for d in run.get('decisions',[])}
        for day,decision in decision_map.items():
            t = day_index[day]; aim = targets[rule][t]
            if decision['nominal_target']!=aim:
                raise ValueError('state_verification_decision_nominal_changed')
            recovered = sorted(k for k,w in aim.items() if w>0 and targets[rule].get(t-1,{}).get(k,0)<=0)
            if decision['recovered_assets']!=recovered:
                raise ValueError('state_verification_recovery_identity_changed')
            if rule in EVENT_RULES:
                previous_day = axis.dates[t-1]
                continuing = sorted(k for k in decision_map.get(previous_day,{}).get('recovered_assets',[]) if aim.get(k,0)>0)
                if decision['continuing_assets']!=continuing:
                    raise ValueError('state_verification_continuation_identity_changed')
                if decision['event_assets']!=events[t]:
                    raise ValueError('state_verification_decision_event_changed')
                triggers = set(recovered)|set(decision['continuing_assets'])
                names = set(aim)|set(decision['decision_units'])
                ordinary = None if triggers&cores else ((names-cores if dt.date.fromisoformat(day).weekday()==6 else set()) | (names-cores if triggers-cores else set()))
                extra = set(events[t])-(names if ordinary is None else ordinary)
                scope = None if ordinary is None else ordinary|set(events[t])
                if decision['event_only_assets']!=sorted(extra) or decision['scope_assets']!=(sorted(scope) if scope else None):
                    raise ValueError('state_verification_family_event_scope_changed')
                event_scope_checks += 1
            weighted = []
            for k,w in decision['target'].items():
                prices = assets[k].window(t,61)
                weighted.append([w*(prices[i]/prices[i-1]-1) for i in range(1,61)])
            portfolio = [math.fsum(xs[i] for xs in weighted) for i in range(60)]
            if stats.stdev(portfolio)*math.sqrt(365)>.6+1e-10:
                raise ValueError('state_verification_planned_risk_cap_changed')
            decisions_checked += 1
        curves.append({'curve':key,**cash_check})
    if cashflow_error>1e-9 or len(curves)!=40:
        raise ValueError('state_verification_cashflow_or_inventory_failed')
    if {e['curve'] for e in result['curve_exposures']}!={f'c60-{r}-c{cost}-d{delay}' for r in CONTROLS+CANDIDATES for cost in (25,50) for delay in (0,1)}:
        raise ValueError('state_verification_curve_inventory_changed')
    for name,digest in result['source_sha256'].items():
        if previous.old.file_hash(repo/name)!=digest or previous.old.file_hash(out/'source'/name)!=digest:
            raise ValueError('state_verification_source_changed')
    return {'verified':True,'research_only':True,'orders_authorized':False,'curve_count':40,
        'manifest_sha256':previous.old.file_hash(out/'manifest.json'),'output_files':len(files),
        'curves_verified':curves,'state_rows_checked':state_checks,'target_values_checked':target_checks,
        'closed_risk_decisions':decisions_checked,'event_scope_checks':event_scope_checks,
        'source_files_checked':len(result['source_sha256']),'max_state_feature_error':state_error,
        'max_episode_cashflow_error':cashflow_error,'control_reproduction':controls,
        'missing_marks':0,'no_fills':0,
        'limitation':'Discovery accounting and causal mechanism checks; no independent OOS, DSR/PBO or economic-regime identification.'}
