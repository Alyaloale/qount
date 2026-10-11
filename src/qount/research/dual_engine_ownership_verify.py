"""Independent round16 cash/book ownership and suppressed-unit checks."""
from __future__ import annotations
import datetime as dt
import json
import math
import statistics as stats
from pathlib import Path


def verify_study(*,out,repo):
 from qount.research.dual_engine_execution_ownership import read_contract,read_inputs,G20_CANDIDATES,G20_CONTROLS,C60_CANDIDATES,C60_CONTROLS,C60_RULES,old
 from qount.research.dual_engine_execution_study import verify_manifest
 files=verify_manifest(out);c=read_contract(out/'contract.json');roots,panel,axis,assets,prices,audit=read_inputs(c,repo)
 if json.loads((out/'input-audit.json').read_text())!=audit:raise ValueError('ownership_verifier_input_identity')
 result=json.loads((out/'results.json').read_text());errors={};curves=[];scope_checks=book_rows=risk_checks=0;ownership_checks=0;controls={}
 def check(a,b,name):
  error=abs(a-b);errors[name]=max(errors.get(name,0),error)
  if error>1e-10*max(1,abs(a),abs(b)):raise ValueError('ownership_verifier_'+name)
 def split(w):
  g=min(.2,w.get('GLD',0));risk={k:v/.2 for k,v in w.items() if k not in ('GLD','BIL') and v>0}
  if w.get('GLD',0)>g:risk['GLD']=(w['GLD']-g)/.2
  risk['BIL']=max(0,1-sum(risk.values()))
  return {'equity_crisis':risk,'gold':{'GLD':g/.2,'BIL':1-g/.2},'reserve':{'BIL':1.}}
 for exposure in result['curve_exposures']:
  key=exposure['curve'];line,rule,cost_token,delay_token=key.split('-');rate=int(cost_token[1:])/10000;delay=int(delay_token[1:]);lag=delay if line=='g20' else 1+delay
  dates=panel.dates if line=='g20' else axis.dates;index={d:i for i,d in enumerate(dates)};annual=252 if line=='g20' else 365;closes,opens=prices[line]
  controls_rules=G20_CONTROLS if line=='g20' else C60_CONTROLS
  source=rule.replace('owned','joint') if line=='g20' else 'rebound_half' if rule in C60_CANDIDATES else rule
  for kind in ('targets','selection'):
   if (out/f'{line}-{rule}-{kind}.json').read_bytes()!=(roots[line]/f'{line}-{source}-{kind}.json').read_bytes():raise ValueError('ownership_verifier_source_or_selection_changed')
  nominal={int(t):w for t,w in json.loads((out/f'{line}-{rule}-targets.json').read_text()).items()}
  first=next(t for t,d in enumerate(dates) if d>=c[line]['start'])
  if line=='g20':nominal.setdefault(first-lag,{'BIL':1.})
  carried={};last=None
  for j in range(min(nominal),len(dates)):
   if j in nominal:last=split(nominal[j])
   carried[j]=last
  run=json.loads((out/f'{key}-ledger.json').read_text());old_units={};old_cash=nav=1.;old_books={b:{'cash':w,'units':{}} for b,w in {'equity_crisis':.2,'gold':.2,'reserve':.6}.items()}
  returns=[];cash_returns=[];turnovers=[];peak=1.;drawdown=0.;bad_dec=bad_latest=0
  for row in run['records']:
   day=row['date'];t=index[day];units=row['units'];names=set(old_units)|set(units)
   open_nav=old_cash+math.fsum(q*opens[k][day] for k,q in old_units.items());actual_flow=0.;fee=0.
   if 'books' in row:
    transfers=0.;aggregate={};cash=0.
    for b,book in row['books'].items():
     before=old_books[b];delta={k:book['units'].get(k,0)-before['units'].get(k,0) for k in set(before['units'])|set(book['units'])}
     flow=math.fsum(abs(q)*opens[k][day] for k,q in delta.items());charge=flow*rate;actual_flow+=flow;fee+=charge;transfers+=book['capital_transfer'];book_rows+=1
     check(book['fee'],charge,'book_fee');check(book['cash'],before['cash']+book['capital_transfer']-math.fsum(q*opens[k][day] for k,q in delta.items())-charge,'book_cash')
     check(book['nav'],book['cash']+math.fsum(q*closes[k][day] for k,q in book['units'].items()),'book_close_nav');cash+=book['cash']
     for k,q in book['units'].items():aggregate[k]=aggregate.get(k,0)+q
     for k,q in delta.items():
      if k!='BIL' and q>1e-12:
       bad_dec+=int(carried[t-lag][b].get(k,0)<=0);bad_latest+=int(carried[t-1][b].get(k,0)<=0);ownership_checks+=1
     if rule in G20_CANDIDATES:
      p=(row.get('joint_plan') or {}).get('books',{}).get(b)
      if p:
       if p['source_target']!=carried[t-lag][b] or row['latest_source'][b]!=carried[t-1][b]:raise ValueError('ownership_verifier_future_or_uncarried_source')
       if any(p['source_target'].get(k,0)<=0 for k,w in p['feasible_shape'].items() if w>0):raise ValueError('ownership_verifier_zero_source_shape')
       expected=sorted(k for k,w in p['target'].items() if k!='BIL' and w>0 and carried[t-1][b].get(k,0)<=0)
       if row['source_zero_vetoes'][b]!=expected:raise ValueError('ownership_verifier_veto_set')
       executed=dict(p['target'])
       if expected:
        for k in expected:executed[k]=0.
        executed['BIL']=max(0.,1-sum(w for k,w in executed.items() if k!='BIL'))
       if executed!=row['execution_book_targets'][b]:raise ValueError('ownership_verifier_veto_target')
       limit=.2 if rule.startswith('owned20') else .4
       if b!='reserve' and p['planned_risk_weight']>limit+1e-12:raise ValueError('ownership_verifier_budget_cap')
    check(transfers,0,'capital_transfer_sum');check(row['cash'],cash,'aggregate_cash')
    for k in set(aggregate)|set(units):check(units.get(k,0),aggregate.get(k,0),'aggregate_units')
    old_books=row['books']
   else:
    delta={k:units.get(k,0)-old_units.get(k,0) for k in names};actual_flow=math.fsum(abs(q)*opens[k][day] for k,q in delta.items());fee=actual_flow*rate
    check(row['cash'],old_cash-math.fsum(q*opens[k][day] for k,q in delta.items())-fee,'cash_flow')
   close_nav=row['cash']+math.fsum(q*closes[k][day] for k,q in units.items());ret=close_nav/nav-1
   check(row['nav'],close_nav,'close_nav');check(row['return'],ret,'return');check(row['turnover'],actual_flow/open_nav,'turnover');check(row['cost_fraction'],fee/open_nav,'fee_fraction')
   if row['cash'] < -1e-10 or row['missing_marks'] or row['no_fills']:raise ValueError('ownership_verifier_unfunded_or_missing')
   if row['signal_date'] and row['signal_date']!=dates[t-lag]:raise ValueError('ownership_verifier_future_fill')
   cash_return=closes['BIL'][day]/closes['BIL'][dates[t-1]]-1 if line=='g20' else 0.;check(row['cash_return'],cash_return,'cash_return')
   if line=='c60' and rule in C60_CANDIDATES:
    plan=row['intent'];band,local=C60_RULES[rule];before=row['acquisition_before_units'];scope=row['effective_acquisition_scope']
    if before is not None:
     aim=row['execution_acquisition_target'];av=row['acquisition_open_nav'];original=None if plan['kind']=='full' else set(plan['scope_assets']);active=set(aim)|set(before) if original is None else set(original)
     protected=set(plan.get('recovered_assets',[]))|set(plan.get('continuing_assets',[]))
     expected=sorted(k for k in active-protected if 'decision_weights' in plan and band and before.get(k,0)>0 and opens[k][day]>0 and aim.get(k,0)>0 and 0<aim[k]*av/(before[k]*opens[k][day])-1<=band)
     if expected!=row['suppressed_topups']:raise ValueError('ownership_verifier_suppression_set')
     expected_scope=active-set(expected) if band and 'decision_weights' in plan else original
     if scope!=(sorted(expected_scope) if expected_scope is not None else None):raise ValueError('ownership_verifier_effective_scope')
     for k in expected:
      if units.get(k,0)!=before[k]:raise ValueError('ownership_verifier_suppressed_owned_units_changed')
      scope_checks+=1
   returns.append(ret);cash_returns.append(cash_return);turnovers.append(actual_flow/open_nav);nav=close_nav;old_cash=row['cash'];old_units=units;peak=max(peak,nav);drawdown=min(drawdown,nav/peak-1)
  if rule in G20_CANDIDATES and (bad_dec or bad_latest):raise ValueError('ownership_verifier_zero_source_purchase')
  if line=='g20' and 'books' in run['records'][0]:
   diagnostic=result['account_diagnostics'][key]
   if diagnostic['source_zero_buy_assets_at_decision']!=bad_dec or diagnostic['source_zero_buy_assets_at_latest_close']!=bad_latest:raise ValueError('ownership_verifier_diagnostic_counts')
  excess=[a-b for a,b in zip(returns,cash_returns,strict=True)];sigma=stats.stdev(excess)
  metrics={'cagr':math.expm1(math.fsum(math.log1p(x) for x in returns)*annual/len(returns)),'cash_excess_sharpe':stats.fmean(excess)/sigma*math.sqrt(annual) if sigma else 0.,'max_drawdown':drawdown,'annual_turnover':math.fsum(turnovers)*annual/len(turnovers)}
  for name,value in metrics.items():check(result['summaries'][line][rule][cost_token+'-'+delay_token][name],value,'metric_'+name)
  if line=='c60':
   decisions={p['decision']:p for p in run['decisions']};cores={k for k,a in assets.items() if a.symbol in ('BTCUSDT','ETHUSDT')}
   for day,p in decisions.items():
    t=index[day]
    if p['nominal_target']!=nominal[t]:raise ValueError('ownership_verifier_nominal_changed')
    if rule in C60_CANDIDATES:
     _,local=C60_RULES[rule];names=set(p['nominal_target'])|set(p['decision_units']);triggers=set(p['recovered_assets'])|set(p['continuing_assets']);scheduled=names-cores if dt.date.fromisoformat(day).weekday()==6 else set()
     expected=None if triggers&cores and not local else scheduled|(names&cores if triggers&cores else set())|(names-cores if triggers-cores else set())
     if p['scope_assets']!=(sorted(expected) if expected else None):raise ValueError('ownership_verifier_recovery_family_scope')
     scope_checks+=1
    windows={k:assets[k].window(t,61) for k in p['target']}
    series=[math.fsum(w*(windows[k][i+1]/windows[k][i]-1) for k,w in p['target'].items()) for i in range(60)]
    if stats.stdev(series)*math.sqrt(365)>.6+1e-10:raise ValueError('ownership_verifier_closed_risk')
    risk_checks+=1
   hold=json.loads((out/f'{key}-holdings.json').read_text());closed=[e for e in hold['episodes'] if e['status']=='closed'];wins=result['summaries'][line][rule][cost_token+'-'+delay_token]['wins']
   for e in hold['episodes']:
    value=e['sell_notional']-e['buy_notional']-e['allocated_fees']
    if e['status']=='open_censored':value+=units.get(e['asset'],0)*closes[e['asset']][run['records'][-1]['date']]
    check(value,e['net_pnl'],'episode_cash_flow')
   if len(closed)!=wins['closed_episodes'] or sum(e['net_pnl']>0 for e in closed)!=wins['winning_episodes']:raise ValueError('ownership_verifier_win_denominator')
  if rule in controls_rules:
   prior=json.loads((roots[line]/f'{key}-ledger.json').read_text())
   if [r['date'] for r in prior['records']]!=[r['date'] for r in run['records']]:raise ValueError('ownership_verifier_control_dates')
   err=max(abs(a['return']-b['return']) for a,b in zip(run['records'],prior['records'],strict=True));controls[key]=err
   if err>1e-12:raise ValueError('ownership_verifier_control_return')
  curves.append({'curve':key,'verified':True,**metrics})
 for name,digest in result['source_sha256'].items():
  if old.file_hash(repo/name)!=digest or old.file_hash(out/'source'/name)!=digest:raise ValueError('ownership_verifier_source_drift')
 if len(curves)!=72 or len(controls)!=36:raise ValueError('ownership_verifier_inventory')
 return {'verified':True,'research_only':True,'orders_authorized':False,'curve_count':72,'manifest_sha256':old.file_hash(out/'manifest.json'),'output_files':len(files),'source_files_checked':len(result['source_sha256']),'curves_verified':curves,'max_identity_errors':errors,'control_reproduction':controls,'book_rows_checked':book_rows,'closed_risk_decisions':risk_checks,'scope_checks':scope_checks,'source_positive_buy_checks':ownership_checks,'missing_marks':0,'no_fills':0,'limitation':'Accounting/cause checks only; consumed discovery, no independent OOS or DSR/PBO.'}
