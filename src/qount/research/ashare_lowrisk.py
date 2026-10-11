"""Separate low-risk uptrend discovery after failed sector-strength strategy.

Reuses frozen source/transaction accounting, never rewrites the prior experiment.
"""
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
from qount.research.ashare_strategy import Book,REAL_ESTATE,ROOT,make_features,metrics,write_json,digest

RULES={
 'capital_cny':1_000_000,'risk_style':'aggressive_unlevered_fully_funded_lowrisk_stock_selection',
 'start':'20150101','end':'20260930','same_base_eligibility':'252past_raw_201valid_meanamount20_ge50m_unknown_industry_retained_as_shared_group',
 'entry_trend':'adj_close_gt_MA200_and_close[t-20]/close[t-120]_gt1',
 'primary_ranking':'126_log_return_population_volatility_ascending_symbol_tie',
 'control_ranking':'20session_mean_amount_descending_symbol_tie_same_entry_trend',
 'maximum_positions':10,'new_entry_fraction':.1,'industry_slots':2,'real_estate_slots':4,
 'review_clock':'first_2015_session_then_every5_exchange_sessions','retention_rank':20,
 'exit':'qualified_close_lt_MA200_or_age_ge252_or_portfolio_drawdown20',
 'portfolio_drawdown':'20pct_anchor_peak_liquidate_cancel_pending_buys_then63sessions_and_all_exits_complete_reset_peak_not_hard_loss_cap',
 'market_breadth_entry_filter':False,'trailing_stock_stop':False,
 'cost_and_execution':'unchanged_frozen_ashare_strategy_v1_costs_open_guard_and_synthetic_adjusted_units',
 'financial_policy_overlay':'not_backtested_no_historical_PIT_data','curves':['sector_base','sector_double_cost','sector_extra_day','price_control'],
 'prior_failed_candidate_unchanged':True,'no_claim_independent_OOS':True}


def vol126(s):
 n=len(s.valid);values=array('d',[math.nan])*n;changes=array('d',[math.nan])*n;total=squares=0.;count=0
 for j in range(1,n):
  if s.valid[j] and s.valid[j-1]:changes[j]=math.log(s.adj_close[j]/s.adj_close[j-1])
  x=changes[j]
  if math.isfinite(x):total+=x;squares+=x*x;count+=1
  if j>=126:
   old=changes[j-126]
   if math.isfinite(old):total-=old;squares-=old*old;count-=1
  if j>=126 and count==126:values[j]=math.sqrt(max(0.,squares/126-(total/126)**2))*math.sqrt(252)
 return values


def select(j,panel,features,vols,metadata):
 eligible=[c for c,f in features.items() if f.eligible[j]]
 trend=[c for c in eligible if panel[c].adj_close[j]>features[c].ma200[j] and features[c].momentum[j]>0 and math.isfinite(vols[c][j])]
 primary=sorted(trend,key=lambda c:(vols[c][j],c));control=sorted(trend,key=lambda c:(-features[c].adv20[j],c))[:20]
 ranked=[];counts=collections.Counter();real=0
 for c in primary:
  industry=metadata.get(c,{}).get('industry') or '__unclassified__'
  if counts[industry]>=2 or (industry in REAL_ESTATE and real>=4):continue
  ranked.append(c);counts[industry]+=1;real+=industry in REAL_ESTATE
  if len(ranked)==20:break
 return {'market_on':bool(trend),'eligible_count':len(eligible),'trend_count':len(trend),'sector_rank':ranked,'price_rank':control,
  'selected_sectors':list(dict.fromkeys(metadata.get(c,{}).get('industry') or '__unclassified__' for c in ranked)),
  'eligible_retired':sum(panel[c].source_kind=='tushare_retired' for c in eligible)}


class LowriskBook(Book):
 def __init__(self,name,metadata):
  super().__init__(name,metadata);self.anchor_peak=self.nav();self.cooldown_until=-1;self.risk_events=[]

 def slots_allow(self,code,excluded=()):
  held=[c for c in self.positions if c not in excluded]
  if len(held)>=10:return False
  if not self.sector_rules:return True
  group=lambda c:self.metadata.get(c,{}).get('industry') or '__unclassified__'
  industry=group(code)
  if sum(group(c)==industry for c in held)>=2:return False
  return not(industry in REAL_ESTATE and sum(group(c) in REAL_ESTATE for c in held)>=4)

 def decisions(self,j,day,panel,features,selection,review,last_j):
  nav=self.nav()
  if self.cooldown_until>=0 and j>=self.cooldown_until and not self.positions and not self.pending_sells:
   self.cooldown_until=-1;self.anchor_peak=nav
  self.anchor_peak=max(self.anchor_peak,nav)
  triggered=self.cooldown_until<0 and nav<=self.anchor_peak*.8
  if triggered:
   self.cooldown_until=j+63
   self.risk_events.append({'date':day,'j':j,'nav_carry_proxy_cny':nav,'anchor_peak':self.anchor_peak,'cooldown_until_j':self.cooldown_until})
   cancelled=sum(i['side']=='buy' for i in self.pending);self.blocks['risk_cancelled_pending_buy']+=cancelled
   self.pending=[i for i in self.pending if i['side']!='buy'];self.pending_buys.clear()
  cooling=self.cooldown_until>=0
  ranking=selection['sector_rank' if self.sector_rules else 'price_rank'];keep=set(ranking);exits={}
  for code,p in self.positions.items():
   c=panel[code].adj_close[j] if panel[code].valid[j] else math.nan;ma=features[code].ma200[j]
   reason=('portfolio_drawdown20' if cooling else 'age252' if j-p.entry_j>=252 else
    'below_MA200_close' if math.isfinite(c) and math.isfinite(ma) and c<ma else
    'weekly_rank_exit' if review and code not in keep else None)
   if reason:exits[code]=reason
  for code,reason in sorted(exits.items()):
   if code in self.pending_sells or j+1+self.delay>last_j:continue
   adv=features[code].adv20[j]
   if not math.isfinite(adv):adv=next((features[code].adv20[k] for k in range(j,-1,-1) if math.isfinite(features[code].adv20[k])),0.)
   self.plan(j,code,'sell',reason,adv20=adv)
  if not review or cooling or not selection['market_on'] or j+1+self.delay>last_j:return
  reserved=[c for c in self.positions if c not in exits]
  for code in ranking:
   if code in self.positions or code in self.pending_buys or len(reserved)>=10:continue
   industry=self.metadata.get(code,{}).get('industry') or '__unclassified__'
   if self.sector_rules:
    if sum((self.metadata.get(c,{}).get('industry') or '__unclassified__')==industry for c in reserved)>=2:continue
    if industry in REAL_ESTATE and sum(self.metadata.get(c,{}).get('industry') in REAL_ESTATE for c in reserved)>=4:continue
   budget=nav*.1;shares=math.floor(budget/panel[code].raw_close[j]/100)*100
   self.plan(j,code,'buy','weekly_lowrisk_entry',adv20=features[code].adv20[j],raw_shares=shares,budget_cny=budget);reserved.append(code)


def backtest(sessions,panel,metadata):
 features={c:make_features(s) for c,s in panel.items()};vols={c:vol126(s) for c,s in panel.items()}
 start=next(j for j,d in enumerate(sessions) if d>='20150101');end=len(sessions)-1
 books={n:LowriskBook(n,metadata) for n in RULES['curves']};signals=[]
 for j in range(start,end+1):
  day=sessions[j];review=(j-start)%5==0
  for book in books.values():book.execute(j,day,panel);book.mark(j,day,panel)
  selection=select(j,panel,features,vols,metadata) if review else {'market_on':False,'sector_rank':[],'price_rank':[]}
  if review:signals.append({'date':day,'j':j,**selection})
  for book in books.values():book.decisions(j,day,panel,features,selection,review,end)
 return books,signals


def run(contract_path,out):
 from qount.research.ashare_backtest_data import load_panel
 contract=json.loads(contract_path.read_text())
 if contract.get('rules')!=RULES or contract.get('authorization')!={'backtest':True,'orders':False,'services':False}:raise ValueError('lowrisk_contract_invalid')
 if sys.platform!='linux' or out.exists() or not out.resolve().is_relative_to(Path('/mnt/e/qount_data/qount/artifacts/equity_selection')):raise ValueError('fresh_WSL_E_required')
 for name,sha in contract['implementation_sha256'].items():
  p=(ROOT/name).resolve()
  if not p.is_relative_to(ROOT) or digest(p)!=sha:raise ValueError('frozen_code_mismatch:'+name)
 if sys.version.split()[0]!=contract['python_version']:raise ValueError('python_version_mismatch')
 sessions,panel,metadata,diagnostics=load_panel(contract);out.mkdir(parents=True);write_json(out/'contract.json',contract)
 started=dt.datetime.now(dt.timezone.utc).isoformat();books,signals=backtest(sessions,panel,metadata)
 summary={'research_only':True,'orders_authorized':False,'promotion_evidence':False,'status':'conditional_lowrisk_uptrend_adjusted_unit_discovery_backtest',
  'started_at':started,'finished_at':dt.datetime.now(dt.timezone.utc).isoformat(),'price_cutoff':sessions[-1],
  'formal_cash_NAV_certified':False,'historical_PIT_certified':False,'financial_or_policy_signal_backtested':False,'independent_OOS':False,
  'DSR_or_PBO':'not_computed_new_strategy_after_prior_failed_discovery','registered_strategy_rule_sets':1,'registered_curves':4,'parameter_searches':0,
  'source':diagnostics,'results':{}}
 write_json(out/'signals.json',signals)
 for name,book in books.items():
  result=metrics(book.curve,book.closed);result.update(fees_cny=sum(t['fees_cny'] for t in book.trades),fills=len(book.trades),blocked=dict(book.blocks),final_open_positions=len(book.positions),portfolio_risk_events=len(book.risk_events))
  result['yearly']={y:metrics([r for r in book.curve if r['date'].startswith(y)],[],initial=next((r['nav_carry_proxy_cny'] for r in reversed(book.curve) if r['date']<y+'0101'),1_000_000)) for y in sorted({r['date'][:4] for r in book.curve})}
  result['segments']={label:metrics([r for r in book.curve if lo<=r['date']<=hi],[],initial=next((r['nav_carry_proxy_cny'] for r in reversed(book.curve) if r['date']<lo),1_000_000)) for label,lo,hi in [('2015–2018','20150101','20181231'),('2019–2022','20190101','20221231'),('2023–2026','20230101','20260930')]}
  summary['results'][name]=result
  for suffix,data in [('curve',book.curve),('fills',book.trades),('closed',book.closed),('intents',book.intents),('risk-events',book.risk_events)]:
   with gzip.open(out/(name+'-'+suffix+'.jsonl.gz'),'wt',encoding='utf-8') as f:
    for row in data:f.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
  holdings=[]
  for code,p in sorted(book.positions.items()):
   f=make_features(panel[code]);ma=f.ma200[-1]
   holdings.append({'symbol':code,'name':metadata.get(code,{}).get('name'),'industry_snapshot':metadata.get(code,{}).get('industry'),**dataclasses.asdict(p),
    'weight_carry_proxy':p.units*p.last_mark/book.nav(),'unrealized_proxy_pnl_cny':p.units*p.last_mark-p.entry_cost,
    'current_mark_missing':p.last_mark_j!=len(sessions)-1,'MA200_exit_level':ma if math.isfinite(ma) else None,
    'max_age_exit_j':p.entry_j+252,'entry_date':sessions[p.entry_j],'dated_ST_board_tradability':'pending','fundamental_review':'current_overlay_separate_not_backtested'})
  write_json(out/(name+'-holdings.json'),holdings)
  write_json(out/(name+'-management.json'),{'asof':sessions[-1],'cash_cny':book.cash,'NAV_carry_proxy_cny':book.nav(),'anchor_peak':book.anchor_peak,
   'cooldown_until_j':book.cooldown_until,'pending_intents_after_horizon':book.pending,'scheduled':False,'orders_authorized':False})
 primary=summary['results']['sector_base'];control=summary['results']['price_control']
 summary['decision']={'historical_proxy_profitable':primary['total_return_carry_proxy']>0,
  'all_primary_cost_delay_cells_positive':all(summary['results'][n]['final_unknown_zero_recovery_return']>0 for n in RULES['curves'][:3]),
  'sector_increment_total_return_over_price_control':primary['total_return_carry_proxy']-control['total_return_carry_proxy'],
  'production_or_profitability_certification':False}
 write_json(out/'summary.json',summary);write_json(out/'manifest.json',{p.name:digest(p) for p in sorted(out.iterdir()) if p.is_file()});return summary
