"""Round16 no-order queue ownership and repeat-acquisition research."""
from __future__ import annotations
import json
import statistics as stats
import sys
from pathlib import Path
from qount.research import dual_engine_states as previous
from qount.research.dual_engine_acquisition import replay_acquisition
from qount.research.dual_engine_ownership import replay_ownership
from qount.research.dual_engine_execution_study import verify_manifest, load_cache, read_opens, paired_year_exclusion
from qount.research.dual_engine_holdings import analyze_units
from qount.research.dual_engine_capital import capital_contributions, SHARES, split_target
from qount.research.dual_engine_registry import POLICY
old = previous.old
prior = previous.previous.prior
G20_CONTROLS = ('aware_gold_rotate','joint20_rotate','joint40_rotate','joint20_sector','joint40_sector')
G20_CANDIDATES = ('owned20_rotate','owned40_rotate','owned20_sector','owned40_sector')
C60_CONTROLS = ('rebound_half','mature_rebound_half','agreement','sat_week')
C60_RULES = {'local_recovery':(0.,True),'topup10':(.1,False),'topup25':(.25,False),
             'local_topup10':(.1,True),'local_topup25':(.25,True)}
C60_CANDIDATES = tuple(C60_RULES)
MECHANISMS = {
 'g20':'Carry last explicit sparse source per book; exclude source-zero held complement from binding joint budget; at fill veto positive target when latest closed source is zero, assign BIL remainder; same dated lag, monthly funding, actual gross book fees. Veto in full/scoped acquisitions may exit existing units before a later queued exit; no continuous investment cap claim.',
 'c60':'Copy rebound_half nominal targets and selection exactly; only Sunday satellite refresh. local variants recover/refill the triggered core/satellite family without coupled core override; simultaneous families union. Suppress only positive requested topups of already-owned assets whose prefee increase/owned open value is <=10% or25%; freeze suppressed units, no redistribution; original reductions, zeros, risk gate and cash solver retained.',
 'protected':'Initial pre-start funding, recovered and next-close continuing assets bypass topup filter; band changes no source target, state threshold, Sunday, lag or fee rate. Bands applied only at acquisition, not a sell inaction region or theoretically optimal cost rule.',
 'objective':'C60 all four cells CAGR strictly higher, drawdown no worse, closed net win rate strictly higher than rebound_half; separately compare historical ranking leader mature_rebound_half. G20 zero source buys at both decision and latest-fill closed source is correctness gate, not return gate. Original historical selection policy unchanged.',
 'stop':'One frozen9-candidate/9-control/72-curve study. No result-conditioned band, timing, state threshold, fit, new source, forward window or rescue.'}


def read_contract(path):
 c=json.loads(path.read_text())
 expected={'study_id':'dual_engine_execution_ownership_20261005','research_only':True,'orders_authorized':False,'promotion_evidence':False,'new_candidate_trials':9,'planned_curves':72,'data_role':'consumed_historical_discovery_pool'}
 if any(c.get(k)!=v for k,v in expected.items()):raise ValueError('ownership_contract_invalid')
 if c['mechanisms']!=MECHANISMS or c['selection_policy']!=POLICY or c['selection_exclusions']!=[] or c['paired_bootstrap']!={'block_lengths':[40,60,120],'draws':400,'seed':20261004}:raise ValueError('ownership_mechanism_changed')
 repo=Path(__file__).resolve().parents[3]
 for line,ref,controls,candidates in (('g20',json.loads((repo/'config/dual-engine-zorder-20261005.json').read_text())['g20'],G20_CONTROLS,G20_CANDIDATES),('c60',previous.read_contract(repo/'config/dual-engine-states-20261005.json')['c60'],C60_CONTROLS,C60_CANDIDATES)):
  if tuple(c[line]['controls'])!=controls or tuple(c[line]['candidates'])!=candidates:raise ValueError('ownership_inventory_changed')
  for k in ('start','end','cost_bps','delays'):
   if c[line][k]!=ref[k]:raise ValueError('ownership_dates_costs_changed')
  if line=='c60':
   for k in ('horizons','risk_window','annual_volatility_cap','core_weight','satellite_weight'):
    if c[line][k]!=ref[k]:raise ValueError('ownership_risk_changed')
 if c['c60_rules']!={k:list(v) for k,v in C60_RULES.items()}:raise ValueError('ownership_rules_changed')
 return c


def read_inputs(c,repo):
 roots={line:Path(d['root']) for line,d in c['prior_results'].items()}
 for line,root in roots.items():verify_manifest(root,expected_hash=c['prior_results'][line]['manifest_sha256'])
 audit=json.loads((roots['g20']/'input-audit.json').read_text());paths={k:Path(v) for k,v in audit['paths'].items()}
 panel,equity=old.load_equity(paths['equity_root'],old.read_contract(repo/'config/dual-engine-optimization-20261004.json'))
 raw,hashes=load_cache(paths['pit_cache']);opns,open_files=read_opens(paths['open_root'])
 if equity['files']!=audit['equity']['files'] or hashes!=audit['cache_sha256'] or open_files!=audit['open_files']:raise ValueError('ownership_inputs_changed')
 for k in ('expansion','rates','inverse','tail'):
  if verify_manifest(paths[k+'_root'])!=audit['input_files'][k]:raise ValueError('ownership_aux_inputs_changed')
 panel=prior.load_inverse(prior.load_tail(prior.load_macro(panel,paths['expansion_root']),paths['tail_root']),paths['inverse_root'])
 cr_audit=json.loads((roots['c60']/'input-audit.json').read_text())
 if hashes!=cr_audit['cache_sha256'] or open_files!=cr_audit['open_files']:raise ValueError('ownership_crypto_inputs_changed')
 axis,assets=old.build_crypto_assets(raw,end=c['c60']['end']);cr_close,cr_open=prior.base.crypto_prices(axis,assets,opns)
 eq_close={s:dict(zip(panel.dates,p,strict=True)) for s,p in panel.total_closes.items()};eq_open={s:dict(zip(panel.dates,p,strict=True)) for s,p in panel.total_opens.items()}
 return roots,panel,axis,assets,{'g20':(eq_close,eq_open),'c60':(cr_close,cr_open)}, {'equity':equity,'cache_sha256':hashes,'open_files':open_files,'paths':{k:str(v) for k,v in paths.items()},'input_files':audit['input_files']}


def carried_sources(targets,first,last):
 out={};latest=None
 for t in range(min(targets),last+1):
  if t in targets:latest=split_target(targets[t])
  if t>=first:out[t]=latest
 return out


def ownership_diagnostics(run,dates,targets,lag):
 carried=carried_sources(targets,min(targets),len(dates)-1);before={b:{} for b in SHARES};bad_dec=bad_fill=0;vetoes=0
 for row in run['records']:
  t=dates.index(row['date']);signal=t-lag
  for b,book in row['books'].items():
   for k,q in book['units'].items():
    if k!='BIL' and q>before[b].get(k,0)+1e-12:
     bad_dec+=int(carried[signal][b].get(k,0)<=0);bad_fill+=int(carried[t-1][b].get(k,0)<=0)
   before[b]=book['units']
  vetoes+=sum(len(a) for a in row.get('source_zero_vetoes',{}).values())
 return {'source_zero_buy_assets_at_decision':bad_dec,'source_zero_buy_assets_at_latest_close':bad_fill,'latest_zero_veto_assets':vetoes,'binding_book_fills':sum(p['binding'] for row in run['records'] for p in (row.get('joint_plan') or {}).get('books',{}).values())}


def run_study(*,contract_path,out,repo):
 previous.previous.ex.require_storage(out);c=read_contract(contract_path)
 if out.exists():raise ValueError('immutable_ownership_results_exist')
 roots,panel,axis,assets,prices,audit=read_inputs(c,repo)
 out.mkdir(parents=True);old.write_json(out/'contract.json',c);old.write_json(out/'input-audit.json',audit)
 summaries={'g20':{},'c60':{}};exposures=[];runs={};checks={};diagnostics={}
 btc=next(k for k,a in assets.items() if a.symbol=='BTCUSDT');cores=tuple(k for k,a in assets.items() if a.symbol in ('BTCUSDT','ETHUSDT'))
 for line,controls,candidates,dates,annual in (('g20',G20_CONTROLS,G20_CANDIDATES,panel.dates,252),('c60',C60_CONTROLS,C60_CANDIDATES,axis.dates,365)):
  closes,opens=prices[line];settings=c[line]
  for rule in controls+candidates:
   source=rule.replace('owned','joint') if line=='g20' else 'rebound_half' if rule in candidates else rule
   target_name=f'{line}-{source}-targets.json';selection_name=f'{line}-{source}-selection.json'
   targets={int(t):w for t,w in json.loads((roots[line]/target_name).read_text()).items()}
   (out/f'{line}-{rule}-targets.json').write_bytes((roots[line]/target_name).read_bytes());(out/f'{line}-{rule}-selection.json').write_bytes((roots[line]/selection_name).read_bytes())
   for cost in settings['cost_bps']:
    for delay in settings['delays']:
     aims=dict(targets);cell=f'c{cost}-d{delay}';key=f'{line}-{rule}-{cell}'
     if line=='g20':
      first=next(i for i,d in enumerate(dates) if d>=settings['start']);aims.setdefault(first-delay,{'BIL':1.})
      if rule in candidates:run=replay_ownership(dates,closes,opens,aims,start=settings['start'],lag=delay,cost_bps=cost,full_refresh=set(old.g20_signals(panel)),limit=.2 if rule.startswith('owned20') else .4)
      elif rule.startswith('joint'):run=prior.candidate_replay(line,rule,dates,closes,opens,aims,settings=settings,delay=delay,cost=cost,panel=panel)
      else:run=prior.base.replay_units(dates,closes,opens,aims,start=settings['start'],lag=delay,cost_bps=cost,cash_asset='BIL')
     elif rule in candidates:
      def risk_scale(t,w):return min(1.,.6/max(prior.base.portfolio_sigma({k:prior.base.daily_returns(assets[k].window(t,61)) for k in w},w,365),1e-6))
      band,local=C60_RULES[rule];run=replay_acquisition(dates,closes,opens,aims,start=settings['start'],lag=1+delay,cost_bps=cost,core_assets=cores,risk_scale=risk_scale,band=band,local=local)
     else:run=prior.candidate_replay(line,'sat_week',dates,closes,opens,aims,settings=settings,delay=delay,cost=cost,assets=assets)
     runs[key]=run;old.write_json(out/f'{key}-ledger.json',run)
     holding=capital_contributions(run,dates,closes,opens) if 'books' in run['records'][0] else analyze_units(run,dates,closes,opens,market='SPY' if line=='g20' else btc)
     old.write_json(out/f'{key}-holdings.json',holding)
     summary={**old.summarize(run,annual),'mean_risk_gross':stats.fmean(r['risk_gross'] for r in run['records'])}
     if line=='c60':summary['wins']=previous.previous.win_statistics(holding,run)
     summaries[line].setdefault(rule,{})[cell]=summary
     diagnostics[key]=(ownership_diagnostics(run,dates,aims,delay) if 'books' in run['records'][0] else {'suppressed_topups':sum(len(r.get('suppressed_topups',[])) for r in run['records']),'core_buy_notional':sum(r.get('core_buy_notional',0) for r in run['records']),'total_buy_notional':sum(r.get('risk_buy_notional',0) for r in run['records'])})
     if rule in G20_CANDIDATES and any(diagnostics[key][k] for k in ('source_zero_buy_assets_at_decision','source_zero_buy_assets_at_latest_close')):raise ValueError('ownership_correctness_failed')
     exposures.append({'curve':key,'role':'candidate' if rule in candidates else 'control'})
     if rule in controls:
      prior_run=json.loads((roots[line]/f'{key}-ledger.json').read_text());assert [r['date'] for r in run['records']]==[r['date'] for r in prior_run['records']]
      error=max(abs(a['return']-b['return']) for a,b in zip(run['records'],prior_run['records'],strict=True))
      if error>1e-12:raise ValueError('ownership_control_reproduction_failed')
      checks[key]=error
   print(json.dumps({'replayed':line+'-'+rule}),flush=True)
 pairs=[('g20',r,b) for r in G20_CANDIDATES for b in (r.replace('owned','joint'),'aware_gold_rotate')]+[('c60',r,b) for r in C60_CANDIDATES for b in ('rebound_half','mature_rebound_half')]+[('c60','local_topup10','topup10'),('c60','local_topup25','topup25'),('c60','local_topup10','local_recovery'),('c60','local_topup25','local_recovery')]
 contrasts={}
 for line,rule,reference in pairs:
  for cell in (('c20-d1','c40-d2') if line=='g20' else ('c25-d0','c50-d1')):
   a,b=runs[f'{line}-{rule}-{cell}'],runs[f'{line}-{reference}-{cell}'];annual=252 if line=='g20' else 365
   contrasts[f'{line}-{rule}-vs-{reference}-{cell}']={'paired':previous.previous.ex.paired_fast(a,b,annual=annual,settings=c['paired_bootstrap']),'same_baseline_best_year_exclusion':paired_year_exclusion(a,b,annual=annual)}
 sources={contract_path.resolve(),repo/'scripts/research/dual_engine_execution_ownership.py',repo/'src/qount/research/dual_engine_ownership_verify.py'}
 for name,module in tuple(sys.modules.items()):
  path=Path(module.__file__).resolve() if getattr(module,'__file__',None) else None
  if name.startswith('qount') and path and path.suffix=='.py':
   if not path.is_relative_to(repo.resolve()/'src'):raise ValueError('ownership_source_outside_delivery')
   sources.add(path)
 hashes={}
 for path in sorted(sources):
  rel=path.relative_to(repo);dest=out/'source'/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(path.read_bytes());hashes[str(rel)]=old.file_hash(path)
 result={'study_id':c['study_id'],'research_only':True,'orders_authorized':False,'promotion_evidence':False,'data_role':c['data_role'],'summaries':summaries,'curve_exposures':exposures,'candidate_trials':9,'source_sha256':hashes,'baseline_reproduction':checks,'contrasts':contrasts,'account_diagnostics':diagnostics,'objective_gates':{r:previous.previous.objective_gate(summaries['c60'][r],summaries['c60']['rebound_half']) for r in C60_CANDIDATES},'ranking_reference_gates':{r:previous.previous.objective_gate(summaries['c60'][r],summaries['c60']['mature_rebound_half']) for r in C60_CANDIDATES},'global_trial_count':None,'dsr_pbo':'not done; history consumed; global trials unknown'}
 if len(exposures)!=72:raise ValueError('ownership_curve_inventory_changed')
 old.write_json(out/'results.json',result);old.write_json(out/'manifest.json',{'research_only':True,'orders_authorized':False,'files':{str(p.relative_to(out)):old.file_hash(p) for p in sorted(out.rglob('*')) if p.is_file()}})
 return result
